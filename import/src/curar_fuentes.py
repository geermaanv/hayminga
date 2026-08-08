"""
curar_fuentes.py
Baja automática de hashtags/cuentas de config.json que dejaron de
producir eventos — corre aparte del pipeline diario (semanal), lee la
hoja FuentesStats que hiker_pipeline.py actualiza en cada corrida.

Regla: 50 intentos seguidos sin ningún evento nuevo -> se saca de
config.json. No se automatizan altas (esas necesitan criterio de
calidad, no solo un número) — solo bajas, que son de bajo riesgo y
fácilmente reversibles (agregar la fuente de nuevo a mano).
"""

import json
from pathlib import Path

from src.sheets import get_service, cargar_fuentes_stats

UMBRAL_INTENTOS_SIN_HIT = 50

CONFIG_PATH = Path("config.json")


def curar() -> list[tuple[str, str]]:
    service = get_service()
    stats = cargar_fuentes_stats(service)

    a_dar_de_baja = [
        (tipo, nombre) for (tipo, nombre), info in stats.items()
        if info["intentos_sin_hit"] >= UMBRAL_INTENTOS_SIN_HIT
    ]
    if not a_dar_de_baja:
        print("[curar_fuentes] Nada para dar de baja")
        return []

    config = json.loads(CONFIG_PATH.read_text())
    hashtags = set(config.get("hashtags") or [])
    cuentas = set(config.get("cuentas_seguidas") or [])

    bajas = []
    for tipo, nombre in a_dar_de_baja:
        if tipo == "hashtag" and nombre in hashtags:
            hashtags.discard(nombre)
            bajas.append((tipo, nombre))
        elif tipo == "cuenta" and nombre in cuentas:
            cuentas.discard(nombre)
            bajas.append((tipo, nombre))

    if not bajas:
        print("[curar_fuentes] Las fuentes con 50+ intentos sin hit ya no están en config.json")
        return []

    config["hashtags"] = sorted(hashtags)
    config["cuentas_seguidas"] = sorted(cuentas)
    CONFIG_PATH.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n")

    for tipo, nombre in bajas:
        print(f"[curar_fuentes] Dada de baja ({tipo}): {nombre} — {UMBRAL_INTENTOS_SIN_HIT}+ intentos sin producir eventos")

    return bajas


if __name__ == "__main__":
    curar()
