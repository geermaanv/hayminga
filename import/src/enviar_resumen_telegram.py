"""
enviar_resumen_telegram.py
Arma un resumen semanal de los próximos eventos activos y lo manda por
Telegram — pensado para que Germán lo reenvíe a mano por WhatsApp
mientras no haya una Comunidad/API de WhatsApp Business armada (ver
ROADMAP.md, Etapa 8) — y, con el mismo texto, al Directorio por mail.

Corre aparte del pipeline de descubrimiento, vía su propio workflow
semanal (enviar-resumen.yml).

Única fuente de verdad del resumen (07/10, ver ROADMAP.md): hasta esa
fecha Code.gs tenía su propia copia de esta lógica (`enviarResumenSemanalDirectorio`,
con su propio fetch de eventos y su propio parser de fecha) para mandar
el mismo resumen por mail al Directorio — y esa copia se desincronizó en
silencio: parseaba solo DD/MM/YYYY mientras Python escribe Fecha_Inicio
en ISO desde hace semanas, así que el mail del Directorio venía vacío de
eventos reales. Ahora Python es la única fuente de verdad: arma el texto
una vez y le pide a Code.gs (acción `enviar_resumen_directorio`, mismo
canal de secreto compartido que `avisar_evento_publicado`) que lo mande
a cada persona del Directorio con consentimiento — Code.gs ya no vuelve
a leer eventos ni a parsear fechas, solo manda el mail.
"""

import json
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


_ASUNTO_EMAIL = "Nuevos cursos, talleres y eventos de bioconstrucción — hayminga.org"


def _enviar_email_directorio(texto: str) -> bool:
    """Le pide a Code.gs que mande el mismo texto por mail a cada persona
    del Directorio con consentimiento — Code.gs solo relay (lee la lista
    de emails y manda), no vuelve a calcular eventos ni a parsear fechas.
    Best-effort: si falla, el envío a Telegram ya salió y no se pierde
    nada — solo no hay mail esta semana, igual que cualquier otro fallo
    de Apps Script en el pipeline (ver avisar_evento_publicado)."""
    apps_script_url = os.environ.get("APPS_SCRIPT_URL")
    secreto = os.environ.get("APPS_SCRIPT_SHARED_SECRET")
    if not apps_script_url or not secreto:
        print("[enviar_resumen_telegram] APPS_SCRIPT_URL/APPS_SCRIPT_SHARED_SECRET no configurados — sin mail al Directorio")
        return False
    try:
        resp = requests.post(
            apps_script_url,
            headers={"Content-Type": "text/plain"},
            data=json.dumps({
                "accion": "enviar_resumen_directorio",
                "secreto": secreto,
                "asunto": _ASUNTO_EMAIL,
                "texto": texto,
            }),
            timeout=30,
        )
        data = resp.json()
        ok = bool(data.get("success"))
        if ok:
            print(f"[enviar_resumen_telegram] mail al Directorio enviado a {data.get('enviados', '?')} persona(s)")
        else:
            print(f"[enviar_resumen_telegram] Code.gs respondió error mandando el mail al Directorio — {data.get('error')}")
        return ok
    except Exception as e:
        print(f"[enviar_resumen_telegram] error pidiéndole a Code.gs el mail al Directorio — {e}")
        return False


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

    _enviar_email_directorio(mensaje)


if __name__ == "__main__":
    enviar_resumen()
