"""
sheets.py
Escribe los eventos en Google Sheets con el schema exacto de hayminga.org.
Columnas: Activo, Nombre, Dirección, Periodo, Fecha_Inicio, Fecha_Fin,
          Es_Virtual, Provincia, Descripción, Organizador, Link_Promocion,
          Tipo_Evento, img, procesado, Id, Contacto, Estado
"""

import os
import json
import uuid
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

SCOPES          = ["https://www.googleapis.com/auth/spreadsheets"]
SPREADSHEET_ID  = os.environ["GOOGLE_SPREADSHEET_ID"]
SHEET_NAME      = "Eventos"

# Nuevas columnas (Id, Contacto, Estado) van al final a propósito: así las
# columnas existentes no cambian de letra y no rompen los rangos fijos
# (ej. load_processed_names usa N:N para 'procesado').
COLUMNS = [
    "Activo", "Nombre", "Dirección", "Periodo", "Fecha_Inicio", "Fecha_Fin",
    "Es_Virtual", "Provincia", "Descripción", "Organizador",
    "Link_Promocion", "Tipo_Evento", "img", "procesado",
    "Id", "Contacto", "Estado",
]


def generate_id() -> str:
    return uuid.uuid4().hex[:10]


def get_service():
    creds_json = os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]
    creds_dict = json.loads(creds_json)
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    return build("sheets", "v4", credentials=creds)


def ensure_header(service):
    result = (
        service.spreadsheets().values()
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
    """Lee la columna 'procesado' (N) para deduplicación."""
    try:
        result = (
            service.spreadsheets().values()
            .get(spreadsheetId=SPREADSHEET_ID, range=f"{SHEET_NAME}!N:N")
            .execute()
        )
        values = result.get("values", [])
        return {row[0].strip().lower() for row in values[1:] if row}
    except Exception:
        return set()


def event_to_row(event: dict) -> list:
    nombre = (event.get("nombre") or "").strip()
    return [
        "true" if event.get("activo") else "false",
        nombre,
        event.get("direccion") or "",
        event.get("periodo") or "",
        event.get("fecha_inicio_iso") or "",
        event.get("fecha_fin_iso") or "",
        "true" if event.get("es_virtual") else "false",
        event.get("provincia") or "",
        event.get("descripcion") or "",
        event.get("organizador") or "",
        event.get("link_promocional") or "",
        event.get("tipo_evento") or "",
        event.get("imagen_url") or "",
        nombre.lower(),  # procesado — clave de deduplicación
        event.get("id") or generate_id(),
        event.get("contacto") or "",
        event.get("estado") or ("confirmado" if event.get("activo") else "pendiente"),
    ]


def append_events(events: list[dict]) -> int:
    if not events:
        return 0

    service = get_service()
    ensure_header(service)
    processed = load_processed_names(service)
    print(f"[sheets] {len(processed)} evento(s) ya registrados")

    rows = []
    for event in events:
        nombre = (event.get("nombre") or "").strip()
        if not nombre:
            continue
        if nombre.lower() in processed:
            print(f"[sheets] Duplicado, saltando: '{nombre}'")
            continue

        rows.append(event_to_row(event))
        processed.add(nombre.lower())

    if not rows:
        print("[sheets] Sin filas nuevas para insertar")
        return 0

    service.spreadsheets().values().append(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{SHEET_NAME}!A1",
        valueInputOption="RAW",
        insertDataOption="INSERT_ROWS",
        body={"values": rows},
    ).execute()

    print(f"[sheets] ✓ {len(rows)} fila(s) insertada(s)")
    return len(rows)


if __name__ == "__main__":
    import sys, json as _json
    data = _json.loads(sys.stdin.read())
    n = append_events(data)
    print(f"Insertados: {n}")
