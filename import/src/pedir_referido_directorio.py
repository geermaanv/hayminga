"""
pedir_referido_directorio.py
Campaña puntual: le pide a cada persona del Directorio que ayude a
sumar más gente a hayminga.org — "crecer en profesionales" (31/10/2026,
ver ROADMAP.md). Texto aprobado por el mantenedor, simple y sin la
palabra "Directorio" a propósito.

A diferencia del resumen semanal, manda a TODOS sin filtrar por
RecibeNovedades (decisión explícita: esto no es "novedades", es un
pedido puntual). El envío real y el filtro de repetición corren en
Code.gs (acción `pedir_referido_directorio`) — Python nunca escribe el
Directorio directamente, lo escribe solo Code.gs (ver CLAUDE.md).
Code.gs guarda la fecha de cada envío en la columna
UltimoPedidoReferido para que una corrida futura no le repita el
pedido a la misma persona antes de MESES_COOLDOWN_REFERIDO meses.

Dry-run por default: solo muestra una vista previa de cuántas personas
recibirían el mail hoy (lectura, gratis), sin mandar nada. --escribir
le pide a Code.gs que mande de verdad.
"""

import argparse
import json
import os
from datetime import date, timedelta

import requests

from src.sheets import SPREADSHEET_ID, get_service

DIRECTORIO_SHEET_NAME = "Directorio"
DIRECTORIO_PREVIEW_RANGE = "F2:L"  # Email .. UltimoPedidoReferido
MESES_COOLDOWN_REFERIDO = 2  # debe coincidir con Code.gs

ASUNTO = "Ayuda para hacer crecer hayminga.org"
TEXTO = (
    "Hola!\n\n"
    "Somos hayminga.org. Gracias por estar con nosotros.\n\n"
    "Queremos seguir creciendo, y la mejor ayuda que nos podés dar es bien "
    "simple: contale a alguien que conozcas y que trabaje con tierra, "
    "quincha, adobe o técnicas parecidas, que existe este espacio.\n\n"
    "Si se te ocurre alguien, reenviale este mail o pasale este link:\n\n"
    "https://hayminga.org?directorio=1\n\n"
    "Gracias por ayudarnos a seguir creciendo.\n\n"
    "Un abrazo,\n"
    "hayminga.org"
)


def previsualizar(service) -> int:
    """Vista previa de solo lectura: aproximadamente cuántas personas
    recibirían el mail hoy. El filtro real (y el único que escribe
    algo) corre en Code.gs — esto nunca escribe el Directorio."""
    values = (
        service.spreadsheets().values()
        .get(spreadsheetId=SPREADSHEET_ID, range=f"{DIRECTORIO_SHEET_NAME}!{DIRECTORIO_PREVIEW_RANGE}")
        .execute()
    ).get("values", [])

    limite = date.today() - timedelta(days=30 * MESES_COOLDOWN_REFERIDO)
    elegibles = 0
    for row in values:
        row = (row + [""] * 7)[:7]
        email = (row[0] or "").strip()
        if not email:
            continue
        ultimo = (row[6] or "").strip()
        if ultimo:
            try:
                if date.fromisoformat(ultimo) > limite:
                    continue
            except ValueError:
                pass
        elegibles += 1
    return elegibles


def pedir(escribir: bool = False) -> int | None:
    service = get_service()
    preview = previsualizar(service)
    print(f"[pedir_referido_directorio] ~{preview} persona(s) recibirían el mail hoy (vista previa, aproximada)")
    print(f"[pedir_referido_directorio] asunto: {ASUNTO}")

    if not escribir:
        print("[pedir_referido_directorio] dry-run — correr con --escribir para mandar de verdad.")
        return None

    apps_script_url = os.environ["APPS_SCRIPT_URL"]
    secreto = os.environ["APPS_SCRIPT_SHARED_SECRET"]
    resp = requests.post(
        apps_script_url,
        headers={"Content-Type": "text/plain"},
        data=json.dumps({
            "accion": "pedir_referido_directorio",
            "secreto": secreto,
            "asunto": ASUNTO,
            "texto": TEXTO,
        }),
        timeout=30,
    )
    data = resp.json()
    if not data.get("success"):
        print(f"[pedir_referido_directorio] Code.gs respondió error — {data.get('error')}")
        return None
    enviados = data.get("enviados", 0)
    print(f"[pedir_referido_directorio] mail mandado a {enviados} persona(s)")
    return enviados


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--escribir", action="store_true", help="Manda el mail de verdad (default: dry-run)")
    args = parser.parse_args()
    pedir(escribir=args.escribir)


if __name__ == "__main__":
    main()
