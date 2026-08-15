"""
reparar_imagenes.py
Recorre los eventos activos con imagen rota (link de Instagram vencido,
ver ROADMAP.md) y las re-sube a Drive: vuelve a pedirle a HikerAPI el
post por su Link_Promocion (trae un link de imagen fresco), lo baja, y
lo sube vía Apps Script (subir_imagen_a_drive) — mismo mecanismo que ya
usa hiker_pipeline.py para los eventos nuevos.

Uso manual, no corre desde ningún workflow.
"""

import requests

from src.hiker_pipeline import _hiker_key, _detectar_media_type, subir_imagen_a_drive
from src.sheets import get_service, SPREADSHEET_ID, SHEET_NAME


def imagen_rota(url: str) -> bool:
    if not url or "cdninstagram" not in url and "fbcdn" not in url:
        return False
    try:
        r = requests.get(url, timeout=10, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        return r.status_code != 200
    except Exception:
        return True


def reparar():
    service = get_service()
    result = service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID, range=f"{SHEET_NAME}!A1:X1000"
    ).execute()
    values = result.get("values", [])
    header = values[0]
    idx = {h: i for i, h in enumerate(header)}

    arregladas = 0
    sin_arreglar = 0
    for i, row in enumerate(values[1:], start=2):
        row = (row + [""] * len(header))[:len(header)]
        if row[idx["Activo"]] != "true":
            continue
        img = row[idx["img"]]
        if not imagen_rota(img):
            continue

        link = row[idx["Link_Promocion"]]
        nombre = row[idx["Nombre"]]
        if not link:
            print(f"[reparar_imagenes] {nombre}: sin Link_Promocion, no se puede reparar")
            sin_arreglar += 1
            continue

        try:
            resp = requests.get(
                "https://api.hikerapi.com/v1/media/by/url",
                params={"url": link}, headers={"x-access-key": _hiker_key()}, timeout=20,
            )
            resp.raise_for_status()
            thumb = resp.json().get("thumbnail_url")
            if not thumb:
                raise RuntimeError("sin thumbnail_url en la respuesta")

            img_resp = requests.get(thumb, timeout=20)
            img_resp.raise_for_status()
            media_type = _detectar_media_type(img_resp.content)

            drive_url = subir_imagen_a_drive(img_resp.content, media_type)
            if not drive_url:
                raise RuntimeError("subir_imagen_a_drive devolvió None")

            service.spreadsheets().values().update(
                spreadsheetId=SPREADSHEET_ID, range=f"{SHEET_NAME}!M{i}",
                valueInputOption="RAW", body={"values": [[drive_url]]},
            ).execute()
            print(f"[reparar_imagenes] ✓ {nombre}")
            arregladas += 1
        except Exception as e:
            print(f"[reparar_imagenes] ✗ {nombre}: {e}")
            sin_arreglar += 1

    print(f"[reparar_imagenes] {arregladas} arregladas, {sin_arreglar} sin arreglar")


if __name__ == "__main__":
    reparar()
