"""
main.py
Orquesta el pipeline completo:
  1. Scraping de Google Images
  2. Extracción con Claude Vision
  3. Escritura en Google Sheets
"""

import sys
from src.scraper import download_images, HASHTAGS
from src.processor import process_batch
from src.sheets import append_events


def run():
    print("=== hayminga.org — pipeline de importación ===\n")

    # 1. Scraping
    all_images = []
    for tag in HASHTAGS:
        print(f"[1/3] Buscando imágenes para #{tag}...")
        images = download_images(tag, max_new=10)
        all_images.extend(images)
        print(f"      {len(images)} imagen(es) nueva(s)\n")

    if not all_images:
        print("Sin imágenes nuevas. Pipeline finalizado.")
        return

    # 2. Procesamiento con Claude Vision
    print(f"[2/3] Procesando {len(all_images)} imagen(es) con Claude Vision...")
    events = process_batch(all_images)
    print(f"      {len(events)} evento(s) extraído(s)\n")

    if not events:
        print("Sin eventos válidos detectados. Pipeline finalizado.")
        return

    # 3. Escritura en Google Sheets
    print("[3/3] Escribiendo en Google Sheets...")
    inserted = append_events(events)
    print(f"      {inserted} evento(s) nuevo(s) cargado(s) en Glide\n")

    print("=== Pipeline completado ===")
    return inserted


if __name__ == "__main__":
    result = run()
    sys.exit(0 if result is not None else 1)
