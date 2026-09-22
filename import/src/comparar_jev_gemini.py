"""
comparar_jev_gemini.py
Corre el mismo set de captions contra el filtro de clasificación de
Gemini (es_evento + confianza, el mismo prompt/criterio que usa
hiker_pipeline.py en producción) y contra Jev, y compara.

Motivo (ver ROADMAP.md, 22/09): evaluar si conviene clasificar eventos con
Jev en vez de o además de Gemini. El repaso del 22/09 dejó el criterio de
confianza explícito en SYSTEM_PROMPT justamente para poder dárselo igual
a los dos lados de esta comparación — las preguntas para Jev abajo son
ese mismo criterio, no uno nuevo inventado para la ocasión.

Alcance deliberadamente acotado a es_evento + confianza (clasificación),
no a la extracción completa de campos: es lo único que se confirmó que la
API de Jev hace (preguntas "choice" sobre un texto — no se probó que
acepte imágenes), y "clasificar eventos" es literalmente cómo lo plantea
el ROADMAP.

Dataset: NO hay captions persistidas en ningún lado (la Sheet no guarda
el texto del post, solo los campos ya extraídos — ver PATRONES.md, columna
coupling). Los casos de abajo son ilustrativos: dos son los mismos
captions del diagnóstico real del 21/09 (ver ROADMAP.md), el resto cubre
a mano los bordes documentados (año no escrito -> confianza media,
agradecimiento post-evento, evento vago, tema ajeno a bioconstrucción).
Para una medición real hace falta correr esto contra captions reales de
una corrida — swapear CASOS por una carga desde un log/export cuando haya
volumen suficiente para que valga la pena.

Gratis salvo por las llamadas a Gemini/Jev que este mismo script hace
(no toca la Sheet, no publica nada). Requiere GEMINI_API_KEY y
TYPESAFE_API_KEY.
"""

import argparse
import json
from datetime import datetime, timezone

from src import hiker_pipeline, jev_client

PREGUNTAS_JEV = {
    "es_evento": {
        "instructions": (
            "¿El texto es la promoción de un evento futuro de bioconstrucción "
            "(taller, curso, minga, charla, festival) con fecha propia? Si el "
            "texto es un agradecimiento o resumen de algo que ya pasó (ej. "
            "'gracias a quienes vinieron', 'quedó hermoso el taller del "
            "sábado') sin invitar a una fecha futura concreta, la respuesta "
            "es 'no' aunque hable de bioconstrucción."
        ),
        "criteria": {
            "si": (
                "Invita a un evento futuro y concreto de bioconstrucción, "
                "con fecha (aunque sea aproximada) todavía no pasada."
            ),
            "no": (
                "No es un evento de bioconstrucción, o es un "
                "agradecimiento/resumen de algo que ya pasó sin invitar a "
                "una fecha futura."
            ),
        },
    },
    "confianza": {
        "instructions": (
            "Evaluá qué tan explícitos están los datos del evento (nombre, "
            "fecha con año, ubicación) en el texto, no la impresión general."
        ),
        "criteria": {
            "alta": (
                "Nombre, fecha CON AÑO ESCRITO (no inferido) y ubicación "
                "concreta (dirección, o 'virtual' sin ambigüedad) están los "
                "tres explícitos en el texto."
            ),
            "media": (
                "Es un evento real y se entiende bien, pero falta o es "
                "impreciso algo secundario (dirección exacta, contacto), o "
                "el año no estaba escrito y hay que inferirlo de otra señal."
            ),
            "baja": (
                "Algo crítico es dudoso o ambiguo: el nombre es vago, la "
                "fecha no es clara, o no está claro que sea un evento de "
                "bioconstrucción."
            ),
        },
    },
}

# id, caption, fecha de publicación del post (ISO, da el año cuando el
# caption no lo trae), nota de qué borde documenta cada caso.
CASOS = [
    {
        "id": "diagnostico_evento",
        "caption": (
            "Taller de bioconstrucción con superadobe. Sábado 12 de "
            "octubre, 10hs, en la Ecoescuela Tay Pichín, San Marcos "
            "Sierras, Córdoba. Cupos limitados, inscripción por DM."
        ),
        "fecha_publicacion": "2026-09-15",
        "nota": "Mismo caption del diagnóstico real (21/09). Sin año "
                "escrito -> confianza debería ser media, no alta.",
    },
    {
        "id": "diagnostico_no_evento",
        "caption": (
            "Miren qué lindo quedó este horno de barro que hicimos la "
            "semana pasada en el patio de casa!"
        ),
        "fecha_publicacion": "2026-09-15",
        "nota": "Mismo caption del diagnóstico real (21/09). No invita a "
                "nada futuro.",
    },
    {
        "id": "agradecimiento_post_evento",
        "caption": (
            "¡Gracias a quienes vinieron al taller de quincha del sábado "
            "pasado! Quedó hermoso, en breve subimos fotos."
        ),
        "fecha_publicacion": "2026-09-20",
        "nota": "El caso explícito del SYSTEM_PROMPT (22/09): agradecimiento "
                "de algo YA pasado, sin fecha futura -> es_evento=no aunque "
                "sea de bioconstrucción.",
    },
    {
        "id": "alta_confianza_completa",
        "caption": (
            "Curso de Bioconstrucción y Permacultura — Sábado 15 de "
            "noviembre de 2026, 9 a 18hs, en Casa de la Cultura, Tandil, "
            "Buenos Aires. Arancel $15.000, inscripción al whatsapp "
            "2494-555555."
        ),
        "fecha_publicacion": "2026-09-20",
        "nota": "Nombre, fecha CON año y dirección concreta, los tres "
                "explícitos -> caso limpio de confianza alta.",
    },
    {
        "id": "evento_vago",
        "caption": "Se viene algo lindo en octubre 👀 bioconstrucción y comunidad. Más info pronto.",
        "fecha_publicacion": "2026-09-18",
        "nota": "Sin nombre ni fecha ni lugar concretos. PATRONES.md pide "
                "blocklist-no-allowlist (dejar pasar la duda) para casos "
                "cortos/ambiguos — ver si Jev es igual de permisivo o "
                "descarta de más.",
    },
    {
        "id": "virtual_sin_anio",
        "caption": (
            "Webinar online: Introducción a la bioconstrucción con tierra. "
            "Miércoles 8/10, 19hs por Zoom. Inscripción gratuita en el "
            "link de la bio."
        ),
        "fecha_publicacion": "2026-09-16",
        "nota": "Virtual sin ambigüedad de lugar, pero año no escrito -> "
                "confianza media.",
    },
    {
        "id": "tema_ajeno",
        "caption": "Feria de emprendedores este finde en el club, sumate con tu stand!",
        "fecha_publicacion": "2026-09-19",
        "nota": "Evento real pero no es de bioconstrucción -> es_evento=no. "
                "Prueba si el criterio de dominio se sostiene en Jev.",
    },
]


def _epoch(fecha_iso: str) -> int:
    return int(datetime.fromisoformat(fecha_iso).replace(tzinfo=timezone.utc).timestamp())


def _gemini_clasificar(caption: str, fecha_publicacion: str) -> dict:
    post = {"caption": caption, "taken_at_ts": _epoch(fecha_publicacion)}
    raw = hiker_pipeline._call_gemini_text(hiker_pipeline._prompt_texto(post))
    data = hiker_pipeline._parse_json(raw)
    if data is None:
        return {"es_evento": None, "confianza": None, "error": f"JSON no parseable: {raw[:200]}"}
    es_evento = "si" if data.get("es_evento") else "no"
    return {"es_evento": es_evento, "confianza": data.get("confianza"), "raw": data}


def _jev_clasificar(caption: str) -> dict:
    respuestas = jev_client.preguntar(caption, PREGUNTAS_JEV)
    return {
        "es_evento": respuestas.get("es_evento"),
        "confianza": respuestas.get("confianza"),
        "raw": respuestas,
    }


def correr_comparacion() -> list[dict]:
    resultados = []
    for caso in CASOS:
        fila = {"id": caso["id"], "nota": caso["nota"]}
        try:
            fila["gemini"] = _gemini_clasificar(caso["caption"], caso["fecha_publicacion"])
        except Exception as e:
            fila["gemini"] = {"error": str(e)}
        try:
            fila["jev"] = _jev_clasificar(caso["caption"])
        except Exception as e:
            fila["jev"] = {"error": str(e)}

        g, j = fila["gemini"], fila["jev"]
        fila["coincide_es_evento"] = (
            "error" not in g and "error" not in j and g.get("es_evento") == j.get("es_evento")
        )
        fila["coincide_confianza"] = (
            "error" not in g and "error" not in j and g.get("confianza") == j.get("confianza")
        )
        resultados.append(fila)
    return resultados


def imprimir_resumen(resultados: list[dict]) -> None:
    print(f"{'caso':<28} {'gemini(evento/confianza)':<28} {'jev(evento/confianza)':<28} coincide")
    print("-" * 100)
    for fila in resultados:
        g, j = fila["gemini"], fila["jev"]
        g_txt = f"{g.get('es_evento')}/{g.get('confianza')}" if "error" not in g else f"ERROR: {g['error'][:40]}"
        j_txt = f"{j.get('es_evento')}/{j.get('confianza')}" if "error" not in j else f"ERROR: {j['error'][:40]}"
        marca = "✓✓" if fila["coincide_es_evento"] and fila["coincide_confianza"] else (
            "✓·" if fila["coincide_es_evento"] else "··"
        )
        print(f"{fila['id']:<28} {g_txt:<28} {j_txt:<28} {marca}")
        print(f"  nota: {fila['nota']}")

    total = len(resultados)
    validos = [f for f in resultados if "error" not in f["gemini"] and "error" not in f["jev"]]
    coinciden_evento = sum(1 for f in validos if f["coincide_es_evento"])
    coinciden_confianza = sum(1 for f in validos if f["coincide_confianza"])
    print("-" * 100)
    print(f"Casos: {total} | con respuesta de ambos lados: {len(validos)}")
    if validos:
        print(f"Coinciden es_evento: {coinciden_evento}/{len(validos)}")
        print(f"Coinciden confianza: {coinciden_confianza}/{len(validos)}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--guardar", help="Ruta para volcar el resultado completo en JSON")
    args = parser.parse_args()

    resultados = correr_comparacion()
    imprimir_resumen(resultados)

    if args.guardar:
        with open(args.guardar, "w", encoding="utf-8") as f:
            json.dump(resultados, f, ensure_ascii=False, indent=2)
        print(f"\nGuardado en {args.guardar}")


if __name__ == "__main__":
    main()
