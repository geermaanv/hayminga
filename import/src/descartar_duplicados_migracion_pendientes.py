"""
descartar_duplicados_migracion_pendientes.py
One-off: el dry-run de migrar_pendientes_publicables.py (01/11/2026, ver
ROADMAP.md) encontró 12 pendientes publicables, de los cuales 4 son
reposts ya marcados como "posible duplicado"/"repost" en su propia
Descripción, de otras 2 filas del mismo lote:

- "12° Encuentro Nacional en Patagonia - Red Protierra Argentina"
  (Id ff930e0787, original) duplicado por c84b4d4d37 y 5787898be1
- "Manos a la Tierra - Taller de Bioconstrucción" (Id b2d96a97e0,
  original) duplicado por 7017bdffac y 02d8c10f0c

Publicar los 4 reposts además del original habría puesto 3 cards del
mismo evento en el sitio a la vez — a diferencia del resto del backlog
(donde el reporte del usuario es la red de seguridad aceptada), acá ya
se sabía de antemano que son duplicados, así que no tiene sentido
publicarlos para después depender de un reporte. Esto los descarta
(nunca se borra una fila, por convención del proyecto) antes de correr
la migración; los dos originales quedan para que migrar_pendientes_publicables.py
los publique normalmente.

Dry-run por default, --escribir para aplicar. Gratis — solo Sheets.
"""

import argparse

from src.sheets import COLUMNS, SHEET_NAME, SPREADSHEET_ID, get_service

IDS_A_DESCARTAR = {"c84b4d4d37", "5787898be1", "7017bdffac", "02d8c10f0c"}

IDX_ID = COLUMNS.index("Id")
IDX_NOMBRE = COLUMNS.index("Nombre")
IDX_DESCRIPCION = COLUMNS.index("Descripción")
IDX_ESTADO = COLUMNS.index("Estado")


def _col_letra(idx: int) -> str:
    letras = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    return letras[idx]


def encontrar_filas() -> list[tuple[int, str, str, str]]:
    """Devuelve [(fila, id, nombre, descripcion_actual), ...]."""
    service = get_service()
    values = (
        service.spreadsheets().values()
        .get(spreadsheetId=SPREADSHEET_ID, range=f"{SHEET_NAME}!A2:Y")
        .execute()
    ).get("values", [])

    encontradas = []
    for i, row in enumerate(values):
        row = (row + [""] * len(COLUMNS))[:len(COLUMNS)]
        if row[IDX_ID] in IDS_A_DESCARTAR:
            encontradas.append((i + 2, row[IDX_ID], row[IDX_NOMBRE], row[IDX_DESCRIPCION]))
    return encontradas


def descartar(escribir: bool = False) -> list[tuple[int, str, str, str]]:
    filas = encontrar_filas()

    if not filas:
        print("[descartar_duplicados_migracion_pendientes] No se encontró ninguna de las filas esperadas")
        return []

    for fila, id_, nombre, _ in filas:
        print(f"[descartar_duplicados_migracion_pendientes] Fila {fila} ({id_}): '{nombre}' -> descartado{'' if escribir else ' (dry-run)'}")

    ids_faltantes = IDS_A_DESCARTAR - {id_ for _, id_, _, _ in filas}
    if ids_faltantes:
        print(f"[descartar_duplicados_migracion_pendientes] AVISO: no se encontraron estos Id esperados: {ids_faltantes}")

    if not escribir:
        print(f"\n[descartar_duplicados_migracion_pendientes] {len(filas)} fila(s), dry-run — correr con --escribir para aplicar.")
        return filas

    col_estado = _col_letra(IDX_ESTADO)
    col_desc = _col_letra(IDX_DESCRIPCION)
    nota = (
        "❌ Descartado: repost de otro evento ya en el Sheet, detectado "
        "antes de migrar el backlog a la política \"publicar y que "
        "reporten\" (ver ROADMAP.md) — se descarta en vez de publicar un "
        "duplicado a sabiendas.\n\n"
    )
    data = []
    for fila, _, _, descripcion_actual in filas:
        data.append({"range": f"{SHEET_NAME}!{col_estado}{fila}", "values": [["descartado"]]})
        data.append({"range": f"{SHEET_NAME}!{col_desc}{fila}", "values": [[nota + descripcion_actual]]})

    service = get_service()
    service.spreadsheets().values().batchUpdate(
        spreadsheetId=SPREADSHEET_ID,
        body={"valueInputOption": "RAW", "data": data},
    ).execute()
    print(f"\n[descartar_duplicados_migracion_pendientes] {len(filas)} fila(s) marcada(s) descartado")
    return filas


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--escribir", action="store_true", help="Aplica la baja (default: dry-run)")
    args = parser.parse_args()
    descartar(escribir=args.escribir)


if __name__ == "__main__":
    main()
