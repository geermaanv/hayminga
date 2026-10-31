"""
revisar_perfiles_protegidos.py
One-off: para las cuentas_protegidas (orgs/redes "institucionales" del
config.json — ver CLAUDE.md), pregunta el perfil completo a HikerAPI para
ver si alguna linkea un sitio propio con agenda/calendario de eventos de
bioconstrucción.

Contexto (ver ROADMAP.md, 31/10/2026): la búsqueda web genérica no
encontró sitio ni agenda pública para ninguna de estas 6 cuentas, pero
Instagram bloquea el scraping directo del bio (HTTP 429 vía WebFetch).
HikerAPI sí puede leerlo con una sola llamada de perfil por cuenta — este
chequeo puntual confirma (o descarta) la hipótesis con el dato real antes
de construir cualquier integración sobre ella.

Costo: 1 llamada a HikerAPI por cuenta_protegida (perfil, no contenido).
Solo lee — no escribe nada en el Sheet ni en config.json.
"""

import json
from pathlib import Path

from src.hiker_pipeline import _hiker_get

CONFIG_PATH = Path("config.json")


def _perfil(username: str) -> dict:
    resp = _hiker_get(
        "https://api.hikerapi.com/v1/user/by/username",
        params={"username": username},
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()


def revisar() -> list[dict]:
    config = json.loads(CONFIG_PATH.read_text())
    cuentas = config.get("cuentas_protegidas") or []
    if not cuentas:
        print("[revisar_perfiles_protegidos] No hay cuentas_protegidas en config.json")
        return []

    resultados = []
    for username in cuentas:
        try:
            data = _perfil(username)
        except Exception as exc:
            print(f"[revisar_perfiles_protegidos] @{username}: error — {exc}")
            continue

        external_url = (data.get("external_url") or "").strip()
        biography = (data.get("biography") or "").strip().replace("\n", " ")
        email = (data.get("public_email") or "").strip()
        categoria = (data.get("category_name") or data.get("business_category_name") or "").strip()
        followers = data.get("follower_count")

        resultados.append({
            "username": username,
            "external_url": external_url,
            "biography": biography,
            "email": email,
            "categoria": categoria,
            "followers": followers,
        })
        print(
            f"[revisar_perfiles_protegidos] @{username}: "
            f"url={external_url or '(sin link)'} | "
            f"email={email or '(sin email público)'} | "
            f"categoria={categoria or '(sin categoría)'} | "
            f"followers={followers}"
        )
        if biography:
            print(f"    bio: {biography}")

    con_url = [r for r in resultados if r["external_url"]]
    print(f"\n[revisar_perfiles_protegidos] {len(con_url)}/{len(resultados)} cuenta(s) con link externo en el bio")
    return resultados


def main():
    revisar()


if __name__ == "__main__":
    main()
