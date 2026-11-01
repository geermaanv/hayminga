"""
corregir_duplicados_post_migracion.py
One-off: migrar_pendientes_publicables.py (01/11/2026, ver ROADMAP.md) solo
revisaba duplicados DENTRO del propio lote de pendientes que migraba —
nunca cruzó contra eventos que YA estaban `confirmado` desde antes. Dos
de las 8 filas publicadas resultaron ser el mismo evento (mismo nombre y
fecha exactos) que otro ya confirmado mucho antes:

- "12° Encuentro Nacional en Patagonia - Red Protierra Argentina"
  (Id 782469dee3, confirmado desde antes) duplicado por ff930e0787
  (publicado por la migración)
- "Autonomía es Libertad" (Id 953bd774da, confirmado desde antes)
  duplicado por 3dc2e2c94d (publicado por la migración)

Esto descarta los dos duplicados nuevos (nunca se borra una fila, por
convención del proyecto), dejando los originales ya confirmados tal
cual estaban.

Dry-run por default, --escribir para aplicar. Gratis — solo Sheets.
"""

import argparse

from src.sheets import COLUMNS, SHEET_NAME, SPREADSHEET_ID, get_service

IDS_A_DESCARTAR = {"ff930e0787", "3dc2e2c94d"}

IDX_ACTIVO = COLUMNS.index("Activo")
IDX_ID = COLUMNS.index("Id")
IDX_NOMBRE = COLUMNS.index("Nombre")
IDX_DESCRIPCION = COLUMNS.index("Descripción")
IDX_ESTADO = COLUMNS.index("Estado")


def _col_letra(idx: int) -> str:
    letras = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    return letras[idx]


def encontrar_filas() -> list[tuple[int, str, str, str]]:
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


def corregir(escribir: bool = False) -> list[tuple[int, str, str, str]]:
    filas = encontrar_filas()

    if not filas:
        print("[corregir_duplicados_post_migracion] No se encontró ninguna de las filas esperadas")
        return []

    for fila, id_, nombre, _ in filas:
        print(f"[corregir_duplicados_post_migracion] Fila {fila} ({id_}): '{nombre}' -> descartado{'' if escribir else ' (dry-run)'}")

    ids_faltantes = IDS_A_DESCARTAR - {id_ for _, id_, _, _ in filas}
    if ids_faltantes:
        print(f"[corregir_duplicados_post_migracion] AVISO: no se encontraron estos Id esperados: {ids_faltantes}")

    if not escribir:
        print(f"\n[corregir_duplicados_post_migracion] {len(filas)} fila(s), dry-run — correr con --escribir para aplicar.")
        return filas

    col_activo = _col_letra(IDX_ACTIVO)
    col_estado = _col_letra(IDX_ESTADO)
    col_desc = _col_letra(IDX_DESCRIPCION)
    nota = (
        "❌ Descartado: la migración del backlog de pendientes (01/11) lo "
        "publicó sin cruzarlo contra eventos ya confirmados — es el mismo "
        "evento que otra fila ya confirmada desde antes.\n\n"
    )
    data = []
    for fila, _, _, descripcion_actual in filas:
        # Bug real (01/11): la primera corrida de este script solo puso
        # Estado=descartado y dejó Activo=true sin tocar — el frontend
        # filtra por Activo, no por Estado, así que los dos duplicados
        # siguieron visibles en el sitio pese a figurar "descartado" en
        # la planilla. Activo=false es la parte que realmente lo saca
        # del sitio.
        data.append({"range": f"{SHEET_NAME}!{col_activo}{fila}", "values": [["false"]]})
        data.append({"range": f"{SHEET_NAME}!{col_estado}{fila}", "values": [["descartado"]]})
        data.append({"range": f"{SHEET_NAME}!{col_desc}{fila}", "values": [[nota + descripcion_actual]]})

    service = get_service()
    service.spreadsheets().values().batchUpdate(
        spreadsheetId=SPREADSHEET_ID,
        body={"valueInputOption": "RAW", "data": data},
    ).execute()
    print(f"\n[corregir_duplicados_post_migracion] {len(filas)} fila(s) marcada(s) descartado")
    return filas


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--escribir", action="store_true", help="Aplica la baja (default: dry-run)")
    args = parser.parse_args()
    corregir(escribir=args.escribir)


if __name__ == "__main__":
    main()
