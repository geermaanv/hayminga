"""Aviso por Telegram al terminar la corrida de import-eventos.

Corre con `if: always()` en el workflow: el punto es enterarse de que una
corrida falló sin tener que entrar a mirar Actions. Hasta ahora un run
cancelado por timeout o una sección caída por SSLEOFError pasaban
silenciosos (pasó varias veces en agosto 2026).

No es un mensaje a usuarios finales, es operativo para el mantenedor, así
que no lleva el recordatorio de cómo sumar eventos.
"""
import json
import os
from pathlib import Path

import requests

from .sheets import COLUMNS, SHEET_NAME, SPREADSHEET_ID, get_service

RESUMEN_PATH = Path("run_summary.json")


def contar_estados() -> tuple[int, int]:
    """(pendientes de confirmar, publicados). Publicado = Activo true, que es
    exactamente lo que el sitio muestra."""
    service = get_service()
    values = (
        service.spreadsheets().values()
        .get(spreadsheetId=SPREADSHEET_ID, range=f"{SHEET_NAME}!A2:U")
        .execute()
    ).get("values", [])
    pendientes = publicados = 0
    for row in values:
        row = (row + [""] * len(COLUMNS))[:len(COLUMNS)]
        if (row[16] or "").strip().lower() == "pendiente_confirmacion":
            pendientes += 1
        if (row[0] or "").strip().lower() == "true":
            publicados += 1
    return pendientes, publicados


def armar_mensaje(estado_job: str) -> str:
    resumen = {}
    if RESUMEN_PATH.exists():
        try:
            resumen = json.loads(RESUMEN_PATH.read_text())
        except Exception:
            resumen = {}

    icono = "OK" if estado_job == "success" else "FALLA"
    lineas = [f"[hayminga] Corrida de import: {icono} ({estado_job})"]

    if resumen:
        lineas.append(f"Eventos nuevos guardados: {resumen.get('eventos_insertados', 0)}")
        error_cuentas = resumen.get("error_cuentas_seguidas") or ""
        if error_cuentas:
            lineas.append(f"Sección cuentas seguidas CAYÓ: {error_cuentas[:120]}")
        else:
            lineas.append("Sección cuentas seguidas: ok")
    else:
        lineas.append("El pipeline no llegó a terminar (sin resumen) — revisar Actions.")

    try:
        pendientes, publicados = contar_estados()
        lineas.append(f"Pendientes de confirmar: {pendientes}")
        lineas.append(f"Publicados (activos): {publicados}")
        if pendientes:
            lineas.append("Revisar: https://hayminga.org/?pendientes")
    except Exception as e:
        lineas.append(f"No se pudieron contar pendientes/publicados: {e}")

    # Con /top apagado (15/08/2026) la comparación ya no existe: todos los
    # posts vienen de /recent. Se informa el volumen a secas, que sigue
    # sirviendo para notar si /recent se cae o devuelve de menos.
    atribucion = (resumen or {}).get("atribucion") or {}
    if atribucion:
        if atribucion.get("top_activo"):
            lineas.append(
                f"recent vs top — recent: {atribucion.get('posts_recent', 0)} posts, "
                f"top: {atribucion.get('posts_top', 0)} posts, "
                f"solo en recent: {atribucion.get('solo_en_recent', 0)}, "
                f"eventos que aportó solo recent: {atribucion.get('eventos_solo_recent', 0)}"
            )
        else:
            lineas.append(
                f"Posts por hashtag (recent): {atribucion.get('posts_recent', 0)} — top apagado"
            )

    return "\n".join(lineas)


def notificar():
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    mensaje = armar_mensaje(os.environ.get("ESTADO_JOB", "desconocido"))
    print(mensaje)
    resp = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        # Sin parse_mode a propósito: el Markdown de Telegram rompe con
        # nombres de evento que traen guiones bajos o asteriscos.
        json={"chat_id": chat_id, "text": mensaje, "disable_web_page_preview": True},
        timeout=30,
    )
    resp.raise_for_status()


if __name__ == "__main__":
    notificar()
