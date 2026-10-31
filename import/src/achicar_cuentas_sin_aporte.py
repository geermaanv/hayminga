"""
achicar_cuentas_sin_aporte.py
One-off: saca de cuentas_seguidas las cuentas que jamás produjeron una
sola fila en la hoja Eventos (ni confirmado, ni pendiente, ni
descartado) — hallazgo del 31/10/2026 (ver ROADMAP.md): de 510
cuentas_seguidas, solo 48 aparecen alguna vez como Username en todo
el historial del Sheet. Con descubrir_candidatos() ya apagado y sin
evidencia de que el canal de cuentas esté aportando, el mantenedor
pidió achicar la lista a solo lo que ya demostró servir.

cuentas_protegidas nunca se sacan, sin importar esto — son las
organizaciones "institucionales" que se decidió mantener aparte de
cualquier métrica de aporte (ver CLAUDE.md).

Dry-run por default, --escribir para aplicar. Gratis — solo Sheets
(lee la hoja Eventos completa una vez).
"""

import argparse
import json
from pathlib import Path

from src.sheets import COLUMNS, SHEET_NAME, SPREADSHEET_ID, get_service

CONFIG_PATH = Path("config.json")

IDX_USERNAME = COLUMNS.index("Username")


def cuentas_con_aporte(service) -> set[str]:
    """Usernames que aparecen en al menos una fila de Eventos, en
    cualquier Estado — señal de que la cuenta alguna vez produjo algo
    que la IA consideró un posible evento, sin importar si quedó
    confirmado, pendiente o descartado después."""
    values = (
        service.spreadsheets().values()
        .get(spreadsheetId=SPREADSHEET_ID, range=f"{SHEET_NAME}!A2:Y")
        .execute()
    ).get("values", [])

    aportantes = set()
    for row in values:
        row = (row + [""] * len(COLUMNS))[:len(COLUMNS)]
        username = (row[IDX_USERNAME] or "").strip().lstrip("@").lower()
        if username:
            aportantes.add(username)
    return aportantes


def achicar(escribir: bool = False) -> list[str]:
    service = get_service()
    aportantes = cuentas_con_aporte(service)

    config = json.loads(CONFIG_PATH.read_text())
    cuentas = config.get("cuentas_seguidas") or []
    protegidas = {c.lstrip("@").lower() for c in (config.get("cuentas_protegidas") or [])}

    a_quitar = [
        c for c in cuentas
        if c.lstrip("@").lower() not in aportantes and c.lstrip("@").lower() not in protegidas
    ]
    con_aporte_en_lista = len(cuentas) - len(a_quitar)

    print(f"[achicar_cuentas_sin_aporte] {len(cuentas)} cuentas_seguidas actuales")
    print(f"[achicar_cuentas_sin_aporte] {con_aporte_en_lista} con al menos 1 fila en Eventos o protegida")
    print(f"[achicar_cuentas_sin_aporte] {len(a_quitar)} cuenta(s) sin aporte nunca, a quitar{'' if escribir else ' (dry-run)'}")

    if not escribir:
        print("[achicar_cuentas_sin_aporte] dry-run — correr con --escribir para aplicar.")
        return a_quitar

    a_quitar_set = set(a_quitar)
    config["cuentas_seguidas"] = [c for c in cuentas if c not in a_quitar_set]
    CONFIG_PATH.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n")
    print(f"[achicar_cuentas_sin_aporte] quedan {len(config['cuentas_seguidas'])} cuentas_seguidas")
    return a_quitar


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--escribir", action="store_true", help="Aplica la quita (default: dry-run)")
    args = parser.parse_args()
    achicar(escribir=args.escribir)


if __name__ == "__main__":
    main()
