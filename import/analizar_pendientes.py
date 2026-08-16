#!/usr/bin/env python3
"""
Analiza qué pasó con los eventos pendientes:
- Cuántos entran a pendientes por corrida
- Qué razones (confianza baja, sin fecha, sin ubicación, etc)
- Cuántos se publican vs descartan
- Tiempo promedio en pendientes antes de revisión

Uso:
    python analizar_pendientes.py
"""

from datetime import datetime, timedelta
from src.sheets import get_service, SPREADSHEET_ID, SHEET_NAME

def analizar_pendientes():
    service = get_service()

    # Leer todos los eventos
    result = service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{SHEET_NAME}!A:Z"
    ).execute()

    rows = result.get("values", [])
    if not rows:
        print("No hay datos")
        return

    # Headers (asumir que están en fila 1)
    headers = {h: i for i, h in enumerate(rows[0]) if h}

    print("\n" + "="*70)
    print("ANÁLISIS DE PENDIENTES")
    print("="*70)

    # Contar por estado
    pendientes = []
    confirmados = []
    descartados = []

    for row in rows[1:]:
        if len(row) <= headers.get("Estado", -1):
            continue

        estado_idx = headers.get("Estado")
        activo_idx = headers.get("Activo")
        fecha_discovery_idx = headers.get("Fecha_Descubrimiento", -1)
        nombre_idx = headers.get("Nombre")
        confianza_idx = headers.get("Confianza", -1)

        if estado_idx and estado_idx < len(row):
            estado = row[estado_idx]
            nombre = row[nombre_idx] if nombre_idx and nombre_idx < len(row) else "?"

            if estado == "pendiente_confirmacion":
                fecha_disc = row[fecha_discovery_idx] if fecha_discovery_idx and fecha_discovery_idx < len(row) else "?"
                confianza = row[confianza_idx] if confianza_idx and confianza_idx < len(row) else "?"
                pendientes.append((nombre, fecha_disc, confianza))
            elif estado == "confirmado":
                confirmados.append(nombre)
            elif estado == "descartado":
                descartados.append(nombre)

    print(f"\n📊 ESTADO ACTUAL:")
    print(f"  Pendientes (sin revisar):     {len(pendientes)}")
    print(f"  Confirmados (publicados):     {len(confirmados)}")
    print(f"  Descartados (rechazados):     {len(descartados)}")

    # Analizar pendientes antiguos
    if pendientes:
        print(f"\n⏱️  ANTIGÜEDAD DE PENDIENTES:")
        hoy = datetime.now().date()
        antiguedad_dias = []

        for nombre, fecha_disc, confianza in pendientes:
            try:
                if fecha_disc and fecha_disc != "?":
                    fecha = datetime.fromisoformat(fecha_disc.split("T")[0]).date()
                    dias = (hoy - fecha).days
                    antiguedad_dias.append((dias, nombre, confianza))
            except:
                pass

        if antiguedad_dias:
            antiguedad_dias.sort(reverse=True)
            print(f"  Más antiguo: {antiguedad_dias[0][0]} días")
            print(f"  Promedio: {sum(d[0] for d in antiguedad_dias) / len(antiguedad_dias):.1f} días")

            # Mostrar top 5 más antiguos
            print(f"\n  Top 5 más antiguos:")
            for dias, nombre, confianza in antiguedad_dias[:5]:
                print(f"    - {dias}d: {nombre} ({confianza})")

    # Tasa de conversión
    total_revision = len(confirmados) + len(descartados)
    if total_revision > 0:
        tasa_publicacion = (len(confirmados) / total_revision) * 100
        print(f"\n📈 TASA DE CONVERSIÓN:")
        print(f"  Publicados: {len(confirmados)}/{total_revision} ({tasa_publicacion:.1f}%)")
        print(f"  Descartados: {len(descartados)}/{total_revision} ({100-tasa_publicacion:.1f}%)")

        if tasa_publicacion > 80:
            print(f"\n  ✅ Buena calidad — 80%+ se publica")
        elif tasa_publicacion > 50:
            print(f"\n  ⚠️  Calidad media — 50-80% se publica")
        else:
            print(f"\n  ❌ Mala calidad — <50% se publica")

    print("\n" + "="*70)

if __name__ == "__main__":
    analizar_pendientes()
