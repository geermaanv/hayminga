"""
processor.py
Envía cada flyer a Gemini Vision (gratis) y extrae los datos del evento
con el schema exacto del Google Sheet de hayminga.org. Si Gemini falla o
se queda sin cuota, reintenta esa misma imagen con Claude como fallback.
"""

import os
import json
import base64
import re
import unicodedata
from pathlib import Path
from datetime import datetime, date
from google import genai
from google.genai import types
from google.genai import errors as genai_errors
import anthropic

from src.state import save_hash, save_link, image_hash
from src.scraper import fetch_caption

# Cambio TEMPORAL para revisar la calidad de datos a mano: mientras esté en
# True, ningún evento se auto-publica (activo queda en False y el estado en
# "pendiente_confirmacion") aunque el extractor lo hubiera dado por bueno.
# Para volver al comportamiento normal, poner en False.
REVISION_MANUAL = True

GEMINI_MODEL = "gemini-3.5-flash-lite"

CLAUDE_MODEL  = "claude-haiku-4-5-20251001"

# Sentinel: ninguno de los proveedores disponibles pudo procesar la imagen
# (red, cuota, respuesta no-JSON). No se marca el hash como visto, para que
# se reintente en una corrida futura en vez de perderse para siempre.
RETRY = object()

# Estado del batch actual: una vez que un proveedor reporta cuota agotada,
# se deja de intentarlo para el resto de las imágenes de esta corrida.
_batch_state = {
    "gemini_exhausted": False,
    "claude_exhausted": False,
    "claude_calls": 0,
    "last_failure_reason": "",
}

HOY = date.today().isoformat()

PROVINCIAS_ARGENTINA = {
    "buenos aires": "Buenos Aires",
    "caba": "CABA",
    "ciudad autonoma de buenos aires": "CABA",
    "catamarca": "Catamarca",
    "chaco": "Chaco",
    "chubut": "Chubut",
    "cordoba": "Córdoba",
    "corrientes": "Corrientes",
    "entre rios": "Entre Ríos",
    "formosa": "Formosa",
    "jujuy": "Jujuy",
    "la pampa": "La Pampa",
    "la rioja": "La Rioja",
    "mendoza": "Mendoza",
    "misiones": "Misiones",
    "neuquen": "Neuquén",
    "rio negro": "Río Negro",
    "salta": "Salta",
    "san juan": "San Juan",
    "san luis": "San Luis",
    "santa cruz": "Santa Cruz",
    "santa fe": "Santa Fe",
    "santiago del estero": "Santiago del Estero",
    "tierra del fuego": "Tierra del Fuego",
    "tucuman": "Tucumán",
}

EVENT_SCHEMA = {
    "type": "object",
    "properties": {
        "es_evento": {"type": "boolean"},
        "nombre": {"type": "string", "nullable": True},
        "tipo_evento": {
            "type": "string",
            "nullable": True,
            "enum": ["Curso", "Taller", "Minga", "Charla", "Evento", "Residencia", "Festival"],
        },
        "fecha_inicio": {"type": "string", "nullable": True},
        "fecha_fin": {"type": "string", "nullable": True},
        "anio_confirmado": {"type": "boolean"},
        "es_virtual": {"type": "boolean"},
        "provincia": {"type": "string", "nullable": True},
        "pais": {"type": "string", "nullable": True},
        "descripcion": {"type": "string", "nullable": True},
        "organizador": {"type": "string", "nullable": True},
        "direccion": {"type": "string", "nullable": True},
        "contacto": {"type": "string", "nullable": True},
        "idioma": {"type": "string", "nullable": True, "enum": ["es", "en", "otro"]},
        "confianza": {"type": "string", "enum": ["alta", "media", "baja"]},
    },
    "required": ["es_evento", "anio_confirmado"],
}

SYSTEM_PROMPT = f"""Sos un extractor de datos de eventos de bioconstrucción para hayminga.org.
Analizás imágenes de flyers y extraés la información del evento.
La estructura de salida está definida por el schema de la API.

Fecha de hoy: {HOY}

Extraé únicamente información visible en la imagen o presente en el caption.
Usá DD/MM/YYYY para las fechas. Si no conocés un dato opcional, devolvé null.
Marcá anio_confirmado=true si el año aparece escrito en la imagen/caption o
si se proporcionó una fecha de publicación indexada. Si el evento muestra día
y mes sin año, usá el año de esa publicación. Nunca uses automáticamente el
año actual. Sin año visible ni fecha de publicación, devolvé fechas null y
anio_confirmado=false.
Si no es un flyer de un evento de bioconstrucción, marcá es_evento como false.
Marcá idioma con el idioma principal del texto del flyer/caption ("es",
"en" u "otro").
No determines si está activo: el sistema lo calcula después usando fecha y país.
"""

PROMPT_TEXT = "Extraé los datos de este flyer de evento."


def read_image(path: Path) -> tuple[bytes, str]:
    data = path.read_bytes()
    magic_types = (
        (b"\xff\xd8\xff", "image/jpeg"),
        (b"\x89PNG\r\n\x1a\n", "image/png"),
        (b"GIF87a", "image/gif"),
        (b"GIF89a", "image/gif"),
        (b"RIFF", "image/webp"),
    )
    for magic, media_type in magic_types:
        if data.startswith(magic):
            return data, media_type

    suffix = path.suffix.lower().lstrip(".")
    media_map = {
        "jpg": "image/jpeg", "jpeg": "image/jpeg",
        "png": "image/png", "gif": "image/gif", "webp": "image/webp",
    }
    media_type = media_map.get(suffix, "image/jpeg")
    return data, media_type


def parse_fecha(fecha_str: str | None) -> tuple[str, str]:
    """Retorna (fecha_iso, periodo) desde DD/MM/YYYY."""
    if not fecha_str:
        return "", ""
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(fecha_str.strip(), fmt)
            return dt.strftime("%Y-%m-%d"), dt.strftime("%Y-%m")
        except ValueError:
            continue
    return "", ""


def _build_prompt_text(caption: str) -> str:
    if not caption:
        return PROMPT_TEXT
    return (
        f"{PROMPT_TEXT}\n\nCaption real del post (texto de Instagram, puede "
        f"tener fecha/lugar/contacto que no está en la imagen):\n{caption}"
    )


def _call_gemini(image_bytes: bytes, media_type: str, prompt_text: str) -> str:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY no configurada")
    client_gemini = genai.Client(api_key=api_key)
    response = client_gemini.models.generate_content(
        model=GEMINI_MODEL,
        contents=[
            types.Part.from_bytes(data=image_bytes, mime_type=media_type),
            prompt_text,
        ],
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_schema=EVENT_SCHEMA,
            thinking_config=types.ThinkingConfig(thinking_level="minimal"),
            max_output_tokens=2048,
        ),
    )
    candidates = response.candidates or []
    finish_reason = getattr(candidates[0], "finish_reason", None) if candidates else None
    finish_reason = getattr(finish_reason, "value", finish_reason)
    if str(finish_reason).upper().endswith("MAX_TOKENS"):
        _batch_state["last_failure_reason"] = "json_truncado"
        print("[processor] Gemini alcanzó MAX_TOKENS; el candidato se reintentará")
    return (response.text or "").strip()


def _call_claude(image_bytes: bytes, media_type: str, prompt_text: str) -> str:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY no configurada — sin fallback disponible")
    client_claude = anthropic.Anthropic(api_key=api_key)
    response = client_claude.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": base64.standard_b64encode(image_bytes).decode("utf-8"),
                    },
                },
                {"type": "text", "text": prompt_text},
            ],
        }],
    )
    raw = response.content[0].text.strip()
    return raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()


def _is_quota_error(e: Exception) -> bool:
    if isinstance(e, genai_errors.ClientError) and getattr(e, "code", None) == 429:
        return True
    if isinstance(e, anthropic.APIStatusError) and "credit balance is too low" in str(e).lower():
        return True
    return False


def _get_raw_json(image_path: Path, image_bytes: bytes, media_type: str, prompt_text: str) -> str | None:
    """Intenta Gemini primero, cae a Claude si falla. Retorna None si ambos
    proveedores fallan (o no hay ninguno disponible)."""
    if not _batch_state["gemini_exhausted"]:
        try:
            return _call_gemini(image_bytes, media_type, prompt_text)
        except Exception as e:
            if _is_quota_error(e):
                _batch_state["gemini_exhausted"] = True
                print(f"[processor] Gemini sin cuota — resto del batch usa Claude")
            else:
                print(f"[processor] Gemini falló en {image_path.name}: {e}")

    if _batch_state["claude_exhausted"]:
        return None
    max_claude_calls = max(0, int(os.getenv("MAX_CLAUDE_CALLS_PER_RUN", "1")))
    if _batch_state["claude_calls"] >= max_claude_calls:
        _batch_state["claude_exhausted"] = True
        print(
            f"[processor] Límite de Claude alcanzado "
            f"({max_claude_calls} llamada(s) por corrida)"
        )
        return None
    try:
        _batch_state["claude_calls"] += 1
        return _call_claude(image_bytes, media_type, prompt_text)
    except Exception as e:
        if _is_quota_error(e):
            _batch_state["claude_exhausted"] = True
            print(f"[processor] Claude también sin crédito")
        else:
            print(f"[processor] Claude (fallback) falló en {image_path.name}: {e}")
        return None


def _necesita_caption(data: dict) -> bool:
    """Solo vale la pena gastar una llamada de SerpAPI en el caption real
    si el evento ya es real pero la extracción quedó floja: confianza
    media/baja, o falta fecha/dirección que el caption suele traer."""
    if data.get("confianza") in ("media", "baja"):
        return True
    return not data.get("fecha_inicio") or not data.get("direccion")


def _parse_json_evento(raw: str, image_path: Path):
    """None si no parsea, dict si sí. No confundir con el None de
    'confirmado que no es evento' — ese se maneja en el caller."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        # Claude a veces envuelve un JSON válido con una explicación o agrega
        # texto después del objeto. Recuperar el primer objeto completo evita
        # desperdiciar la extracción sin aceptar JSON truncado.
        decoder = json.JSONDecoder()
        for start, char in enumerate(raw):
            if char != "{":
                continue
            try:
                parsed, _ = decoder.raw_decode(raw[start:])
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                print(
                    f"[processor] JSON recuperado de respuesta con texto extra "
                    f"en {image_path.name}"
                )
                return parsed

        if not _batch_state["last_failure_reason"]:
            _batch_state["last_failure_reason"] = "json_invalido"
        print(f"[processor] Error JSON en {image_path.name}: {e} | raw: '{raw[:200]}'")
        return None


def _normalizar_texto(value: str | None) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").strip().lower())
    return "".join(char for char in text if not unicodedata.combining(char))


def _normalizar_provincia(value: str | None) -> str:
    return PROVINCIAS_ARGENTINA.get(_normalizar_texto(value), "")


def _es_argentina(value: str | None) -> bool:
    return _normalizar_texto(value) in {"argentina", "ar"}


SOURCE_STOPWORDS = {
    "taller", "curso", "evento", "encuentro", "jornada", "minga",
    "bioconstruccion", "construccion", "natural", "naturales",
    "arquitectura", "bioarquitectura", "argentina", "presencial",
    "virtual", "para", "sobre", "desde", "hasta", "como", "esta",
    "este", "estos", "estas", "con", "del", "los", "las", "una",
    "por", "que",
}
MONTH_NAMES = {
    1: "enero", 2: "febrero", 3: "marzo", 4: "abril", 5: "mayo",
    6: "junio", 7: "julio", 8: "agosto", 9: "septiembre",
    10: "octubre", 11: "noviembre", 12: "diciembre",
}


def _source_tokens(value: str | None) -> set[str]:
    text = _normalizar_texto(value)
    return {
        token for token in re.findall(r"[a-z0-9]+", text)
        if len(token) >= 4 and token not in SOURCE_STOPWORDS
    }


def _source_contains_date(context: str, iso_date: str | None) -> bool:
    if not iso_date:
        return False
    try:
        parsed = date.fromisoformat(str(iso_date)[:10])
    except ValueError:
        return False
    normalized = _normalizar_texto(context)
    day = str(parsed.day)
    month = MONTH_NAMES[parsed.month]
    numeric_patterns = {
        f"{parsed.day}/{parsed.month}", f"{parsed.day:02d}/{parsed.month:02d}",
        f"{parsed.day}-{parsed.month}", f"{parsed.day:02d}-{parsed.month:02d}",
    }
    return bool(
        re.search(rf"\b{re.escape(day)}\s+(?:de\s+)?{month}\b", normalized)
        or any(pattern in normalized for pattern in numeric_patterns)
    )


def source_matches_event(event: dict, indexed_context: str) -> bool:
    """Verificación conservadora entre lo leído del flyer y el post.

    Los términos genéricos no cuentan como evidencia. Para publicar se exige
    un nombre suficientemente coincidente y una segunda señal (fecha, lugar
    u organizador), o un nombre casi idéntico con tres términos específicos.
    """
    if not indexed_context:
        return False
    context_tokens = _source_tokens(indexed_context)
    name_tokens = _source_tokens(event.get("nombre"))
    shared_name = name_tokens & context_tokens
    name_ratio = len(shared_name) / len(name_tokens) if name_tokens else 0

    place_tokens = _source_tokens(
        " ".join(filter(None, (event.get("direccion"), event.get("provincia"))))
    )
    organizer_tokens = _source_tokens(event.get("organizador"))
    date_match = _source_contains_date(
        indexed_context,
        event.get("fecha_inicio_iso") or event.get("fecha_inicio"),
    )
    corroboration = bool(
        date_match
        or place_tokens & context_tokens
        or organizer_tokens & context_tokens
    )
    return bool(
        (len(shared_name) >= 2 and name_ratio >= 0.5 and corroboration)
        or (len(shared_name) >= 3 and name_ratio >= 0.75)
    )


def validate_event_data(data: dict, today: date | None = None) -> dict:
    """Normaliza campos extraídos y calcula `activo` sin delegarlo al modelo."""
    result = dict(data)
    today = today or date.today()

    fecha_inicio_iso, periodo = parse_fecha(result.get("fecha_inicio"))
    fecha_fin_iso, _ = parse_fecha(result.get("fecha_fin"))
    result["fecha_inicio_iso"] = fecha_inicio_iso
    result["fecha_fin_iso"] = fecha_fin_iso
    result["periodo"] = periodo

    provincia = _normalizar_provincia(result.get("provincia"))
    if provincia:
        result["provincia"] = provincia
        if not result.get("pais"):
            result["pais"] = "Argentina"
    else:
        result["provincia"] = ""

    if _es_argentina(result.get("pais")):
        result["pais"] = "Argentina"

    fecha_inicio = date.fromisoformat(fecha_inicio_iso) if periodo else None
    fecha_fin = None
    if fecha_fin_iso:
        try:
            fecha_fin = date.fromisoformat(fecha_fin_iso)
        except ValueError:
            fecha_fin_iso = ""
            result["fecha_fin_iso"] = ""

    rango_valido = not (fecha_inicio and fecha_fin and fecha_fin < fecha_inicio)
    fecha_relevante = fecha_fin or fecha_inicio
    ubicacion_valida = result.get("pais") == "Argentina"
    result["activo"] = bool(
        result.get("nombre")
        and fecha_inicio
        and result.get("anio_confirmado") is not False
        and rango_valido
        and fecha_relevante >= today
        and ubicacion_valida
    )
    if not rango_valido:
        result["fecha_fin_iso"] = ""

    confianza = str(result.get("confianza") or "baja").lower()
    result["confianza"] = confianza if confianza in {"alta", "media", "baja"} else "baja"
    return result


def extract_event_data(image_path: Path, metadata: dict):
    """Retorna dict (evento extraído), None (confirmado que no es un flyer
    de evento) o RETRY (ambos proveedores fallaron, reintentar más tarde).

    Dos pasadas como mucho: la primera sin caption (gratis, no gasta
    SerpAPI); la segunda con el caption real del post, pero SOLO si la
    primera dio un evento real con datos flojos — así no se gasta una
    llamada de SerpAPI en cada imagen que termina siendo basura."""
    _batch_state["last_failure_reason"] = ""
    image_bytes, media_type = read_image(image_path)

    supplied_caption = str(metadata.get("caption") or "").strip()
    initial_prompt = _build_prompt_text(supplied_caption)
    raw = _get_raw_json(image_path, image_bytes, media_type, initial_prompt)
    if raw is None:
        return RETRY
    data = _parse_json_evento(raw, image_path)
    if data is None:
        return RETRY

    if not data.get("es_evento", True):
        print(f"[processor] {image_path.name}: no es evento, saltando")
        return None

    link = metadata.get("link", "")
    indexed_context = ""
    necesita_fecha_publicacion = data.get("anio_confirmado") is False
    if link and (necesita_fecha_publicacion or (
        not supplied_caption and _necesita_caption(data)
    )):
        indexed_context = fetch_caption(link)
        if indexed_context:
            combined_context = "\n".join(
                part for part in (supplied_caption, indexed_context) if part
            )
            prompt_text = _build_prompt_text(combined_context)
            raw2 = _get_raw_json(image_path, image_bytes, media_type, prompt_text)
            data2 = _parse_json_evento(raw2, image_path) if raw2 else None
            if data2 and data2.get("es_evento", True):
                data = data2  # el reintento con caption reemplaza al primero

    # Enriquecer con metadata de URLs
    data["imagen_url"]       = metadata.get("thumbnail", "")
    data["link_promocional"] = metadata.get("link", "")
    data["fuente"]            = metadata.get("source", "google_images")
    data["fecha_descubrimiento"] = metadata.get("discovered_at", date.today().isoformat())
    data = validate_event_data(data)

    # Un evento automático futuro sólo se publica si la ficha indexada del
    # post coincide con la información visual. Ante cualquier duda se conserva
    # para revisión, sin exponer un link posiblemente ajeno.
    if data.get("activo") and data.get("fuente") == "google_images":
        if link and not indexed_context:
            indexed_context = fetch_caption(link)
        verified = bool(link and source_matches_event(data, indexed_context))
        data["fuente_verificada"] = verified
        if not verified:
            data["activo"] = False
            data["estado"] = "pendiente_confirmacion"
            data["link_promocional"] = ""
            data["motivo_revision"] = "imagen_y_link_sin_coincidencia_suficiente"
            print(
                f"[processor] {image_path.name}: fuente no verificada; "
                "queda en revisión"
            )

    if REVISION_MANUAL and data.get("activo"):
        data["activo"] = False
        data["estado"] = "pendiente_confirmacion"

    activo = data.get("activo", False)
    print(
        f"[processor] {image_path.name}: '{data.get('nombre','?')}' "
        f"— {'✓ activo' if activo else '✗ inactivo'} "
        f"— confianza {data.get('confianza','?')}"
    )
    return data


def process_batch(items: list[tuple[Path, dict]], candidate_store=None) -> list[dict]:
    results = []
    for path, metadata in items:
        attempts = int(metadata.get("_candidate_attempts", 0)) + 1
        if candidate_store:
            candidate_store.update(metadata, status="procesando", attempts=attempts)
        try:
            outcome = extract_event_data(path, metadata)
        except Exception as error:
            if candidate_store:
                candidate_store.update(
                    metadata,
                    status="reintentar",
                    attempts=attempts,
                    reason="error_inesperado",
                    last_error=str(error)[:500],
                )
            raise

        if outcome is RETRY:
            if candidate_store:
                candidate_store.update(
                    metadata,
                    status="reintentar",
                    attempts=attempts,
                    reason=_batch_state["last_failure_reason"] or "proveedores_no_disponibles",
                )
            if _batch_state["gemini_exhausted"] and _batch_state["claude_exhausted"]:
                print("[processor] Ambos proveedores sin cuota — se corta el batch acá")
                break
            continue  # hash no se marca visto: se reintenta en una corrida futura

        h = metadata.get("hash") or image_hash(path.read_bytes())
        save_hash(h)
        save_link(metadata.get("link", ""))
        if outcome is None:
            if candidate_store:
                candidate_store.update(
                    metadata,
                    status="descartado",
                    attempts=attempts,
                    reason="no_es_evento",
                )
            continue

        outcome["_candidate_id"] = metadata.get("_candidate_id", "")
        outcome["_candidate_row"] = metadata.get("_candidate_row")
        outcome["_candidate_attempts"] = attempts
        if candidate_store:
            candidate_store.update(
                metadata,
                status="extraido",
                attempts=attempts,
                event=outcome,
            )
        results.append(outcome)
    return results


if __name__ == "__main__":
    import sys
    paths = [(Path(p), {}) for p in sys.argv[1:]] if len(sys.argv) > 1 \
        else [(p, {}) for p in Path("images").glob("*.jpg")]
    events = process_batch(paths)
    print(f"\n{len(events)} evento(s) extraído(s):")
    for e in events:
        print(json.dumps(e, ensure_ascii=False, indent=2))
