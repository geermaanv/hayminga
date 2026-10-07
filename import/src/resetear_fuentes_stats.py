"""
resetear_fuentes_stats.py
One-off: reinicia a 0 IntentosSinHit en FuentesStats para las fuentes
que acaban de volver a config.json después de restaurar las bajas
masivas del 01/10/2026 (ver ROADMAP.md) — 94 cuentas y 19 hashtags se
fueron en pocos días porque curar_fuentes.py no tenía tope de bajas por
corrida. Sin este reset, la próxima corrida de curar_fuentes.py las
vuelve a dar de baja: su contador en la Sheet seguía en 50+, restaurar
config.json no lo toca.

Dry-run por default (solo imprime qué resetearía), --escribir para
aplicar. Gratis (no llama a HikerAPI/Gemini), solo lee/escribe la Sheet.
"""

import argparse
import json
from pathlib import Path

from src.sheets import SPREADSHEET_ID, FUENTES_STATS_SHEET_NAME, get_service, cargar_fuentes_stats

CONFIG_PATH = Path("config.json")


def _fuentes_en_config() -> set[tuple[str, str]]:
    config = json.loads(CONFIG_PATH.read_text())
    hashtags = {("hashtag", h) for h in (config.get("hashtags") or [])}
    cuentas = {("cuenta", c) for c in (config.get("cuentas_seguidas") or [])}
    return hashtags | cuentas


def resetear(escribir: bool = False) -> list[tuple[str, str, int]]:
    service = get_service()
    stats = cargar_fuentes_stats(service)
    objetivo = _fuentes_en_config()

    a_resetear = [
        (tipo, nombre, info) for (tipo, nombre), info in stats.items()
        if (tipo, nombre) in objetivo and info["intentos_sin_hit"] > 0
    ]
    if not a_resetear:
        print("[resetear_fuentes_stats] Nada para resetear")
        return []

    for tipo, nombre, info in a_resetear:
        print(f"[resetear_fuentes_stats] {tipo} {nombre}: {info['intentos_sin_hit']} -> 0{'' if escribir else ' (dry-run)'}")

    if not escribir:
        print(f"\n[resetear_fuentes_stats] {len(a_resetear)} fuente(s), dry-run — correr con --escribir para aplicar.")
        return [(t, n, i["intentos_sin_hit"]) for t, n, i in a_resetear]

    updates = [
        {"range": f"{FUENTES_STATS_SHEET_NAME}!C{info['fila']}", "values": [["0"]]}
        for _, _, info in a_resetear
    ]
    service.spreadsheets().values().batchUpdate(
        spreadsheetId=SPREADSHEET_ID,
        body={"valueInputOption": "RAW", "data": updates},
    ).execute()
    print(f"[resetear_fuentes_stats] {len(a_resetear)} fuente(s) reseteada(s)")
    return [(t, n, i["intentos_sin_hit"]) for t, n, i in a_resetear]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--escribir", action="store_true", help="Aplica el reset (default: dry-run)")
    args = parser.parse_args()
    resetear(escribir=args.escribir)


if __name__ == "__main__":
    main()
