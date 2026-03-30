"""
processor.py
Envía cada flyer a Claude Vision y extrae los 4 campos del evento.
"""

import os
import json
import base64
from pathlib import Path
import anthropic

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

SYSTEM_PROMPT = """Sos un extractor de datos de eventos de bioconstrucción.
Analizás imágenes de flyers de Instagram y extraés la información del evento.
Respondés ÚNICAMENTE con un JSON válido, sin texto adicional, sin markdown.

Formato exacto:
{
  "nombre": "nombre del evento o minga",
  "fecha": "fecha en formato DD/MM/YYYY, o rango si aplica. null si no encontrás",
  "lugar": "ciudad, provincia o dirección. null si no encontrás",
  "contacto": "link, email, teléfono o usuario de Instagram. null si no encontrás",
  "descripcion": "una línea describiendo el evento. null si no podés inferir",
  "confianza": "alta | media | baja"
}

Si la imagen no es un flyer de evento de bioconstrucción, respondé:
{"es_evento": false}
"""


def encode_image(path: Path) -> tuple[str, str]:
    """Retorna (base64_data, media_type)."""
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


def extract_event_data(image_path: Path) -> dict | None:
    """
    Procesa una imagen con Claude Vision.
    Retorna dict con los datos del evento, o None si no es un evento válido.
    """
    try:
        b64, media_type = encode_image(image_path)

        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=500,
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
        data = json.loads(raw)

        if not data.get("es_evento", True):
            print(f"[processor] {image_path.name}: no es un evento, saltando")
            return None

        data["imagen_fuente"] = image_path.name
        print(f"[processor] {image_path.name}: '{data.get('nombre', '?')}' — confianza {data.get('confianza', '?')}")
        return data

    except json.JSONDecodeError as e:
        print(f"[processor] Error parseando JSON para {image_path.name}: {e}")
        return None
    except Exception as e:
        print(f"[processor] Error procesando {image_path.name}: {e}")
        return None


def process_batch(image_paths: list[Path]) -> list[dict]:
    """Procesa una lista de imágenes y retorna los eventos extraídos."""
    results = []
    for path in image_paths:
        data = extract_event_data(path)
        if data:
            results.append(data)
    return results


if __name__ == "__main__":
    import sys
    paths = [Path(p) for p in sys.argv[1:]] if len(sys.argv) > 1 else list(Path("images").glob("*.jpg"))
    events = process_batch(paths)
    print(f"\n{len(events)} evento(s) extraído(s):")
    for e in events:
        print(json.dumps(e, ensure_ascii=False, indent=2))
