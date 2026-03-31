"""
sheets.py
Escribe los eventos extraídos en Google Sheets con los campos de Glide.
"""

import os
import json
from datetime import datetime

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SPREADSHEET_ID = os.environ["GOOGLE_SPREADSHEET_ID"]
SHEET_NAME = "Eventos"

COLUMNS = [
    "Activo",
    "Nombre",
    "Dirección",
    "Fecha_Inicio",
    "Modalidad",
    "Descripción",
    "Organizador",
    "Link_Promocion",
    "Tipo_Evento",
    "img",
    "Nivel_Requerido",
    "Fecha_Fin",
    "Lugares_Disponibles",
    "Es_Practico",
]


def get_service():
    creds_json = os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]
    creds_dict = json.loads(creds_json)
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    return build("sheets", "v4", credentials=creds)


def get_existing_names(service) -> set:
    result = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=SPREADSHEET_ID, range=f"{SHEET_NAME}!B:B")
        .execute()
    )
    values = result.get("values", [])
    return {row[0].strip().lower() for row in values[1:] if row}


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


def append_events(events: list[dict]) -> int:
    if not events:
        return 0

    service = get_service()
    ensure_header(service)
    existing = get_existing_names(service)

    rows = []
    for event in events:
        nombre = (event.get("nombre") or "").strip()
        if nombre.lower() in existing:
            print(f"[sheets] Duplicado, saltando: '{nombre}'")
            continue

        row = [
            "true",
            nombre,
            event.get("lugar") or "",
            event.get("fecha_inicio") or "",
            event.get("modalidad") or "",
            event.get("descripcion") or "",
            event.get("organizador") or "",
            event.get("link_promocional") or "",
            event.get("tipo_evento") or "",
            event.get("imagen_url") or "",
            event.get("nivel_requerido") or "",
            event.get("fecha_fin") or "",
            event.get("lugares_disponibles") or "",
            "true" if event.get("incluye_practica") else "false",
        ]
        rows.append(row)
        existing.add(nombre.lower())

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

    print(f"[sheets] {len(rows)} fila(s) insertada(s)")
    return len(rows)
