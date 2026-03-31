"""
glide.py
Escribe eventos directamente en Glide Tables via API interna.
No requiere autenticación — app pública.
"""

import json
import uuid
import time
import requests
from datetime import datetime

APP_ID = "vecHaq4izl5UJg73ROm7"
TABLE_NAME = "native-table-VkXzhDu5bqR3gxbKBrbt"
DEVICE_ID = "CUCtih2pK7WbOyhMBs1Z"
ENDPOINT = f"https://hayminga.glide.page/api/container/playerFunctionSmall/enqueueDataAction"

HEADERS = {
    "Content-Type": "application/json",
    "Origin": "https://hayminga.glide.page",
    "Referer": "https://hayminga.glide.page/",
}


def date_to_glide_timestamp(date_str: str) -> dict | None:
    """Convierte DD/MM/YYYY o YYYY-MM-DD a formato glide-date-time."""
    if not date_str:
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(date_str.strip(), fmt)
            timestamp_ms = int(dt.timestamp() * 1000)
            return {"kind": "glide-date-time", "value": timestamp_ms, "tzOffset": None}
        except ValueError:
            continue
    return None


def generate_row_id() -> str:
    """Genera un rowID compatible con el formato de Glide."""
    raw = uuid.uuid4().bytes[:16]
    import base64
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def add_row(event: dict) -> bool:
    """
    Agrega un evento a Glide Tables.
    Retorna True si fue exitoso.
    """
    job_id = str(uuid.uuid4()).replace("-", "")[:20]
    row_id = generate_row_id()
    req_id = str(uuid.uuid4()).replace("-", "")[:20]

    fecha_inicio = date_to_glide_timestamp(event.get("fecha_inicio") or event.get("fecha"))
    fecha_fin = date_to_glide_timestamp(event.get("fecha_fin"))

    column_values = {
        "$rowID": row_id,
        "Nombre": event.get("nombre") or "",
        "Dirección": event.get("lugar") or "",
        "Modalidad": event.get("modalidad") or "",
        "Descripción": event.get("descripcion") or "",
        "Organizador": event.get("organizador") or "",
        "Link": event.get("link_promocional") or "",
        "3pjMi": event.get("tipo_evento") or "",
        "6YHWp": event.get("nivel_requerido") or "",
        "Hr0F2": event.get("imagen_url") or "",
        "zg7Yb": bool(event.get("incluye_practica")),
    }

    if fecha_inicio:
        column_values["Fecha"] = fecha_inicio
    if fecha_fin:
        column_values["RigtA"] = fecha_fin
    if event.get("lugares_disponibles"):
        column_values["luKjF"] = int(event["lugares_disponibles"])

    payload = {
        "appID": APP_ID,
        "kind": "add-row-to-table",
        "actionMetadata": {
            "jobID": job_id,
            "deviceID": DEVICE_ID,
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
            print(f"[glide] Error {resp.status_code}: {resp.text[:200]}")
            return False
    except Exception as e:
        print(f"[glide] Error: {e}")
        return False


def add_events(events: list[dict]) -> int:
    """Agrega una lista de eventos a Glide. Retorna cantidad insertada."""
    if not events:
        return 0

    inserted = 0
    for event in events:
        success = add_row(event)
        if success:
            inserted += 1
        time.sleep(0.5)  # evitar rate limiting

    print(f"[glide] {inserted} evento(s) insertado(s)")
    return inserted
