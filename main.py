"""
main.py
Orquesta el pipeline completo:
  1. Scraping de Google Images via SerpAPI
  2. Extracción con Claude Vision
  3. Escritura directa en Glide Tables
"""

import sys
from src.scraper import download_images, HASHTAGS
from src.processor import process_batch
from src.glide import add_events


def run():
    print("=== hayminga.org — pipeline de importación ===\n")

    # 1. Scraping
    all_items = []
    for tag in HASHTAGS:
        print(f"[1/3] Buscando imágenes para #{tag}...")
        items = download_images(tag, max_new=10)
        all_items.extend(items)
        print(f"      {len(items)} imagen(es) nueva(s)\n")

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

    # 3. Escritura directa en Glide
    print("[3/3] Escribiendo en Glide...")
    inserted = add_events(events)
    print(f"      {inserted} evento(s) cargado(s) en Glide\n")

    print("=== Pipeline completado ===")
    return inserted


if __name__ == "__main__":
    result = run()
    sys.exit(0 if result is not None else 1)
