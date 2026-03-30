"""
sheets.py
Escribe los eventos extraídos en Google Sheets.
Glide lee el Sheet automáticamente.
"""

import os
import json
from datetime import datetime
from pathlib import Path

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SPREADSHEET_ID = os.environ["GOOGLE_SPREADSHEET_ID"]
SHEET_NAME = "Eventos"

# Columnas del Sheet (deben existir en la hoja)
COLUMNS = [
    "nombre",
    "fecha",
    "lugar",
    "contacto",
    "descripcion",
    "confianza",
    "imagen_fuente",
    "fecha_importacion",
]


def get_service():
    """Autenticación con service account desde variable de entorno."""
    creds_json = os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]
    creds_dict = json.loads(creds_json)
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    return build("sheets", "v4", credentials=creds)


def get_existing_names(service) -> set:
    """Lee los nombres de eventos ya cargados para evitar duplicados."""
    result = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=SPREADSHEET_ID, range=f"{SHEET_NAME}!A:A")
        .execute()
    )
    values = result.get("values", [])
    # Salta el header (fila 1)
    return {row[0].strip().lower() for row in values[1:] if row}


def ensure_header(service):
    """Crea el header si la hoja está vacía."""
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
    """
    Agrega eventos nuevos al Sheet.
    Retorna cantidad de filas insertadas.
    """
    if not events:
        return 0

    service = get_service()
    ensure_header(service)
    existing = get_existing_names(service)

    rows = []
    today = datetime.now().strftime("%d/%m/%Y")

    for event in events:
        nombre = (event.get("nombre") or "").strip()
        if nombre.lower() in existing:
            print(f"[sheets] Duplicado, saltando: '{nombre}'")
            continue

        row = [
            nombre,
            event.get("fecha") or "",
            event.get("lugar") or "",
            event.get("contacto") or "",
            event.get("descripcion") or "",
            event.get("confianza") or "",
            event.get("imagen_fuente") or "",
            today,
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


if __name__ == "__main__":
    # Test con datos de ejemplo
    test_events = [
        {
            "nombre": "Minga de adobe en Mendoza",
            "fecha": "15/04/2025",
            "lugar": "Mendoza, Argentina",
            "contacto": "@bioconstruye_mendoza",
            "descripcion": "Construcción de muro de adobe en finca familiar",
            "confianza": "alta",
            "imagen_fuente": "test.jpg",
        }
    ]
    inserted = append_events(test_events)
    print(f"Test: {inserted} evento(s) insertado(s)")
