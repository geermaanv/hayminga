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


def _formatear_duracion(segundos: float) -> str:
    minutos, seg = divmod(round(segundos), 60)
    return f"{minutos}m {seg}s" if minutos else f"{seg}s"


def contar_pendientes() -> int:
    """Tamaño total de la cola de revisión (?pendientes), no solo lo que
    entró en esta corrida — para saber si hay que ir a revisar."""
    service = get_service()
    values = (
        service.spreadsheets().values()
        .get(spreadsheetId=SPREADSHEET_ID, range=f"{SHEET_NAME}!A2:U")
        .execute()
    ).get("values", [])
    pendientes = 0
    for row in values:
        row = (row + [""] * len(COLUMNS))[:len(COLUMNS)]
        if (row[16] or "").strip().lower() == "pendiente_confirmacion":
            pendientes += 1
    return pendientes


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
        insertados = resumen.get("eventos_insertados", 0)
        pendientes_nuevos = resumen.get("eventos_pendientes_insertados", 0)
        confirmados_nuevos = insertados - pendientes_nuevos
        lineas.append(
            f"Eventos nuevos: {insertados} "
            f"({confirmados_nuevos} confirmados directo, {pendientes_nuevos} pendientes de revisión)"
        )
        if "duracion_segundos" in resumen:
            lineas.append(f"Duración: {_formatear_duracion(resumen['duracion_segundos'])}")
        if "llamadas_hikerapi" in resumen:
            lineas.append(f"Llamadas a HikerAPI: {resumen['llamadas_hikerapi']}")
        # Real incidente 12/09/2026: una key de HikerAPI rota hizo fallar
        # las 179 llamadas de la corrida con 401, pero como cada fuente
        # atrapa su propio error y sigue con la siguiente, el job terminó
        # "success" con 0 posts — indistinguible de un día real sin
        # eventos nuevos hasta que alguien leyó el log a mano.
        llamadas = resumen.get("llamadas_hikerapi", 0)
        errores = resumen.get("errores_hikerapi", 0)
        if llamadas and errores / llamadas >= 0.5:
            lineas.append(
                f"⚠️ {errores}/{llamadas} llamadas a HikerAPI fallaron con 401 "
                f"Unauthorized — revisar HIKERAPI_KEY, no es un día sin eventos"
            )
        error_cuentas = resumen.get("error_cuentas_seguidas") or ""
        if error_cuentas:
            lineas.append(f"Sección cuentas seguidas CAYÓ: {error_cuentas[:120]}")
        else:
            lineas.append("Sección cuentas seguidas: ok")
    else:
        lineas.append("El pipeline no llegó a terminar (sin resumen) — revisar Actions.")

    # Aviso a organizadores vía mail (ver ROADMAP.md, 09/2026): el evento
    # ya se publicó solo, esto es cuántos avisos + CTA (Directorio, tag a
    # @hayminga) salieron hoy. Se lista el detalle (no solo el conteo) para
    # poder revisar a mano si hace falta — ver ROADMAP.md, 14/09. Se muestra
    # siempre, incluso en 0 — antes se ocultaba la línea entera y eso se leía
    # como que el conteo nunca llegaba.
    detalle_avisos = (resumen or {}).get("avisos_organizador_detalle") or []
    enviadas_hoy = (resumen or {}).get("validaciones_organizador_enviadas", len(detalle_avisos))
    lineas.append(f"Avisos mandados a organizadores hoy: {enviadas_hoy}")
    for aviso in detalle_avisos:
        lineas.append(f"  · {aviso.get('email', '')} — {aviso.get('nombre', '')}")

    try:
        pendientes = contar_pendientes()
        sufijo = " — revisar: https://hayminga.org/?pendientes" if pendientes else ""
        lineas.append(f"Pendientes de confirmar (cola total): {pendientes}{sufijo}")
    except Exception as e:
        lineas.append(f"No se pudo contar la cola de pendientes: {e}")

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
