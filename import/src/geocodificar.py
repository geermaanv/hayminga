"""
geocodificar.py
Convierte la dirección de texto de un evento en latitud/longitud usando
Nominatim (OpenStreetMap), que es gratis.

Por qué hace falta: la única fuente de coordenadas del pipeline es la
ubicación que etiquetó quien publicó el post en Instagram, y la mayoría no
etiqueta nada — 87 de 126 eventos importados quedaron sin coordenadas. El
frontend los manda al centroide de la provincia, así que el mapa los
muestra en el medio de la nada aunque la dirección diga "Ecoescuela Tay
Pichín, San Marcos Sierras, Córdoba".

Prioridad de coordenadas (la de arriba gana):
  1. Ubicación etiquetada en el post — es la que puso el organizador
  2. Geocodificación de la dirección extraída (esto)
  3. Nada: el frontend cae al centroide de la provincia

Regla de diseño: **ante la duda, no devolver nada**. Un pin en el lugar
equivocado es peor que ninguno — sin coordenadas el mapa al menos es
honesto y muestra "en algún lugar de esta provincia". Por eso el resultado
se valida contra el recuadro de Argentina y contra la provincia declarada.
"""
import os
import re
import time

import requests

# Nominatim pide un User-Agent identificable y como máximo 1 consulta por
# segundo. Con 2-3 direcciones nuevas por corrida sobra de lejos.
_USER_AGENT = os.environ.get("NOMINATIM_USER_AGENT", "hayminga.org (germanv@gmail.com)")
_INTERVALO = 1.1
# Tope de consultas por dirección: abajo de esto se pierde tanta precisión
# que el resultado ya no aporta sobre el centroide de la provincia.
_MAX_CONSULTAS_POR_DIRECCION = 5
_ultima_consulta = [0.0]

# Recuadro de Argentina continental + Tierra del Fuego. Cualquier resultado
# de afuera es un error de geocodificación, no un evento en otro país: los
# de otros países ya se descartan antes de llegar acá.
_LAT_MIN, _LAT_MAX = -55.2, -21.7
_LNG_MIN, _LNG_MAX = -73.7, -53.6

# Un resultado a nivel provincia o país no es una ubicación: es el centroide
# que el frontend ya calcula solo cuando la fila no tiene coordenadas.
# Escribirlo sería fingir precisión que no existe. Caso real: "El Hoyo,
# Comarca Andina, Chubut" resolvía al medio de Chubut, a 400 km del pueblo.
_NIVELES_DEMASIADO_GRUESOS = {"state", "country", "continent", "region"}

# Direcciones que no son lugares físicos: eventos virtuales donde el campo
# trae el link de la videollamada.
_NO_ES_LUGAR = re.compile(r"https?://|meet\.google|zoom\.us|youtube|instagram\.com|^\s*online\s*$", re.I)


def _dentro_de_argentina(lat: float, lng: float) -> bool:
    return _LAT_MIN <= lat <= _LAT_MAX and _LNG_MIN <= lng <= _LNG_MAX


def _normalizar(texto: str) -> str:
    import unicodedata
    t = unicodedata.normalize("NFKD", (texto or "").lower())
    return "".join(c for c in t if not unicodedata.combining(c))


def _consultar_nominatim(consulta: str) -> list[dict]:
    espera = _INTERVALO - (time.monotonic() - _ultima_consulta[0])
    if espera > 0:
        time.sleep(espera)
    _ultima_consulta[0] = time.monotonic()
    resp = requests.get(
        "https://nominatim.openstreetmap.org/search",
        params={"q": consulta, "format": "json", "countrycodes": "ar",
                "limit": 3, "addressdetails": 1},
        headers={"User-Agent": _USER_AGENT},
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json() or []


def geocodificar_direccion(direccion: str | None, provincia: str | None = None) -> tuple[float, float] | None:
    """Devuelve (lat, lng) o None. None es una respuesta perfectamente
    válida y frecuente: mejor sin coordenadas que con las equivocadas."""
    direccion = (direccion or "").strip()
    if not direccion or _NO_ES_LUGAR.search(direccion):
        return None

    provincia = (provincia or "").strip()
    for intento in _variantes(direccion, provincia):
        # La dirección extraída del flyer muchas veces ya nombra la
        # provincia; agregarla igual no molesta y desambigua los topónimos
        # repetidos, que en Argentina son moneda corriente (San Martín,
        # Belgrano, Rivadavia...).
        consulta = ", ".join(p for p in (intento, provincia, "Argentina") if p)
        try:
            resultados = _consultar_nominatim(consulta)
        except Exception as e:
            print(f"[geocodificar] error consultando '{consulta[:50]}' — {e}")
            return None
        punto = _primer_resultado_valido(resultados, provincia)
        if punto:
            return punto
    return None


def _variantes(direccion: str, provincia: str = "") -> list[str]:
    """Consultas a probar, de más precisa a más general.

    Dos motivos para no mandar solo la dirección completa:

    1. El flyer suele arrancar con el nombre del salón —"Ecoescuela Tay
       Pichín, San Marcos Sierras, Córdoba"— y Nominatim no conoce el
       salón, así que la consulta entera no devuelve nada aunque el pueblo
       exista. Sacando el primer tramo resuelve.
    2. Hay tramos que son nombres regionales y no unidades administrativas
       ("Comarca Andina"): si están en la consulta, no devuelve nada aunque
       el resto sea válido. Por eso también se prueba cada tramo suelto.

    Se pierde el punto exacto del salón y se gana el centro del pueblo, que
    es muchísimo mejor que el centroide de la provincia.
    """
    tramos = [t.strip() for t in re.split(r"[,\u2013\u2014]|\s-\s", direccion) if t.strip()]
    if not tramos:
        return []
    # La provincia y el país se agregan aparte a cada consulta: dejarlos como
    # tramos sueltos gastaba intentos del tope en "Chubut" y "Argentina", que
    # además resuelven al centroide. Por eso se sacan de la lista de tramos
    # (pero no de la consulta completa, donde sí ayudan a desambiguar).
    utiles = [t for t in tramos
              if _normalizar(t) not in ("argentina", _normalizar(provincia))] or tramos
    candidatos = [", ".join(tramos)]
    if len(utiles) > 1:
        candidatos.append(", ".join(utiles[1:]))
    # Tramos sueltos del más general al más específico: el último suele ser
    # la localidad o el partido, que es lo que Nominatim sí conoce.
    candidatos.extend(reversed(utiles))
    vistos, salida = set(), []
    for c in candidatos:
        if c and c.lower() not in vistos:
            vistos.add(c.lower())
            salida.append(c)
    return salida[:_MAX_CONSULTAS_POR_DIRECCION]


def _primer_resultado_valido(resultados: list[dict], provincia: str) -> tuple[float, float] | None:
    provincia_norm = _normalizar(provincia)
    for r in resultados:
        try:
            lat, lng = float(r["lat"]), float(r["lon"])
        except (KeyError, ValueError, TypeError):
            continue
        if not _dentro_de_argentina(lat, lng):
            continue
        if (r.get("addresstype") or "").lower() in _NIVELES_DEMASIADO_GRUESOS:
            continue
        # Si sabemos la provincia, el resultado tiene que caer en ella. Sin
        # este chequeo, "Belgrano" puede devolver un punto a 1000 km.
        if provincia_norm:
            estado = _normalizar((r.get("address") or {}).get("state") or "")
            # CABA aparece con varios nombres según el dato de OSM
            if provincia_norm in ("caba", "ciudad autonoma de buenos aires"):
                ok = "buenos aires" in estado
            else:
                ok = provincia_norm in estado or estado in provincia_norm
            if estado and not ok:
                continue
        return lat, lng
    return None


def backfill(dry_run: bool = True) -> int:
    """Completa las coordenadas de las filas que ya están en el Sheet.
    Arranca en dry_run: imprime qué haría sin escribir nada."""
    from src.sheets import COLUMNS, SHEET_NAME, SPREADSHEET_ID, get_service

    service = get_service()
    values = (
        service.spreadsheets().values()
        .get(spreadsheetId=SPREADSHEET_ID, range=f"{SHEET_NAME}!A2:Y")
        .execute()
    ).get("values", [])

    updates = []
    for i, row in enumerate(values, start=2):
        row = (row + [""] * len(COLUMNS))[:len(COLUMNS)]
        if row[21].strip() and row[22].strip():
            continue
        if not row[2].strip():
            continue
        punto = geocodificar_direccion(row[2], row[7])
        estado = f"{punto[0]:.5f}, {punto[1]:.5f}" if punto else "(sin resolver)"
        print(f"  fila {i:3}  {estado:24} {row[2][:52]}")
        if punto:
            updates.append((i, punto))

    print(f"\n{len(updates)} fila(s) con coordenadas nuevas")
    if dry_run:
        print("(dry run — no se escribió nada; correr con --escribir para aplicar)")
        return len(updates)

    if updates:
        service.spreadsheets().values().batchUpdate(
            spreadsheetId=SPREADSHEET_ID,
            body={"valueInputOption": "RAW", "data": [
                {"range": f"{SHEET_NAME}!V{fila}:W{fila}", "values": [[lat, lng]]}
                for fila, (lat, lng) in updates
            ]},
        ).execute()
        print(f"escritas {len(updates)} fila(s)")
    return len(updates)


if __name__ == "__main__":
    import sys
    backfill(dry_run="--escribir" not in sys.argv)
