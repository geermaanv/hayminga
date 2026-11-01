"""
migrar_pendientes_publicables.py
Aplica retroactivamente al backlog existente la política "publicar y que
reporten" (31/10-01/11/2026, ver ROADMAP.md): todo pendiente_confirmacion
con confianza alta/media pasa a confirmado/Activo=true, dejando el reporte
del usuario (ver Code.gs, reportar_evento) como red de seguridad en vez de
esperar una revisión manual que capaz no llega. confianza=baja nunca se
toca acá — ese cambio de política no la alcanza, sigue yendo 100% a
revisión.

Mismos filtros duros que ya aplica procesar_post() al descubrir un evento
nuevo (hiker_pipeline.py) — no se publica acá nada que esos filtros ya
descartarían hoy: país confirmado distinto de Argentina, evento virtual
sin ningún país resuelto, fecha ya vencida, o rango de fechas inválido
(fin antes que inicio). Lo que no pasa estos filtros queda tal cual
estaba (pendiente): esto nunca retrocede nada, solo adelanta lo que ya
cumple la regla nueva.

Nunca borra una fila. Dry-run por default, --escribir para aplicar.
Gratis — solo Sheets.
"""

import argparse
from datetime import date

from src.processor import CONFIANZA_PUBLICABLE
from src.sheets import COLUMNS, SHEET_NAME, SPREADSHEET_ID, get_service, parse_fecha_flexible

IDX_ACTIVO = COLUMNS.index("Activo")
IDX_NOMBRE = COLUMNS.index("Nombre")
IDX_FECHA_INICIO = COLUMNS.index("Fecha_Inicio")
IDX_FECHA_FIN = COLUMNS.index("Fecha_Fin")
IDX_ES_VIRTUAL = COLUMNS.index("Es_Virtual")
IDX_ESTADO = COLUMNS.index("Estado")
IDX_PAIS = COLUMNS.index("Pais")
IDX_CONFIANZA = COLUMNS.index("Confianza")


def _col_letra(idx: int) -> str:
    letras = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    return letras[idx]


def _publicable(row: list, hoy: date) -> bool:
    if row[IDX_ESTADO] != "pendiente_confirmacion":
        return False
    confianza = str(row[IDX_CONFIANZA] or "baja").lower()
    if confianza not in CONFIANZA_PUBLICABLE:
        return False
    if not row[IDX_NOMBRE]:
        return False

    fecha_inicio = parse_fecha_flexible(row[IDX_FECHA_INICIO])
    if not fecha_inicio:
        return False
    fecha_fin = parse_fecha_flexible(row[IDX_FECHA_FIN]) if row[IDX_FECHA_FIN] else None
    if fecha_fin and fecha_fin < fecha_inicio:
        return False  # mismo rango_valido que validate_event_data()
    fecha_relevante = fecha_fin or fecha_inicio
    if fecha_relevante < hoy:
        return False  # ya vencido — lo saca limpiar_pendientes_vencidos.py, no esto

    pais = (row[IDX_PAIS] or "").strip()
    if pais and pais != "Argentina":
        return False  # país confirmado no-Argentina: nunca se publica (hard filter)
    es_virtual = str(row[IDX_ES_VIRTUAL] or "").lower() == "true"
    if es_virtual and not pais:
        return False  # virtual sin país resuelto: mismo hard filter de hiker_pipeline.py

    return True


def encontrar_publicables(service, hoy: date | None = None) -> list[tuple[int, str]]:
    """Devuelve [(fila, nombre), ...] — fila ya incluye el offset de
    header (fila 2 = primer evento). Un solo GET para todo el rango,
    igual que limpiar_pendientes_vencidos.py (ver ROADMAP.md 31/10:
    un GET por fila agotó la cuota de lectura de Sheets a mitad de
    corrida)."""
    hoy = hoy or date.today()
    values = (
        service.spreadsheets().values()
        .get(spreadsheetId=SPREADSHEET_ID, range=f"{SHEET_NAME}!A2:Y")
        .execute()
    ).get("values", [])

    publicables = []
    for i, row in enumerate(values):
        row = (row + [""] * len(COLUMNS))[:len(COLUMNS)]
        if _publicable(row, hoy):
            publicables.append((i + 2, row[IDX_NOMBRE]))
    return publicables


def migrar(escribir: bool = False) -> list[tuple[int, str]]:
    service = get_service()
    publicables = encontrar_publicables(service)

    if not publicables:
        print("[migrar_pendientes_publicables] Sin pendientes para publicar")
        return []

    for fila, nombre in publicables:
        print(f"[migrar_pendientes_publicables] Fila {fila}: '{nombre}' -> confirmado{'' if escribir else ' (dry-run)'}")

    if not escribir:
        print(f"\n[migrar_pendientes_publicables] {len(publicables)} fila(s), dry-run — correr con --escribir para aplicar.")
        return publicables

    col_activo = _col_letra(IDX_ACTIVO)
    col_estado = _col_letra(IDX_ESTADO)
    data = []
    for fila, _ in publicables:
        data.append({"range": f"{SHEET_NAME}!{col_activo}{fila}", "values": [["true"]]})
        data.append({"range": f"{SHEET_NAME}!{col_estado}{fila}", "values": [["confirmado"]]})

    service.spreadsheets().values().batchUpdate(
        spreadsheetId=SPREADSHEET_ID,
        body={"valueInputOption": "RAW", "data": data},
    ).execute()
    print(f"\n[migrar_pendientes_publicables] {len(publicables)} fila(s) publicada(s)")
    return publicables


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--escribir", action="store_true", help="Aplica la migración (default: dry-run)")
    args = parser.parse_args()
    migrar(escribir=args.escribir)


if __name__ == "__main__":
    main()
