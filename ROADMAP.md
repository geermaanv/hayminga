# Roadmap / historial de hayminga.org

Reconstruido a partir de `git log` — sirve para que cualquiera entienda de un vistazo qué existe, por qué, y cuál es el estado actual.

**Leer primero:** `ESTRATEGIA.md` (fases) → aquí (decisiones en contexto) → `PATRONES.md` (restricciones).

---

## Pre-Fase 1: Fundaciones (Etapas 1-5, 2024-junio 2026)

**Contexto:** Sitio estático con scraping manual. Estructura básica del portal + directorio de profesionales.

- **Etapa 1:** Sitio estático (index.html + CNAME, GitHub Pages) + pipeline separado
- **Etapa 2:** Unificación de repos (`a054fb4` / `ece849f`)
- **Etapa 3:** Cambio Claude → Gemini (primario) + Claude (fallback)
- **Etapa 4:** Canales de carga manual (web form, mail intake)
- **Etapa 5:** Directorio de profesionales (doble opt-in)

**Salida:** Dos canales de datos (manual + scraping), sitio funcional pero bajo volumen.

---

## Fase 1: Importación automática (Etapas 6-9.8, agosto 2026 - HOY)

**Objetivo:** Llenar portal de eventos automáticamente (HikerAPI) para alcanzar masa crítica sin depender de entrada manual.

**KPI:** Bajar cantidad de pendientes por corrida (menos ruido en revisión manual).

### Etapa 6: Bugs de datos/infra (15-18 ago)

Encontrados durante escalada:
- Booleans nativos rompen GViz → `"true"`/`"false"` como strings
- GViz header detection unreliable → agregar `&headers=1`
- Fórmula injection (`+`, `=`, `-`) → sanitizar
- Latitud/Longitud formato inconsistente → fallback a centroid
- Eventos sin `Id` → fallan silenciosamente en confirmar

**Decisión:** Arreglaro en paralelo a escalada, no bloquear.

### Etapa 7: Rediseño UI (ago 2026)

Iteración con prototipos en Artifacts antes de código. Toggle Eventos/Directorio, filtros unificados, vista por defecto = Lista.

**Rationale F1:** UI debe ser clara para usuarios nuevos (sin masa crítica, cada usuario importa).

### Etapa 9.5: Curación de duplicados (14 ago)

**Problema encontrado:** Mismo evento en dos posts distintos (shortcode ≠ pero nombre/fecha/provincia ≈) genera duplicados.

- Implementó dedup por shortcode + fuzzy matching por nombre+fecha+provincia
- Si match ambiguo → inserta a `pendiente_confirmacion` con nota (manual merge)
- Botón "Descartar" en `?pendientes` (no elimina fila, solo `Estado=descartado`)

**Rationale F1:** No perder datos, mejor revisar que silenciar.

### Etapa 9.6: HikerAPI + medición de recent vs top (14-15 ago)

**Problem:** Importación tenía dos problemas:
1. Sin monitoreo, no sabíamos si cambios ayudaban o empeoraban
2. `top` endpoint trae posts antiguos (popularidad histórica), no recientes

**Solución:**
- Implementó `v2/hashtag/medias/recent` + atribución por endpoint
- Midió 3 corridas: `recent` trajo 8 eventos, `top` trajo 0
- **Decisión:** Apagar `top` (USAR_TOP=False), guardar fetch_hashtag_posts() como red de seguridad

| Corrida | recent posts | top posts | solo recent | eventos solo recent |
|---------|---|---|---|---|
| 15/08 08:07 | 846 | 629 | 776 | **8** |
| 15/08 20:08 | 874 | 633 | 805 | 0 |

**Rationale F1:** Medir antes de decidir. 42 llamadas/día que no aportan → apagar. Mantener fallback por si v2 se cae.

**TODO:** Revisar ~22/08 si `recent` se mantiene estable. Si sí, `fetch_hashtag_posts()` puede desaparecer.

### Cron bajado a 1x/día (15 ago)

**Problema:** Dos corridas diarias (08:00 + 20:00) con <2 eventos/corrida en promedio = costo inútil de HikerAPI.

**Decisión:** Una sola corrida 07:11 (deja día para revisar `?pendientes`; minuto 7 para evitar congestión de cron).

**Side effect:** Email intake tardaba 24h. **Resuelto:** Separar a `email-intake.yml` cron cada 3h (gratis si cola vacía).

**Rationale F1:** Volumen bajo aún, costo > beneficio de dos corridas. Email intake merece su propio cron.

### Etapa 9.7: País vacío + hashtags candidatos (15 ago)

**Problema 1:** Filtro de país solo actuaba si IA ponía valor explícito. Si dejaba vacío → evento extranjero en pendientes.

**Solución:** `_pais_desde_texto()` en `validate_event_data()` cuando provincia no matchea Y país sigue vacío. Con guarda: si palabra "país" va seguida de número (patrón de calle porteña) → no cuenta.

**Rationale F1:** Mejorar detección temprana (ahora es aún más temprana, en `_detectar_pais_temprana()` antes de descargar).

**Problema 2:** ¿Qué hashtags nuevos agregar? Hoy se hacía a mano.

**Solución:** `candidatos_hashtags.py` - lee `Hashtags_Post` de eventos confirmados, propone nuevos candidatos. Deliberadamente NO auto-agrega (requiere revisión manual para evitar clusters de tema errado, como hongos).

**Rationale F1:** Automatizar descubrimiento, pero mantener control de calidad. Ejemplo: el filtro encontró exactamente el cluster de hongos que ya se había rechazado.

### Etapa 9.8: Duplicados por repost con texto distinto (15 ago)

Gap anterior era shortcode idéntico. Gap actual: **mismo evento en dos posts distintos** (shortcode ≠, texto/fecha ligeramente distinto).

No se persistía `username` en Sheet (tendría que cambiar schema). Solución sin schema change: `find_probable_duplicate()` en `sheets.py` — nombre parecido (tokens compartidos, sin stopwords) + provincia + fecha ±10 días.

Corre solo si clave exacta no matcheó, nunca descarta (inserta a revisión).

**Rationale F1:** No cambiar schema sin poder probar. Señal equivalente sin fricción.

### Hoy: Optimizaciones de importación (16 ago)

**Detección temprana de país** (`_detectar_pais_temprana()`): Detecta país en caption ANTES de descargar imagen. Si no-argentina → descarta sin desperdicio.

**Descarga diferida de imagen:** `extraer_evento()` ahora recibe `image_url`, descarga solo si necesita (cuando texto es ambiguo).

**Idioma único:** Usa `_parece_ingles()` (regex temprano) como fuente canónica; elimina filtro redundante de JSON de IA.

**Rationale F1:** Bajar pendientes/corrida — automatizar más, detectar antes.

---

## Fase 2: Validación por organizador (Próxima)

**Objetivo:** Reducir carga manual, dejar que organizador valide su propio evento.

**Cómo:** Notificar al organizador que originó el evento → "¿Correcto? Sí/No" → automatizado o fallback manual.

**KPI:** 70%+ validado sin intervención manual.

**Decisiones pendientes:**
- Cómo contactar al organizador (email, WhatsApp, Instagram DM)
- Timeout antes de fallback a manual
- UX de validación

---

## Fase 3: Aporte directo (Futura)

**Objetivo:** Organizadores pueblan la base (no scraping, contribución directa).

**Cómo:** Formulario mejorado + WhatsApp + mail intake existente.

**KPI:** 30% de eventos nuevos vienen de aporte directo.

**Hito:** Cuando F2 sea estable + volumen de aporte directo crezca.

---

## Flags temporales activos

- **`REVISION_MANUAL = true`** en `processor.py` + `Code.gs` — mientras esté true, todo va a revisión manual. Pasará a false cuando calidad sea suficiente (Etapa 2).
- **`USAR_TOP = False`** en `hiker_pipeline.py` — apagado porque `recent` aportaba todos los eventos en medición. Se guarda `fetch_hashtag_posts()` como fallback.
- **Cron:** 1x/día a las ~08:07 Argentina. Revisitar si volumen crece.

---

## Decisiones claves: Por qué así

**¿Por qué HikerAPI y no Google Images?**
- Google Images: links cruzados, imágenes ambiguas, sin caption real, poca ubicación
- HikerAPI: datos directos del post (caption completo, fecha real, lat/lng si etiquetó)

**¿Por qué importación agresiva en F1?**
- Sin masa crítica no hay atracción
- Sin atracción no hay organizadores dispuestos a aportar
- Importación es "priming" del mercado hasta que arranque el ciclo virtuoso

**¿Por qué revisión manual (no auto-publicación)?**
- F1 estamos aprendiendo qué es "calidad" en este mercado
- Ruido es bajo en costo (mano de obra) vs beneficio (aprendemos patrones)
- F2 → auto-publicación cuando confianza > threshold

**¿Por qué mantener `fetch_hashtag_posts()` apagado?**
- La medición mostró 0 eventos en 3 corridas
- Pero `v2/hashtag/medias/recent` es endpoint nuevo (riesgo: podría caer o cambiar)
- Mantener fallback es bajo costo (1 línea de código)

---

## Métricas a monitorear

**Ahora (F1):**
- Eventos activos: meta 50+
- Pendientes por corrida: meta <10
- Tráfico: medir con GA4

**Transición a F2:**
- 10%+ de eventos nuevos de aporte directo
- Cantidad de pendientes estable

**Transición a F3:**
- 30%+ de eventos nuevos de aporte directo
- 70%+ validado por organizador sin manual
