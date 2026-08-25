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

### Optimizaciones de importación (17 ago)

**Detección temprana de país** (`_detectar_pais_temprana()`): Detecta país en caption ANTES de descargar imagen. Si no-argentina → descarta sin desperdicio.

**Descarga diferida de imagen:** `extraer_evento()` ahora recibe `image_url`, descarga solo si necesita (cuando texto es ambiguo).

**Idioma único:** Usa `_parece_ingles()` (regex temprano) como fuente canónica; elimina filtro redundante de JSON de IA.

**Rationale F1:** Bajar pendientes/corrida — automatizar más, detectar antes.

### Instrumentación para decidir con datos (17 ago)

No se tocó la lógica: solo se agregó lo necesario para responder preguntas que hasta ahora se contestaban a ojo.

- **`[METRICA]` en `extraer_evento()`** — cuántos posts se resuelven solo con caption vs. cuántos necesitan la imagen, y en cuántos la imagen efectivamente cambió el resultado. Si la mayoría se resuelve sin imagen, la descarga es desperdicio; si no, está bien como está. `analizar_metricas.py` parsea el log.
- **`[PENDIENTE]` en `procesar_post()`** — por qué cada evento cae a revisión (`confianza_baja`, `sin_fecha`, `sin_ubicacion`...). Hasta ahora se sabía cuántos había, no por qué.
- **`analizar_pendientes.py`** — tasa de publicación (confirmados sobre revisados) y antigüedad promedio de la cola.

Los KPI de ESTRATEGIA pasaron de números absolutos a ratios en la misma vuelta: "menos de 10 pendientes" no escala con el volumen, "menos del 12%" sí.

### Vocabulario de técnicas desde los propios eventos (17 ago)

Para armar el campo de técnicas del Directorio hacía falta una lista, y la tentación era inventarla. Salió de contar los 50 eventos confirmados (`candidatos_tecnicas.py`): permacultura 7, revoques 5, quincha 4, y una cola larga de 12 técnicas con un solo evento.

Cuatro cosas que el conteo mostró y la intuición no:

1. **Permacultura le gana a todo** y agroecología aparece 3 veces: el alcance real es hábitat sustentable, no solo bioconstrucción.
2. **El criterio de `candidatos_hashtags` no se traslada.** Ahí frecuencia 1 = ruido; acá superadobe, earthship y yurta aparecen una vez y son técnicas reales con poca oferta. Filtrar por frecuencia borraría lo más específico. Hay un test que fija ese comportamiento para que nadie lo "corrija" copiando del hermano.
3. **Terminaciones es el cluster más grande** (revoques + pinturas + estucos + pisos + cal) y no estaba en el radar. Es lo que se puede enseñar en una jornada, sin obra.
4. **"Bioarquitectura" con 5 es ruido disfrazado** — es un enfoque, no una técnica. Mismo caso que "bioconstrucción".

Segunda salida del script, tan útil como la primera: los eventos donde no detectó ninguna técnica. Leerlos es el mecanismo de descubrimiento — así apareció "geometrías orgánicas en techos".

### Rediseño del Directorio (17-18 ago)

**El punto de partida, medido:** 45 organizadores distintos en los eventos confirmados (unos 30 reales al deduplicar) y **2 personas en el Directorio**, que eran Germán y Maxi. O sea: cero usuarios. El cuello de botella no era el modelo de datos sino que no había nadie — pero como migrar 2 filas cuesta cero y migrar 200 cuesta caro, convenía cambiar el esquema justo ahora.

**El problema del modelo viejo:** un solo campo `Intereses` mezclaba interés temático, rol y actividad, y no había forma de decir "sé hacer quincha".

**El modelo nuevo, dos bloques:**

- **Técnicas** (hasta 5), cada una con su relación: *la hago para otros / la enseño / la estudio / en obra propia*. Multi-select, porque el que mejor hace quincha suele ser el que la enseña.
- **Qué te interesa**: interés en una **actividad** (construir mi casa, conseguir terreno, formar comunidad, organizar mingas, ofrecer mi espacio, difundir), no en un tema. Incluye al que recién llega —que no puede afirmar "organizo eventos" pero sí "me interesa"— y es la lista de reclutamiento para Fase 3.

**El intereses-vs-servicios que motivó todo se disolvió:** no son dos vocabularios, es uno solo usado de dos lados. "La estudio" es simplemente otra relación con la misma técnica.

**Tres intentos de rankear gente, los tres descartados:** campo de matrícula (polémico en un ambiente donde el saber se transmite en la práctica), "nivel de experiencia" por técnica (autodeclarado, y en cultura de minga los que más saben se subestiman), y un badge *ofrece / en camino* calculado en la tarjeta. El último se detectó recién al ver la tarjeta propia sellada "EN CAMINO". Quedó como regla en PATRONES: el sitio no clasifica personas.

**Lo que se dejó afuera a propósito:** filtros finos por técnica y agrupación en buckets. Con dos personas, un filtro que siempre devuelve vacío es peor que no tenerlo. Los datos se guardan estructurados igual, así el filtro se agrega después sobre datos limpios.

**Consentimiento de novedades:** era un checkbox `checked disabled` — parecía control y no respondía. Ahora es real, con columna `RecibeNovedades` que el resumen semanal respeta.

**Bugs que solo aparecieron probando en el navegador**, ninguno visible leyendo el código: los encabezados nuevos no se creaban en una hoja ya existente (datos escritos sin nombre de columna, GViz devolviendo `undefined`, en silencio); los intereses con coma adentro se partían en dos chips; el cartel de confirmación quedaba fuera de pantalla al alargarse el formulario; y `scrollIntoView` no servía dentro del modal.

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

## Calidad de datos: username, dedup por cuenta, geocoding (21 ago)

Tres cambios encadenados, todos habilitados por lo mismo: persistir el
`username` de Instagram que origina cada evento — dato que HikerAPI ya
traía pero que antes solo vivía en memoria (usado únicamente para el
filtro de `cuentas_excluidas`).

**Username persistido** (`5d0a08f`): columna nueva al final de `Eventos`.
No cuesta ninguna llamada extra. Habilitó los otros dos cambios.

**Cuarta señal de dedup, por cuenta de origen** (`2beeb16`): las tres
señales existentes (shortcode, clave exacta, nombre+provincia+fecha) no
agarraban el caso de la misma cuenta repromocionando el mismo evento con
la fecha extraída distinta — el gap que había quedado abierto desde la
Etapa 9.8 por no tener el username. Verificado en seco contra los 132
eventos ya cargados antes de activarlo: 8 pares candidatos (~6%), la
mayoría duplicados reales. Encontró de paso un caso real
(`@aulaabierta.ambiente` con "Techos y Cubiertas Vivas" cargado dos veces
con fechas separadas por dos meses) y un falso positivo que hubo que
blindar explícitamente (ediciones distintas del mismo taller, tipo
"Módulo II", no son duplicados — `_MARCAS_DE_EDICION`).

**Geocodificación de la dirección extraída** (`f44cff6`): la única fuente
de coordenadas era la ubicación etiquetada en el post, y la mayoría de
los posts no etiqueta nada — 87 de 126 eventos importados quedaban sin
coordenadas, cayendo al centroide de la provincia. Ahora, si no hay
etiqueta pero sí `direccion`, se resuelve con Nominatim (gratis).
Backfill de lo ya cargado: 25 filas completadas, eventos activos
ubicados en el mapa pasaron de 23 a 35. Regla de diseño: ante la duda,
no devolver nada — un pin en el lugar equivocado es peor que ninguno.

## De importación a contacto: la cola de Instagram (21-22 ago)

Con `@hayminga` recién creada, se armó el mecanismo para convertir la
importación en contacto real con organizadores — el puente hacia F3.

**`mensajes_organizadores.py`** (`5d0a08f`): genera el mensaje de
invitación al Directorio para cada cuenta que organizó un evento ya
publicado, citando su propio evento. Deliberadamente no manda nada —
automatizar DMs viola los términos de Instagram, y el valor del mensaje
está en que es personal, no en que sea rápido. 35 cuentas distintas
identificadas (deduplicando por username: el mismo "Aula Abierta"
aparecía escrito de tres formas distintas en el campo `Organizador` de
texto libre).

**Cola de contenido en una hoja nueva** (`5eaff85`, `7090881`): los DMs
más historias por evento y el carrusel semanal, todo en una sola hoja
`Instagram` idempotente por `Clave` (`dm:<username>`,
`historia:<Id>`, `carrusel:2026-W34`). Corre colgada de
`email-intake.yml` (cada 3h) y no del import diario, para que un evento
confirmado tenga su pieza en horas, no en 24h. Regla operativa: las
filas se marcan `descartado`, nunca se borran — borrar libera la clave y
la próxima corrida la recrea.

**`INSTAGRAM.md`** (`11d5c50`): guía paso a paso para alguien sin
experiencia previa en la plataforma. La advertencia que más importa:
con una cuenta nueva, mandar los 35 DM el mismo día se parece a un bot
y puede terminar con la cuenta limitada — ritmo sugerido de 5 a 8 por
día.

**Estado al 25/8: la cola tiene 80 piezas, todas sin tocar.** El código
está listo hace días; lo que falta es la acción humana de sentarse a
mandar los primeros mensajes. Es el pendiente más importante del
proyecto hoy, no uno más de la lista.

## Directorio: de campos estructurados a texto libre (22 ago)

Después de armar el modelo de técnicas con relación (`hago`/`enseño`/
`estudio`/`obra propia`) e intereses por actividad, se lo simplificó
del todo (`ab79500`): un solo campo de texto obligatorio ("Contanos de
vos") más un checkbox de disponibilidad para trabajos.

El argumento no fue solo bajar la fricción del formulario — fue que el
texto libre **descubre vocabulario que los campos estructurados no**:
en Fase 1, con el Directorio vacío, el formulario funciona como
instrumento de investigación, igual que ya se decidió con el campo de
técnica del modelo anterior. Lo que se escriba se puede minar después,
como ya hace `candidatos_tecnicas.py` con los eventos.

Sobrevive un solo dato estructurado, `OfreceServicios`: es el único que
el que busca necesita y el único que no se puede inferir del texto sin
que el sitio termine clasificando personas — la misma regla que ya
había cerrado la discusión del badge ofrece/en camino en PATRONES.md.

**Estado al 25/8: 1 sola fila (la de prueba de Germán).** El modelo ya
no es el problema; el problema es el mismo de siempre — falta gente, y
la vía de entrada son los 35 DM de la cola de Instagram.

## Identidad visual: favicon, comunidad de WhatsApp, "¿Qué es hayminga?" (21-24 ago)

**Reescritura completa de la sección "¿Qué es hayminga?"** (`35410b0`):
revisión párrafo por párrafo con el usuario, resuelta con un prototipo
publicado como Artifact (fuentes y colores reales del sitio embebidos)
antes de tocar `index.html` — nunca se cambió el archivo real en frío.
Cambios de fondo, no solo de redacción: afirmar en vez de aspirar
("es el nexo" en vez de "busca ser"), "saberes" consistente en todo el
texto, comportamiento en vez de identidad ("tenés experiencia
construyendo" en vez de "sos constructor/a"), cierre iterativo con
WhatsApp + mail en vez de un cartel estático de "primera versión". De
rebote, un bug real de producción: los bullets de "Nuestra misión" se
partían en columnas por un `display:flex` mal puesto en el `<li>` —
estaba en el sitio desde antes de esta ronda, no era solo del prototipo.

**Favicon** (`4641566`, `004613e`): del concepto elegido en una ronda de
tres alternativas de marca (todas partiendo del propio vocabulario del
proyecto, no de un ícono de "eco" genérico) — las iniciales de "hay" +
"minga" unidas por una barra que hace de junta de mortero. La
rasterización con la tipografía real (Syne) resultó más difícil de lo
esperado: ni QuickLook ni el navegador sandboxeado esperaban a que
cargara la fuente embebida: la versión final se generó con Chrome
headless real. La primera versión (fondo claro) se perdía en una barra
de pestañas junto a otros favicons — se reemplazó por una de fondo
oscuro, mucho más contraste.

**WhatsApp: de lista de difusión a Comunidad** (`536d86d`, más
`aaa245c`/`b39f282`): la línea de "recibí novedades" quedó marcada por
WhatsApp — el patrón de mandar el mismo mensaje uno por uno a cada
contacto es exactamente lo que el algoritmo antispam detecta. Solución
de raíz, no un parche: una Comunidad de WhatsApp, donde se publica una
vez y llega a todos sin reenvío. Se migraron los dos links de
"novedades" (header y footer); los otros tres links de WhatsApp del
sitio (compartir evento, sugerir/colaborar, botón de compartir) quedan
como línea directa a propósito — son mensajes puntuales a hayminga, no
un canal de difusión.

## Cierre de una pregunta abierta: ¿hace falta la imagen? (25 ago)

Se había instrumentado el pipeline (`[METRICA]` en `extraer_evento()`)
para medir cuántos eventos se resuelven solo con el caption del post
contra cuántos necesitan la imagen — la sospecha era que tal vez se
podía ahorrar la descarga en más casos de los que se hacía. La
instrumentación estuvo puesta 5 días sin que nadie corriera el
análisis. Corrida sobre la semana completa (5 corridas, ~2500
intentos):

- 9.4% se resuelve solo con el caption
- 90.6% necesita la imagen
- de los que necesitaron imagen, en el 48.3% de los casos la imagen
  cambió el resultado respecto del intento solo-texto

**Conclusión: la imagen es crítica, no un desperdicio.** Cierra la
pregunta con datos en vez de dejarla abierta indefinidamente — y
también deja una lección de proceso: instrumentar sin agendar cuándo se
revisa es solo la mitad del trabajo (ver CLAUDE.md, regla de
actualizar ROADMAP).

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
