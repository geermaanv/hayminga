"""
pedir_referido_cuentas_instagram.py
Campaña puntual: a las cuentas de Instagram que seguimos
(cuentas_seguidas + cuentas_protegidas) y que ya tienen email público
cacheado (CuentasIds!EmailPublico, gratis — ya se resolvió en corridas
anteriores), les pide sumarse al Directorio o compartirlo con otros
profesionales — "crecer en profesionales" (31/10/2026, ver
ROADMAP.md). Mismo texto simple aprobado por el mantenedor.

A diferencia de pedir_referido_directorio.py (donde Code.gs lee y
filtra el Directorio, que es suyo), acá Python ya tiene todo lo que
necesita: CuentasIds es una hoja de Python (se lee y escribe directo,
ver CLAUDE.md). Esto calcula la lista final de emails (con email
cacheado, no ya en el Directorio, sin pedido reciente) y le pide a
Code.gs solo que la mande (acción enviar_mail_lista, relay puro, sin
leer ni filtrar nada del lado de Apps Script). Columna nueva en
CuentasIds (E, UltimoPedidoReferido) para no repetirle el pedido a la
misma cuenta antes de MESES_COOLDOWN_REFERIDO meses — un solo GET +
como mucho un solo batchUpdate para toda la columna, no uno por fila
(lección del incidente de cuota de Sheets del mismo día, ver
ROADMAP.md).

Dry-run por default: vista previa de a quién le mandaría, sin escribir
nada. --escribir manda de verdad y actualiza el registro. Gratis — no
llama a HikerAPI ni a ningún proveedor de IA, solo Sheets.
"""

import argparse
import json
import os
from datetime import date, timedelta
from pathlib import Path

import requests

from src.sheets import CUENTAS_IDS_SHEET_NAME, SPREADSHEET_ID, cargar_emails_directorio, get_service

CONFIG_PATH = Path("config.json")
MESES_COOLDOWN_REFERIDO = 2  # mismo criterio que pedir_referido_directorio.py

ASUNTO = "Te invitamos a sumarte a hayminga.org"
TEXTO = (
    "Hola!\n\n"
    "Somos hayminga.org, un espacio para gente que trabaja con tierra, "
    "quincha, adobe y técnicas parecidas en Argentina.\n\n"
    "Te invitamos a sumarte, es gratis y te toma menos de 2 minutos:\n\n"
    "https://hayminga.org?directorio=1\n\n"
    "Además de sumarte vos, nos ayudaría mucho si se lo podés compartir "
    "a otros profesionales o fanáticos de la bioconstrucción.\n\n"
    "Gracias,\n"
    "hayminga.org"
)


def _cuentas_objetivo() -> set[str]:
    config = json.loads(CONFIG_PATH.read_text())
    seguidas = {c.lstrip("@").lower() for c in (config.get("cuentas_seguidas") or [])}
    protegidas = {c.lstrip("@").lower() for c in (config.get("cuentas_protegidas") or [])}
    return seguidas | protegidas


def destinatarios_elegibles(service) -> list[tuple[int, str, str]]:
    """Devuelve [(fila, username, email), ...] de cuentas que seguimos,
    con email público cacheado, que no están ya en el Directorio y a
    las que no se les pidió esto en los últimos MESES_COOLDOWN_REFERIDO
    meses. Fila ya incluye el offset de header (fila 2 = primera
    cuenta)."""
    objetivo = _cuentas_objetivo()
    emails_directorio = cargar_emails_directorio(service)

    values = (
        service.spreadsheets().values()
        .get(spreadsheetId=SPREADSHEET_ID, range=f"{CUENTAS_IDS_SHEET_NAME}!A2:E")
        .execute()
    ).get("values", [])

    limite = date.today() - timedelta(days=30 * MESES_COOLDOWN_REFERIDO)
    elegibles = []
    for i, row in enumerate(values):
        row = (row + [""] * 5)[:5]
        username = (row[0] or "").strip().lower()
        email = (row[3] or "").strip()
        if username not in objetivo or not email:
            continue
        if email.lower() in emails_directorio:
            continue
        ultimo = (row[4] or "").strip()
        if ultimo:
            try:
                if date.fromisoformat(ultimo) > limite:
                    continue
            except ValueError:
                pass
        elegibles.append((i + 2, username, email))
    return elegibles


def pedir(escribir: bool = False) -> list[tuple[int, str, str]]:
    service = get_service()
    elegibles = destinatarios_elegibles(service)

    print(f"[pedir_referido_cuentas_instagram] {len(elegibles)} cuenta(s) elegible(s):")
    for _, username, email in elegibles:
        print(f"  @{username}: {email}")

    if not elegibles:
        return elegibles
    if not escribir:
        print("[pedir_referido_cuentas_instagram] dry-run — correr con --escribir para mandar de verdad.")
        return elegibles

    apps_script_url = os.environ["APPS_SCRIPT_URL"]
    secreto = os.environ["APPS_SCRIPT_SHARED_SECRET"]
    resp = requests.post(
        apps_script_url,
        headers={"Content-Type": "text/plain"},
        data=json.dumps({
            "accion": "enviar_mail_lista",
            "secreto": secreto,
            "emails": [email for _, _, email in elegibles],
            "asunto": ASUNTO,
            "texto": TEXTO,
        }),
        timeout=30,
    )
    data = resp.json()
    if not data.get("success"):
        print(f"[pedir_referido_cuentas_instagram] Code.gs respondió error — {data.get('error')}")
        return elegibles

    hoy = date.today().isoformat()
    updates = [
        {"range": f"{CUENTAS_IDS_SHEET_NAME}!E{fila}", "values": [[hoy]]}
        for fila, _, _ in elegibles
    ]
    service.spreadsheets().values().batchUpdate(
        spreadsheetId=SPREADSHEET_ID,
        body={"valueInputOption": "RAW", "data": updates},
    ).execute()
    print(
        f"[pedir_referido_cuentas_instagram] mail mandado a "
        f"{data.get('enviados', len(elegibles))} cuenta(s), registro actualizado"
    )
    return elegibles


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--escribir", action="store_true", help="Manda el mail de verdad (default: dry-run)")
    args = parser.parse_args()
    pedir(escribir=args.escribir)


if __name__ == "__main__":
    main()
