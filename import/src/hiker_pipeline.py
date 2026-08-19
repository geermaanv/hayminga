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
from datetime import datetime, timezone, date

from google import genai
from google.genai import types
from google.genai import errors as genai_errors
import anthropic

from src.processor import (
    EVENT_SCHEMA, SYSTEM_PROMPT, GEMINI_MODEL, CLAUDE_MODEL,
    validate_event_data, _pais_desde_texto, _pais_desde_telefono,
)
from src.geocodificar import geocodificar_direccion
from src.sheets import (
    append_events, get_service, instagram_shortcode, actualizar_fuentes_stats,
    cargar_cuentas_ids, cargar_cuentas_pais, guardar_cuentas_ids,
    SPREADSHEET_ID, SHEET_NAME,
)

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


# Costo de HikerAPI por corrida: se sabía informalmente (ver ROADMAP.md,
# "Control de costo de HikerAPI" — el susto de los $4 en pocos días) pero
# nunca quedó un número real en los logs de cada corrida. Contador simple,
# incrementado en el único punto por el que pasan todas las llamadas
# pagas (_hiker_get) — no cuenta _download_image, que baja la imagen ya
# resuelta y no es una llamada a la API de HikerAPI.
_llamadas_hikerapi = [0]


def _hiker_get(url: str, **kwargs):
    _llamadas_hikerapi[0] += 1
    return requests.get(url, headers={"x-access-key": _hiker_key()}, **kwargs)


def _item_a_post(item: dict) -> dict | None:
    code = item.get("code")
    image_url = item.get("thumbnail_url") or ""
    if not code or not image_url:
        return None
    location = item.get("location") or {}
    return {
        "link": f"https://www.instagram.com/p/{code}/",
        "image_url": image_url,
        "caption": item.get("caption_text") or "",
        "taken_at_ts": item.get("taken_at_ts"),
        "lat": location.get("lat"),
        "lng": location.get("lng"),
        "location_name": location.get("name") or "",
        "location_address": location.get("address") or "",
        "username": ((item.get("user") or {}).get("username") or "").lower(),
    }


def _item_v2_a_post(media: dict) -> dict | None:
    code = media.get("code")
    candidatos = (media.get("image_versions2") or {}).get("candidates") or []
    image_url = candidatos[0]["url"] if candidatos else ""
    if not code or not image_url:
        return None
    location = media.get("location") or {}
    return {
        "link": f"https://www.instagram.com/p/{code}/",
        "image_url": image_url,
        "caption": (media.get("caption") or {}).get("text") or "",
        "taken_at_ts": media.get("taken_at"),
        "lat": location.get("lat"),
        "lng": location.get("lng"),
        "location_name": location.get("name") or "",
        "location_address": location.get("address") or "",
        "username": ((media.get("user") or {}).get("username") or "").lower(),
    }


def fetch_hashtag_posts_recent(hashtag: str, amount: int = 30) -> list[dict]:
    """v1/hashtag/medias/recent devuelve siempre [] (esa pestaña de
    Instagram está más restringida ahí), pero v2 sí funciona y trae
    contenido genuinamente reciente (confirmado: posts de 1-3 días) —
    a diferencia de /top que mezcla popularidad histórica con lo nuevo."""
    resp = _hiker_get(
        "https://api.hikerapi.com/v2/hashtag/medias/recent",
        params={"name": hashtag, "amount": amount},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    sections = ((data.get("response") or {}).get("sections")) or []
    posts = []
    for section in sections:
        medias = (section.get("layout_content") or {}).get("medias") or []
        for m in medias:
            post = _item_v2_a_post(m.get("media") or {})
            if post:
                posts.append(post)
    return posts


def fetch_hashtag_posts(hashtag: str, amount: int = 30) -> list[dict]:
    # hashtag/medias/recent devuelve siempre [] (esa pestaña de Instagram
    # está más restringida); hashtag/medias/top sí trae datos reales.
    resp = _hiker_get(
        "https://api.hikerapi.com/v1/hashtag/medias/top",
        params={"name": hashtag, "amount": amount},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    items = data if isinstance(data, list) else data.get("items", [])
    return [p for item in items if (p := _item_a_post(item))]


def resolver_user_id(username: str) -> int | None:
    resp = _hiker_get(
        "https://api.hikerapi.com/v1/user/by/username",
        params={"username": username},
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json().get("pk")


def resolver_user_id_y_pais(username: str) -> tuple[int | None, str]:
    """Igual que resolver_user_id, pero además saca la señal de país que
    ya trae la misma respuesta: public_phone_country_code. No agrega
    ninguna llamada — es un solo request, antes se tiraba el resto del
    perfil después de sacar el pk. Confirmado con datos reales (16/08/2026):
    NO depende de ser cuenta "Business" — 2 de 4 cuentas propias lo tenían
    poblado con is_business=false. Cobertura parcial, pero gratis."""
    resp = _hiker_get(
        "https://api.hikerapi.com/v1/user/by/username",
        params={"username": username},
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()
    codigo = (data.get("public_phone_country_code") or "").strip()
    pais = _pais_desde_telefono("+" + codigo) if codigo else ""
    return data.get("pk"), pais


def fetch_user_posts(username: str, amount: int = 12, user_id: int | None = None) -> list[dict]:
    """A diferencia de hashtag/medias/top (más comentado/likeado
    HISTÓRICAMENTE), esto trae el timeline real y cronológico de una
    cuenta puntual — para cuentas ya conocidas de organizadores
    argentinos, es mucho más confiable que pescar en hashtags globales.

    `user_id` opcional: pasarlo (cacheado) evita una llamada extra a
    HikerAPI para resolverlo — es pago por request."""
    if user_id is None:
        user_id = resolver_user_id(username)
    if not user_id:
        return []
    resp = _hiker_get(
        "https://api.hikerapi.com/v1/user/medias",
        params={"user_id": user_id, "amount": amount},
        timeout=30,
    )
    resp.raise_for_status()
    items = resp.json()
    items = items if isinstance(items, list) else items.get("items", [])
    return [p for item in items if (p := _item_a_post(item))]


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


def subir_imagen_a_drive(image_bytes: bytes, media_type: str) -> str | None:
    """El link de imagen que devuelve HikerAPI/Instagram es firmado y
    temporal — vence (confirmado en producción: 22 de 37 eventos activos
    con la imagen rota). Se sube a Drive vía Apps Script (mismo mecanismo
    que ya usa el formulario de mail/web) para tener un link propio y
    estable. Si falla, se sigue con el link de Instagram como estaba
    antes — mejor una imagen que vence tarde que ningún evento."""
    apps_script_url = os.environ.get("APPS_SCRIPT_URL")
    secreto = os.environ.get("APPS_SCRIPT_SHARED_SECRET")
    if not apps_script_url or not secreto:
        return None
    ext = "png" if media_type == "image/png" else ("webp" if media_type == "image/webp" else "jpg")
    try:
        resp = requests.post(
            apps_script_url,
            headers={"Content-Type": "text/plain"},  # evita preflight de CORS, igual que el frontend
            data=json.dumps({
                "accion": "subir_imagen",
                "secreto": secreto,
                "imagen_base64": base64.b64encode(image_bytes).decode("ascii"),
                "imagen_mime": media_type,
                "imagen_nombre": f"evento.{ext}",
            }),
            timeout=30,
        )
        data = resp.json()
        return data.get("url") if data.get("success") else None
    except Exception as e:
        print(f"[hiker_pipeline] error subiendo imagen a Drive — {e}")
        return None


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


def extraer_evento(post: dict, image_url: str | None) -> dict | None:
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

    # Métrica: ¿se resolvió solo con texto o necesitó imagen?
    if data is not None and not data.get("es_evento", True):
        print(f"[METRICA] DESCARTADO_SOLO_TEXTO: {post['link']}")
        return data

    tiene_datos_basicos = (
        data and
        data.get("nombre") and
        (data.get("fecha_inicio_iso") or data.get("es_virtual"))
    )
    if tiene_datos_basicos:
        print(f"[METRICA] RESUELTO_SOLO_TEXTO: {post['link']} — {data.get('nombre')}")
        # Pero sigue adelante igual (medir si imagen mejora)

    if image_url:
        print(f"[METRICA] INTENTA_CON_IMAGEN: {post['link']}")
        IMAGES_DIR.mkdir(exist_ok=True)
        image_filename = post["link"].rstrip("/").rsplit("/", 1)[-1] + ".jpg"
        image_path = IMAGES_DIR / image_filename
        if _download_image(image_url, image_path):
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
                # Métrica: ¿la imagen mejoró la extracción?
                nombre_antes = data.get("nombre") if data else None
                nombre_despues = data2.get("nombre")
                if nombre_despues and nombre_despues != nombre_antes:
                    print(f"[METRICA] IMAGEN_MEJORÓ: {post['link']} — {nombre_antes} → {nombre_despues}")
                data = data2

    return data


# hashtag/medias/top trae los posteos con más likes/comentarios
# HISTÓRICAMENTE, no los recientes — mezcla contenido evergreen viejo con
# eventos nuevos reales. Casi ningún evento se anuncia con tanta
# anticipación, así que un posteo publicado hace más de esto casi seguro
# ya pasó: ni vale la pena gastar una llamada a la IA en extraerlo.
# Bajado de 270 a 180 (caso real: post de 252 días/36 semanas con curso
# online sin fecha explícita — sobrevivió los dos filtros de fecha
# porque no había fecha_inicio para comparar Y estaba bajo los 270 días).
_MAX_ANTIGUEDAD_POST_DIAS = 180

# Umbral para marcar en el log una cuenta seguida como posiblemente
# inactiva (no da de baja sola, ver el loop de cuentas_seguidas en run()).
_MAX_INACTIVIDAD_CUENTA_DIAS = 180

# La IA no es confiable marcando idioma/país cuando el flyer no lo dice
# explícito (confirmado con casos reales: "4-day cob course", "Bamboo
# Anatomy Workshop" quedaron con Pais e idioma vacíos y pasaron el
# filtro). Un chequeo de palabras comunes sobre el caption real, antes
# de gastar la llamada a la IA, es más confiable y además ahorra costo.
_PALABRAS_ES = {
    "de", "la", "el", "en", "y", "que", "para", "con", "un", "una", "los",
    "las", "del", "se", "por", "curso", "taller", "evento", "vení",
    "inscripción", "inscripciones", "cupos", "más", "info", "gratis",
}
_PALABRAS_EN = {
    "the", "and", "for", "with", "workshop", "course", "learn", "book",
    "now", "our", "your", "we", "you", "this", "join", "register", "class",
}


def _parece_ingles(texto: str) -> bool:
    palabras = re.findall(r"[a-záéíóúñ']+", (texto or "").lower())
    if len(palabras) < 6:
        return False
    en = sum(1 for p in palabras if p in _PALABRAS_EN)
    es = sum(1 for p in palabras if p in _PALABRAS_ES)
    return en >= 3 and en > es


def _detectar_pais_temprana(post: dict) -> str:
    """Detecta país desde datos disponibles SIN IA ni descarga de imagen.
    Solo busca en caption + location_address. pais_cuenta es un fallback
    muy débil que se aplica al final (en procesar_post, después de validate_event_data).
    Retorna país detectado o string vacío."""
    pais = _pais_desde_texto(
        post.get("caption", ""),
        post.get("location_address", ""),
    )
    return pais


def procesar_post(
    post: dict, existing_links: set, cuentas_excluidas: set = frozenset(),
    pais_cuenta: str = "",
) -> dict | None:
    if post.get("username") and post["username"] in cuentas_excluidas:
        return None

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

    if _parece_ingles(post.get("caption")):
        return None

    pais_detectado = _detectar_pais_temprana(post)
    if pais_detectado and pais_detectado != "Argentina":
        return None

    data = extraer_evento(post, post["image_url"])
    if not data or not data.get("es_evento", True):
        return None

    data["imagen_url"] = post["image_url"]

    image_filename = post["link"].rstrip("/").rsplit("/", 1)[-1] + ".jpg"
    image_path = IMAGES_DIR / image_filename
    if image_path.exists():
        image_bytes_subida = image_path.read_bytes()
        drive_url = subir_imagen_a_drive(image_bytes_subida, _detectar_media_type(image_bytes_subida))
        if drive_url:
            data["imagen_url"] = drive_url
    data["link_promocional"] = post["link"]
    data["username"] = post.get("username") or ""
    data["fuente"] = "hikerapi_hashtag"
    data["fecha_descubrimiento"] = datetime.now(timezone.utc).isoformat()
    # Para más adelante: juntar hashtags de eventos activos y ver cuáles
    # no están todavía en config.json (los posts suelen traer muchos más
    # de los que buscamos nosotros).
    data["hashtags_post"] = " ".join(sorted(set(re.findall(r"#\w+", post.get("caption") or ""))))
    data = validate_event_data(data)

    # Última señal de país, más débil que las anteriores a propósito: es
    # del perfil de la cuenta (aplica a TODOS sus posts), no de este evento
    # puntual — si el flyer o el contacto de este post ya dijeron algo,
    # eso gana. Solo entra si validate_event_data no encontró nada.
    if not data.get("pais") and pais_cuenta:
        data["pais"] = pais_cuenta

    # Un posteo puede ser reciente (pasa el filtro de antigüedad de arriba,
    # que mira cuándo se PUBLICÓ el post) pero anunciar un evento que ya
    # pasó (ej. reposteos, posts indexados tarde). Acá no hay ambigüedad
    # como con país/idioma: si el evento ya fue, no tiene sentido revisarlo.
    fecha_relevante = data.get("fecha_fin_iso") or data.get("fecha_inicio_iso")
    if fecha_relevante and fecha_relevante < date.today().isoformat():
        return None

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
    elif data.get("direccion"):
        # La mayoría de los posts no trae ubicación etiquetada (87 de 126 de
        # los ya importados quedaron sin coordenadas y el mapa los manda al
        # centroide de la provincia). Si el flyer dejó una dirección, se
        # intenta resolverla — gratis, y devuelve None cuando no está seguro.
        punto = geocodificar_direccion(data.get("direccion"), data.get("provincia"))
        if punto:
            data["latitud"], data["longitud"] = punto

    confianza = str(data.get("confianza") or "baja").lower()
    if data.get("activo") and confianza != "alta":
        data["activo"] = False
        data["estado"] = "pendiente_confirmacion"
        # Métrica: ¿por qué entra a pendientes?
        razon_pendiente = []
        if confianza == "media":
            razon_pendiente.append("confianza_media")
        elif confianza == "baja":
            razon_pendiente.append("confianza_baja")
        if not data.get("nombre"):
            razon_pendiente.append("sin_nombre")
        if not (data.get("fecha_inicio_iso") or data.get("es_virtual")):
            razon_pendiente.append("sin_fecha")
        if not data.get("provincia") and not data.get("latitud"):
            razon_pendiente.append("sin_ubicacion")
        razon = ",".join(razon_pendiente) or "otra_razon"
        print(f"[PENDIENTE] {data.get('nombre', 'SIN_NOMBRE')} — {razon} — {post['link']}")

    return data


def run() -> int:
    _llamadas_hikerapi[0] = 0  # por si run() se llama más de una vez en el mismo proceso (tests)
    config = json.loads(Path("config.json").read_text())
    hashtags = config.get("hashtags") or []
    if not hashtags:
        print("[hiker_pipeline] Sin hashtags configurados en config.json")
        return 0
    cuentas_excluidas = {c.lstrip("@").lower() for c in config.get("cuentas_excluidas") or []}

    service = get_service()
    existing = service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID, range=f"{SHEET_NAME}!K2:K",
    ).execute().get("values", [])
    # Se guardan ambas formas (link completo y shortcode) para que el
    # chequeo temprano en procesar_post() haga match sin importar si el
    # link viene como /p/, /reel/ o /reels/.
    existing_links = {row[0] for row in existing if row}
    existing_links |= {instagram_shortcode(row[0]) for row in existing if row and instagram_shortcode(row[0])}
    print(f"[hiker_pipeline] {len(existing_links)} link(s) ya en el Sheet")

    eventos_totales_insertados = [0]  # lista para poder mutar desde dentro de los loops
    fuentes_resultados = {}  # (tipo, nombre) -> hubo al menos 1 evento en esta corrida
    # `top` apagado (15/08/2026): la medición por endpoint dio 0 eventos
    # aportados por /top en 3 corridas contra 8 de /recent, y el solapamiento
    # entre ambos resultó mínimo — /top traía ~630 posts por corrida que el
    # dedup ya descartaba por conocidos. Son 42 llamadas pagas por corrida
    # para nada. Se apaga con un flag y NO se borra fetch_hashtag_posts():
    # sigue siendo la red de seguridad si el endpoint v2 de /recent se cae o
    # cambia (ya se vieron 404s). Revisar ~22/08 — ver ROADMAP.md Etapa 9.6.
    USAR_TOP = False

    atribucion = {"posts_recent": 0, "posts_top": 0, "solo_en_recent": 0, "eventos_solo_recent": 0}
    for hashtag in hashtags:
        posts = []
        shortcodes_recent = set()
        shortcodes_top = set()
        try:
            posts_recent = fetch_hashtag_posts_recent(hashtag)
            shortcodes_recent = {instagram_shortcode(p["link"]) for p in posts_recent}
            atribucion["posts_recent"] += len(posts_recent)
            posts.extend(posts_recent)
        except Exception as e:
            print(f"[hiker_pipeline] #{hashtag} (recent): error consultando HikerAPI — {e}")
        if USAR_TOP:
            try:
                posts_top = fetch_hashtag_posts(hashtag)
                atribucion["posts_top"] += len(posts_top)
                shortcodes_top = {instagram_shortcode(p["link"]) for p in posts_top}
                atribucion["solo_en_recent"] += len(shortcodes_recent - shortcodes_top)
                posts.extend(posts_top)
            except Exception as e:
                print(f"[hiker_pipeline] #{hashtag} (top): error consultando HikerAPI — {e}")
        else:
            atribucion["solo_en_recent"] += len(shortcodes_recent)
        if not posts:
            continue
        print(f"[hiker_pipeline] #{hashtag}: {len(posts)} post(s)")
        fuentes_resultados[("hashtag", hashtag)] = False

        eventos_hashtag = []
        for post in posts:
            try:
                evento = procesar_post(post, existing_links, cuentas_excluidas)
            except Exception as e:
                print(f"[hiker_pipeline] {post['link']}: error procesando — {e}")
                continue
            if evento:
                eventos_hashtag.append(evento)
                shortcode = instagram_shortcode(post["link"])
                if shortcode in shortcodes_recent and shortcode not in shortcodes_top:
                    atribucion["eventos_solo_recent"] += 1
                existing_links.add(post["link"])
                existing_links.add(shortcode)
                fuentes_resultados[("hashtag", hashtag)] = True

        # Guardar ya (no acumular todo para el final): un run de 33 hashtags
        # + ~140 cuentas puede superar el timeout de 45min del workflow si
        # hay un día lento de red (pasó en producción). Si el proceso muere
        # a mitad de camino, esto asegura que lo ya encontrado no se pierda.
        if eventos_hashtag:
            try:
                inserted_hashtag = append_events(eventos_hashtag)
                eventos_totales_insertados[0] += inserted_hashtag
            except Exception as e:
                print(f"[hiker_pipeline] #{hashtag}: error guardando en el Sheet — {e}")

    # Timeline real de cuentas ya conocidas de organizadores argentinos —
    # a diferencia de los hashtags, no compite por popularidad global, así
    # que es más confiable para encontrar eventos argentinos genuinos.
    cuentas_seguidas = [c.lstrip("@").lower() for c in config.get("cuentas_seguidas") or []]
    ids_nuevos = {}
    pais_nuevos = {}
    error_cuentas = ""
    try:
        # Todo este bloque va en un try/except: un fallo transitorio acá
        # (pasó dos veces con un SSLEOFError de red) no debe hacer perder
        # los eventos ya encontrados por hashtag arriba — antes el script
        # moría entero y nunca llegaba a append_events().
        ids_cacheados = cargar_cuentas_ids(service)
        pais_cacheado = cargar_cuentas_pais(service)
        for username in cuentas_seguidas:
            pais_cuenta = pais_cacheado.get(username, "")
            try:
                user_id = ids_cacheados.get(username)
                if user_id is None:
                    user_id, pais_resuelto = resolver_user_id_y_pais(username)
                    if user_id:
                        ids_nuevos[username] = user_id
                    if pais_resuelto:
                        pais_nuevos[username] = pais_resuelto
                        pais_cuenta = pais_resuelto
                posts = fetch_user_posts(username, user_id=user_id)
            except Exception as e:
                print(f"[hiker_pipeline] @{username}: error consultando HikerAPI — {e}")
                continue
            print(f"[hiker_pipeline] @{username}: {len(posts)} post(s)")
            fuentes_resultados[("cuenta", username)] = False

            # No se da de baja sola — se marca en el log para revisión manual,
            # mismo criterio que la curación de hashtags (juntar el dato,
            # decidir con más contexto que solo el número).
            ultimo_post_ts = max((p["taken_at_ts"] for p in posts if p.get("taken_at_ts")), default=None)
            if ultimo_post_ts:
                antiguedad = datetime.now(timezone.utc) - datetime.fromtimestamp(ultimo_post_ts, tz=timezone.utc)
                if antiguedad.days > _MAX_INACTIVIDAD_CUENTA_DIAS:
                    print(f"[hiker_pipeline] @{username}: sin posts hace {antiguedad.days} días, "
                          f"revisar si sigue activa")
            elif posts == []:
                print(f"[hiker_pipeline] @{username}: 0 posts encontrados, revisar si la cuenta existe/es pública")

            eventos_cuenta = []
            for post in posts:
                try:
                    evento = procesar_post(post, existing_links, cuentas_excluidas, pais_cuenta)
                except Exception as e:
                    print(f"[hiker_pipeline] {post['link']}: error procesando — {e}")
                    continue
                if evento:
                    eventos_cuenta.append(evento)
                    existing_links.add(post["link"])
                    existing_links.add(instagram_shortcode(post["link"]))
                    fuentes_resultados[("cuenta", username)] = True

            if eventos_cuenta:
                try:
                    inserted_cuenta = append_events(eventos_cuenta)
                    eventos_totales_insertados[0] += inserted_cuenta
                except Exception as e:
                    print(f"[hiker_pipeline] @{username}: error guardando en el Sheet — {e}")
    except Exception as e:
        print(f"[hiker_pipeline] error en la sección de cuentas seguidas — {e}")
        error_cuentas = str(e)

    inserted = eventos_totales_insertados[0]
    print(f"[hiker_pipeline] {inserted} evento(s) nuevo(s) escrito(s) en total")
    print(f"[hiker_pipeline] {_llamadas_hikerapi[0]} llamada(s) a HikerAPI en esta corrida")
    atribucion["top_activo"] = USAR_TOP
    if USAR_TOP:
        print(f"[hiker_pipeline] atribución hashtags — recent: {atribucion['posts_recent']} post(s), "
              f"top: {atribucion['posts_top']} post(s), solo en recent: {atribucion['solo_en_recent']}, "
              f"eventos que solo recent trajo: {atribucion['eventos_solo_recent']}")
    else:
        print(f"[hiker_pipeline] hashtags — recent: {atribucion['posts_recent']} post(s) "
              f"(top apagado, ver ROADMAP.md Etapa 9.6)")

    # Resumen para el paso de notificación del workflow (corre con if: always(),
    # así que si el pipeline se muere antes de esta línea el archivo no existe
    # y el notificador lo reporta como corrida incompleta).
    try:
        Path("run_summary.json").write_text(json.dumps({
            "eventos_insertados": inserted,
            "error_cuentas_seguidas": error_cuentas,
            "atribucion": atribucion,
            "llamadas_hikerapi": _llamadas_hikerapi[0],
        }))
    except Exception as e:
        print(f"[hiker_pipeline] error escribiendo run_summary.json — {e}")

    try:
        actualizar_fuentes_stats(service, fuentes_resultados)
    except Exception as e:
        print(f"[hiker_pipeline] error actualizando FuentesStats — {e}")

    try:
        guardar_cuentas_ids(service, ids_nuevos, pais_nuevos)
    except Exception as e:
        print(f"[hiker_pipeline] error guardando CuentasIds — {e}")

    return inserted


if __name__ == "__main__":
    run()
