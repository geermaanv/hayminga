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
coupling). Los 30 casos de CASOS son a mano/ilustrativos: dos son los
captions reales del diagnóstico del 21/09 (ver ROADMAP.md), el resto cubre
a mano los bordes documentados (año no escrito -> confianza media,
agradecimiento post-evento, evento vago, tema ajeno/adyacente a
bioconstrucción, texto informal/confuso, dato crítico ausente).

`--pendientes N` es la aproximación más cercana a datos reales que se
puede hacer sin loguear captions nuevos: toma hasta N eventos que HOY
están frenados en `pendiente_confirmacion` por `confianza=baja` de
Gemini, arma un texto proxy con los campos que Gemini ya extrajo
(nombre, descripción, fecha, lugar — ver `_reconstruir_texto`), y le
pregunta a Jev si los publicaría. No es el caption original (no se
persiste), así que no mide si Jev "ve" algo que Gemini no vio — mide si,
con la MISMA información, Jev es más o menos permisivo que Gemini. Solo
llama a Jev (Gemini ya dio su veredicto real, guardado en la Sheet).

Gratis salvo por las llamadas a Gemini/Jev que este mismo script hace
(no toca la Sheet, no publica nada — ni siquiera en modo --pendientes,
que solo lee). Requiere GEMINI_API_KEY y TYPESAFE_API_KEY para el modo
default; --pendientes además requiere GOOGLE_SERVICE_ACCOUNT_JSON y
GOOGLE_SPREADSHEET_ID (no requiere GEMINI_API_KEY, no vuelve a llamar a
Gemini).
"""

import argparse
import json
from datetime import datetime, timezone

from src import hiker_pipeline, jev_client, sheets
from src.processor import CONFIANZA_PUBLICABLE

PREGUNTAS_JEV = {
    "es_evento": {
        "instructions": (
            "¿El texto es la promoción de un evento futuro de bioconstrucción "
            "(taller, curso, minga, charla, festival) con fecha propia? Si el "
            "texto es un agradecimiento o resumen de algo que ya pasó (ej. "
            "'gracias a quienes vinieron', 'quedó hermoso el taller del "
            "sábado') y no menciona ningún evento futuro, la respuesta es "
            "'no' aunque hable de bioconstrucción. Pero si ese mismo texto "
            "TAMBIÉN anuncia un próximo evento concreto, aunque sea breve "
            "(ej. 'gracias a quienes vinieron! ya estamos organizando el "
            "próximo para el 14 de noviembre'), la respuesta es 'si' — no "
            "descartes el texto entero solo porque empieza agradeciendo "
            "algo pasado."
        ),
        "criteria": {
            "si": (
                "Invita a un evento futuro y concreto de bioconstrucción, "
                "con fecha (aunque sea aproximada) todavía no pasada — "
                "incluso si el mismo texto también agradece o resume algo "
                "ya pasado."
            ),
            "no": (
                "No es un evento de bioconstrucción, o es un "
                "agradecimiento/resumen de algo que ya pasó sin mencionar "
                "ningún evento futuro."
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
    {
        "id": "fecha_relativa_sin_dia",
        "caption": (
            "Se viene el próximo taller de bioconstrucción con tierra "
            "cruda acá en el espacio, en dos semanas. Consultanos por acá "
            "para más info y quedar anotado."
        ),
        "fecha_publicacion": "2026-09-14",
        "nota": "Fecha relativa ('en dos semanas'), sin día/mes/año ni "
                "lugar concretos -> nombre vago del evento y fecha no "
                "verificable, debería ser confianza baja.",
    },
    {
        "id": "festival_multidia_completo",
        "caption": (
            "Festival de Construcción Natural — del 20 al 22 de marzo de "
            "2027 en el Predio Ferial, Villa General Belgrano, Córdoba. "
            "Tres días de talleres de quincha, superadobe y techos vivos. "
            "Entradas por Alternativa Tickets."
        ),
        "fecha_publicacion": "2026-09-10",
        "nota": "Nombre, rango de fechas CON año y ubicación concreta, "
                "los tres explícitos -> confianza alta, aunque el evento "
                "dure varios días (no es un edge case de duración, sino "
                "de completitud de datos).",
    },
    {
        "id": "virtual_completo_con_anio",
        "caption": (
            "Curso online 'Introducción al bioconstrucción con adobe' — "
            "arranca el 3 de noviembre de 2026, por Zoom, 4 clases en "
            "vivo. Inscripción en el link de la bio, cupos limitados."
        ),
        "fecha_publicacion": "2026-09-21",
        "nota": "Virtual con año explícito y modalidad sin ambigüedad "
                "('por Zoom') -> confianza alta. Contrasta con "
                "virtual_sin_anio (mismo tipo de evento, sin año).",
    },
    {
        "id": "mixto_agradecimiento_y_proximo",
        "caption": (
            "¡Terminamos el taller de techos verdes del fin de semana, "
            "gracias a todes los que vinieron! Y ya estamos organizando "
            "el próximo para el 14 de noviembre, mismo lugar. Más info "
            "pronto."
        ),
        "fecha_publicacion": "2026-09-21",
        "nota": "Mezcla agradecimiento por algo pasado CON un anuncio de "
                "evento futuro concreto (día y mes, año no escrito) -> "
                "es_evento=si a pesar del agradecimiento inicial (el "
                "SYSTEM_PROMPT exige 'sin invitar a fecha futura concreta' "
                "para descartar); confianza media por año inferido. "
                "Corregido el 22/09 tras la segunda corrida (ver "
                "ROADMAP.md) — antes Gemini lo descartaba entero.",
    },
    {
        "id": "agradecimiento_con_futuro_vago_sin_fecha",
        "caption": (
            "¡Gracias a todes! Nos seguimos viendo pronto por acá, ya va "
            "a haber más talleres."
        ),
        "fecha_publicacion": "2026-09-21",
        "nota": "Contraprueba del fix de mixto_agradecimiento_y_proximo: "
                "menciona 'más talleres' pero SIN fecha concreta -> tiene "
                "que seguir siendo es_evento=no. Si esto da 'si', el fix "
                "del 22/09 se pasó de permisivo.",
    },
    {
        "id": "nombre_vago_fecha_clara",
        "caption": (
            "Nos vemos el sábado 10 de octubre de 2026 en la finca, va a "
            "estar bueno."
        ),
        "fecha_publicacion": "2026-09-12",
        "nota": "Fecha con año explícito, pero sin nombre de evento ni "
                "lugar concreto ('la finca' no es una dirección) -> "
                "nombre vago, debería ser confianza baja pese a la fecha "
                "clara.",
    },
    {
        "id": "sin_lugar_media",
        "caption": (
            "Taller de techos de paja — sábado 7 de noviembre de 2026, "
            "en la zona, cupos limitados. Escribinos por acá para la "
            "dirección exacta."
        ),
        "fecha_publicacion": "2026-09-13",
        "nota": "Nombre y fecha con año explícitos, pero dirección "
                "solo aproximada ('en la zona') -> falta/impreciso algo "
                "secundario, confianza media.",
    },
    {
        "id": "contacto_incompleto_alta",
        "caption": (
            "Curso de bahareque y quincha — 21 de noviembre de 2026, "
            "Chapadmalal, Buenos Aires. Cupos limitados."
        ),
        "fecha_publicacion": "2026-09-11",
        "nota": "Nombre, fecha con año y lugar concreto, los tres "
                "explícitos; sin dato de contacto, que es secundario y no "
                "forma parte del criterio de confianza -> alta.",
    },
    {
        "id": "minga_alta_limpia",
        "caption": (
            "Minga comunitaria de construcción con adobe — domingo 5 de "
            "julio de 2026, Escuela Rural N°12, Chubut. Se suma cualquiera "
            "con ganas de aprender."
        ),
        "fecha_publicacion": "2026-06-20",
        "nota": "Variante de caso limpio con otra técnica (minga/adobe) y "
                "publicación con meses de anticipación -> confianza alta.",
    },
    {
        "id": "domain_borderline_arquitectura_sustentable",
        "caption": (
            "Charla sobre arquitectura sustentable y eficiencia "
            "energética en la vivienda — miércoles 4 de noviembre de "
            "2026, Centro Cultural, Neuquén."
        ),
        "fecha_publicacion": "2026-09-17",
        "nota": "Borde de dominio: 'arquitectura sustentable' es adyacente "
                "a bioconstrucción pero no la nombra (puede ser eficiencia "
                "energética convencional, no construcción natural) — sin "
                "respuesta correcta definida, prueba si los dos lados "
                "leen el dominio igual de ancho o angosto.",
    },
    {
        "id": "post_evento_fotos_sin_futuro",
        "caption": (
            "Así quedó el techo verde que armamos ayer con el grupo, un "
            "embole total pero valió la pena 😅🌱"
        ),
        "fecha_publicacion": "2026-09-20",
        "nota": "Recap de algo pasado sin la palabra 'gracias' (frase más "
                "informal) y sin ninguna mención de futuro -> es_evento=no, "
                "prueba que la regla de recap no dependa de la palabra "
                "'gracias' puntual.",
    },
    {
        "id": "anuncio_fecha_ya_pasada",
        "caption": (
            "Vení al taller de bioconstrucción con superadobe, sábado 10 "
            "de octubre de 2024, Escuela de Oficios, Río Negro."
        ),
        "fecha_publicacion": "2026-09-15",
        "nota": "Anuncio con formato idéntico a un caso alta, pero el año "
                "escrito (2024) ya pasó respecto a la fecha de publicación "
                "(2026) — la clasificación de es_evento/confianza no "
                "filtra por fecha pasada (eso lo hace procesar_post "
                "después, ver CLAUDE.md), así que debería seguir dando "
                "si/alta acá; solo prueba que el modelo no confunda 'año "
                "viejo' con 'agradecimiento'.",
    },
    {
        "id": "recurrente_todos_los_sabados",
        "caption": (
            "Talleres de bioconstrucción todos los sábados de octubre, "
            "desde el 3, en la chacra, San Martín de los Andes, Neuquén."
        ),
        "fecha_publicacion": "2026-09-16",
        "nota": "Evento recurrente (varias fechas, no una) con año no "
                "escrito y lugar aproximado ('la chacra') -> al menos dos "
                "cosas imprecisas a la vez, probablemente baja.",
    },
    {
        "id": "sede_a_confirmar_media",
        "caption": (
            "Festival de Bioconstrucción Latinoamericano — del 10 al 15 "
            "de enero de 2027, sede a confirmar."
        ),
        "fecha_publicacion": "2026-09-14",
        "nota": "Nombre y fecha con año explícitos y claros, pero "
                "ubicación explícitamente pendiente ('sede a confirmar') "
                "-> falta un dato secundario, confianza media.",
    },
    {
        "id": "caption_ultra_corto_vago",
        "caption": "🔥🔥🔥 Octubre nos vemos 🔥🔥🔥",
        "fecha_publicacion": "2026-09-18",
        "nota": "Menos de 6 palabras reales, sin ningún dato verificable — "
                "mismo espíritu que evento_vago pero más extremo. Prueba "
                "el límite inferior de información.",
    },
    {
        "id": "curso_alta_tecnica_distinta",
        "caption": (
            "Curso de construcción con fardos de paja — sábado 28 de "
            "noviembre de 2026, Predio Municipal, El Bolsón, Río Negro. "
            "Inscripción por mail, arancel solidario."
        ),
        "fecha_publicacion": "2026-09-10",
        "nota": "Otro caso limpio (técnica distinta, fardos de paja) para "
                "no sobre-representar 'alta' con un solo tipo de evento "
                "en la muestra.",
    },
    {
        "id": "virtual_lugar_generico_baja",
        "caption": (
            "Charla sobre bioconstrucción, se hace por internet, después "
            "pasamos el link."
        ),
        "fecha_publicacion": "2026-09-19",
        "nota": "Virtual pero sin fecha ninguna y modalidad dicha de forma "
                "informal ('por internet', no 'Zoom' ni link) -> "
                "confianza baja, más débil que virtual_sin_anio (que sí "
                "tenía fecha).",
    },
    {
        "id": "domain_permacultura_adyacente",
        "caption": (
            "Encuentro de permacultura y agroecología — sábado 24 de "
            "octubre de 2026, La Plata, Buenos Aires. Habrá intercambio "
            "de semillas y charlas sobre diseño de sistemas."
        ),
        "fecha_publicacion": "2026-09-12",
        "nota": "Permacultura sin mención de construcción natural — "
                "dominio adyacente pero no bioconstrucción en sentido "
                "estricto. Igual que domain_borderline_arquitectura_"
                "sustentable, sin respuesta correcta definida.",
    },
    {
        "id": "festival_multidia_sin_anio",
        "caption": (
            "Festival de Construcción Natural — del 20 al 22 de marzo, "
            "Predio Ferial, Villa General Belgrano, Córdoba. Talleres de "
            "quincha, superadobe y techos vivos."
        ),
        "fecha_publicacion": "2026-09-10",
        "nota": "Igual a festival_multidia_completo pero SIN año escrito "
                "-> contraste directo, debería bajar de alta a media por "
                "el mismo motivo que diagnostico_evento/virtual_sin_anio.",
    },
    {
        "id": "texto_confuso_baja",
        "caption": (
            "che vengan el finde q hay algo de tierra y eso, en lo de "
            "martín, después les paso bien la posta"
        ),
        "fecha_publicacion": "2026-09-19",
        "nota": "Texto genuinamente confuso/informal: ni nombre de "
                "evento, ni fecha exacta, ni dirección, ni claridad de que "
                "sea bioconstrucción -> baja, prueba robustez ante texto "
                "poco estructurado (más realista que un flyer prolijo).",
    },
    {
        "id": "evento_con_solo_mes_sin_dia",
        "caption": (
            "Taller de quincha en noviembre de 2026, San Marcos Sierras, "
            "Córdoba. Fecha exacta a confirmar según demanda."
        ),
        "fecha_publicacion": "2026-09-15",
        "nota": "Año escrito pero sin día concreto ('fecha exacta a "
                "confirmar') -> dato crítico (fecha) ambiguo pese al año "
                "explícito, probablemente baja más que media.",
    },
    {
        "id": "evento_hora_sin_fecha",
        "caption": (
            "Taller de bioconstrucción con tierra, arranca a las 10hs, "
            "en el vivero municipal, Bariloche, Río Negro."
        ),
        "fecha_publicacion": "2026-09-20",
        "nota": "Hora concreta pero SIN fecha (ni día ni mes) — dato "
                "crítico ausente pese a que el resto suena específico -> "
                "baja.",
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
    """La API de Jev no devuelve el string elegido directo: cada pregunta
    vuelve como {"type": "choice", "choice": "<opción>", "confidence": ...,
    "probabilities": {...}} — más rico que la salida plana de Gemini
    (trae confianza numérica de la propia clasificación), pero hay que
    extraer "choice" para comparar contra el string de Gemini."""
    respuestas = jev_client.preguntar(caption, PREGUNTAS_JEV)
    es_evento = respuestas.get("es_evento") or {}
    confianza = respuestas.get("confianza") or {}
    return {
        "es_evento": es_evento.get("choice"),
        "es_evento_confidence": es_evento.get("confidence"),
        "confianza": confianza.get("choice"),
        "confianza_confidence": confianza.get("confidence"),
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
        if "error" not in j:
            j_txt = (
                f"{j.get('es_evento')}({j.get('es_evento_confidence')})/"
                f"{j.get('confianza')}({j.get('confianza_confidence')})"
            )
        else:
            j_txt = f"ERROR: {j['error'][:40]}"
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


def _reconstruir_texto(row: list) -> str:
    """Arma un texto proxy del caption original a partir de los campos ya
    extraídos por Gemini (no hay caption crudo persistido, ver PATRONES.md
    — columna coupling). No es el texto real que vio Gemini, así que no
    sirve para re-evaluar a Gemini con justicia, pero sí para ver qué
    clasificación le daría Jev a la misma información que ya tenemos."""
    nombre, direccion, fecha_inicio = row[1], row[2], row[4]
    es_virtual, provincia, descripcion = row[6], row[7], row[8]
    tipo_evento, contacto = row[11], row[15]

    partes = [p for p in (nombre, tipo_evento, descripcion) if p]
    lugar = direccion or provincia or ("Virtual" if es_virtual == "TRUE" else "")
    partes.append(f"Fecha: {fecha_inicio or 'sin especificar'}. Lugar: {lugar or 'sin especificar'}.")
    if contacto:
        partes.append(f"Contacto: {contacto}")
    return " ".join(partes)


def cargar_casos_reales_pendientes(limite: int = 20) -> list[dict]:
    """Eventos reales frenados en pendiente_confirmacion por confianza baja
    (no por duplicado ambiguo, que es la otra razón de llegar a ese estado
    — ver CLAUDE.md). Son la cola de revisión manual que el proyecto
    quiere reducir (ver ROADMAP.md 22/09: "el proceso de importación no
    puede basarse en el trabajo manual de Germán")."""
    service = sheets.get_service()
    result = (
        service.spreadsheets().values()
        .get(spreadsheetId=sheets.SPREADSHEET_ID, range=f"{sheets.SHEET_NAME}!A2:Y")
        .execute()
    )
    casos = []
    for row in result.get("values", []):
        row = (row + [""] * len(sheets.COLUMNS))[:len(sheets.COLUMNS)]
        estado = (row[16] or "").strip().lower()
        confianza_real = (row[18] or "").strip().lower()
        if estado != "pendiente_confirmacion" or confianza_real != "baja":
            continue
        texto = _reconstruir_texto(row)
        if not texto.strip():
            continue
        casos.append({
            "id": row[14] or f"fila_sin_id_{len(casos) + 1}",
            "nombre": row[1] or "(sin nombre)",
            "caption": texto,
            "confianza_real": confianza_real,
        })
        if len(casos) >= limite:
            break
    return casos


def correr_contra_pendientes(limite: int = 20) -> list[dict]:
    casos = cargar_casos_reales_pendientes(limite)
    resultados = []
    for caso in casos:
        try:
            jev = _jev_clasificar(caso["caption"])
        except Exception as e:
            jev = {"error": str(e)}
        resultados.append({
            "id": caso["id"], "nombre": caso["nombre"],
            "confianza_gemini_real": caso["confianza_real"], "jev": jev,
        })
    return resultados


def imprimir_resumen_pendientes(resultados: list[dict]) -> None:
    print("Eventos reales en pendiente_confirmacion por confianza_baja de Gemini:")
    print(f"{'id':<14} {'nombre':<40} {'jev(evento/confianza)':<28} ¿Jev lo publicaría?")
    print("-" * 110)
    rescatables = 0
    for fila in resultados:
        j = fila["jev"]
        nombre = fila["nombre"][:38]
        if "error" in j:
            print(f"{fila['id']:<14} {nombre:<40} ERROR: {j['error'][:50]}")
            continue
        j_txt = f"{j.get('es_evento')}({j.get('es_evento_confidence')})/{j.get('confianza')}({j.get('confianza_confidence')})"
        publicaria = (j.get("es_evento") == "si" and j.get("confianza") in CONFIANZA_PUBLICABLE)
        if publicaria:
            rescatables += 1
        print(f"{fila['id']:<14} {nombre:<40} {j_txt:<28} {'SI' if publicaria else 'no'}")

    validos = [f for f in resultados if "error" not in f["jev"]]
    print("-" * 110)
    print(f"Eventos evaluados: {len(resultados)} | con respuesta de Jev: {len(validos)}")
    if validos:
        print(f"Jev los publicaría (es_evento=si y confianza en {CONFIANZA_PUBLICABLE}): {rescatables}/{len(validos)}")
        print("Nota: el texto de entrada es reconstruido de los campos ya extraídos, "
              "no el caption original (no se persiste, ver PATRONES.md) — esto mide "
              "si Jev es más permisivo con la MISMA información que ya tiene Gemini, "
              "no si vería algo que Gemini no vio en la imagen/caption real.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--guardar", help="Ruta para volcar el resultado completo en JSON")
    parser.add_argument(
        "--pendientes", type=int, metavar="N", default=None,
        help="En vez de CASOS, corre Jev contra hasta N eventos reales en "
             "pendiente_confirmacion con confianza=baja (requiere "
             "GOOGLE_SERVICE_ACCOUNT_JSON/GOOGLE_SPREADSHEET_ID; no llama a "
             "Gemini, compara contra la confianza ya registrada en la Sheet)",
    )
    args = parser.parse_args()

    if args.pendientes is not None:
        resultados = correr_contra_pendientes(args.pendientes)
        imprimir_resumen_pendientes(resultados)
    else:
        resultados = correr_comparacion()
        imprimir_resumen(resultados)

    if args.guardar:
        with open(args.guardar, "w", encoding="utf-8") as f:
            json.dump(resultados, f, ensure_ascii=False, indent=2)
        print(f"\nGuardado en {args.guardar}")


if __name__ == "__main__":
    main()
