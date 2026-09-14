"""
backfill_cuentas_email.py
Completa PaisTelefono/EmailPublico para cuentas de CuentasIds cacheadas
antes de que existieran estos campos (ver ROADMAP.md, 09/2026 y 14/09).

El bug: resolver_user_id_pais_y_email() solo corre en hiker_pipeline.py
si el user_id todavía no está cacheado (`if user_id is None`) — a
propósito, para no gastar una llamada paga por cuenta en cada corrida.
Pero eso significa que las cuentas ya resueltas antes de que este campo
existiera nunca pasan de nuevo por esa llamada, así que nunca se les
completa el email aunque lo tengan público (confirmado con datos reales:
@diplomadobioarquitectura y @ecoaldea_nakkal tienen public_email pero no
dispararon ningún aviso).

Este script corre UNA SOLA VEZ, a mano — no está colgado de ningún cron.
Dry-run por default (solo cuenta cuántas cuentas faltan); correr con
--escribir para de verdad llamar a HikerAPI (pago, una llamada por cuenta
sin país o sin email) y guardar el resultado.
"""
import sys

from src.hiker_pipeline import resolver_user_id_pais_y_email
from src.sheets import (
    actualizar_cuentas_ids, cargar_cuentas_email, cargar_cuentas_ids,
    cargar_cuentas_pais, get_service,
)


def backfill(dry_run: bool = True):
    service = get_service()
    ids = cargar_cuentas_ids(service)
    pais = cargar_cuentas_pais(service)
    email = cargar_cuentas_email(service)

    faltantes = sorted(u for u in ids if u not in pais or u not in email)
    print(f"[backfill_cuentas_email] {len(faltantes)} de {len(ids)} cuenta(s) sin país o email cacheado")
    if dry_run:
        print("[backfill_cuentas_email] dry run — no se llamó a HikerAPI; correr con --escribir para aplicar")
        return

    pais_nuevos, email_nuevos = {}, {}
    for username in faltantes:
        try:
            _, pais_resuelto, email_resuelto = resolver_user_id_pais_y_email(username)
        except Exception as e:
            print(f"[backfill_cuentas_email] @{username}: error consultando HikerAPI — {e}")
            continue
        if pais_resuelto:
            pais_nuevos[username] = pais_resuelto
        if email_resuelto:
            email_nuevos[username] = email_resuelto
        print(f"[backfill_cuentas_email] @{username}: país={pais_resuelto or '-'} email={email_resuelto or '-'}")

    actualizar_cuentas_ids(service, pais_nuevos, email_nuevos)
    print(f"[backfill_cuentas_email] {len(email_nuevos)} email(s) y {len(pais_nuevos)} país(es) nuevo(s) guardado(s)")


if __name__ == "__main__":
    backfill(dry_run="--escribir" not in sys.argv)
