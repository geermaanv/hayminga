"""
email_intake.py
Procesa la cola de eventos cargados manualmente por mail (llenada por un
Apps Script que lee una casilla de Gmail — ver import/apps-script/Code.gs).
Reusa el mismo extractor que el pipeline automático (processor.py): el
cuerpo del mail hace el papel del caption de Instagram, y la imagen
adjunta (subida a Drive por el Apps Script) el papel del flyer scrapeado.
"""

import os
import json
import requests
from pathlib import Path
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

from src.processor import extract_event_data, RETRY
from src.sheets import append_events, event_dedupe_key, SPREADSHEET_ID, SCOPES

QUEUE_SHEET = "Cola_Manual"
QUEUE_RANGE = f"{QUEUE_SHEET}!A2:G"
IMAGES_DIR  = Path("images_manual")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    )
}


def get_service():
    creds_json = os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]
    creds = Credentials.from_service_account_info(json.loads(creds_json), scopes=SCOPES)
    return build("sheets", "v4", credentials=creds)


def load_pending_rows(service) -> list[dict]:
    """Lee 'Cola_Manual': Timestamp, Remitente, Asunto, CodigoReferencia,
    CuerpoTexto, ImagenDriveUrl, Procesado. Si la hoja no existe todavía
    (Apps Script no corrió aún), no hay nada que hacer."""
    try:
        result = service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID, range=QUEUE_RANGE
        ).execute()
    except Exception as e:
        print(f"[email_intake] Sin hoja '{QUEUE_SHEET}' todavía ({e})")
        return []

    rows = result.get("values", [])
    pending = []
    for i, row in enumerate(rows):
        row = (row + [""] * 7)[:7]
        timestamp, remitente, asunto, codigo, cuerpo, imagen_url, procesado = row
        status = procesado.strip().lower()
        terminal = (
            status in {"true", "duplicado"}
            or (status.startswith("error:") and status != "error: no se pudo extraer el evento")
        )
        if terminal or not imagen_url:
            continue
        pending.append({
            "sheet_row": i + 2,  # +2: la hoja empieza en A2 (fila 1 = header)
            "remitente":  remitente,
            "asunto":     asunto,
            "codigo":     codigo,
            "cuerpo":     cuerpo,
            "imagen_url": imagen_url,
            "timestamp":  timestamp,
        })
    return pending


def mark_row(service, sheet_row: int, status: str):
    service.spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{QUEUE_SHEET}!G{sheet_row}",
        valueInputOption="RAW",
        body={"values": [[status]]},
    ).execute()


def download_drive_image(drive_url: str, dest: Path) -> bool:
    try:
        resp = requests.get(drive_url, headers=HEADERS, timeout=20)
        if resp.status_code != 200 or len(resp.content) < 1000:
            return False
        dest.write_bytes(resp.content)
        return True
    except Exception as e:
        print(f"[email_intake] Error descargando imagen: {e}")
        return False


def process_queue() -> int:
    service = get_service()
    pending = load_pending_rows(service)
    if not pending:
        print("[email_intake] Sin envíos manuales pendientes")
        return 0

    print(f"[email_intake] {len(pending)} envío(s) manual(es) pendiente(s)")
    IMAGES_DIR.mkdir(exist_ok=True)
    events = []
    retry_failures = 0

    for item in pending:
        dest = IMAGES_DIR / f"manual_{item['sheet_row']}.jpg"
        if not download_drive_image(item["imagen_url"], dest):
            mark_row(service, item["sheet_row"], "error: no se pudo descargar la imagen")
            continue

        metadata = {
            "caption": item["cuerpo"],
            "link": "",
            "thumbnail": item["imagen_url"],
            "source": "email",
            "discovered_at": item["timestamp"],
        }
        outcome = extract_event_data(dest, metadata)

        if outcome is RETRY:
            mark_row(service, item["sheet_row"], "reintentar")
            retry_failures += 1
            continue
        if outcome is None:
            # alguien mandó un mail a propósito — si el extractor no lo
            # reconoce como evento, vale la pena que un humano lo revise
            # en vez de descartarlo en silencio
            mark_row(service, item["sheet_row"], "error: no es un evento")
            continue
        if not (outcome.get("nombre") or "").strip():
            mark_row(service, item["sheet_row"], "error: evento sin nombre")
            continue

        if not outcome.get("contacto") and item["remitente"]:
            outcome["contacto"] = item["remitente"]

        events.append((outcome, item["sheet_row"]))

    inserted_keys = set()
    if events:
        inserted_keys = append_events([event for event, _ in events], return_inserted_keys=True)
        confirmed_keys = set()
        for event, sheet_row in events:
            key = event_dedupe_key(event)
            if key in inserted_keys and key not in confirmed_keys:
                mark_row(service, sheet_row, "true")
                confirmed_keys.add(key)
            else:
                mark_row(service, sheet_row, "duplicado")
        print(f"[email_intake] {len(inserted_keys)} evento(s) manual(es) cargado(s)")

    if retry_failures:
        raise RuntimeError(
            f"{retry_failures} envío(s) manual(es) quedaron para reintentar"
        )
    return len(inserted_keys)


if __name__ == "__main__":
    process_queue()
