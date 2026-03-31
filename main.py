"""
main.py
Orquesta el pipeline completo.
"""

import sys
from src.scraper import download_all
from src.processor import process_batch
from src.glide import add_events


def run():
    print("=== hayminga.org — pipeline de importación ===\n")

    # 1. Scraping
    print("[1/3] Buscando imágenes...")
    all_items = download_all()
    print(f"      {len(all_items)} imagen(es) nueva(s) en total\n")

    if not all_items:
        print("Sin imágenes nuevas. Pipeline finalizado.")
        return

    # 2. Procesamiento con Claude Vision
    print(f"[2/3] Procesando {len(all_items)} imagen(es) con Claude Vision...")
    events = process_batch(all_items)
    print(f"      {len(events)} evento(s) extraído(s)\n")

    if not events:
        print("Sin eventos válidos detectados. Pipeline finalizado.")
        return

    # 3. Escritura en Glide
    print("[3/3] Escribiendo en Glide...")
    inserted = add_events(events)
    print(f"      {inserted} evento(s) cargado(s) en Glide\n")

    print("=== Pipeline completado ===")
    return inserted


if __name__ == "__main__":
    result = run()
    sys.exit(0 if result is not None else 1)
