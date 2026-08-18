"""
candidatos_tecnicas.py
Reporte de solo lectura: qué técnicas constructivas aparecen en los
eventos ya CONFIRMADOS y con qué frecuencia. Sirve para armar y mantener
la lista de sugerencias del campo "técnica" del Directorio, sin
inventarla a ojo — el vocabulario sale de lo que la comunidad
efectivamente enseña y practica en Argentina, no de una lista teórica.

Es el mismo espíritu que `candidatos_hashtags.py` (leer eventos
confirmados, contar, reportar sin auto-agregar) pero con una diferencia
importante en el criterio:

    `candidatos_hashtags` exige 2+ eventos porque un hashtag que aparece
    una sola vez casi siempre es ruido de un post puntual (nombre propio,
    ubicación). Acá NO hay mínimo: una técnica que aparece una sola vez
    —superadobe, earthship, yurta, bambú— no es ruido, es una técnica
    real con poca oferta ese semestre. Filtrarlas por frecuencia sería
    borrar del vocabulario justo lo más específico.

Segunda salida, tan útil como la primera: los eventos confirmados donde
NO se detectó ninguna técnica conocida. Leerlos a mano es el mecanismo de
descubrimiento de vocabulario nuevo (así apareció "geometrías orgánicas
en techos", que no estaba en ninguna lista previa).

Usa exclusivamente la API de Sheets (gratis) — no llama a HikerAPI ni a
ningún proveedor de IA, así que correr esto no gasta nada.
"""
import re
import unicodedata

from src.sheets import COLUMNS, SHEET_NAME, SPREADSHEET_ID, get_service

# Técnica canónica -> variantes con las que aparece escrita en los
# posteos. El agrupamiento de sinónimos es deliberadamente manual: "techo
# verde", "cubierta viva" y "cubierta verde" son la misma cosa y ningún
# algoritmo lo va a deducir solo. Sumar variantes acá a medida que
# aparezcan en la lista de "sin clasificar" de abajo.
TECNICAS = {
    "quincha":                  ["quincha"],
    "adobe":                    [r"\badobes?\b"],
    "superadobe":               ["superadobe"],
    "tierra cruda":             ["tierra cruda", "construccion con tierra", "construccion en tierra"],
    "revoques":                 ["revoque"],
    "pinturas naturales":       ["pintura"],
    "estucos":                  ["estuco"],
    "pisos":                    [r"\bpisos?\b"],
    "cal":                      [r"\bcal\b"],
    "techo verde":              [r"techos? (vivos?|verdes?)", r"cubiertas? (vivas?|verdes?)", "techos y cubiertas"],
    "estructuras de madera":    ["estructuras? de madera", "wood frame"],
    "tiny house":               ["tiny house"],
    "yurta":                    ["yurta"],
    "bambu":                    ["bambu"],
    "earthship":                ["earthship"],
    "cimentacion":              ["cimentacion"],
    "albanileria":              ["albanileria"],
    "estufas y hornos":         ["estufa", "rocket", "inercia termica", r"\bhornos?\b"],
    "diseno bioclimatico":      ["bioclimatic"],
    "tratamiento de aguas":     ["tratamiento de agua", "tratamiento de las agua", "sistemas biologicos"],
    "captacion de lluvia":      ["agua de lluvia", "reutilizar la lluvia", "cosecha de agua"],
    "reconocimiento de suelos": ["reconocimiento de suelo"],
    "permacultura":             ["permacultura", "permacultural"],
    "agroecologia y huerta":    ["agroecolog", "huerta", "bosque comestible"],
    "diseno de espacios":       ["diseno de espacios"],
    "geobiologia":              ["geobiolog", "feng shui", "radiestesia"],
    "hongos":                   ["girgola", r"\bhongos?\b", "micelio"],
}

# Términos que matchean muchísimo pero no son una técnica: son el nombre
# del rubro entero o de un enfoque. Como categoría no sirven para nada
# (todo el que está en hayminga hace bioconstrucción), así que ni se
# cuentan. Caso testigo: "bioarquitectura" daba 5 eventos y no le decía
# nada a nadie.
_NO_SON_TECNICAS = {
    "bioconstruccion", "bioarquitectura", "arquitectura biologica",
    "sustentable", "sustentabilidad", "construccion natural",
}


def _normalizar(texto: str | None) -> str:
    """Minúsculas, sin acentos y sin las tipografías 'fancy' de Instagram
    (𝗧𝗔𝗟𝗟𝗘𝗥 y similares) — NFKD las devuelve a ASCII, sin eso los títulos
    más gritados del feed no matchean nunca."""
    # Ojo el orden: NFKD primero y lower() después. Los caracteres
    # matemáticos de Instagram no tienen mapeo de mayúscula/minúscula, así
    # que lower() no los toca — hay que pasarlos a ASCII antes.
    texto = unicodedata.normalize("NFKD", texto or "")
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", texto.lower())


def analizar(service=None) -> tuple[list[tuple[str, int]], list[str]]:
    """Devuelve (candidatos, sin_clasificar):

    - candidatos: [(tecnica, cantidad_de_eventos_confirmados), ...] de más
      a menos frecuente. Sin mínimo — ver el docstring del módulo.
    - sin_clasificar: títulos de eventos confirmados donde no se detectó
      ninguna técnica conocida, para leer a mano y descubrir vocabulario.
    """
    service = service or get_service()
    values = (
        service.spreadsheets().values()
        .get(spreadsheetId=SPREADSHEET_ID, range=f"{SHEET_NAME}!A2:X")
        .execute()
    ).get("values", [])

    eventos = []
    for row in values:
        row = (row + [""] * len(COLUMNS))[:len(COLUMNS)]
        # Solo confirmados: es la única señal de que un humano ya validó
        # que el evento es real, mismo criterio que candidatos_hashtags.
        if (row[16] or "").strip().lower() != "confirmado":
            continue
        eventos.append((
            (row[1] or "").strip(),
            _normalizar(f"{row[1]} {row[8]} {row[11]}"),
        ))

    conteo: dict[str, int] = {}
    sin_clasificar: list[str] = []

    for nombre, texto in eventos:
        encontradas = {
            tecnica for tecnica, variantes in TECNICAS.items()
            if any(re.search(v, texto) for v in variantes)
        }
        for tecnica in encontradas:
            conteo[tecnica] = conteo.get(tecnica, 0) + 1
        if not encontradas:
            sin_clasificar.append(nombre)

    candidatos = sorted(conteo.items(), key=lambda par: (-par[1], par[0]))
    return candidatos, sin_clasificar


def reportar():
    candidatos, sin_clasificar = analizar()

    if not candidatos:
        print("[candidatos_tecnicas] Sin eventos confirmados para analizar")
        return

    total = sum(1 for _ in candidatos)
    print(f"[candidatos_tecnicas] {total} técnica(s) detectada(s) en eventos confirmados:")
    for tecnica, n in candidatos:
        print(f"  {n:3} evento(s)  {tecnica}")

    if sin_clasificar:
        print(f"\n[candidatos_tecnicas] {len(sin_clasificar)} evento(s) sin técnica detectada — "
              "leerlos para descubrir vocabulario nuevo y sumarlo a TECNICAS:")
        for nombre in sin_clasificar:
            print(f"  - {nombre}")


if __name__ == "__main__":
    reportar()
