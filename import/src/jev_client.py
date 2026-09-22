"""
jev_client.py
Cliente mínimo para la API de Jev (TypeSafe AI, modelo "system one") — ver
ROADMAP.md, 21-22/09: acceso confirmado con un workflow de diagnóstico
temporal (ya borrado), usado ahora por src/comparar_jev_gemini.py para
evaluar si conviene clasificar eventos con Jev en vez de o además de
Gemini. Solo hace preguntas de tipo "choice" sobre un texto (`state`) — es
lo único que se probó funcionando; no se confirmó soporte de imágenes.
"""

import os
import requests

TYPESAFE_API_URL = "https://api.typesafe.ai/v1/systemone"
JEV_MODEL = "jev-latest"


def preguntar(state: str, preguntas: dict[str, dict], timeout: int = 30) -> dict[str, str]:
    """Manda un texto (`state`) y un dict de preguntas tipo choice
    ({clave: {"instructions": ..., "criteria": {opcion: descripcion}}}),
    todas en un solo request. Devuelve {clave: opcion_elegida}.
    Sin timeout explícito una llamada colgada bloquea el proceso entero
    (mismo incidente real que motivó el timeout de genai.Client, ver
    PATRONES.md) — 30s es el mismo margen usado ahí."""
    api_key = os.environ.get("TYPESAFE_API_KEY")
    if not api_key:
        raise RuntimeError("TYPESAFE_API_KEY no configurada")

    questions_payload = {
        clave: {
            "type": "choice",
            "instructions": pregunta["instructions"],
            "criteria": pregunta["criteria"],
        }
        for clave, pregunta in preguntas.items()
    }
    resp = requests.post(
        TYPESAFE_API_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={"state": state, "model": JEV_MODEL, "questions": questions_payload},
        timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()
    return data.get("answers", {})
