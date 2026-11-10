"""
armar_perfiles_organizadores.py
Piloto: en vez de pedirle al organizador que llene el formulario del
Directorio desde cero, armamos un borrador de su perfil con datos que
ya están disponibles (evento que publicó, bio pública de Instagram) y
se lo mandamos para que diga "sí", "con cambios" o "no" — baja la
fricción a confirmar en vez de completar (ver ROADMAP.md, idea del
mantenedor 10/2026).

Dry-run por default (solo muestra, no gasta nada más que las llamadas a
HikerAPI del armado): primero filtra gratis (CuentasIds!EmailPublico,
ya cacheado, sin email no hay forma de contactar por este canal) y
solo para ese subconjunto —acotado por --limite, porque esto SÍ
cuesta: una llamada a HikerAPI por cuenta para traer
biography/full_name— arma el borrador de perfil. --escribir le pide a
Code.gs (accion directorio_crear_borrador) que cree la fila
(Activo=false, Estado=borrador) y mande el mail de verdad — Python
nunca escribe el Directorio directamente (ver CLAUDE.md).

Universo de organizadores (ampliado 11/2026, a pedido del mantenedor):
cuentas con un evento `confirmado` O `pendiente_confirmacion` —
`descartado` no cuenta, porque ya se determinó activamente que no es
un evento real o es un duplicado, así que invitar en base a eso sería
peor que no invitar. Separado a propósito de
`mensajes_organizadores.analizar()` (que sigue siendo solo
`confirmado`): ese alimenta además la cola vieja de DM
(`dm_organizador`), cuyo texto afirma "ya está publicado" — ahí sí
tiene que ser cierto. Acá el mail distingue los dos casos (ver
`evento_confirmado` más abajo y `avisarBorradorDirectorio_` en
Code.gs).

Pensado para colgarse de un cron (ver `hiker_pipeline.py`, 1x/día tras el import) con un tope
chico por corrida (`_MAX_POR_CORRIDA_AUTOMATICA`) — mismo criterio que
`_MAX_VALIDACIONES_ORGANIZADOR_POR_CORRIDA` en `hiker_pipeline.py`: un
goteo, no una tanda grande, aunque el pool elegible en un momento dado
sea mucho más grande (ver ROADMAP.md, incidentes de
`curar_fuentes.py` por no tener un tope duro).
"""
import argparse
import json
import os

import requests

from src.sheets import COLUMNS, CUENTAS_IDS_SHEET_NAME, SHEET_NAME, SPREADSHEET_ID, cargar_emails_directorio, get_service

LIMITE_DEFAULT = 10  # tope de llamadas pagas a HikerAPI por corrida manual/de prueba
_MAX_POR_CORRIDA_AUTOMATICA = 5  # tope por corrida cuando cuelga de un cron, sin revisión humana

_ESTADOS_ELEGIBLES = {"confirmado", "pendiente_confirmacion"}


def _organizadores_candidatos(service) -> list[dict]:
    """Agrupado por cuenta de Instagram (no por evento ni por el texto
    libre de Organizador). Para cada cuenta, el evento a citar se elige
    así: uno activo si hay (invita mejor algo que todavía va a pasar);
    si no, uno confirmado (afirmación cierta); si no, el primero
    pendiente_confirmacion encontrado. `evento_confirmado` le dice al
    mail qué tan afirmativo puede ser el texto."""
    values = (
        service.spreadsheets().values()
        .get(spreadsheetId=SPREADSHEET_ID, range=f"{SHEET_NAME}!A2:Y")
        .execute()
    ).get("values", [])

    por_cuenta: dict[str, dict] = {}
    for row in values:
        row = (row + [""] * len(COLUMNS))[:len(COLUMNS)]
        estado = (row[16] or "").strip().lower()
        if estado not in _ESTADOS_ELEGIBLES:
            continue
        usuario = (row[24] or "").strip().lstrip("@").lower()
        if not usuario:
            continue
        entrada = por_cuenta.setdefault(usuario, {"usuario": usuario, "eventos": []})
        entrada["eventos"].append({
            "nombre": (row[1] or "").strip(),
            "provincia": (row[7] or "").strip(),
            "activo": (row[0] or "").strip().lower() == "true",
            "confirmado": estado == "confirmado",
        })

    salida = []
    for datos in por_cuenta.values():
        eventos = datos["eventos"]
        activos = [e for e in eventos if e["activo"]]
        confirmados = [e for e in eventos if e["confirmado"]]
        citado = activos[0] if activos else (confirmados[0] if confirmados else eventos[0])
        salida.append({
            "usuario": datos["usuario"],
            "eventos": len(eventos),
            "evento_citado": citado["nombre"],
            "provincia": citado["provincia"],
            "evento_confirmado": citado["confirmado"],
        })
    return sorted(salida, key=lambda d: (-d["eventos"], d["usuario"]))


def _hiker_headers() -> dict:
    return {"x-access-key": os.environ["HIKERAPI_KEY"]}


def _perfil_instagram(username: str) -> dict:
    """Una llamada paga. full_name + biography para armar el borrador —
    mismo endpoint que ya se usa (gratis) para país/email en
    hiker_pipeline.py, pero esos campos no se cachean hoy en CuentasIds,
    así que para el piloto se vuelve a pedir."""
    resp = requests.get(
        "https://api.hikerapi.com/v1/user/by/username",
        params={"username": username}, headers=_hiker_headers(), timeout=20,
    )
    if resp.status_code != 200:
        return {}
    data = resp.json()
    return {
        "full_name": (data.get("full_name") or "").strip(),
        "biography": (data.get("biography") or "").strip().replace("\n", " "),
    }


def _emails_cacheados(service) -> dict[str, str]:
    values = (
        service.spreadsheets().values()
        .get(spreadsheetId=SPREADSHEET_ID, range=f"{CUENTAS_IDS_SHEET_NAME}!A2:D")
        .execute()
    ).get("values", [])
    salida = {}
    for row in values:
        row = (row + [""] * 4)[:4]
        username = (row[0] or "").strip().lower()
        email = (row[3] or "").strip()
        if username and email:
            salida[username] = email
    return salida


def candidatos_con_email(service=None) -> list[dict]:
    """Filtro gratis (sin llamar a HikerAPI): organizadores con email ya
    cacheado, que no estén ya en el Directorio. Devuelve TODOS los que
    cumplen — el tope de costo se aplica después, al armar el perfil."""
    service = service or get_service()
    organizadores = _organizadores_candidatos(service)
    emails_cache = _emails_cacheados(service)
    ya_en_directorio = cargar_emails_directorio(service)

    salida = []
    for org in organizadores:
        email = emails_cache.get(org["usuario"])
        if not email or email.lower() in ya_en_directorio:
            continue
        salida.append({**org, "email": email})
    return salida


def armar_borradores(limite: int = LIMITE_DEFAULT) -> list[dict]:
    service = get_service()
    candidatos = candidatos_con_email(service)

    print(f"[armar_perfiles_organizadores] {len(candidatos)} organizador(es) con email cacheado, "
          f"sin estar ya en el Directorio")
    if not candidatos:
        return []

    a_procesar = candidatos[:limite]
    if len(candidatos) > limite:
        print(f"[armar_perfiles_organizadores] procesando solo los primeros {limite} "
              f"(--limite) — cada uno es una llamada paga a HikerAPI")

    borradores = []
    for c in a_procesar:
        perfil_ig = _perfil_instagram(c["usuario"])
        borradores.append({
            "usuario": c["usuario"],
            "email": c["email"],
            "nombre": perfil_ig.get("full_name") or c["usuario"],
            "provincia": c["provincia"],
            "evento_citado": c["evento_citado"],
            "evento_confirmado": c["evento_confirmado"],
            "bio": perfil_ig.get("biography"),
        })
    return borradores


def crear_borrador(b: dict) -> str | None:
    """Le pide a Code.gs que cree la fila (Activo=false, Estado=borrador) y
    mande el mail con los tres links de un clic (confirmar/editar/rechazar)
    — texto revisado con el mantenedor, ver ROADMAP.md 11/2026. Python nunca
    escribe el Directorio directamente (CLAUDE.md)."""
    apps_script_url = os.environ["APPS_SCRIPT_URL"]
    secreto = os.environ["APPS_SCRIPT_SHARED_SECRET"]
    resp = requests.post(
        apps_script_url,
        headers={"Content-Type": "text/plain"},
        data=json.dumps({
            "accion": "directorio_crear_borrador",
            "secreto": secreto,
            "nombre": b["nombre"],
            "provincia": b["provincia"],
            "descripcion": b["bio"],
            "email": b["email"],
            "evento": b["evento_citado"],
            "evento_confirmado": b["evento_confirmado"],
        }),
        timeout=30,
    )
    data = resp.json()
    if not data.get("success"):
        print(f"[armar_perfiles_organizadores] Code.gs respondió error para {b['email']} — {data.get('error')}")
        return None
    return data.get("id")


def reportar(limite: int = LIMITE_DEFAULT, escribir: bool = False):
    borradores = armar_borradores(limite)
    if not borradores:
        print("[armar_perfiles_organizadores] Nada para mostrar")
        return

    for i, b in enumerate(borradores, 1):
        print("=" * 68)
        print(f"{i}. @{b['usuario']}  →  {b['email']}")
        print("=" * 68)
        print(f"Nombre (borrador):     {b['nombre']}")
        print(f"Provincia (borrador):  {b['provincia'] or '(sin dato)'}")
        estado_evento = "confirmado" if b["evento_confirmado"] else "pendiente de revisión"
        print(f"Evento citado ({estado_evento}): {b['evento_citado']}")
        print(f"Descripcion (borrador, de la bio pública de Instagram):")
        print(f"  {b['bio'] or '(sin bio pública o vacía)'}")
        if escribir:
            id_creado = crear_borrador(b)
            print(f"  → borrador creado, mail mandado (Id={id_creado})" if id_creado
                  else "  → NO se pudo crear/mandar, ver error arriba")
        print()

    if not escribir:
        print("[armar_perfiles_organizadores] dry-run — correr con --escribir para crear los borradores y mandar el mail.")


def correr_automatico(limite: int = _MAX_POR_CORRIDA_AUTOMATICA) -> int:
    """Para colgar de un cron sin revisión humana (ver hiker_pipeline.py) —
    siempre --escribir, siempre acotado al tope chico, nunca al --limite
    manual que se usa para probar. Devuelve cuántos borradores se crearon
    de verdad."""
    borradores = armar_borradores(limite)
    creados = 0
    for b in borradores:
        if crear_borrador(b):
            creados += 1
    print(f"[armar_perfiles_organizadores] {creados}/{len(borradores)} borrador(es) creado(s) automáticamente")
    return creados


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limite", type=int, default=LIMITE_DEFAULT,
                         help=f"Máximo de perfiles a armar (cada uno llama a HikerAPI, paga). Default {LIMITE_DEFAULT}.")
    parser.add_argument("--escribir", action="store_true",
                         help="Crea el borrador en el Directorio y manda el mail de verdad (default: dry-run, solo muestra).")
    args = parser.parse_args()
    reportar(limite=args.limite, escribir=args.escribir)


if __name__ == "__main__":
    main()
