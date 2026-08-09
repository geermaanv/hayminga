"""
curar_fuentes.py
Baja automática de hashtags/cuentas de config.json que dejaron de
producir eventos — corre aparte del pipeline diario (semanal), lee la
hoja FuentesStats que hiker_pipeline.py actualiza en cada corrida.

Regla: 50 intentos seguidos sin ningún evento nuevo -> se saca de
config.json. No se automatizan altas (esas necesitan criterio de
calidad, no solo un número) — solo bajas, que son de bajo riesgo y
fácilmente reversibles (agregar la fuente de nuevo a mano).

También descubre candidatas nuevas y las agrega directo a config.json:
usa v2/user/suggested/profiles de HikerAPI — las cuentas que Instagram
sugiere como similares a cada una de las que ya seguimos. Da señal
mucho mejor que revisar la lista de seguidores de una cuenta (ahí la
mayoría es ruido — fans, cuentas personales sin relación al tema). El
riesgo de una alta mala es bajo: si no produce nada, la baja automática
la saca sola a los 50 intentos.

Para no repetir la misma consulta de "sugeridas" en cada corrida, se
registra en la hoja CuentasConsultadas cuándo se consultó cada cuenta
— solo se vuelve a consultar después de _DIAS_ANTES_DE_RECONSULTAR.
"""

import json
import os
from datetime import date
from pathlib import Path

import requests

from src.sheets import (
    get_service, cargar_fuentes_stats,
    cargar_cuentas_consultadas, marcar_cuentas_consultadas,
    cargar_cuentas_ids, guardar_cuentas_ids,
)

UMBRAL_INTENTOS_SIN_HIT = 50
_DIAS_ANTES_DE_RECONSULTAR = 30
MIN_SUGERENCIAS_PARA_AGREGAR = 2  # sugerida por al menos N cuentas nuestras

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


def _sugeridas_para(username: str, pk: int | None = None) -> list[str]:
    if pk is None:
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


def descubrir_candidatos() -> list[str]:
    """Consulta 'sugeridas' de Instagram para cada cuenta que ya seguimos
    (salteando las consultadas hace menos de _DIAS_ANTES_DE_RECONSULTAR)
    y agrega directo a config.json las que no estén ya ahí."""
    service = get_service()
    config = json.loads(CONFIG_PATH.read_text())
    cuentas_actuales = {c.lower() for c in config.get("cuentas_seguidas") or []}
    excluidas = {c.lower() for c in config.get("cuentas_excluidas") or []}

    consultadas = cargar_cuentas_consultadas(service)
    hoy = date.today()
    a_consultar = []
    for username in sorted(cuentas_actuales):
        fecha_str = consultadas.get(username)
        if fecha_str:
            dias = (hoy - date.fromisoformat(fecha_str)).days
            if dias < _DIAS_ANTES_DE_RECONSULTAR:
                continue
        a_consultar.append(username)

    if not a_consultar:
        print("[curar_fuentes] Todas las cuentas se consultaron hace poco, nada para revisar")
        return []
    print(f"[curar_fuentes] Consultando sugeridas para {len(a_consultar)} cuenta(s)")

    ids_cacheados = cargar_cuentas_ids(service)
    ids_nuevos = {}
    conteo: dict[str, int] = {}
    consultadas_ahora = []
    for username in a_consultar:
        try:
            pk = ids_cacheados.get(username)
            if pk is None:
                pk = _pk_de(username)
                if pk:
                    ids_nuevos[username] = pk
            sugeridas = _sugeridas_para(username, pk=pk)
            consultadas_ahora.append(username)
        except Exception as e:
            print(f"[curar_fuentes] @{username}: error consultando sugeridas — {e}")
            continue
        for s in sugeridas:
            s = s.lower()
            if s in cuentas_actuales or s in excluidas:
                continue
            conteo[s] = conteo.get(s, 0) + 1

    # "sugeridas" de Instagram no es puramente temático — sin este piso
    # mínimo, una corrida real trajo más de 900 cuentas sin relación
    # (surf en Francia, acroyoga en los Alpes, etc.). Que la sugiera más
    # de una cuenta nuestra es la señal de que sí tiene que ver con el
    # tema, no solo con el algoritmo genérico de "cuentas parecidas".
    nuevas = {u for u, n in conteo.items() if n >= MIN_SUGERENCIAS_PARA_AGREGAR}

    marcar_cuentas_consultadas(service, consultadas_ahora)
    guardar_cuentas_ids(service, ids_nuevos)

    if not nuevas:
        print("[curar_fuentes] Sin candidatas nuevas esta vez")
        return []

    config["cuentas_seguidas"] = sorted(cuentas_actuales | nuevas)
    CONFIG_PATH.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n")
    for u in sorted(nuevas):
        print(f"[curar_fuentes] Cuenta nueva agregada: @{u}")
    return sorted(nuevas)


if __name__ == "__main__":
    curar()
    descubrir_candidatos()
