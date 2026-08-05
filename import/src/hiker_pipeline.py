"""
hiker_pipeline.py
Pipeline de descubrimiento nuevo, basado 100% en HikerAPI (sin Google
Images/SerpAPI/Serper y sin la capa defensiva que existía para compensar
sus problemas — ver ROADMAP.md, sección "Etapa 10").

Por cada hashtag: una llamada trae varios posts recientes, cada uno ya
con imagen completa, caption entero, fecha real de publicación y
ubicación (lat/lng si el que publicó la etiqueteó). Con eso:

1. Si el link ya está en el Sheet, se descarta antes de gastar una
   llamada a la IA.
2. Primer intento de extracción SOLO CON TEXTO (más rápido/liviano que
   mandar la imagen). Si falta algo clave (nombre, fecha o si no está
   claro si es evento), se reintenta con la imagen.
3. Se valida y se escribe al Sheet — `append_events` ya se encarga del
   dedup por nombre+fecha+provincia (agarra reposteos con link distinto
   del mismo evento).
4. Si algo del batch falla puntualmente, se loguea y se sigue: no hay
   cola de reintentos — "no pasa nada si falla un día".

Confianza alta → se publica solo. Media/baja → pendiente_confirmacion
(mismo mecanismo de revisión manual que ya existe).
"""

import os
import re
import time
import json
import base64
import requests
from pathlib import Path
from datetime import datetime, timezone

from google import genai
from google.genai import types
from google.genai import errors as genai_errors
import anthropic

from src.processor import (
    EVENT_SCHEMA, SYSTEM_PROMPT, GEMINI_MODEL, CLAUDE_MODEL,
    validate_event_data,
)
from src.sheets import append_events, get_service, instagram_shortcode, SPREADSHEET_ID, SHEET_NAME

IMAGES_DIR = Path("images_hiker")

PROMPT_SOLO_TEXTO = (
    "Extraé los datos de este posteo de Instagram usando SOLO el texto "
    "de abajo (todavía no tenés la imagen del flyer)."
)
PROMPT_CON_IMAGEN = "Extraé los datos de este flyer de evento."


def _hiker_key() -> str:
    key = os.environ.get("HIKERAPI_KEY")
    if not key:
        raise RuntimeError("HIKERAPI_KEY no configurada")
    return key


def fetch_hashtag_posts(hashtag: str, amount: int = 30) -> list[dict]:
    # hashtag/medias/recent devuelve siempre [] (esa pestaña de Instagram
    # está más restringida); hashtag/medias/top sí trae datos reales.
    resp = requests.get(
        "https://api.hikerapi.com/v1/hashtag/medias/top",
        params={"name": hashtag, "amount": amount},
        headers={"x-access-key": _hiker_key()},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    items = data if isinstance(data, list) else data.get("items", [])
    posts = []
    for item in items:
        code = item.get("code")
        image_url = item.get("thumbnail_url") or ""
        if not code or not image_url:
            continue
        location = item.get("location") or {}
        posts.append({
            "link": f"https://www.instagram.com/p/{code}/",
            "image_url": image_url,
            "caption": item.get("caption_text") or "",
            "taken_at_ts": item.get("taken_at_ts"),
            "lat": location.get("lat"),
            "lng": location.get("lng"),
            "location_name": location.get("name") or "",
            "location_address": location.get("address") or "",
        })
    return posts


def _download_image(url: str, dest: Path) -> bool:
    resp = requests.get(url, timeout=20)
    if resp.status_code != 200 or len(resp.content) < 1000:
        return False
    dest.write_bytes(resp.content)
    return True


def _detectar_media_type(image_bytes: bytes) -> str:
    """El nombre de archivo siempre es .jpg (ver _download_image), pero el
    contenido real puede ser otra cosa — Instagram sirve thumbnails en
    webp bastante seguido. Claude rechaza la llamada si el media_type no
    coincide con los bytes reales, así que hay que mirar los magic bytes."""
    if image_bytes[:4] == b"RIFF" and image_bytes[8:12] == b"WEBP":
        return "image/webp"
    if image_bytes[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    return "image/jpeg"


def _fecha_publicacion(post: dict) -> str:
    if not post.get("taken_at_ts"):
        return ""
    return datetime.fromtimestamp(post["taken_at_ts"], tz=timezone.utc).date().isoformat()


def _prompt_texto(post: dict) -> str:
    fecha_pub = _fecha_publicacion(post)
    partes = [PROMPT_SOLO_TEXTO]
    if fecha_pub:
        partes.append(f"Fecha de publicación: {fecha_pub}")
    partes.append(f"Caption:\n{post['caption']}")
    return "\n\n".join(partes)


def _prompt_imagen(post: dict) -> str:
    fecha_pub = _fecha_publicacion(post)
    partes = [PROMPT_CON_IMAGEN]
    if fecha_pub:
        partes.append(f"Fecha de publicación: {fecha_pub}")
    if post.get("caption"):
        partes.append(f"Caption:\n{post['caption']}")
    return "\n\n".join(partes)


# El free tier de Gemini para este modelo permite 15 llamadas/minuto; con
# facturación activada en el proyecto el límite sube muchísimo (cientos/
# miles de RPM). Configurable por env var para no tener que tocar código
# si el límite real cambia — default conservador por si corre sin billing.
_GEMINI_MIN_INTERVAL = float(os.environ.get("GEMINI_MIN_INTERVAL_SECONDS", "4.5"))
_ultima_llamada_gemini = 0.0


def _esperar_turno_gemini():
    global _ultima_llamada_gemini
    espera = _GEMINI_MIN_INTERVAL - (time.monotonic() - _ultima_llamada_gemini)
    if espera > 0:
        time.sleep(espera)
    _ultima_llamada_gemini = time.monotonic()


# Claude es pago (a diferencia de Gemini free tier): si Gemini se queda sin
# cuota diaria a mitad de corrida, sin este techo se cae a Claude para todo
# el resto del batch. Con esto, superado el límite simplemente se skipea
# el resto (mismo criterio de "no pasa nada si falla un día").
_MAX_CLAUDE_CALLS = int(os.environ.get("MAX_CLAUDE_CALLS_PER_RUN", "15"))
_claude_calls = 0


class _ClaudeLimitExceeded(Exception):
    pass


def _llamar_claude_con_limite(fn, *args):
    global _claude_calls
    if _claude_calls >= _MAX_CLAUDE_CALLS:
        raise _ClaudeLimitExceeded()
    _claude_calls += 1
    return fn(*args)


def _call_gemini_text(prompt_text: str) -> str:
    _esperar_turno_gemini()
    api_key = os.environ["GEMINI_API_KEY"]
    # Sin esto, una llamada colgada (red/servidor) bloquea el proceso
    # entero indefinidamente — pasó en un run real: 2 hashtags procesados
    # en 30s y después 44 minutos sin ningún log hasta que el timeout del
    # workflow lo canceló.
    client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=30_000))
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=[prompt_text],
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_schema=EVENT_SCHEMA,
            thinking_config=types.ThinkingConfig(thinking_level="minimal"),
            max_output_tokens=2048,
        ),
    )
    return (response.text or "").strip()


def _call_gemini_image(image_bytes: bytes, media_type: str, prompt_text: str) -> str:
    _esperar_turno_gemini()
    api_key = os.environ["GEMINI_API_KEY"]
    # Sin esto, una llamada colgada (red/servidor) bloquea el proceso
    # entero indefinidamente — pasó en un run real: 2 hashtags procesados
    # en 30s y después 44 minutos sin ningún log hasta que el timeout del
    # workflow lo canceló.
    client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=30_000))
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=[types.Part.from_bytes(data=image_bytes, mime_type=media_type), prompt_text],
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_schema=EVENT_SCHEMA,
            thinking_config=types.ThinkingConfig(thinking_level="minimal"),
            max_output_tokens=2048,
        ),
    )
    return (response.text or "").strip()


def _call_claude_text(prompt_text: str) -> str:
    api_key = os.environ["ANTHROPIC_API_KEY"]
    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt_text}],
    )
    raw = response.content[0].text.strip()
    return raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()


def _call_claude_image(image_bytes: bytes, media_type: str, prompt_text: str) -> str:
    api_key = os.environ["ANTHROPIC_API_KEY"]
    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {
                    "type": "base64", "media_type": media_type,
                    "data": base64.standard_b64encode(image_bytes).decode("utf-8"),
                }},
                {"type": "text", "text": prompt_text},
            ],
        }],
    )
    raw = response.content[0].text.strip()
    return raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()


def _parse_json(raw: str) -> dict | None:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        decoder = json.JSONDecoder()
        for start, char in enumerate(raw):
            if char != "{":
                continue
            try:
                parsed, _ = decoder.raw_decode(raw[start:])
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                continue
        return None


def extraer_evento(post: dict, image_path: Path | None) -> dict | None:
    """Primera pasada solo con texto, nada más que para filtrar gratis lo
    que claramente no es un evento. Si SÍ es evento (o el texto no fue
    concluyente), se manda la imagen también — ya recibe el caption como
    contexto además de la foto, así que casi siempre saca más datos que
    el texto solo (dirección exacta, WhatsApp escrito en el flyer, etc.)."""
    try:
        raw = _call_gemini_text(_prompt_texto(post))
    except genai_errors.ClientError:
        try:
            raw = _llamar_claude_con_limite(_call_claude_text, _prompt_texto(post))
        except _ClaudeLimitExceeded:
            return None
    data = _parse_json(raw)

    if data is not None and not data.get("es_evento", True):
        return data  # el texto ya alcanzó para descartarlo, no gastar la imagen

    if image_path:
        image_bytes = image_path.read_bytes()
        media_type = _detectar_media_type(image_bytes)
        try:
            raw = _call_gemini_image(image_bytes, media_type, _prompt_imagen(post))
        except genai_errors.ClientError:
            try:
                raw = _llamar_claude_con_limite(_call_claude_image, image_bytes, media_type, _prompt_imagen(post))
            except _ClaudeLimitExceeded:
                return data
        data2 = _parse_json(raw)
        if data2 is not None:
            data = data2

    return data


# hashtag/medias/top trae los posteos con más likes/comentarios
# HISTÓRICAMENTE, no los recientes — mezcla contenido evergreen viejo con
# eventos nuevos reales. Casi ningún evento se anuncia con tanta
# anticipación, así que un posteo publicado hace más de esto casi seguro
# ya pasó: ni vale la pena gastar una llamada a la IA en extraerlo.
_MAX_ANTIGUEDAD_POST_DIAS = 270


def procesar_post(post: dict, existing_links: set) -> dict | None:
    # Comparar por shortcode (código del posteo), no por link exacto: el
    # mismo posteo puede llegar como /p/, /reel/ o /reels/ según quién lo
    # comparta (ej. carga manual vs. lo que arma esta función más abajo).
    shortcode = instagram_shortcode(post["link"])
    if shortcode and shortcode in existing_links:
        return None
    if post["link"] in existing_links:
        return None

    if post.get("taken_at_ts"):
        antiguedad = datetime.now(timezone.utc) - datetime.fromtimestamp(post["taken_at_ts"], tz=timezone.utc)
        if antiguedad.days > _MAX_ANTIGUEDAD_POST_DIAS:
            return None

    IMAGES_DIR.mkdir(exist_ok=True)
    image_path = IMAGES_DIR / (post["link"].rstrip("/").rsplit("/", 1)[-1] + ".jpg")
    if not _download_image(post["image_url"], image_path):
        image_path = None

    data = extraer_evento(post, image_path)
    if not data or not data.get("es_evento", True):
        return None

    data["imagen_url"] = post["image_url"]
    data["link_promocional"] = post["link"]
    data["fuente"] = "hikerapi_hashtag"
    data["fecha_descubrimiento"] = datetime.now(timezone.utc).isoformat()
    # Para más adelante: juntar hashtags de eventos activos y ver cuáles
    # no están todavía en config.json (los posts suelen traer muchos más
    # de los que buscamos nosotros).
    data["hashtags_post"] = " ".join(sorted(set(re.findall(r"#\w+", post.get("caption") or ""))))
    data = validate_event_data(data)

    # Los hashtags son globales (no hay forma de filtrar por país en la
    # búsqueda); lo que no es de Argentina se descarta acá, no tiene
    # sentido ocupar una fila del Sheet con algo que nunca va a publicarse.
    if data.get("pais") and data["pais"] != "Argentina":
        return None

    # Ubicación real etiquetada por quien publicó > geocoding de texto
    if post.get("lat") and post.get("lng"):
        data["latitud"] = post["lat"]
        data["longitud"] = post["lng"]
        if not data.get("direccion") and post.get("location_address"):
            data["direccion"] = post["location_address"]

    confianza = str(data.get("confianza") or "baja").lower()
    if data.get("activo") and confianza != "alta":
        data["activo"] = False
        data["estado"] = "pendiente_confirmacion"

    return data


def run() -> int:
    config = json.loads(Path("config.json").read_text())
    hashtags = config.get("hashtags") or []
    if not hashtags:
        print("[hiker_pipeline] Sin hashtags configurados en config.json")
        return 0

    service = get_service()
    existing = service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID, range=f"{SHEET_NAME}!K2:K",
    ).execute().get("values", [])
    existing_links = {row[0] for row in existing if row}
    print(f"[hiker_pipeline] {len(existing_links)} link(s) ya en el Sheet")

    eventos = []
    for hashtag in hashtags:
        try:
            posts = fetch_hashtag_posts(hashtag)
        except Exception as e:
            print(f"[hiker_pipeline] #{hashtag}: error consultando HikerAPI — {e}")
            continue
        print(f"[hiker_pipeline] #{hashtag}: {len(posts)} post(s)")

        for post in posts:
            try:
                evento = procesar_post(post, existing_links)
            except Exception as e:
                print(f"[hiker_pipeline] {post['link']}: error procesando — {e}")
                continue
            if evento:
                eventos.append(evento)
                existing_links.add(post["link"])

    inserted = append_events(eventos)
    print(f"[hiker_pipeline] {inserted} evento(s) nuevo(s) escrito(s)")
    return inserted


if __name__ == "__main__":
    run()
