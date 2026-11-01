"""
actualizar_perfil_german.py
One-off: completa Descripcion y Tecnicas del propio perfil del
mantenedor en el Directorio (Id efae2fc344, germanv@gmail.com), que
había quedado con Descripcion vacía desde el alta. Contenido acordado
con el mantenedor en el chat — sin inventar técnicas ni experiencia
que no haya mencionado él mismo.

Directorio es una hoja que normalmente solo escribe Code.gs (ver
CLAUDE.md) — este script es la única excepción, puntual y de una sola
vez, para una edición que hoy no tiene acción pública propia (no existe
un "editar mi perfil" en el sitio todavía).

Dry-run por default, --escribir para aplicar. Gratis — solo Sheets.
"""

import argparse

from src.sheets import SPREADSHEET_ID, get_service

DIRECTORIO_SHEET_NAME = "Directorio"
DIRECTORIO_HEADERS = [
    "Id", "Nombre", "Provincia", "Intereses", "Descripcion", "Email",
    "Whatsapp", "Tecnicas", "AnioDesde", "RecibeNovedades", "OfreceServicios",
    "UltimoPedidoReferido",
]
ID_OBJETIVO = "efae2fc344"

NUEVA_DESCRIPCION = (
    "Cofundador de hayminga.org. Estudiante amateur de bioconstrucción — "
    "hoy combinando wood frame con quincha, bloques de tierra comprimida "
    "(BTA) y arcilla, con el objetivo de construir mi propia casa. Me "
    "gusta sumarme a mingas de otros para aprender en la práctica, codo "
    "a codo."
)
NUEVAS_TECNICAS = (
    "quincha:estudio; wood frame:estudio; bloques de tierra comprimida:estudio; arcilla:estudio"
)


def _col_letra(idx: int) -> str:
    letras = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    return letras[idx]


def encontrar_fila() -> int | None:
    service = get_service()
    values = (
        service.spreadsheets().values()
        .get(spreadsheetId=SPREADSHEET_ID, range=f"{DIRECTORIO_SHEET_NAME}!A2:L")
        .execute()
    ).get("values", [])

    idx_id = DIRECTORIO_HEADERS.index("Id")
    for i, row in enumerate(values):
        if len(row) > idx_id and row[idx_id] == ID_OBJETIVO:
            return i + 2
    return None


def actualizar(escribir: bool = False) -> int | None:
    fila = encontrar_fila()
    if fila is None:
        print(f"[actualizar_perfil_german] No se encontró la fila con Id {ID_OBJETIVO}")
        return None

    print(f"[actualizar_perfil_german] Fila {fila} ({ID_OBJETIVO}){'' if escribir else ' (dry-run)'}:")
    print(f"  Descripcion -> {NUEVA_DESCRIPCION}")
    print(f"  Tecnicas -> {NUEVAS_TECNICAS}")

    if not escribir:
        print("\n[actualizar_perfil_german] dry-run — correr con --escribir para aplicar.")
        return fila

    col_desc = _col_letra(DIRECTORIO_HEADERS.index("Descripcion"))
    col_tecnicas = _col_letra(DIRECTORIO_HEADERS.index("Tecnicas"))

    service = get_service()
    service.spreadsheets().values().batchUpdate(
        spreadsheetId=SPREADSHEET_ID,
        body={
            "valueInputOption": "RAW",
            "data": [
                {"range": f"{DIRECTORIO_SHEET_NAME}!{col_desc}{fila}", "values": [[NUEVA_DESCRIPCION]]},
                {"range": f"{DIRECTORIO_SHEET_NAME}!{col_tecnicas}{fila}", "values": [[NUEVAS_TECNICAS]]},
            ],
        },
    ).execute()
    print("\n[actualizar_perfil_german] Actualizado")
    return fila


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--escribir", action="store_true", help="Aplica la actualización (default: dry-run)")
    args = parser.parse_args()
    actualizar(escribir=args.escribir)


if __name__ == "__main__":
    main()
