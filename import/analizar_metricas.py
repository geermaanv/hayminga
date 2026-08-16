#!/usr/bin/env python3
"""
Parsea logs de una corrida de hiker_pipeline.py para mostrar métricas
de caption-only vs imagen.

Uso:
    python analizar_metricas.py < output.log
    # o
    python -m src.hiker_pipeline 2>&1 | python analizar_metricas.py
"""

import sys
from collections import defaultdict

metrics = defaultdict(int)
imagen_mejoro = []
resuelto_solo = []
intenta_imagen = []

for line in sys.stdin:
    line = line.strip()

    if "[METRICA]" not in line:
        continue

    if "DESCARTADO_SOLO_TEXTO:" in line:
        metrics["descartado_solo_texto"] += 1
    elif "RESUELTO_SOLO_TEXTO:" in line:
        metrics["resuelto_solo_texto"] += 1
        # Extraer link
        parts = line.split("RESUELTO_SOLO_TEXTO: ")
        if len(parts) > 1:
            resuelto_solo.append(parts[1])
    elif "INTENTA_CON_IMAGEN:" in line:
        metrics["intenta_con_imagen"] += 1
        parts = line.split("INTENTA_CON_IMAGEN: ")
        if len(parts) > 1:
            intenta_imagen.append(parts[1])
    elif "IMAGEN_MEJORÓ:" in line:
        metrics["imagen_mejoro"] += 1
        parts = line.split("IMAGEN_MEJORÓ: ")
        if len(parts) > 1:
            imagen_mejoro.append(parts[1])

# Estadísticas
total_descartado = metrics["descartado_solo_texto"]
total_resuelto = metrics["resuelto_solo_texto"]
total_intenta = metrics["intenta_con_imagen"]
total_mejoro = metrics["imagen_mejoro"]

print("\n" + "="*60)
print("MÉTRICAS DE CAPTION-ONLY VS IMAGEN")
print("="*60)

print(f"\n📊 RESUMEN:")
print(f"  Descartados (no evento):        {total_descartado}")
print(f"  Resueltos SOLO CON CAPTION:     {total_resuelto} ✅")
print(f"  Intentados CON IMAGEN:          {total_intenta}")
print(f"    └─ Imagen mejoró resultado:   {total_mejoro}")

if total_intenta > 0:
    pct_mejoro = (total_mejoro / total_intenta) * 100
    print(f"    └─ Tasa mejora por imagen:    {pct_mejoro:.1f}%")

total_con_intento = total_resuelto + total_intenta
if total_con_intento > 0:
    pct_resuelto_sin_imagen = (total_resuelto / total_con_intento) * 100
    print(f"\n📈 CLAVE:")
    print(f"  % resuelto SOLO con caption:   {pct_resuelto_sin_imagen:.1f}%")
    print(f"  % que necesitó imagen:         {100 - pct_resuelto_sin_imagen:.1f}%")

print(f"\n💡 INTERPRETACIÓN:")
if pct_resuelto_sin_imagen > 60:
    print("  → Imagen agrega poco valor (60%+ resuelto sin ella)")
    print("  → Considerar descargar imagen solo en casos específicos")
elif pct_resuelto_sin_imagen > 30:
    print("  → Imagen tiene valor intermedio (30-60% resuelto sin ella)")
    print("  → Keep como está, pero monitor")
else:
    print("  → Imagen es crítica (<30% resuelto sin ella)")
    print("  → No toques, está bien así")

if total_mejoro > 0 and total_intenta > 0:
    print(f"\n  Imagen mejoró en {total_mejoro}/{total_intenta} intentos ({pct_mejoro:.1f}%)")
    if pct_mejoro < 20:
        print("  → Mejora marginal, considerar agresivo")
    elif pct_mejoro < 50:
        print("  → Mejora moderada, valioso")
    else:
        print("  → Mejora significativa, crítico")

print("\n" + "="*60)
