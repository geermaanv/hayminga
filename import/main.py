"""
main.py — hayminga.org pipeline v2
Google Images (última semana, imágenes grandes) → Claude Vision → Google Sheets
"""

import sys
from src.scraper import download_all
from src.processor import process_batch
from src.sheets import append_events


def run():
    print("=== hayminga.org — pipeline v2 ===\n")

    print("[1/3] Buscando imágenes en Google Images (última semana, isz:l)...")
    all_items = download_all()
    print(f"      {len(all_items)} imagen(es) nueva(s)\n")

    if not all_items:
        print("Sin imágenes nuevas. Pipeline finalizado.")
        return 0

    print(f"[2/3] Procesando {len(all_items)} imagen(es) con Claude Vision...")
    events = process_batch(all_items)
    print(f"      {len(events)} evento(s) detectado(s)\n")

    if not events:
        print("Sin eventos válidos. Pipeline finalizado.")
        return 0

    activos   = [e for e in events if e.get("activo")]
    inactivos = [e for e in events if not e.get("activo")]
    print(f"      {len(activos)} activo(s), {len(inactivos)} inactivo(s) (pasados o fuera de AR)\n")

    print("[3/3] Escribiendo en Google Sheets...")
    inserted = append_events(events)  # escribe todos, activo=false los inactivos
    print(f"      {inserted} fila(s) nueva(s) en el Sheet\n")

    print("=== Pipeline completado ===")
    return inserted


if __name__ == "__main__":
    result = run()
    sys.exit(0 if result is not None else 1)
