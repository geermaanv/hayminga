"""
sheets.py
Escribe los eventos en Google Sheets con el schema exacto de hayminga.org.
Columnas: Activo, Nombre, Dirección, Periodo, Fecha_Inicio, Fecha_Fin,
          Es_Virtual, Provincia, Descripción, Organizador, Link_Promocion,
          Tipo_Evento, img, procesado, Id, Contacto, Estado, Pais,
          Confianza, Fuente, Fecha_Descubrimiento
"""

import os
import json
import uuid
import re
import unicodedata
from datetime import date
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

SCOPES          = ["https://www.googleapis.com/auth/spreadsheets"]
SPREADSHEET_ID  = os.environ["GOOGLE_SPREADSHEET_ID"]
SHEET_NAME      = "Eventos"

# Estadísticas de fuentes de descubrimiento (hashtags/cuentas de
# hiker_pipeline.py) — las lee y actualiza el curador semanal
# (curar_fuentes.py) para dar de baja solas las que dejaron de servir.
FUENTES_STATS_SHEET_NAME = "FuentesStats"
FUENTES_STATS_HEADERS = ["Tipo", "Nombre", "IntentosSinHit", "UltimoHit"]

# Nuevas columnas (Id, Contacto, Estado) van al final a propósito: así las
# columnas existentes no cambian de letra ni rompen consumidores que todavía
# esperan esas posiciones.
COLUMNS = [
    "Activo", "Nombre", "Dirección", "Periodo", "Fecha_Inicio", "Fecha_Fin",
    "Es_Virtual", "Provincia", "Descripción", "Organizador",
    "Link_Promocion", "Tipo_Evento", "img", "procesado",
    "Id", "Contacto", "Estado", "Pais",
    "Confianza", "Fuente", "Fecha_Descubrimiento",
    "Latitud", "Longitud", "Hashtags_Post",
]


def generate_id() -> str:
    return uuid.uuid4().hex[:10]


def get_service():
    creds_json = os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]
    creds_dict = json.loads(creds_json)
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    return build("sheets", "v4", credentials=creds)


def ensure_header(service):
    result = (
        service.spreadsheets().values()
        .get(spreadsheetId=SPREADSHEET_ID, range=f"{SHEET_NAME}!1:1")
        .execute()
    )
    current = result.get("values", [[]])
    current = current[0] if current else []

    if not current:
        service.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=f"{SHEET_NAME}!A1",
            valueInputOption="RAW",
            body={"values": [COLUMNS]},
        ).execute()
        print("[sheets] Header creado")
    elif current != COLUMNS[: len(current)]:
        # el header existente no coincide con el prefijo esperado — no lo
        # tocamos para no romper una hoja con columnas reordenadas a mano
        print(f"[sheets] AVISO: header de la hoja no coincide con COLUMNS: {current}")
    elif len(current) < len(COLUMNS):
        # header viejo (de antes de agregar columnas nuevas al final):
        # completar las que faltan sin tocar las existentes
        faltantes = COLUMNS[len(current):]
        service.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=f"{SHEET_NAME}!{_col_letter(len(current) + 1)}1",
            valueInputOption="RAW",
            body={"values": [faltantes]},
        ).execute()
        print(f"[sheets] Header actualizado, columnas agregadas: {faltantes}")


def _sheet_existe(service, sheet_name: str) -> bool:
    meta = service.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
    return any(s["properties"]["title"] == sheet_name for s in meta["sheets"])


def get_or_create_sheet_with_headers(service, sheet_name: str, headers: list[str]):
    if not _sheet_existe(service, sheet_name):
        service.spreadsheets().batchUpdate(
            spreadsheetId=SPREADSHEET_ID,
            body={"requests": [{"addSheet": {"properties": {"title": sheet_name}}}]},
        ).execute()
        service.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=f"{sheet_name}!A1",
            valueInputOption="RAW",
            body={"values": [headers]},
        ).execute()
        print(f"[sheets] Hoja '{sheet_name}' creada")


def cargar_fuentes_stats(service) -> dict[tuple, dict]:
    """Devuelve {(tipo, nombre): {"fila": N, "intentos_sin_hit": int}}."""
    get_or_create_sheet_with_headers(service, FUENTES_STATS_SHEET_NAME, FUENTES_STATS_HEADERS)
    result = (
        service.spreadsheets().values()
        .get(spreadsheetId=SPREADSHEET_ID, range=f"{FUENTES_STATS_SHEET_NAME}!A2:D")
        .execute()
    )
    stats = {}
    for i, row in enumerate(result.get("values", []), start=2):
        row = (row + [""] * 4)[:4]
        tipo, nombre = row[0], row[1]
        try:
            intentos = int(row[2] or 0)
        except ValueError:
            intentos = 0
        stats[(tipo, nombre)] = {"fila": i, "intentos_sin_hit": intentos}
    return stats


def actualizar_fuentes_stats(service, resultados: dict[tuple, bool]):
    """resultados: {(tipo, nombre): hubo_hit_en_esta_corrida}. Suma 1 al
    contador si no hubo hit, lo resetea a 0 si sí hubo — así 50 intentos
    seguidos sin producir nada es la señal de "esta fuente ya no sirve"."""
    if not resultados:
        return
    stats = cargar_fuentes_stats(service)
    hoy = date.today().isoformat()
    updates = []
    nuevas = []
    for (tipo, nombre), hubo_hit in resultados.items():
        actual = stats.get((tipo, nombre))
        if actual is None:
            nuevas.append([tipo, nombre, "0" if hubo_hit else "1", hoy if hubo_hit else ""])
            continue
        nuevo_valor = 0 if hubo_hit else actual["intentos_sin_hit"] + 1
        if hubo_hit:
            updates.append({
                "range": f"{FUENTES_STATS_SHEET_NAME}!C{actual['fila']}:D{actual['fila']}",
                "values": [[str(nuevo_valor), hoy]],
            })
        else:
            # no tocar UltimoHit (columna D) si no hubo hit — se mantiene el histórico
            updates.append({
                "range": f"{FUENTES_STATS_SHEET_NAME}!C{actual['fila']}",
                "values": [[str(nuevo_valor)]],
            })

    if updates:
        service.spreadsheets().values().batchUpdate(
            spreadsheetId=SPREADSHEET_ID,
            body={"valueInputOption": "RAW", "data": updates},
        ).execute()

    if nuevas:
        service.spreadsheets().values().append(
            spreadsheetId=SPREADSHEET_ID,
            range=f"{FUENTES_STATS_SHEET_NAME}!A1",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": nuevas},
        ).execute()


def _col_letter(n: int) -> str:
    """1 -> A, 27 -> AA, etc."""
    letters = ""
    while n > 0:
        n, rem = divmod(n - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def _normalize_key_part(value) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").strip().lower())
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def event_dedupe_key(event: dict) -> str:
    nombre = _normalize_key_part(event.get("nombre"))
    fecha = _normalize_key_part(event.get("fecha_inicio_iso") or event.get("fecha_inicio"))
    provincia = _normalize_key_part(event.get("provincia"))
    return "|".join((nombre, fecha, provincia))


_IG_SHORTCODE_RE = re.compile(r"instagram\.com/(?:p|reel|reels)/([A-Za-z0-9_-]+)")


def instagram_shortcode(link: str) -> str:
    """El mismo posteo de Instagram se puede linkear como /p/, /reel/ o
    /reels/ según quién lo comparta — comparar solo el código evita
    duplicados como el mismo evento cargado a mano y descubierto por el
    pipeline con URLs distintas mismo posteo."""
    match = _IG_SHORTCODE_RE.search(link or "")
    return match.group(1) if match else ""


def load_processed_events(service) -> list[dict]:
    """Trae nombre/fecha/provincia, link e Id de cada fila existente —
    se usa para detectar tanto duplicados exactos (mismo posteo) como
    ambiguos (misma clave nombre+fecha+provincia, contenido distinto)."""
    try:
        result = (
            service.spreadsheets().values()
            .get(spreadsheetId=SPREADSHEET_ID, range=f"{SHEET_NAME}!A2:U")
            .execute()
        )
        values = result.get("values", [])
        out = []
        for row in values:
            row = (row + [""] * len(COLUMNS))[:len(COLUMNS)]
            out.append({
                "key": event_dedupe_key({
                    "nombre": row[1], "fecha_inicio_iso": row[4], "provincia": row[7],
                }),
                "shortcode": instagram_shortcode(row[10]),
                "id": row[14],
                "nombre": row[1],
            })
        return out
    except Exception:
        return []


def event_to_row(event: dict) -> list:
    nombre = (event.get("nombre") or "").strip()
    return [
        "true" if event.get("activo") else "false",
        nombre,
        event.get("direccion") or "",
        event.get("periodo") or "",
        event.get("fecha_inicio_iso") or "",
        event.get("fecha_fin_iso") or "",
        "true" if event.get("es_virtual") else "false",
        event.get("provincia") or "",
        event.get("descripcion") or "",
        event.get("organizador") or "",
        event.get("link_promocional") or "",
        event.get("tipo_evento") or "",
        event.get("imagen_url") or "",
        nombre.lower(),  # procesado — clave de deduplicación
        event.get("id") or generate_id(),
        event.get("contacto") or "",
        event.get("estado") or ("confirmado" if event.get("activo") else "pendiente_confirmacion"),
        event.get("pais") or "",
        event.get("confianza") or "",
        event.get("fuente") or "",
        event.get("fecha_descubrimiento") or "",
        event.get("latitud") or "",
        event.get("longitud") or "",
        event.get("hashtags_post") or "",
    ]


def append_events(events: list[dict], return_inserted_keys: bool = False):
    if not events:
        return set() if return_inserted_keys else 0

    service = get_service()
    ensure_header(service)
    existentes = load_processed_events(service)
    processed = {e["key"] for e in existentes}
    shortcodes = {e["shortcode"]: e for e in existentes if e["shortcode"]}
    print(f"[sheets] {len(processed)} evento(s) ya registrados")

    rows = []
    inserted_keys = set()
    for event in events:
        nombre = (event.get("nombre") or "").strip()
        if not nombre:
            continue

        shortcode = instagram_shortcode(event.get("link_promocional"))
        if shortcode and shortcode in shortcodes:
            print(f"[sheets] Duplicado (mismo posteo de Instagram), saltando: '{nombre}'")
            continue

        key = event_dedupe_key(event)
        if key in processed:
            existente = next((e for e in existentes if e["key"] == key), None)
            print(f"[sheets] Posible duplicado ambiguo (misma clave, link distinto), "
                  f"pasa a revisión: '{nombre}'")
            nota = (
                f"⚠️ Posible duplicado del evento existente "
                f"'{existente['nombre'] if existente else '?'}' "
                f"(id {existente['id'] if existente else '?'}) — mismo nombre/fecha/provincia "
                "pero distinto posteo de origen. Revisar y fusionar datos si corresponde.\n\n"
            )
            event["descripcion"] = nota + (event.get("descripcion") or "")
            event["activo"] = False
            event["estado"] = "pendiente_confirmacion"

        event.setdefault("id", generate_id())
        rows.append(event_to_row(event))
        processed.add(key)
        if shortcode:
            shortcodes[shortcode] = {"nombre": nombre, "id": event["id"]}
        inserted_keys.add(key)

    if not rows:
        print("[sheets] Sin filas nuevas para insertar")
        return set() if return_inserted_keys else 0

    service.spreadsheets().values().append(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{SHEET_NAME}!A1",
        valueInputOption="RAW",
        insertDataOption="INSERT_ROWS",
        body={"values": rows},
    ).execute()

    print(f"[sheets] ✓ {len(rows)} fila(s) insertada(s)")
    return inserted_keys if return_inserted_keys else len(rows)


if __name__ == "__main__":
    import sys, json as _json
    data = _json.loads(sys.stdin.read())
    n = append_events(data)
    print(f"Insertados: {n}")
