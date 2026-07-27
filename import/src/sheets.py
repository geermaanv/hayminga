"""
sheets.py
Escribe los eventos en Google Sheets con el schema exacto de hayminga.org.
Columnas: Activo, Nombre, Dirección, Periodo, Fecha_Inicio, Fecha_Fin,
          Es_Virtual, Provincia, Descripción, Organizador, Link_Promocion,
          Tipo_Evento, img, procesado, Id, Contacto, Estado, Pais,
          Confianza, Fuente, Fecha_Descubrimiento
"""

import os
import json
import uuid
import re
import unicodedata
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

SCOPES          = ["https://www.googleapis.com/auth/spreadsheets"]
SPREADSHEET_ID  = os.environ["GOOGLE_SPREADSHEET_ID"]
SHEET_NAME      = "Eventos"

# Nuevas columnas (Id, Contacto, Estado) van al final a propósito: así las
# columnas existentes no cambian de letra ni rompen consumidores que todavía
# esperan esas posiciones.
COLUMNS = [
    "Activo", "Nombre", "Dirección", "Periodo", "Fecha_Inicio", "Fecha_Fin",
    "Es_Virtual", "Provincia", "Descripción", "Organizador",
    "Link_Promocion", "Tipo_Evento", "img", "procesado",
    "Id", "Contacto", "Estado", "Pais",
    "Confianza", "Fuente", "Fecha_Descubrimiento",
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
    current = result.get("values", [[]])
    current = current[0] if current else []

    if not current:
        service.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=f"{SHEET_NAME}!A1",
            valueInputOption="RAW",
            body={"values": [COLUMNS]},
        ).execute()
        print("[sheets] Header creado")
    elif current != COLUMNS[: len(current)]:
        # el header existente no coincide con el prefijo esperado — no lo
        # tocamos para no romper una hoja con columnas reordenadas a mano
        print(f"[sheets] AVISO: header de la hoja no coincide con COLUMNS: {current}")
    elif len(current) < len(COLUMNS):
        # header viejo (de antes de agregar columnas nuevas al final):
        # completar las que faltan sin tocar las existentes
        faltantes = COLUMNS[len(current):]
        service.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=f"{SHEET_NAME}!{_col_letter(len(current) + 1)}1",
            valueInputOption="RAW",
            body={"values": [faltantes]},
        ).execute()
        print(f"[sheets] Header actualizado, columnas agregadas: {faltantes}")


def _col_letter(n: int) -> str:
    """1 -> A, 27 -> AA, etc."""
    letters = ""
    while n > 0:
        n, rem = divmod(n - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def _normalize_key_part(value) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").strip().lower())
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def event_dedupe_key(event: dict) -> str:
    nombre = _normalize_key_part(event.get("nombre"))
    fecha = _normalize_key_part(event.get("fecha_inicio_iso") or event.get("fecha_inicio"))
    provincia = _normalize_key_part(event.get("provincia"))
    return "|".join((nombre, fecha, provincia))


def load_processed_keys(service) -> set:
    """Construye claves nombre+fecha+provincia desde las filas existentes."""
    try:
        result = (
            service.spreadsheets().values()
            .get(spreadsheetId=SPREADSHEET_ID, range=f"{SHEET_NAME}!A2:U")
            .execute()
        )
        values = result.get("values", [])
        keys = set()
        for row in values:
            row = (row + [""] * len(COLUMNS))[:len(COLUMNS)]
            keys.add(event_dedupe_key({
                "nombre": row[1],
                "fecha_inicio_iso": row[4],
                "provincia": row[7],
            }))
        return keys
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
        event.get("pais") or "",
        event.get("confianza") or "",
        event.get("fuente") or "",
        event.get("fecha_descubrimiento") or "",
    ]


def append_events(events: list[dict], return_inserted_keys: bool = False):
    if not events:
        return set() if return_inserted_keys else 0

    service = get_service()
    ensure_header(service)
    processed = load_processed_keys(service)
    print(f"[sheets] {len(processed)} evento(s) ya registrados")

    rows = []
    inserted_keys = set()
    for event in events:
        nombre = (event.get("nombre") or "").strip()
        if not nombre:
            continue
        key = event_dedupe_key(event)
        if key in processed:
            print(f"[sheets] Duplicado, saltando: '{nombre}'")
            continue

        rows.append(event_to_row(event))
        processed.add(key)
        inserted_keys.add(key)

    if not rows:
        print("[sheets] Sin filas nuevas para insertar")
        return set() if return_inserted_keys else 0

    service.spreadsheets().values().append(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{SHEET_NAME}!A1",
        valueInputOption="RAW",
        insertDataOption="INSERT_ROWS",
        body={"values": rows},
    ).execute()

    print(f"[sheets] ✓ {len(rows)} fila(s) insertada(s)")
    return inserted_keys if return_inserted_keys else len(rows)


if __name__ == "__main__":
    import sys, json as _json
    data = _json.loads(sys.stdin.read())
    n = append_events(data)
    print(f"Insertados: {n}")
