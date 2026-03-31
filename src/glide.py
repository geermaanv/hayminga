"""
glide.py
Escribe eventos directamente en Glide Tables via API interna.
Usa columna 'procesado' en Google Sheets para deduplicación.
"""

import json
import uuid
import time
import os
import requests
from datetime import datetime

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

APP_ID = "vecHaq4izl5UJg73ROm7"
TABLE_NAME = "native-table-VkXzhDu5bqR3gxbKBrbt"
DEVICE_ID = "OdykpGGHmwH7CQlPpDwC"
ENDPOINT = "https://hayminga.glide.page/api/container/playerFunctionSmall/enqueueDataAction"

SPREADSHEET_ID = os.environ["GOOGLE_SPREADSHEET_ID"]
SHEET_NAME = "Eventos"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

HEADERS = {
    "Content-Type": "application/json",
    "Origin": "https://hayminga.glide.page",
    "Referer": "https://hayminga.glide.page/",
}

COLUMNS = [
    "Activo", "Nombre", "Dirección", "Fecha_Inicio", "Fecha_Fin",
    "Es_Virtual", "Provincia", "Descripción", "Organizador",
    "Link_Promocion", "Tipo_Evento", "img", "procesado",
]


def get_sheets_service():
    creds_json = os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]
    creds_dict = json.loads(creds_json)
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    return build("sheets", "v4", credentials=creds)


def ensure_header(service):
    result = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=SPREADSHEET_ID, range=f"{SHEET_NAME}!1:1")
        .execute()
    )
    if not result.get("values"):
        service.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=f"{SHEET_NAME}!A1",
            valueInputOption="RAW",
            body={"values": [COLUMNS]},
        ).execute()
        print("[sheets] Header creado")


def load_processed_names(service) -> set:
    try:
        result = (
            service.spreadsheets()
            .values()
            .get(spreadsheetId=SPREADSHEET_ID, range=f"{SHEET_NAME}!M:M")
            .execute()
        )
        values = result.get("values", [])
        return {row[0].strip().lower() for row in values[1:] if row}
    except Exception:
        return set()


def register_event(service, event: dict):
    row = [
        "true",
        event.get("nombre") or "",
        event.get("lugar") or "",
        event.get("fecha_inicio") or "",
        event.get("fecha_fin") or "",
        "true" if event.get("es_virtual") else "false",
        event.get("provincia") or "",
        event.get("descripcion") or "",
        event.get("organizador") or "",
        event.get("link_promocional") or "",
        event.get("tipo_evento") or "",
        event.get("imagen_url") or "",
        (event.get("nombre") or "").strip().lower(),
    ]
    service.spreadsheets().values().append(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{SHEET_NAME}!A1",
        valueInputOption="RAW",
        insertDataOption="INSERT_ROWS",
        body={"values": [row]},
    ).execute()


def date_to_glide_timestamp(date_str: str) -> dict | None:
    if not date_str:
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(date_str.strip(), fmt)
            return {"kind": "glide-date-time", "value": int(dt.timestamp() * 1000), "tzOffset": None}
        except ValueError:
            continue
    return None


def generate_row_id() -> str:
    import base64
    return base64.urlsafe_b64encode(uuid.uuid4().bytes[:16]).decode().rstrip("=")


def add_row_to_glide(event: dict) -> bool:
    job_id = str(uuid.uuid4()).replace("-", "")[:20]
    row_id = generate_row_id()
    req_id = str(uuid.uuid4()).replace("-", "")[:20]

    fecha_inicio = date_to_glide_timestamp(event.get("fecha_inicio"))
    fecha_fin = date_to_glide_timestamp(event.get("fecha_fin"))

    column_values = {"$rowID": row_id, "Estado": True}

    def add_if(key, val):
        if val:
            column_values[key] = val

    add_if("Nombre", event.get("nombre"))
    add_if("Dirección", event.get("lugar"))
    add_if("Descripción", event.get("descripcion"))
    add_if("Organizador", event.get("organizador"))
    add_if("Link", event.get("link_promocional"))
    add_if("3pjMi", event.get("tipo_evento"))
    add_if("Hr0F2", event.get("imagen_url"))
    add_if("pS1BP", event.get("provincia"))

    if event.get("es_virtual") is not None:
        column_values["Modalidad"] = bool(event.get("es_virtual"))
    if fecha_inicio:
        column_values["Fecha"] = fecha_inicio
    if fecha_fin:
        column_values["RigtA"] = fecha_fin

    payload = {
        "appID": APP_ID,
        "kind": "add-row-to-table",
        "actionMetadata": {
            "jobID": job_id,
            "deviceID": DEVICE_ID,
            "appID": APP_ID,
        },
        "payload": {
            "tableName": {"name": TABLE_NAME, "isSpecial": False},
            "columnValues": column_values,
            "fromBuilder": False,
            "fromDataEditor": False,
            "writeSource": "player",
        },
    }

    try:
        resp = requests.post(
            f"{ENDPOINT}?reqid={req_id}",
            headers=HEADERS,
            json=payload,
            timeout=15,
        )
        if resp.status_code == 200:
            print(f"[glide] ✓ '{event.get('nombre')}'")
            return True
        else:
            print(f"[glide] Error {resp.status_code}: {resp.text}")
            return False
    except Exception as e:
        print(f"[glide] Error: {e}")
        return False


def add_events(events: list[dict]) -> int:
    if not events:
        return 0

    service = get_sheets_service()
    ensure_header(service)
    processed = load_processed_names(service)
    print(f"[glide] {len(processed)} evento(s) ya en el registro")

    inserted = 0
    for event in events:
        nombre = (event.get("nombre") or "").strip()
        if not nombre:
            continue
        if nombre.lower() in processed:
            print(f"[glide] Duplicado, saltando: '{nombre}'")
            continue

        success = add_row_to_glide(event)
        if success:
            register_event(service, event)
            processed.add(nombre.lower())
            inserted += 1
            time.sleep(0.5)

    print(f"[glide] {inserted} evento(s) insertado(s)")
    return inserted
