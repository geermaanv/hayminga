"""
curar_fuentes.py
Baja automática de hashtags/cuentas de config.json que dejaron de
producir eventos — corre aparte del pipeline diario (semanal), lee la
hoja FuentesStats que hiker_pipeline.py actualiza en cada corrida.

Regla: 50 intentos seguidos sin ningún evento nuevo -> se saca de
config.json. No se automatizan altas (esas necesitan criterio de
calidad, no solo un número) — solo bajas, que son de bajo riesgo y
fácilmente reversibles (agregar la fuente de nuevo a mano).

También descubre candidatas nuevas a mano (no las agrega solo): usa
v2/user/suggested/profiles de HikerAPI — las cuentas que Instagram
sugiere como similares a cada una de las que ya seguimos. Da señal
mucho mejor que revisar la lista de seguidores de una cuenta (ahí la
mayoría es ruido — fans, cuentas personales sin relación al tema).
"""

import json
import os
from pathlib import Path

import requests

from src.sheets import get_service, cargar_fuentes_stats

UMBRAL_INTENTOS_SIN_HIT = 50
MIN_SUGERENCIAS_PARA_MOSTRAR = 2  # sugerida por al menos N cuentas nuestras

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


def _hiker_headers() -> dict:
    return {"x-access-key": os.environ["HIKERAPI_KEY"]}


def _pk_de(username: str) -> int | None:
    resp = requests.get(
        "https://api.hikerapi.com/v1/user/by/username",
        params={"username": username}, headers=_hiker_headers(), timeout=20,
    )
    if resp.status_code != 200:
        return None
    return resp.json().get("pk")


def _sugeridas_para(username: str) -> list[str]:
    pk = _pk_de(username)
    if not pk:
        return []
    resp = requests.get(
        "https://api.hikerapi.com/v2/user/suggested/profiles",
        params={"user_id": pk}, headers=_hiker_headers(), timeout=20,
    )
    if resp.status_code != 200:
        return []
    return [u["username"] for u in resp.json().get("users", []) if u.get("username")]


def descubrir_candidatos() -> list[tuple[str, int]]:
    """Consulta 'sugeridas' de Instagram para cada cuenta que ya seguimos
    y devuelve las que no están todavía en config.json, ordenadas por
    cuántas de nuestras cuentas la sugirieron (más veces = más señal).
    No las agrega solo — solo las reporta para revisión manual."""
    config = json.loads(CONFIG_PATH.read_text())
    cuentas_actuales = {c.lower() for c in config.get("cuentas_seguidas") or []}
    excluidas = {c.lower() for c in config.get("cuentas_excluidas") or []}

    conteo: dict[str, int] = {}
    for username in sorted(cuentas_actuales):
        try:
            sugeridas = _sugeridas_para(username)
        except Exception as e:
            print(f"[curar_fuentes] @{username}: error consultando sugeridas — {e}")
            continue
        for s in sugeridas:
            s = s.lower()
            if s in cuentas_actuales or s in excluidas:
                continue
            conteo[s] = conteo.get(s, 0) + 1

    candidatos = sorted(
        ((u, n) for u, n in conteo.items() if n >= MIN_SUGERENCIAS_PARA_MOSTRAR),
        key=lambda x: -x[1],
    )
    if candidatos:
        print(f"[curar_fuentes] {len(candidatos)} cuenta(s) candidata(s) nueva(s) (revisar a mano):")
        for u, n in candidatos:
            print(f"  @{u} (sugerida por {n} cuenta(s) nuestra(s))")
    else:
        print("[curar_fuentes] Sin candidatas nuevas esta vez")
    return candidatos


if __name__ == "__main__":
    curar()
    descubrir_candidatos()
