"""
main.py — hayminga.org pipeline v2
Google Images (última semana, imágenes grandes) → Gemini Vision (Claude
como fallback) → Google Sheets. También procesa la cola de eventos
cargados manualmente por mail (ver src/email_intake.py).
"""

import sys
from dotenv import load_dotenv

load_dotenv()

from src.scraper import download_all
from src.processor import process_batch
from src.sheets import append_events
from src.email_intake import process_queue as process_manual_queue


def run():
    print("=== hayminga.org — pipeline v2 ===\n")
    inserted_total = 0

    print("[1/4] Buscando imágenes en Google Images (última semana, isz:l)...")
    all_items = download_all()
    print(f"      {len(all_items)} imagen(es) nueva(s)\n")

    if all_items:
        print(f"[2/4] Procesando {len(all_items)} imagen(es) con Gemini/Claude...")
        events = process_batch(all_items)
        print(f"      {len(events)} evento(s) detectado(s)\n")

        if events:
            activos   = [e for e in events if e.get("activo")]
            inactivos = [e for e in events if not e.get("activo")]
            print(f"      {len(activos)} activo(s), {len(inactivos)} inactivo(s) (pasados o fuera de AR)\n")

            print("[3/4] Escribiendo en Google Sheets...")
            inserted = append_events(events)  # escribe todos, activo=false los inactivos
            print(f"      {inserted} fila(s) nueva(s) en el Sheet\n")
            inserted_total += inserted
    else:
        print("Sin imágenes nuevas del scraping.\n")

    print("[4/4] Procesando cola de carga manual (mail)...")
    inserted_total += process_manual_queue()

    print(f"\n=== Pipeline completado — {inserted_total} evento(s) nuevo(s) en total ===")
    return inserted_total


if __name__ == "__main__":
    result = run()
    sys.exit(0 if result is not None else 1)
