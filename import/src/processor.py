"""
processor.py
Envía cada flyer a Gemini Vision (gratis) y extrae los datos del evento
con el schema exacto del Google Sheet de hayminga.org. Si Gemini falla o
se queda sin cuota, reintenta esa misma imagen con Claude como fallback.
"""

import os
import json
import base64
from pathlib import Path
from datetime import datetime, date
from google import genai
from google.genai import types
from google.genai import errors as genai_errors
import anthropic

from src.state import save_hash, save_link, image_hash

client_gemini = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
GEMINI_MODEL = "gemini-flash-latest"

_claude_key   = os.environ.get("ANTHROPIC_API_KEY")
client_claude = anthropic.Anthropic(api_key=_claude_key) if _claude_key else None
CLAUDE_MODEL  = "claude-haiku-4-5-20251001"

# Sentinel: ninguno de los proveedores disponibles pudo procesar la imagen
# (red, cuota, respuesta no-JSON). No se marca el hash como visto, para que
# se reintente en una corrida futura en vez de perderse para siempre.
RETRY = object()

# Estado del batch actual: una vez que un proveedor reporta cuota agotada,
# se deja de intentarlo para el resto de las imágenes de esta corrida.
_batch_state = {"gemini_exhausted": False, "claude_exhausted": False}

HOY = date.today().isoformat()

SYSTEM_PROMPT = f"""Sos un extractor de datos de eventos de bioconstrucción para hayminga.org.
Analizás imágenes de flyers y extraés la información del evento.
Respondés ÚNICAMENTE con un JSON válido, sin texto adicional, sin markdown.

Fecha de hoy: {HOY}

Formato exacto de respuesta:
{{
  "nombre": "nombre del evento",
  "tipo_evento": "Curso | Taller | Minga | Charla | Evento | Residencia | Festival",
  "fecha_inicio": "DD/MM/YYYY o null",
  "fecha_fin": "DD/MM/YYYY o null",
  "es_virtual": true o false,
  "provincia": "provincia argentina o null — si es otro país poner null",
  "pais": "Argentina | Chile | Uruguay | México | otro",
  "descripcion": "una línea descriptiva del evento o null",
  "organizador": "nombre del organizador o null",
  "direccion": "dirección o ciudad o null",
  "confianza": "alta | media | baja",
  "activo": true o false
}}

Reglas para el campo 'activo':
- true SOLO si: el evento es en Argentina Y la fecha_inicio es posterior a hoy ({HOY})
- false si: es en otro país, o la fecha ya pasó, o no se puede determinar la fecha

Si la imagen NO es un flyer de evento de bioconstrucción, respondé exactamente:
{{"es_evento": false}}
"""

PROMPT_TEXT = "Extraé los datos de este flyer de evento."


def read_image(path: Path) -> tuple[bytes, str]:
    suffix = path.suffix.lower().lstrip(".")
    media_map = {
        "jpg": "image/jpeg", "jpeg": "image/jpeg",
        "png": "image/png",  "webp": "image/webp",
    }
    media_type = media_map.get(suffix, "image/jpeg")
    return path.read_bytes(), media_type


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
    return fecha_str, ""


def _call_gemini(image_bytes: bytes, media_type: str) -> str:
    response = client_gemini.models.generate_content(
        model=GEMINI_MODEL,
        contents=[
            types.Part.from_bytes(data=image_bytes, mime_type=media_type),
            PROMPT_TEXT,
        ],
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
            max_output_tokens=1024,
        ),
    )
    return (response.text or "").strip()


def _call_claude(image_bytes: bytes, media_type: str) -> str:
    if client_claude is None:
        raise RuntimeError("ANTHROPIC_API_KEY no configurada — sin fallback disponible")
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
                {"type": "text", "text": PROMPT_TEXT},
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


def _get_raw_json(image_path: Path, image_bytes: bytes, media_type: str) -> str | None:
    """Intenta Gemini primero, cae a Claude si falla. Retorna None si ambos
    proveedores fallan (o no hay ninguno disponible)."""
    if not _batch_state["gemini_exhausted"]:
        try:
            return _call_gemini(image_bytes, media_type)
        except Exception as e:
            if _is_quota_error(e):
                _batch_state["gemini_exhausted"] = True
                print(f"[processor] Gemini sin cuota — resto del batch usa Claude")
            else:
                print(f"[processor] Gemini falló en {image_path.name}: {e}")

    if _batch_state["claude_exhausted"]:
        return None
    try:
        return _call_claude(image_bytes, media_type)
    except Exception as e:
        if _is_quota_error(e):
            _batch_state["claude_exhausted"] = True
            print(f"[processor] Claude también sin crédito")
        else:
            print(f"[processor] Claude (fallback) falló en {image_path.name}: {e}")
        return None


def extract_event_data(image_path: Path, metadata: dict):
    """Retorna dict (evento extraído), None (confirmado que no es un flyer
    de evento) o RETRY (ambos proveedores fallaron, reintentar más tarde)."""
    image_bytes, media_type = read_image(image_path)
    raw = _get_raw_json(image_path, image_bytes, media_type)
    if raw is None:
        return RETRY

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"[processor] Error JSON en {image_path.name}: {e} | raw: '{raw[:200]}'")
        return RETRY

    if not data.get("es_evento", True):
        print(f"[processor] {image_path.name}: no es evento, saltando")
        return None

    # Enriquecer con metadata de URLs
    data["imagen_url"]       = metadata.get("thumbnail", "")
    data["link_promocional"] = metadata.get("link", "")

    # Parsear fechas
    fecha_inicio_iso, periodo = parse_fecha(data.get("fecha_inicio"))
    fecha_fin_iso, _          = parse_fecha(data.get("fecha_fin"))
    data["fecha_inicio_iso"] = fecha_inicio_iso
    data["fecha_fin_iso"]    = fecha_fin_iso
    data["periodo"]          = periodo

    activo = data.get("activo", False)
    print(
        f"[processor] {image_path.name}: '{data.get('nombre','?')}' "
        f"— {'✓ activo' if activo else '✗ inactivo'} "
        f"— confianza {data.get('confianza','?')}"
    )
    return data


def process_batch(items: list[tuple[Path, dict]]) -> list[dict]:
    results = []
    for path, metadata in items:
        outcome = extract_event_data(path, metadata)

        if outcome is RETRY:
            if _batch_state["gemini_exhausted"] and _batch_state["claude_exhausted"]:
                print("[processor] Ambos proveedores sin cuota — se corta el batch acá")
                break
            continue  # hash no se marca visto: se reintenta en una corrida futura

        h = metadata.get("hash") or image_hash(path.read_bytes())
        save_hash(h)
        save_link(metadata.get("link", ""))
        if outcome is not None:
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
