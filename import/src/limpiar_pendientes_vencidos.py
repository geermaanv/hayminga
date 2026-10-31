"""
limpiar_pendientes_vencidos.py
Marca descartado todo evento en pendiente_confirmacion cuya fecha ya
pasó (fecha_fin, o fecha_inicio si no hay fin) — nunca puede llegar a
publicarse como "próximo" y hoy no hay ningún mecanismo que lo saque
de la cola de revisión. Hallazgo real (31/10/2026, ver ROADMAP.md): de
133 pendientes, 80 (60%) ya estaban vencidos, algunos desde fines de
agosto — puro ruido que tapa a los pocos realmente accionables.

Mismo criterio de "ya pasó" que usa procesar_post() al descartar en el
momento del descubrimiento (hiker_pipeline.py) — esto corre la misma
regla, pero sobre lo que quedó pendiente y nunca se revisó a tiempo.
Nunca borra una fila (por convención del proyecto): solo cambia Estado
a descartado y agrega una nota a la Descripción.

Dry-run por default, --escribir para aplicar. Gratis — solo Sheets.
"""

import argparse
from datetime import date

from src.sheets import COLUMNS, SHEET_NAME, SPREADSHEET_ID, get_service, parse_fecha_flexible

IDX_FECHA_INICIO = COLUMNS.index("Fecha_Inicio")
IDX_FECHA_FIN = COLUMNS.index("Fecha_Fin")
IDX_DESCRIPCION = COLUMNS.index("Descripción")
IDX_ESTADO = COLUMNS.index("Estado")
IDX_NOMBRE = COLUMNS.index("Nombre")


def _col_letra(idx: int) -> str:
    letras = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    return letras[idx]


def _vencido(row: list, hoy: date) -> bool:
    fecha_relevante = (row[IDX_FECHA_FIN] if len(row) > IDX_FECHA_FIN else "") or \
        (row[IDX_FECHA_INICIO] if len(row) > IDX_FECHA_INICIO else "")
    fecha = parse_fecha_flexible(fecha_relevante)
    return fecha is not None and fecha < hoy


def encontrar_vencidos(service, hoy: date | None = None) -> list[tuple[int, str]]:
    """Devuelve [(fila, nombre), ...] de pendientes vencidos. Fila ya
    incluye el offset de header (fila 2 = primer evento)."""
    hoy = hoy or date.today()
    values = (
        service.spreadsheets().values()
        .get(spreadsheetId=SPREADSHEET_ID, range=f"{SHEET_NAME}!A2:Y")
        .execute()
    ).get("values", [])

    vencidos = []
    for i, row in enumerate(values):
        row = (row + [""] * len(COLUMNS))[:len(COLUMNS)]
        if row[IDX_ESTADO] != "pendiente_confirmacion":
            continue
        if _vencido(row, hoy):
            vencidos.append((i + 2, row[IDX_NOMBRE]))
    return vencidos


def limpiar(escribir: bool = False) -> list[tuple[int, str]]:
    service = get_service()
    vencidos = encontrar_vencidos(service)

    if not vencidos:
        print("[limpiar_pendientes_vencidos] Sin pendientes vencidos")
        return []

    for fila, nombre in vencidos:
        print(f"[limpiar_pendientes_vencidos] Fila {fila}: '{nombre}' -> descartado{'' if escribir else ' (dry-run)'}")

    if not escribir:
        print(f"\n[limpiar_pendientes_vencidos] {len(vencidos)} fila(s), dry-run — correr con --escribir para aplicar.")
        return vencidos

    col_estado = _col_letra(IDX_ESTADO)
    col_desc = _col_letra(IDX_DESCRIPCION)
    nota = (
        "🗑️ Descartado automáticamente: quedó en pendiente_confirmacion "
        "sin revisar hasta que su fecha ya pasó, nunca va a poder "
        "publicarse como evento próximo.\n\n"
    )
    data = []
    for fila, _ in vencidos:
        descripcion_actual = (
            service.spreadsheets().values()
            .get(spreadsheetId=SPREADSHEET_ID, range=f"{SHEET_NAME}!{col_desc}{fila}")
            .execute()
        ).get("values", [[""]])[0][0]
        data.append({"range": f"{SHEET_NAME}!{col_estado}{fila}", "values": [["descartado"]]})
        data.append({"range": f"{SHEET_NAME}!{col_desc}{fila}", "values": [[nota + descripcion_actual]]})

    service.spreadsheets().values().batchUpdate(
        spreadsheetId=SPREADSHEET_ID,
        body={"valueInputOption": "RAW", "data": data},
    ).execute()
    print(f"\n[limpiar_pendientes_vencidos] {len(vencidos)} fila(s) marcada(s) descartado")
    return vencidos


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--escribir", action="store_true", help="Aplica la limpieza (default: dry-run)")
    args = parser.parse_args()
    limpiar(escribir=args.escribir)


if __name__ == "__main__":
    main()
