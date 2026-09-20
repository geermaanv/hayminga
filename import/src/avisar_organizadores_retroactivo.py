"""
avisar_organizadores_retroactivo.py
Manda el aviso de "tu evento ya está publicado" (avisar_evento_publicado)
a organizadores de eventos que YA se publicaron pero que en su momento no
lo dispararon — por ejemplo, eventos de hashtag publicados antes del fix
del 16/09 (ver ROADMAP.md), cuando el aviso solo corría para
cuentas_seguidas.

No publica nada (los eventos elegidos ya son confirmado/Activo=true):
solo revisa si la cuenta que los originó tiene email público (cacheado o
resuelto al vuelo, mismo criterio que backfill_cuentas_email.py — llamada
paga a HikerAPI solo cuando hace falta) y manda el mail.

Sin deduplicación por cuenta por default, mismo criterio que el pipeline
diario: cada evento elegible manda su propio aviso, aunque dos eventos de
la semana sean de la misma cuenta. `--uno-por-cuenta` cambia esto para
una tanda grande y retroactiva (ej. --desde=2020-01-01, donde una misma
cuenta puede acumular 5-7 eventos): manda UN solo aviso por cuenta, del
evento con Fecha_Descubrimiento más reciente — evita bombardear a la
misma persona con varios mails de golpe en un envío histórico.

`ya_taggeado` se aproxima con Hashtags_Post (columna persistida) en vez
del regex sobre el caption completo que usa el pipeline en vivo — ese
campo solo captura "#hayminga", no menciones "@hayminga" sueltas, así que
puede subestimar el agradecimiento en algún caso borde.

Dry-run por default (solo lista qué mandaría, no llama a Apps Script ni
escribe nada); correr con --escribir para mandar de verdad. `--limite=N`
para cortar después de N avisos reales, por las dudas. `--desde=YYYY-MM-DD`
cambia el corte de Fecha_Descubrimiento (default: lunes de esta semana) —
usar una fecha bien vieja (ej. --desde=2020-01-01) para cubrir TODOS los
eventos ya publicados, no solo los recientes.
"""
import sys
from datetime import date, timedelta

from src.hiker_pipeline import avisar_evento_publicado, resolver_user_id_pais_y_email
from src.sheets import (
    COLUMNS, SHEET_NAME, SPREADSHEET_ID, actualizar_cuentas_ids,
    cargar_cuentas_email, cargar_cuentas_ids, cargar_emails_directorio,
    get_service, guardar_cuentas_ids,
)


def lunes_de_esta_semana(hoy: date) -> date:
    return hoy - timedelta(days=hoy.weekday())


def eventos_elegibles(service, desde: date) -> list[dict]:
    """Confirmado + Activo + con cuenta de origen + descubierto desde
    `desde` (inclusive). Eventos de la cola manual/form (sin Username) se
    saltean acá — no hay a quién avisar."""
    values = (
        service.spreadsheets().values()
        .get(spreadsheetId=SPREADSHEET_ID, range=f"{SHEET_NAME}!A2:Y")
        .execute()
    ).get("values", [])

    elegibles = []
    for row in values:
        row = (row + [""] * len(COLUMNS))[:len(COLUMNS)]
        if (row[16] or "").strip().lower() != "confirmado":
            continue
        if (row[0] or "").strip().lower() != "true":
            continue
        username = (row[24] or "").strip().lstrip("@").lower()
        if not username:
            continue
        try:
            fecha = date.fromisoformat((row[20] or "")[:10])
        except ValueError:
            continue
        if fecha < desde:
            continue
        elegibles.append({
            "nombre": row[1],
            "username": username,
            "hashtags_post": row[23] or "",
            "fecha_descubrimiento": fecha,
        })
    return elegibles


def un_evento_por_cuenta(eventos: list[dict]) -> list[dict]:
    """Para un envío retroactivo grande: si una misma cuenta originó
    varios eventos elegibles, se queda solo con el más reciente (por
    Fecha_Descubrimiento) — un aviso por organizador, no uno por evento."""
    ultimo_por_cuenta: dict[str, dict] = {}
    for evento in eventos:
        actual = ultimo_por_cuenta.get(evento["username"])
        if actual is None or evento["fecha_descubrimiento"] > actual["fecha_descubrimiento"]:
            ultimo_por_cuenta[evento["username"]] = evento
    return list(ultimo_por_cuenta.values())


def avisar(
    dry_run: bool = True, desde: date | None = None, limite: int | None = None,
    uno_por_cuenta: bool = False,
) -> int:
    service = get_service()
    desde = desde or lunes_de_esta_semana(date.today())
    eventos = eventos_elegibles(service, desde)
    print(f"[avisar_organizadores_retroactivo] {len(eventos)} evento(s) confirmado(s)/activo(s) "
          f"con cuenta de origen desde {desde.isoformat()}")
    if uno_por_cuenta:
        eventos = un_evento_por_cuenta(eventos)
        print(f"[avisar_organizadores_retroactivo] {len(eventos)} cuenta(s) distinta(s) "
              f"(uno-por-cuenta: se queda con el evento más reciente de cada una)")

    ids_cacheados = cargar_cuentas_ids(service)
    email_cacheado = cargar_cuentas_email(service)
    emails_directorio = cargar_emails_directorio(service)

    ids_nuevos, pais_nuevos, email_nuevos = {}, {}, {}
    pais_actualizar, email_actualizar = {}, {}
    enviados = 0

    for evento in eventos:
        if limite is not None and enviados >= limite:
            print(f"[avisar_organizadores_retroactivo] tope de {limite} alcanzado, se corta acá")
            break
        username = evento["username"]
        email = email_cacheado.get(username, "")
        if not email:
            try:
                user_id, pais_resuelto, email_resuelto = resolver_user_id_pais_y_email(username)
            except Exception as e:
                print(f"[avisar_organizadores_retroactivo] @{username}: error resolviendo email — {e}")
                continue
            if not email_resuelto:
                print(f"[avisar_organizadores_retroactivo] @{username}: sin email público, se saltea")
                continue
            if username in ids_cacheados:
                if pais_resuelto:
                    pais_actualizar[username] = pais_resuelto
                email_actualizar[username] = email_resuelto
            else:
                if user_id:
                    ids_nuevos[username] = user_id
                if pais_resuelto:
                    pais_nuevos[username] = pais_resuelto
                email_nuevos[username] = email_resuelto
            email_cacheado[username] = email_resuelto
            email = email_resuelto

        ya_en_directorio = email.strip().lower() in emails_directorio
        ya_taggeado = "#hayminga" in (evento["hashtags_post"] or "").lower()

        if dry_run:
            print(f"[avisar_organizadores_retroactivo] (dry-run) mandaría a {email} — "
                  f"'{evento['nombre']}' (directorio={ya_en_directorio}, taggeado={ya_taggeado})")
            enviados += 1
            continue

        if avisar_evento_publicado(evento, email, ya_en_directorio, ya_taggeado):
            enviados += 1
            print(f"[avisar_organizadores_retroactivo] mandado a {email} — '{evento['nombre']}'")
        else:
            print(f"[avisar_organizadores_retroactivo] {email}: FALLÓ el envío — '{evento['nombre']}'")

    if not dry_run:
        guardar_cuentas_ids(service, ids_nuevos, pais_nuevos, email_nuevos)
        actualizar_cuentas_ids(service, pais_actualizar, email_actualizar)

    print(f"[avisar_organizadores_retroactivo] {enviados} aviso(s) "
          f"{'simulado(s) — correr con --escribir para mandar de verdad' if dry_run else 'mandado(s)'}")
    return enviados


if __name__ == "__main__":
    argv = sys.argv[1:]
    escribir = "--escribir" in argv
    uno_por_cuenta = "--uno-por-cuenta" in argv
    limite = None
    desde = None
    for arg in argv:
        if arg.startswith("--limite="):
            limite = int(arg.split("=", 1)[1])
        elif arg.startswith("--desde="):
            desde = date.fromisoformat(arg.split("=", 1)[1])
    avisar(dry_run=not escribir, desde=desde, limite=limite, uno_por_cuenta=uno_por_cuenta)
