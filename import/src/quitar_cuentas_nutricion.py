"""
quitar_cuentas_nutricion.py
One-off: saca de cuentas_seguidas las 170 cuentas de nutrición/cocina/
recetas/salud que terminaron ahí sin relación con bioconstrucción —
hallazgo del 31/10/2026 (ver ROADMAP.md): la corrida real mostró que el
canal de cuentas_seguidas (6.051 posts, 678 cuentas) no mandó NI UN
SOLO post a la IA, y revisando config.json se vio que 170 de 680
cuentas (25%) son de este tipo. Entraron vía descubrir_candidatos()
("sugeridas" de Instagram, que agrupa por audiencia parecida, no por
tema — el mismo mecanismo que ya había dejado pasar cuentas de
surf/acroyoga en un incidente anterior).

Verificado antes de armar esta lista: ninguna de estas 170 cuentas
aparece como Username en ningún evento (confirmado, pendiente o
descartado) de toda la historia del Sheet — sacarlas no pierde nada.

Ver también curar_fuentes.py (_parece_relevante): a partir de ahora
descubrir_candidatos() exige que la bio de la cuenta tenga señal
temática antes de agregarla, para que esto no se repita.

Dry-run por default (solo imprime el diff), --escribir para aplicar.
Gratis — no llama a HikerAPI ni a ningún proveedor de IA, solo lee y
escribe config.json local.
"""

import argparse
import json
from pathlib import Path

CONFIG_PATH = Path("config.json")

CUENTAS_A_QUITAR = [
    "_cnutricion", "afp.nutricion", "agusaldanutri", "alecasalecocina",
    "alejococinaok", "analuz.nutricion", "anita.sintacc.cocina", "anto.nutri",
    "antojaterecetas", "apnutricion_", "ayegonzalez.nutricion",
    "az.nutricionysalud", "bfit.nutricion", "burdmannutricion",
    "camilonarecetas", "camucocina", "carozococina", "casirecetas_",
    "cecirecetas", "cesococina", "charo.recetas", "chekacocina",
    "clari.nutri", "cocina.activa.ar", "cocinaconvalentino",
    "cocinandoando_", "cocinaninjaok", "cocinaquesana", "cocinarencasa",
    "cocinasaludable_", "comidasimple_", "daireauxnutricion",
    "eg.nutricion", "elgatococina", "elgordococina", "emprecocina.arg",
    "evecocinaybienestar", "evelyn.recetas", "fispsalud", "fredococina",
    "galucocina", "georgimarino.nutri", "hagamosnutricion",
    "hernan.nutricion", "integralnutricion", "itatirecetas",
    "jacicubas.nutricion", "jhony.cocina", "joacorecetas", "jw.nutricion",
    "kulinaria.recetas", "lacocinadesyl", "lacocinarebelde_oficial",
    "larusacocina", "lasrecetasdesimon", "legalmentesaludable",
    "leticia.nutricion", "levartenutricion", "lic.veggie",
    "licnutricion.mp", "lovenutricion", "lutizzinutricion", "maiacocina",
    "mamamelliscocina", "mamasilvicocina", "mar_recetas_", "matycocinaok",
    "maxicocinaok", "melanie.cocina", "melina.nutricion", "millie.recetas",
    "mlc_nutricion", "mvc.nutricion", "nardalepescasaycocina",
    "nutri.antonelaiorio", "nutri.emicieli", "nutri.flor",
    "nutri.laufernandez", "nutri.mic", "nutri.nicoleramos",
    "nutri.recipes", "nutri.rosalyn", "nutri.sm", "nutri.tiipss",
    "nutri.vanesacraichic", "nutri_agusuzcudun", "nutrialimentar",
    "nutriarte.argentina", "nutricion.ag", "nutricion.candelablanco",
    "nutricion.carlacapeche", "nutricion.cd", "nutricion.crodriguez",
    "nutricion.en.linea", "nutricion.guiada", "nutricion.lamborizio",
    "nutricion.mc", "nutricion.mila", "nutricion.objetivosano",
    "nutricion.pizzicatti", "nutricion.rosariovicente",
    "nutricion.salud.arg", "nutricion.silce", "nutricion.valearevalo",
    "nutricion.vh", "nutricion_cm", "nutricionamiunes", "nutricionbc_",
    "nutricionconden", "nutricionconmeli_", "nutriciondeatres",
    "nutricionista.lucia.patane", "nutricionista.marianazanotta",
    "nutricionista.sofiashan", "nutricionistacintiamartin",
    "nutricionnataliaantar", "nutricionsgf", "nutricionsofiquesada",
    "nutricionxsalud", "nutricionyalgomas", "nutricionyarmonia",
    "nutricionyat", "nutriconcept.arg", "nutriconsciente.uy",
    "nutricreando_habitos", "nutriendo_equilibrio", "nutriendohabitosok",
    "nutrilanutricion", "nutrileilalev", "nutriliano", "nutrir.pr",
    "nutrisalud.filippelli", "nutrisaludbsas", "nutrisoul.ar",
    "nutrite.uy", "nutrivida_saludable", "paulinacocina", "pulicocina",
    "quimey_nutricion", "recetasalmaximomv", "recetasbahia",
    "recetascalinda", "recetasdepilu", "recetasmateras",
    "recetassingluten_", "renutrirme.condiabetes", "revolucionenlacocina",
    "ricoysanococina", "romina.nutricion", "sabricocina_ok",
    "sabrina.recetas", "saludablemente.veggie", "saludablepractico",
    "saludentrecomidas", "sarale_recetas", "ser.veggie", "silbus.recetas",
    "silvana_cocinando", "so.cocina", "sofientucocina", "toienlacocina",
    "vakkaru.nutricion", "valesaglietti.nutricion", "vanerecetas",
    "vaninutricion", "veggie.attack", "victoria_veggie",
    "vida.sana.recetas", "voyacocinar", "yaminutri",
]


def quitar(escribir: bool = False) -> list[str]:
    config = json.loads(CONFIG_PATH.read_text())
    cuentas = config.get("cuentas_seguidas") or []
    a_quitar = set(CUENTAS_A_QUITAR)

    encontradas = [c for c in cuentas if c in a_quitar]
    no_encontradas = a_quitar - set(encontradas)

    print(f"[quitar_cuentas_nutricion] {len(encontradas)}/{len(CUENTAS_A_QUITAR)} cuenta(s) encontrada(s) en config.json")
    if no_encontradas:
        print(f"[quitar_cuentas_nutricion] {len(no_encontradas)} ya no estaban: {sorted(no_encontradas)}")

    if not escribir:
        print("[quitar_cuentas_nutricion] dry-run — correr con --escribir para aplicar.")
        return encontradas

    config["cuentas_seguidas"] = sorted(c for c in cuentas if c not in a_quitar)
    CONFIG_PATH.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n")
    print(f"[quitar_cuentas_nutricion] {len(encontradas)} cuenta(s) quitada(s), quedan {len(config['cuentas_seguidas'])}")
    return encontradas


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--escribir", action="store_true", help="Aplica la quita (default: dry-run)")
    args = parser.parse_args()
    quitar(escribir=args.escribir)


if __name__ == "__main__":
    main()
