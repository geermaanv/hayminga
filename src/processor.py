"""
processor.py
Envía cada flyer a Claude Vision y extrae los datos del evento.
"""

import os
import json
import base64
from pathlib import Path
import anthropic

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

SYSTEM_PROMPT = """Sos un extractor de datos de eventos de bioconstrucción.
Analizás imágenes de flyers y extraés la información del evento.
Respondés ÚNICAMENTE con un JSON válido, sin texto adicional, sin markdown.

Formato exacto:
{
  "nombre": "nombre del evento",
  "tipo_evento": "Curso | Taller | Minga | Charla | Evento | Residencia | Festival",
  "fecha_inicio": "DD/MM/YYYY o null",
  "fecha_fin": "DD/MM/YYYY o null",
  "lugar": "ciudad, provincia, país o null",
  "modalidad": "Presencial | Virtual | Híbrido o null",
  "incluye_practica": true o false,
  "descripcion": "una línea o null",
  "lugares_disponibles": número o null,
  "nivel_requerido": "Inicial | Medio | Experto o null",
  "organizador": "nombre del organizador o null",
  "confianza": "alta | media | baja"
}

Si la imagen no es un flyer de evento de bioconstrucción, respondé:
{"es_evento": false}
"""


def encode_image(path: Path) -> tuple[str, str]:
    suffix = path.suffix.lower().lstrip(".")
    media_map = {
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "webp": "image/webp",
    }
    media_type = media_map.get(suffix, "image/jpeg")
    data = base64.standard_b64encode(path.read_bytes()).decode("utf-8")
    return data, media_type


def extract_event_data(image_path: Path, metadata: dict) -> dict | None:
    """
    Procesa una imagen con Claude Vision.
    metadata contiene: thumbnail, original, link
    """
    raw = ""
    try:
        b64, media_type = encode_image(image_path)

        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=600,
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": b64,
                            },
                        },
                        {
                            "type": "text",
                            "text": "Extraé los datos de este flyer de evento.",
                        },
                    ],
                }
            ],
        )

        raw = response.content[0].text.strip()
        raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        data = json.loads(raw)

        if not data.get("es_evento", True):
            print(f"[processor] {image_path.name}: no es un evento, saltando")
            return None

        # Agregar metadata de URLs
        data["imagen_url"] = metadata.get("original") or metadata.get("thumbnail", "")
        data["link_promocional"] = metadata.get("link", "")

        print(f"[processor] {image_path.name}: '{data.get('nombre', '?')}' — confianza {data.get('confianza', '?')}")
        return data

    except json.JSONDecodeError as e:
        print(f"[processor] Error parseando JSON para {image_path.name}: {e}")
        print(f"[processor] Respuesta cruda: '{raw[:200]}'")
        return None
    except Exception as e:
        print(f"[processor] Error procesando {image_path.name}: {e}")
        return None


def process_batch(items: list[tuple[Path, dict]]) -> list[dict]:
    """Procesa una lista de (path, metadata) y retorna los eventos extraídos."""
    results = []
    for path, metadata in items:
        data = extract_event_data(path, metadata)
        if data:
            results.append(data)
    return results


if __name__ == "__main__":
    import sys
    paths = [(Path(p), {}) for p in sys.argv[1:]] if len(sys.argv) > 1 else [(p, {}) for p in Path("images").glob("*.jpg")]
    events = process_batch(paths)
    print(f"\n{len(events)} evento(s) extraído(s):")
    for e in events:
        print(json.dumps(e, ensure_ascii=False, indent=2))
