"""
mensajes_organizadores.py
Reporte de solo lectura: arma el mensaje personalizado para invitar al
Directorio a cada cuenta que organizó un evento ya publicado en el sitio.

No manda nada — deja el texto listo para copiar y pegar en Instagram. Es a
propósito: automatizar DMs va contra los términos de Instagram y además el
valor del mensaje está en que nombra *su* evento. Lo que se automatiza es
la preparación, no el envío.

Ordena por cantidad de eventos publicados: quien más aportó sin saberlo es
por quien conviene empezar.

Solo lee el Sheet (gratis). No llama a HikerAPI ni a ningún proveedor de IA.
"""
import re

from src.sheets import COLUMNS, SHEET_NAME, SPREADSHEET_ID, get_service

# Trato: siempre "ustedes". Se intentó deducir persona vs. colectivo del
# campo Organizador y no se puede: "Matria Permacultura" y "Juan Pérez" son
# las dos dos palabras con mayúscula. Como casi todas las cuentas del rubro
# son proyectos, y tratar de "ustedes" a un proyecto unipersonal no suena
# mal (al revés sí), se usa plural siempre y el reporte avisa cómo cambiarlo
# en los pocos casos que sean una persona.


def armar_mensaje(evento: str, provincia: str) -> str:
    su, quieren, les, taggean = "su", "quieren", "les", "taggean"
    publiquen, mandan, comodo, hacen = "publiquen", "mandan", "les queda", "hacen"
    donde = f" en {provincia}" if provincia else ""

    return (
        "Hola! Soy Germán, de hayminga.org 🌿\n\n"
        f"Armamos un portal que junta los eventos de bioconstrucción de todo el "
        f"país en un solo lugar, y {su} \"{evento}\"{donde} ya está publicado ahí: "
        "hayminga.org\n\n"
        f"Si {quieren}, {les} armamos perfil en el directorio así {les} encuentra "
        "quien esté buscando gente que trabaje con estas técnicas. Es gratis y "
        "lleva dos minutos.\n\n"
        f"Y si {taggean} #hayminga cuando {publiquen} algo nuevo, lo tomamos solos "
        f"— o {mandan} el flyer por WhatsApp o mail, como {comodo} más cómodo.\n\n"
        f"¡Gracias por lo que {hacen}!"
    )


def analizar(service=None) -> list[dict]:
    """Una entrada por CUENTA de Instagram (no por evento ni por el texto
    libre de Organizador, que trae la misma cuenta escrita de varias formas
    — 'Aula Abierta', 'Aula Abierta / UNC', 'Aula Abierta y UTN'...).
    Ordenado de más a menos eventos publicados."""
    service = service or get_service()
    values = (
        service.spreadsheets().values()
        .get(spreadsheetId=SPREADSHEET_ID, range=f"{SHEET_NAME}!A2:Y")
        .execute()
    ).get("values", [])

    por_cuenta: dict[str, dict] = {}
    for row in values:
        row = (row + [""] * len(COLUMNS))[:len(COLUMNS)]
        if (row[16] or "").strip().lower() != "confirmado":
            continue
        usuario = (row[24] or "").strip().lstrip("@").lower()
        if not usuario:
            continue
        entrada = por_cuenta.setdefault(usuario, {
            "usuario": usuario, "eventos": [], "organizador": (row[9] or "").strip(),
        })
        entrada["eventos"].append({
            "nombre": (row[1] or "").strip(),
            "provincia": (row[7] or "").strip(),
            "activo": (row[0] or "").strip().lower() == "true",
        })

    salida = []
    for datos in por_cuenta.values():
        # Se cita un evento activo si hay: invita mejor algo que todavía va a
        # pasar que uno que ya terminó.
        eventos = datos["eventos"]
        citado = next((e for e in eventos if e["activo"]), eventos[0])
        salida.append({
            "usuario": datos["usuario"],
            "eventos": len(eventos),
            "otros": [e["nombre"] for e in eventos if e["nombre"] != citado["nombre"]],
            "mensaje": armar_mensaje(citado["nombre"], citado["provincia"]),
        })
    return sorted(salida, key=lambda d: (-d["eventos"], d["usuario"]))


def reportar(limite: int = 0):
    cuentas = analizar()
    if not cuentas:
        print("[mensajes_organizadores] Sin eventos confirmados con cuenta de origen")
        return
    print(f"[mensajes_organizadores] {len(cuentas)} cuenta(s) para invitar")
    print("   Todos en 'ustedes'. Si el contacto es una persona y no un proyecto: "
          "quieren→querés, les→te, taggean→taggeás, publiquen→publiques, "
          "mandan→mandás, hacen→hacés.\n")
    for i, c in enumerate(cuentas if not limite else cuentas[:limite], 1):
        print("=" * 68)
        print(f"{i}. @{c['usuario']}   ({c['eventos']} evento/s publicados)")
        print("=" * 68)
        print(c["mensaje"])
        if c["otros"]:
            # Por si el evento citado no es el mejor para ese contacto — el
            # script elige uno activo, pero puede no ser el más on-topic.
            print("\n   otros eventos suyos, por si conviene citar otro:")
            for n in c["otros"]:
                print(f"     · {n}")
        print()


if __name__ == "__main__":
    import sys
    reportar(int(sys.argv[1]) if len(sys.argv) > 1 else 0)
