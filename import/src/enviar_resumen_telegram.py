"""
enviar_resumen_telegram.py
Arma un resumen semanal de los próximos eventos activos y lo manda por
Telegram — pensado para que Germán lo reenvíe a mano por WhatsApp
mientras no haya una Comunidad/API de WhatsApp Business armada (ver
ROADMAP.md, Etapa 8).

Corre aparte del pipeline de descubrimiento, vía su propio workflow
semanal (enviar-resumen.yml).
"""

import os
from datetime import date, timedelta

import requests

from src.sheets import get_service, parse_fecha_flexible, SPREADSHEET_ID, SHEET_NAME

DIAS_HACIA_ADELANTE = 60
MAX_EVENTOS_EN_RESUMEN = 15


def proximos_eventos() -> list[dict]:
    service = get_service()
    result = (
        service.spreadsheets().values()
        .get(spreadsheetId=SPREADSHEET_ID, range=f"{SHEET_NAME}!A1:Y1000")
        .execute()
    )
    values = result.get("values", [])
    if not values:
        return []
    header = values[0]
    idx = {h: i for i, h in enumerate(header)}

    hoy = date.today()
    limite = hoy + timedelta(days=DIAS_HACIA_ADELANTE)

    eventos = []
    for row in values[1:]:
        row = (row + [""] * len(header))[:len(header)]
        if row[idx["Activo"]] != "true":
            continue
        fecha = parse_fecha_flexible(row[idx["Fecha_Inicio"]])
        if not fecha or not (hoy <= fecha <= limite):
            continue
        eventos.append({
            "nombre": row[idx["Nombre"]],
            "tipo_evento": row[idx["Tipo_Evento"]],
            "fecha": fecha,
            "provincia": row[idx["Provincia"]],
            "es_virtual": row[idx["Es_Virtual"]] == "true",
            "link": row[idx["Link_Promocion"]],
            # Campos que no usa el digest de Telegram pero sí el generador de
            # contenido de Instagram (contenido_instagram.py). Se leen acá
            # para no duplicar la lectura del Sheet ni el filtro de fechas.
            "id": row[idx["Id"]],
            "imagen": row[idx.get("img", 12)] if "img" in idx else "",
            "username": (row[idx["Username"]].strip().lower() if "Username" in idx else ""),
            "estado": row[idx["Estado"]] if "Estado" in idx else "",
        })

    eventos.sort(key=lambda e: e["fecha"])
    return eventos[:MAX_EVENTOS_EN_RESUMEN]


# Recordatorio de cómo aportar eventos — tiene que ir en todo mensaje
# saliente a usuarios finales (pedido explícito del usuario, ver memoria
# hayminga-outbound-messages-cta).
_CTA = (
    "¿Conocés un evento? Compartí la captura o el link por acá, mandalo "
    "por mail, o si publicás vos en Instagram taggeá #hayminga."
)


def _formatear_mensaje(eventos: list[dict]) -> str:
    if not eventos:
        return (
            "🌿 hayminga — esta semana no hay eventos nuevos confirmados "
            f"para los próximos {DIAS_HACIA_ADELANTE} días.\n\n{_CTA}"
        )

    # https://hayminga.org como primer link del mensaje a propósito: WhatsApp
    # arma la vista previa grande con el PRIMER link que encuentra en todo
    # el texto — si no, agarra el link de Instagram del primer evento y la
    # tarjeta gigante tapa el resto de la lista.
    lineas = [
        "🌿 Próximos eventos de bioconstrucción en Argentina", "",
        "https://hayminga.org", "",
        _CTA, "",
    ]
    for ev in eventos:
        fecha_str = ev["fecha"].strftime("%d/%m")
        lugar = "Virtual" if ev["es_virtual"] else (ev["provincia"] or "")
        partes = [p for p in (lugar, ev["tipo_evento"]) if p]
        encabezado = " - ".join(partes)
        linea = f"📅 {fecha_str}"
        if encabezado:
            linea += f" | {encabezado}"
        linea += f" — {ev['nombre']}"
        lineas.append(linea)
        if ev["link"]:
            lineas.append(ev["link"])
        lineas.append("")

    lineas.append(_CTA)
    return "\n".join(lineas)


def enviar_resumen():
    eventos = proximos_eventos()
    mensaje = _formatear_mensaje(eventos)

    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    # Sin parse_mode a propósito: los títulos y links son texto arbitrario
    # que no controlamos (vienen de Instagram) — un solo "_" o "*" sin
    # pareja en cualquiera de ellos rompe el parseo de Markdown de Telegram
    # y tira el mensaje entero (pasó en producción con un link real).
    resp = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": mensaje},
        timeout=20,
    )
    resp.raise_for_status()
    print(f"[enviar_resumen_telegram] {len(eventos)} evento(s) — mensaje enviado")


if __name__ == "__main__":
    enviar_resumen()
