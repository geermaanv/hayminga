"""
email_intake.py
Procesa la cola de eventos cargados manualmente por mail (llenada por un
Apps Script que lee una casilla de Gmail — ver import/apps-script/Code.gs).
Reusa el mismo extractor que el pipeline automático (processor.py): el
cuerpo del mail hace el papel del caption de Instagram, y la imagen
adjunta (subida a Drive por el Apps Script) el papel del flyer scrapeado.
"""

import os
import re
import json
import html
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


URL_RE = re.compile(r"https?://\S+")


def extract_link(texto: str) -> str:
    """Saca el primer link del cuerpo del mail; prioriza uno de Instagram
    si hay varios, porque suele ser el que corresponde al evento."""
    urls = [u.rstrip(".,;)>\"'") for u in URL_RE.findall(texto or "")]
    for url in urls:
        if "instagram.com" in url:
            return url
    return urls[0] if urls else ""


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
        if terminal:
            continue
        if not imagen_url and not extract_link(cuerpo):
            # sin imagen adjunta y sin link, no hay de dónde sacar el flyer
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


OG_IMAGE_RE = re.compile(r'property="og:image"\s+content="([^"]+)"')

# Instagram le sirve al navegador una app de React sin meta tags en el HTML
# inicial (las arma con JS), pero a los bots conocidos de vista previa
# (Facebook, WhatsApp, etc.) les sirve una versión server-rendered con
# og:image — usamos ese mismo user-agent para poder leerla.
CRAWLER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; facebookexternalhit/1.1; "
        "+http://www.facebook.com/externalhit_uatext.php)"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
}


def download_instagram_image(link: str, dest: Path) -> str:
    """Cuando alguien comparte solo el link del post (sin adjuntar el
    flyer), bajamos la imagen directo del post público vía su etiqueta
    og:image — la misma que usa WhatsApp para armar la vista previa.
    Devuelve la URL de esa imagen (para guardarla como thumbnail) o ''
    si no se pudo."""
    try:
        page = requests.get(link, headers=CRAWLER_HEADERS, timeout=20)
        match = OG_IMAGE_RE.search(page.text)
        if not match:
            return ""
        img_url = html.unescape(match.group(1))
        resp = requests.get(img_url, headers=HEADERS, timeout=20)
        if resp.status_code != 200 or len(resp.content) < 1000:
            return ""
        dest.write_bytes(resp.content)
        return img_url
    except Exception as e:
        print(f"[email_intake] Error bajando imagen de Instagram: {e}")
        return ""


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
        link = extract_link(item["cuerpo"])

        thumbnail = item["imagen_url"]
        if thumbnail:
            ok = download_drive_image(thumbnail, dest)
        elif link:
            thumbnail = download_instagram_image(link, dest)
            ok = bool(thumbnail)
        else:
            ok = False

        if not ok:
            mark_row(service, item["sheet_row"], "error: no se pudo descargar la imagen")
            continue

        metadata = {
            "caption": item["cuerpo"],
            "link": link,
            "thumbnail": thumbnail,
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
