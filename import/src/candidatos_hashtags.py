"""
candidatos_hashtags.py
Reporte de solo lectura: qué hashtags aparecen seguido en eventos ya
CONFIRMADOS y no están en `config.json.hashtags`. No agrega nada solo —
a diferencia de `descubrir_candidatos()` en curar_fuentes.py (que sí
auto-agrega cuentas), acá el criterio es deliberadamente manual: mezclar
temas mal sale caro (caso real: un cluster de 6 hashtags de cultivo de
hongos entró en la revisión de Hashtags_Post porque un solo evento mezcló
bioconstrucción con micología — no se sumaron porque hubieran traído
contenido de otro tema por completo. Un conteo automático sin revisión
humana los habría agregado igual). Ver ROADMAP.md, Etapa 9.

Usa exclusivamente la API de Sheets (gratis, ya se lee en cada corrida) —
no llama a HikerAPI ni a ningún proveedor de IA, así que correr esto no
gasta nada.
"""
import json
import re
from collections import Counter
from pathlib import Path

from src.sheets import COLUMNS, SHEET_NAME, SPREADSHEET_ID, get_service

CONFIG_PATH = Path("config.json")

# Debajo de esto, un hashtag es más probable que sea ruido de un post
# puntual (nombre propio del organizador, ubicación, etc.) que una fuente
# real de descubrimiento — el mismo espíritu que MIN_SUGERENCIAS_PARA_AGREGAR
# en curar_fuentes.py: pedir que lo respalde más de un evento distinto.
MIN_EVENTOS_PARA_SUGERIR = 2

# Hashtags genéricos que van a aparecer en casi cualquier post de la
# comunidad sin ser temáticos por sí solos — no tiene sentido sugerirlos
# como fuente nueva de búsqueda.
_RUIDO = {
    "bioconstruccion", "permacultura", "sustentable", "sustentabilidad",
    "ecologico", "arquitecturasustentable", "hayminga", "argentina",
}


def _hashtags_configurados() -> set[str]:
    config = json.loads(CONFIG_PATH.read_text())
    return {h.lstrip("#").lower() for h in config.get("hashtags") or []}


def analizar(service=None) -> list[tuple[str, int]]:
    """Devuelve [(hashtag, cantidad_de_eventos_confirmados), ...] para
    hashtags que aparecen en eventos confirmados, no están ya en
    config.json y no son ruido genérico. Ordenado de más a menos frecuente."""
    service = service or get_service()
    values = (
        service.spreadsheets().values()
        .get(spreadsheetId=SPREADSHEET_ID, range=f"{SHEET_NAME}!A2:X")
        .execute()
    ).get("values", [])

    configurados = _hashtags_configurados()
    conteo: Counter[str] = Counter()

    for row in values:
        row = (row + [""] * len(COLUMNS))[:len(COLUMNS)]
        estado = (row[16] or "").strip().lower()
        # Solo eventos confirmados: son los que un humano ya validó como
        # reales — la mejor señal disponible de que el hashtag es temático
        # y no ruido de un post que ni siquiera terminó siendo un evento.
        if estado != "confirmado":
            continue
        hashtags_post = row[23] or ""
        vistos_en_esta_fila = set()
        for tag in re.findall(r"#(\w+)", hashtags_post):
            tag = tag.lower()
            if tag in configurados or tag in _RUIDO or tag in vistos_en_esta_fila:
                continue
            vistos_en_esta_fila.add(tag)
            conteo[tag] += 1

    candidatos = [(tag, n) for tag, n in conteo.items() if n >= MIN_EVENTOS_PARA_SUGERIR]
    return sorted(candidatos, key=lambda par: (-par[1], par[0]))


def reportar():
    candidatos = analizar()
    if not candidatos:
        print("[candidatos_hashtags] Sin candidatos nuevos "
              f"(mínimo {MIN_EVENTOS_PARA_SUGERIR} eventos confirmados distintos)")
        return
    print(f"[candidatos_hashtags] {len(candidatos)} candidato(s) — "
          "revisar a mano antes de sumar a config.json (no se auto-agregan):")
    for tag, n in candidatos:
        print(f"  #{tag}: {n} evento(s) confirmado(s)")


if __name__ == "__main__":
    reportar()
