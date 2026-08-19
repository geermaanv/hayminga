"""
contenido_instagram.py
Arma la cola de contenido para la cuenta @hayminga de Instagram.

No publica nada: escribe filas listas para copiar y pegar en una hoja
`Instagram` del mismo Sheet. Publicar por API no se puede para lo que más
sirve —historias con sticker de mención— y los DMs automáticos van contra
los términos. Lo que se automatiza es la preparación, que es donde se va
el tiempo: a quién mencionar, qué texto, qué hashtags, y sobre todo qué
falta publicar.

Idempotente: cada pieza tiene una `Clave` determinística derivada del dato
("historia:<id de evento>", "carrusel:2026-W34"). Antes de generar lee las
claves que ya están y saltea. Correrlo cien veces produce lo mismo que
correrlo una, así que puede ir colgado de un cron frecuente sin cuidado.

IMPORTANTE para quien use la hoja: las filas no se borran, se marcan
`descartado`. El generador saltea las claves existentes en CUALQUIER
estado; si una fila se borra, la clave desaparece y la próxima corrida la
vuelve a crear. Mismo criterio que `Estado=descartado` en Eventos.
"""
from datetime import date

from src.enviar_resumen_telegram import proximos_eventos
from src.sheets import (SPREADSHEET_ID, get_or_create_sheet_with_headers,
                        get_service)

INSTAGRAM_SHEET_NAME = "Instagram"
INSTAGRAM_HEADERS = [
    "Clave", "Estado", "Tipo", "Fecha_Evento", "Titulo", "Mencionar",
    "Link_Origen", "Imagen", "Texto", "Hashtags", "Evento_Id", "Generada",
]

# Hashtags fijos y curados. NO se derivan de Hashtags_Post del evento a
# propósito: ese campo trae lo que puso cualquiera, y así es como termina
# saliendo un post de bioconstrucción con #fungi (ver el cluster de hongos
# en ROADMAP.md). Mejor una lista corta que se revisa a mano.
_HASHTAGS_BASE = (
    "#hayminga #bioconstruccion #construccionnatural #arquitecturasustentable "
    "#permacultura #construccionentierra #argentina"
)

# Recordatorio de cómo aportar eventos: va en todo mensaje que llega a
# usuarios finales (ver memoria hayminga-outbound-messages-cta). En la
# historia se usa la versión corta — no entra un párrafo en una story.
_CTA_LARGO = (
    "¿Organizás algo? Taggeá #hayminga cuando lo publiques y lo tomamos "
    "solos, o mandanos el flyer por WhatsApp o mail."
)
_CTA_CORTO = "Taggeá #hayminga y lo publicamos 🌿"

_MESES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
          "agosto", "septiembre", "octubre", "noviembre", "diciembre")


def _fecha_legible(f: date) -> str:
    return f"{f.day} de {_MESES[f.month - 1]}"


def _claves_existentes(service) -> set[str]:
    get_or_create_sheet_with_headers(service, INSTAGRAM_SHEET_NAME, INSTAGRAM_HEADERS)
    values = (
        service.spreadsheets().values()
        .get(spreadsheetId=SPREADSHEET_ID, range=f"{INSTAGRAM_SHEET_NAME}!A2:A")
        .execute()
    ).get("values", [])
    return {row[0].strip() for row in values if row and row[0].strip()}


def _fila(clave, tipo, fecha_evento, titulo, mencionar, link, imagen, texto, evento_id=""):
    return [clave, "pendiente", tipo, fecha_evento, titulo, mencionar,
            link, imagen, texto, _HASHTAGS_BASE, evento_id,
            date.today().isoformat()]


def _pieza_historia(ev: dict) -> list:
    """Una historia por evento. El flujo real es abrir el post original en
    Instagram y compartirlo a la historia, así que lo que importa es el
    Link_Origen — no hace falta subir la imagen ni escribir mucho."""
    donde = "Online" if ev["es_virtual"] else (ev["provincia"] or "Argentina")
    mencion = f"@{ev['username']}" if ev["username"] else ""
    texto = (
        f"{_fecha_legible(ev['fecha'])} · {donde}\n"
        f"{ev['nombre']}\n"
        + (f"por {mencion}\n" if mencion else "")
        + "\nhayminga.org"
    )
    return _fila(
        clave=f"historia:{ev['id']}", tipo="historia_evento",
        fecha_evento=ev["fecha"].isoformat(),
        titulo=ev["nombre"][:60], mencionar=mencion,
        link=ev["link"], imagen=ev.get("imagen") or "", texto=texto,
        evento_id=ev["id"],
    )


def _pieza_carrusel(eventos: list[dict], hoy: date) -> list:
    """Un carrusel semanal con los próximos eventos. El texto de cada placa
    va numerado en el mismo campo: las imágenes se arman a mano (Canva), lo
    que se automatiza es no tener que redactar ni ordenar nada."""
    anio, semana, _ = hoy.isocalendar()
    placas = [f"[placa 1] Próximos eventos de bioconstrucción\nhayminga.org"]
    for i, ev in enumerate(eventos, start=2):
        donde = "Online" if ev["es_virtual"] else (ev["provincia"] or "")
        placas.append(f"[placa {i}] {_fecha_legible(ev['fecha'])} · {donde}\n{ev['nombre']}")

    menciones = " ".join(sorted({f"@{e['username']}" for e in eventos if e["username"]}))
    caption = (
        "Lo que viene en bioconstrucción 🌿\n\n"
        + "\n".join(f"· {_fecha_legible(e['fecha'])} — {e['nombre']}" for e in eventos)
        + "\n\nTodos los eventos, con fecha y lugar, en hayminga.org\n\n"
        + _CTA_LARGO
        + (f"\n\nGracias a {menciones}" if menciones else "")
    )
    return _fila(
        clave=f"carrusel:{anio}-W{semana:02d}", tipo="carrusel_semanal",
        fecha_evento=hoy.isoformat(),
        titulo=f"Carrusel semana {anio}-W{semana:02d} ({len(eventos)} eventos)",
        mencionar=menciones, link="", imagen="",
        texto="\n\n".join(placas) + "\n\n--- CAPTION ---\n\n" + caption,
    )


def generar(service=None, hoy: date | None = None) -> int:
    """Agrega a la hoja Instagram las piezas que faltan. Devuelve cuántas."""
    service = service or get_service()
    hoy = hoy or date.today()

    # Solo eventos ya confirmados: mientras REVISION_MANUAL esté en true todo
    # entra como pendiente, y no corresponde promocionar algo sin revisar.
    eventos = [e for e in proximos_eventos()
               if (e.get("estado") or "").strip().lower() == "confirmado"]

    existentes = _claves_existentes(service)
    filas = []

    for ev in eventos:
        if not ev.get("id") or f"historia:{ev['id']}" in existentes:
            continue
        filas.append(_pieza_historia(ev))

    anio, semana, _ = hoy.isocalendar()
    if eventos and f"carrusel:{anio}-W{semana:02d}" not in existentes:
        filas.append(_pieza_carrusel(eventos[:8], hoy))

    if not filas:
        print("[contenido_instagram] Sin piezas nuevas")
        return 0

    service.spreadsheets().values().append(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{INSTAGRAM_SHEET_NAME}!A1",
        valueInputOption="RAW", insertDataOption="INSERT_ROWS",
        body={"values": filas},
    ).execute()
    print(f"[contenido_instagram] {len(filas)} pieza(s) nueva(s) en la cola")
    return len(filas)


if __name__ == "__main__":
    generar()
