"""
agregar_encuentro_protierra_2026.py
One-off: carga el 12° Encuentro Nacional de la Red Protierra Argentina
(3 al 7 de noviembre de 2026, Epuyén, Chubut) como pendiente_confirmacion.

Contexto (ver ROADMAP.md, 31/10/2026): revisando por qué el pipeline de
HikerAPI casi no encuentra eventos, se chequeó si las cuentas_protegidas
tenían sitio propio. redprotierra.com.ar (fuera del radar del pipeline,
que solo mira Instagram) confirma el evento en su nota del 28/10:
"Del 3 al 7 de Noviembre en la Patagonia". El linktree de
@redprotierraargentina confirma el lugar (Epuyén) con el título de su
formulario de inscripción ("12* encuentro nacional Epuyen2026"). No se
pudo leer la nota completa (redprotierra.com.ar bloquea el acceso
automatizado con un challenge anti-bot) ni confirmar lugar exacto,
costo o contacto — por eso entra como pendiente_confirmacion, igual que
cualquier evento con dato incompleto, nunca confirmado automáticamente.

Dry-run por default (solo imprime la fila que insertaría), --escribir
para aplicar. Gratis: no llama a HikerAPI ni a ningún proveedor de IA,
solo Sheets (para escribir) y Nominatim (para geocodificar, también
gratis) si se usa --escribir.
"""

import argparse
from datetime import datetime, timezone

from src.geocodificar import geocodificar_direccion
from src.sheets import append_events

EVENTO = {
    "nombre": "12° Encuentro Nacional de la Red Protierra Argentina",
    "tipo_evento": "Evento",
    "direccion": "Epuyén, Chubut",
    "provincia": "Chubut",
    "pais": "Argentina",
    "es_virtual": False,
    "fecha_inicio_iso": "2026-11-03",
    "fecha_fin_iso": "2026-11-07",
    "organizador": "Red Protierra Argentina",
    "descripcion": (
        "12° Encuentro Nacional de la Red Protierra Argentina, del 3 al "
        "7 de noviembre de 2026 en Epuyén, Chubut (Patagonia). Dato "
        "confirmado por la nota del 28/10/2026 en redprotierra.com.ar y "
        "por el formulario de inscripción enlazado desde el perfil de "
        "Instagram @redprotierraargentina. Lugar exacto, costo y "
        "contacto no pudieron confirmarse automáticamente — revisar "
        "antes de confirmar. Compartí en WhatsApp, por mail o "
        "etiquetando #hayminga si tenés más datos."
    ),
    "link_promocional": (
        "https://redprotierra.com.ar/2026/10/28/"
        "se-viene-el-12-encuentro-nacional-de-la-red-protierra-argentina/"
    ),
    "fuente": "revision_manual_pipeline",
    "confianza": "media",
    "activo": False,
    "estado": "pendiente_confirmacion",
    "fecha_descubrimiento": datetime.now(timezone.utc).isoformat(),
}


def construir_evento() -> dict:
    evento = dict(EVENTO)
    punto = geocodificar_direccion(evento["direccion"], evento["provincia"])
    if punto:
        evento["latitud"], evento["longitud"] = punto
    return evento


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--escribir", action="store_true", help="Aplica la inserción (default: dry-run)")
    args = parser.parse_args()

    evento = construir_evento()
    print("[agregar_encuentro_protierra_2026] Evento a insertar:")
    for clave, valor in evento.items():
        print(f"  {clave}: {valor}")

    if not args.escribir:
        print("\n[agregar_encuentro_protierra_2026] dry-run — correr con --escribir para aplicar.")
        return

    inserted = append_events([evento])
    print(f"\n[agregar_encuentro_protierra_2026] {inserted} fila(s) insertada(s)")


if __name__ == "__main__":
    main()
