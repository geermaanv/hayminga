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
from src.sheets import append_events, event_dedupe_key
from src.candidates import CandidateStore
from src.email_intake import process_queue as process_manual_queue


def run():
    print("=== hayminga.org — pipeline v2 ===\n")
    inserted_total = 0
    candidate_store = CandidateStore()

    print("[1/4] Buscando imágenes en Google Images (última semana, isz:l)...")
    retry_items = candidate_store.load_retries()
    discovered_items = download_all()
    new_items = candidate_store.register(discovered_items)
    all_items = retry_items + new_items
    print(
        f"      {len(discovered_items)} descubierta(s), "
        f"{len(retry_items)} reintento(s), {len(all_items)} a procesar\n"
    )

    if all_items:
        print(f"[2/4] Procesando {len(all_items)} imagen(es) con Gemini/Claude...")
        events = process_batch(all_items, candidate_store=candidate_store)
        print(f"      {len(events)} evento(s) detectado(s)\n")

        if events:
            activos   = [e for e in events if e.get("activo")]
            inactivos = [e for e in events if not e.get("activo")]
            print(f"      {len(activos)} activo(s), {len(inactivos)} inactivo(s) (pasados o fuera de AR)\n")

            print("[3/4] Escribiendo en Google Sheets...")
            inserted_keys = append_events(events, return_inserted_keys=True)
            finalized_keys = set()
            for event in events:
                key = event_dedupe_key(event)
                metadata = {
                    "_candidate_row": event.get("_candidate_row"),
                    "_candidate_attempts": event.get("_candidate_attempts", 0),
                }
                if key in inserted_keys and key not in finalized_keys:
                    candidate_store.update(
                        metadata,
                        status="publicado",
                        attempts=event.get("_candidate_attempts", 0),
                        event=event,
                        event_id=event.get("id", ""),
                    )
                    finalized_keys.add(key)
                else:
                    candidate_store.update(
                        metadata,
                        status="duplicado",
                        attempts=event.get("_candidate_attempts", 0),
                        event=event,
                        reason="evento_ya_existente",
                    )
            print(f"      {len(inserted_keys)} fila(s) nueva(s) en el Sheet\n")
            inserted_total += len(inserted_keys)
    else:
        print("Sin imágenes nuevas del scraping.\n")

    print("[4/4] Procesando cola de carga manual (mail)...")
    inserted_total += process_manual_queue()

    print(f"\n=== Pipeline completado — {inserted_total} evento(s) nuevo(s) en total ===")
    return inserted_total


if __name__ == "__main__":
    result = run()
    sys.exit(0 if result is not None else 1)
