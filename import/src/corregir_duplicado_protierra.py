"""
corregir_duplicado_protierra.py
One-off: corrige el error de agregar_encuentro_protierra_2026.py — el
evento que cargó YA estaba en el Sheet, descubierto antes por HikerAPI
y ya `confirmado` (Id 782469dee3, "12° Encuentro Nacional en Patagonia -
Red Protierra Argentina", vía Instagram, fecha_fin real 2026-11-10, no
2026-11-07 como se asumió de la nota de redprotierra.com.ar). La fila
nueva quedó como duplicado ambiguo en pendiente_confirmacion (mismo
nombre/fecha/provincia, link distinto) — esto la marca `descartado`
(nunca se borra una fila, por convención del proyecto) con una nota
explicando por qué.

Dry-run por default, --escribir para aplicar. Gratis — solo Sheets.
"""

import argparse

from src.sheets import COLUMNS, SHEET_NAME, SPREADSHEET_ID, get_service

NOMBRE_DUPLICADO = "12° Encuentro Nacional de la Red Protierra Argentina"
FUENTE_DUPLICADO = "revision_manual_pipeline"
ID_EVENTO_REAL = "782469dee3"

IDX_DESCRIPCION = COLUMNS.index("Descripción")
IDX_ID = COLUMNS.index("Id")
IDX_ESTADO = COLUMNS.index("Estado")
IDX_FUENTE = COLUMNS.index("Fuente")
IDX_NOMBRE = COLUMNS.index("Nombre")


def _col_letra(idx: int) -> str:
    letras = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    return letras[idx]


def encontrar_fila() -> int | None:
    service = get_service()
    values = (
        service.spreadsheets().values()
        .get(spreadsheetId=SPREADSHEET_ID, range=f"{SHEET_NAME}!A2:Y")
        .execute()
    ).get("values", [])

    for i, row in enumerate(values):
        row = (row + [""] * len(COLUMNS))[:len(COLUMNS)]
        if row[IDX_NOMBRE] == NOMBRE_DUPLICADO and row[IDX_FUENTE] == FUENTE_DUPLICADO:
            return i + 2  # +2: fila 1 es header, values es 0-indexado desde fila 2
    return None


def corregir(escribir: bool = False) -> None:
    fila = encontrar_fila()
    if fila is None:
        print("[corregir_duplicado_protierra] No se encontró la fila duplicada — nada para hacer")
        return

    print(f"[corregir_duplicado_protierra] Fila {fila}: marcar Estado=descartado{'' if escribir else ' (dry-run)'}")
    if not escribir:
        print("[corregir_duplicado_protierra] dry-run — correr con --escribir para aplicar.")
        return

    service = get_service()
    nota = (
        f"❌ Descartado: es el mismo evento que el Id {ID_EVENTO_REAL} "
        "(\"12° Encuentro Nacional en Patagonia - Red Protierra Argentina\"), "
        "ya confirmado y descubierto antes vía Instagram. Esta fila se "
        "cargó por error desde una fuente externa (redprotierra.com.ar) "
        "sin cruzar primero contra lo ya confirmado.\n\n"
    )
    col_estado = _col_letra(IDX_ESTADO)
    col_desc = _col_letra(IDX_DESCRIPCION)
    descripcion_actual = (
        service.spreadsheets().values()
        .get(spreadsheetId=SPREADSHEET_ID, range=f"{SHEET_NAME}!{col_desc}{fila}")
        .execute()
    ).get("values", [[""]])[0][0]

    service.spreadsheets().values().batchUpdate(
        spreadsheetId=SPREADSHEET_ID,
        body={
            "valueInputOption": "RAW",
            "data": [
                {"range": f"{SHEET_NAME}!{col_estado}{fila}", "values": [["descartado"]]},
                {"range": f"{SHEET_NAME}!{col_desc}{fila}", "values": [[nota + descripcion_actual]]},
            ],
        },
    ).execute()
    print("[corregir_duplicado_protierra] Corregido")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--escribir", action="store_true", help="Aplica la corrección (default: dry-run)")
    args = parser.parse_args()
    corregir(escribir=args.escribir)


if __name__ == "__main__":
    main()
