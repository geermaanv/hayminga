"""
processor.py
Envía cada flyer a Claude Vision y extrae los datos del evento
con el schema exacto del Google Sheet de hayminga.org.
"""

import os
import json
import base64
from pathlib import Path
from datetime import datetime, date
import anthropic

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

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


def encode_image(path: Path) -> tuple[str, str]:
    suffix = path.suffix.lower().lstrip(".")
    media_map = {
        "jpg": "image/jpeg", "jpeg": "image/jpeg",
        "png": "image/png",  "webp": "image/webp",
    }
    media_type = media_map.get(suffix, "image/jpeg")
    data = base64.standard_b64encode(path.read_bytes()).decode("utf-8")
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
    return fecha_str, ""


def extract_event_data(image_path: Path, metadata: dict) -> dict | None:
    raw = ""
    try:
        b64, media_type = encode_image(image_path)

        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=600,
            system=SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": media_type, "data": b64},
                    },
                    {"type": "text", "text": "Extraé los datos de este flyer de evento."},
                ],
            }],
        )

        raw = response.content[0].text.strip()
        raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        data = json.loads(raw)

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

    except json.JSONDecodeError as e:
        print(f"[processor] Error JSON en {image_path.name}: {e} | raw: '{raw[:200]}'")
        return None
    except Exception as e:
        print(f"[processor] Error en {image_path.name}: {e}")
        return None


def process_batch(items: list[tuple[Path, dict]]) -> list[dict]:
    results = []
    for path, metadata in items:
        data = extract_event_data(path, metadata)
        if data:
            results.append(data)
    return results


if __name__ == "__main__":
    import sys
    paths = [(Path(p), {}) for p in sys.argv[1:]] if len(sys.argv) > 1 \
        else [(p, {}) for p in Path("images").glob("*.jpg")]
    events = process_batch(paths)
    print(f"\n{len(events)} evento(s) extraído(s):")
    for e in events:
        print(json.dumps(e, ensure_ascii=False, indent=2))
