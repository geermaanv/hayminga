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

## Timeout de import-eventos: de día degradado a límite estructural (09/09)

Dos corridas seguidas se cortaron justo a los 60 minutos (el límite
subido de 45 a 60 el 16/08 por un día malo de HikerAPI). La primera
parecía repetir ese patrón: decenas de `504 DEADLINE_EXCEEDED` de
Gemini. Pero la segunda, disparada manualmente media hora después, tuvo
Gemini sano — un solo timeout en toda la corrida — y aun así llegó
apenas a la mitad de `cuentas_seguidas` (74+) antes de cortarse.

**Conclusión: ya no es un día externo degradado, es la lista de cuentas
creciendo.** Hashtags + cuentas necesitan hoy ~100 minutos incluso sin
ningún problema de API. Subir el margen otra vez (60→120) compra
tiempo, pero si la lista sigue creciendo al ritmo de `curar_fuentes.py`
agregando candidatas, va a volver a quedarse corto — la próxima vez
que esto pase, medir si conviene partir el descubrimiento (hashtags y
cuentas) en dos jobs en paralelo en vez de seguir subiendo el número.

Sin pérdida de datos en ninguna de las dos corridas: el guardado es
incremental y los posts no llegados a procesar quedan para la corrida
siguiente (`RETRY` en `processor.py`, no se marcan como vistos).

## Corrección: no era crecimiento gradual, era un bug de altas que se
retroalimenta (12/09)

La entrada anterior quedó corta. Tres corridas más después de subir a
120 min volvieron a cortarse justo en el límite — subir el número solo
pateó el problema unos días. La causa real: `curar_fuentes.py` agregó
**515 cuentas en una sola corrida** el 08/09 (137 → 652, `dc1696e`,
cuentas sin relación al tema tipo `@0zod.boy`), no un crecimiento
orgánico de a poco — y el bug se retroalimenta: más cuentas fuente
generan más consultas de "sugeridas" con más superposición entre sí, así
que la corrida siguiente (11/09, `64fe5f8`) agregó **~2976 más de
golpe** (652 → 3627) antes de que esto se detectara.

El piso `MIN_SUGERENCIAS_PARA_AGREGAR=2` ("sugerida por al menos 2
cuentas nuestras") ya existía justamente para este problema — un
incidente previo sin el piso trajo más de 900 cuentas de golpe — pero
resultó insuficiente: con cientos de cuentas fuente diversas, Instagram
sugiere en común suficientes cuentas genéricas de "vida natural" como
para que un piso de 2 casi no filtre nada.

**Fix:** revertidas todas las altas del bug (`cuentas_seguidas` vuelve a
las 137 de antes del 08/09), piso subido a 3, y sobre todo un tope duro
(`MAX_ALTAS_POR_CORRIDA=15`) que prioriza las más sugeridas y deja el
resto para la corrida siguiente — así una mala tanda de "sugeridas"
nunca vuelve a multiplicar la lista de una vez, incluso si el piso
vuelve a resultar débil. El timeout de 120 min queda como está (no hace
daño tener margen de sobra), pero ya no debería hacer falta con 137
cuentas.

**Lección:** cuando el mismo síntoma vuelve a pasar después de
"arreglarlo" subiendo un número, el número no era la causa — hay que
mirar qué cambió en los datos, no solo en el límite. Y un mecanismo de
alta automática sin tope de volumen es peligroso por diseño: un piso de
calidad débil no solo deja pasar ruido, se multiplica solo.

## Validación de eventos por el organizador vía email (12/09)

El trabajo manual no escala — la cola de `?pendientes` viene subiendo
(43 → 56 en una semana) y no hay tiempo para bajarla a mano. Al mismo
tiempo, la cola de DM a organizadores (`dm_organizador`, para invitarlos
al Directorio) lleva semanas con 35 mensajes preparados y cero enviados:
Instagram prohíbe automatizar DMs, y "alguien tiene que tocarlo a mano
en el teléfono" resultó ser un cuello de botella real, no solo teórico.

**Descubrimiento clave:** HikerAPI ya trae `public_email` en la misma
respuesta de `user/by/username` que se usa hoy para detectar país (sin
llamada extra). Medido con datos reales: **~62% de cobertura** (8 de 13
cuentas de `cuentas_seguidas` al azar tenían el campo poblado), incluso
en cuentas que no son "Business" — mismo patrón que
`public_phone_country_code`.

**Diseño:** en vez de otra cola manual, se reusó el mecanismo que ya
existía en `Code.gs` para el opt-in del Directorio (link de un solo uso
por token, `MailApp.sendEmail` + `doGet()`). Cuando hay email
disponible, el evento no cae en `pendiente_confirmacion` — se le manda
un mail al organizador con "¿confirmás o rechazás?" y queda en un
estado nuevo y transitorio, `pendiente_organizador`. Si no responde en
~5-7 días, cae a `pendiente_confirmacion` de siempre — es un atajo
opcional, no un reemplazo de la revisión manual.

Tope de 10 mails por corrida (`_MAX_VALIDACIONES_ORGANIZADOR_POR_CORRIDA`)
a propósito — mismo espíritu que `MAX_ALTAS_POR_CORRIDA`: después del
incidente de `curar_fuentes.py` la regla en esta parte del proyecto es
"nunca automatizar sin tope de volumen", y además una tanda grande de
mails de golpe desde una cuenta se ve menos genuina que un goteo diario.

**Métricas, no solo automatización:** cada solicitud queda en una hoja
nueva `ValidacionesOrganizador` (Pendiente/Confirmado/Rechazado/Vencido)
para poder responder con datos, no intuición, si el canal vale la pena
— cuántos confirman vs. cuántos nunca responden. Se suma también al
aviso diario de Telegram (duración de la corrida + validaciones
mandadas hoy + acumulado histórico), no solo al resumen semanal.

## Corrección: se sacó el mecanismo de confirmar/rechazar por token (14/09)

La entrada anterior (12/09) todavía pedía "¿confirmás o rechazás?" por
mail con link de un solo uso. Repensándolo: pedirle al organizador que
haga clic para confirmar algo que HikerAPI ya trae con bastante señal de
confianza (email público de la cuenta que posteó) es fricción de más, y
un link roto o un mail a spam deja el evento colgado en
`pendiente_organizador` sin necesidad.

**Cambio de modelo:** el evento se publica directo apenas hay email
disponible (`Estado=confirmado`, `Activo=true`, sin pasar por
`pendiente_confirmacion` ni por ningún estado transitorio nuevo) y el
mail que se manda ya no pide nada — avisa que el evento está publicado,
con link, y dos CTA: sumarse al Directorio (con la razón: te hace
encontrable todo el año, no solo la semana del evento) y taggear a
`@hayminga` la próxima vez para no depender de que lo encontremos por
hashtag. Si algo está mal, el organizador responde el mail y se corrige
a mano — no hay volumen para que eso sea un cuello de botella.

Con esto se cae todo lo que existía solo para sostener el flujo de
click: el estado `pendiente_organizador`, la hoja
`ValidacionesOrganizador` y el desglose de confirmaron/rechazaron/
esperando/vencieron en Telegram. Queda solo el conteo de mails mandados
por corrida (mismo tope de 10) — la métrica que importa ahora no es
"cuántos confirman" sino simplemente si el canal se usa y si llegan
respuestas pidiendo cambios.

**Mail más inteligente, no siempre el mismo texto (14/09):** dos ajustes
para que el mail no le pida a nadie algo que no corresponde. Primero,
`sheets.cargar_emails_directorio()` lee la columna Email del Directorio
antes de armar el mail: si el organizador ya está inscripto, se saca el
párrafo de invitación — invitar de nuevo a quien ya se sumó suena a que
no se le prestó atención. Segundo, `procesar_post()` ya detecta con
regex (`ya_taggeado_hayminga`) si el caption del post traía `#hayminga`
o `@hayminga`; si es así, el mail agradece en vez de pedir que lo haga
la próxima vez.

De paso se resolvió el bug de cobertura que quedó pendiente el 12/09:
`resolver_user_id_pais_y_email()` solo corre para cuentas sin `user_id`
cacheado (para no gastar una llamada paga por cuenta en cada corrida), así
que las cuentas resueltas antes de que existiera el campo `EmailPublico`
nunca lo completaban solas — confirmado en producción con
`@diplomadobioarquitectura` y `@ecoaldea_nakkal`, ambas con email público
real que nunca disparó ningún aviso. En vez de tocar el pipeline diario
(que repetiría el mismo gasto todos los días para siempre), se agregó
`backfill_cuentas_email.py`: script manual de una sola corrida, dry-run
por default, que resuelve solo las cuentas con país o email faltante y
guarda con `sheets.actualizar_cuentas_ids()` (a diferencia de
`guardar_cuentas_ids()`, que solo agrega filas nuevas, este actualiza las
que ya existen).

El aviso diario de Telegram ahora también lista el detalle (email +
nombre del evento) de cada mail mandado ese día, no solo el conteo — es
la idea original del 12/09 ("responder con datos, no intuición, si el
canal sirve") pero sin la infraestructura de estados/hoja que se sacó:
alcanza con guardar la lista en `run_summary.json` para el día.

## El aviso por email ahora corre para todo evento, no solo cuentas_seguidas (16/09)

Probando el flujo en producción (14 y 15/09) salieron 0 avisos en ambas
corridas a pesar de tener 77 cuentas con email ya cacheadas — el motivo
era simple: los eventos nuevos de esos dos días vinieron de hashtag, y
`avisar_evento_publicado` solo estaba cableado para `cuentas_seguidas`
(la única fuente donde la cuenta ya se resolvía gratis de antemano).
Confuso además porque, sin ver el código, "tiene email pero no le
llegó nada" parece un bug.

**Cambio:** `_intentar_publicar_con_email()` centraliza la lógica que
antes vivía solo en el loop de `cuentas_seguidas` y ahora la llaman los
dos loops de descubrimiento (hashtag y cuenta) apenas `procesar_post()`
devuelve un evento. Para hashtag, que no resuelve la cuenta de antemano,
se paga una llamada a HikerAPI por evento — pero por evento YA FILTRADO
Y EXTRAÍDO (unos pocos por día), no por cada uno de los ~800-900 posts
crudos que trae un hashtag antes de descartar la enorme mayoría; el
costo extra es marginal comparado con las 179 llamadas que ya hace la
corrida.

**Sin deduplicación por cuenta, a propósito** (pedido explícito): si a
una cuenta ya se le mandó un aviso — hoy o cualquier día anterior — un
evento nuevo de esa misma cuenta manda el suyo igual. Cada evento es su
propia notificación; no hay lógica de "ya le escribimos, no de nuevo".

**Backfill retroactivo:** el fix de arriba solo aplica hacia adelante —
los eventos de hashtag ya publicados esa semana se quedaron sin aviso
porque en su momento no corría esa lógica. `avisar_organizadores_retroactivo.py`
hace lo mismo que haría el pipeline en vivo pero sobre eventos que ya
están `confirmado`/`Activo=true` (no publica nada de nuevo, solo avisa):
filtra por fecha de descubrimiento (`lunes_de_esta_semana()` por
default), resuelve el email si no está cacheado (mismo costo por evento
que el fix de arriba) y manda el mail. `ya_taggeado` se aproxima con la
columna `Hashtags_Post` en vez del caption completo — solo capta
`#hayminga`, no una mención `@hayminga` suelta, así que en el borde
puede no agradecer cuando correspondería. Dry-run por default,
`--escribir` para mandar de verdad, `--limite=N` como freno manual (el
tope de la corrida diaria no aplica acá, es un script aparte).

**Cobertura real medida (20/09):** corriendo el backfill con
`--desde=2020-01-01` (todos los eventos ya publicados, no solo esta
semana) dio 121 eventos elegibles, 63 con email resoluble — pero solo
**39 cuentas distintas**: varias acumulaban 5-7 eventos cada una (ej.
`centronakkal` con 7), y mandar uno por evento las hubiera bombardeado
con varios mails de golpe en la misma tanda. Se agregó
`--uno-por-cuenta` (usa `un_evento_por_cuenta()`) para este caso: manda
un solo aviso por cuenta, del evento con `Fecha_Descubrimiento` más
reciente — deliberadamente distinto del "sin deduplicación" de arriba,
que sigue siendo la regla para la corrida diaria en vivo. La
deduplicación por cuenta solo tiene sentido para una tanda retroactiva
grande, nunca para el flujo normal.

**Copy revisado (20/09):** tres ajustes al mail — "Ya que estamos:
sumate..." sonaba a ocurrencia tardía, pasó a "Te invitamos a
sumarte..." con "te lleva menos de 90 segundos" (baja la fricción
percibida); se agregó "Hacé clic para darte de alta:" antes del link
del Directorio (el link solo, sin texto que lo introduzca, se perdía);
y el CTA de taggear a @hayminga ahora explica el motivo ("nos permite
automatizar la importación y te asegura que lo publicamos
rápidamente") en vez de solo pedirlo — la razón vende mejor que el
pedido pelado.

## Corrección: revisión del criterio de clasificación, y REVISION_MANUAL nunca frenó a HikerAPI (22/09)

Repasando juntos (Germán y Claude) el criterio completo de qué se
publica solo y qué no, salió a la luz un desfasaje entre la
documentación y el código real: el `CLAUDE.md` decía que
`REVISION_MANUAL=true` hacía que "everything lands as
pendiente_confirmacion", pero eso solo era cierto para el camino de
mail intake (`extract_event_data`, usado por `email_intake.py`).
**`hiker_pipeline.py` — el canal de HikerAPI, que es el volumen
real — nunca chequeó ese flag.** El único gate ahí siempre fue
`confianza != "alta"`, así que cualquier evento de hashtag o cuenta
seguida con confianza alta se viene publicando solo, sin pasar por
`?pendientes`, desde que existe esa lógica — nadie lo notó porque
nadie lo había auditado línea por línea contra la documentación.

No es un bug a revertir: cuando `?pendientes` empezó a acumularse fue
una decisión consciente dejar de depender de revisión manual — el
código ya reflejaba esa decisión, solo que a medias y sin que el
`CLAUDE.md` se enterara. La postura del proyecto de acá en adelante,
dicha explícitamente: **el proceso de importación no puede depender
del trabajo manual de Germán**, por volumen. Se aprovechó para
prolijizar en vez de solo parchear:

- **`CONFIANZA_PUBLICABLE = {"alta", "media"}`** en `processor.py`:
  un solo criterio de publicación para todo el pipeline de Python.
  Antes de esto, "alta y media publican" (pedido explícito — antes
  solo alta lo hacía) hubiera sido un cambio a un umbral que nunca
  se aplicaba parejo entre los dos canales.
- **`REVISION_MANUAL` se borró** de `processor.py`. `extract_event_data()`
  (mail intake) ahora usa el mismo `CONFIANZA_PUBLICABLE` que
  `hiker_pipeline.py` — ya no hay dos criterios de publicación
  distintos sin razón para que difieran.
- El `REVISION_MANUAL` de `Code.gs` (formulario web `+ Nuevo Evento`)
  es un flag distinto, en otro archivo, y queda como está: ese canal
  no tiene `confianza` porque lo completa una persona a mano, no una IA.

**Otros tres ajustes al criterio, del mismo repaso:**

- **Idioma**: `_parece_ingles()` pasó a `_parece_extranjero()`,
  sumando una lista de palabras distintivas de portugués (con
  tildes/ortografía que no existen en español, para no confundir con
  vocabulario romance compartido). Además, se implementó de verdad el
  chequeo post-extracción que el `CLAUDE.md` decía que existía pero
  no estaba en ningún lado: si la IA extrae `idioma` distinto de
  `"es"`, se descarta — defensa en profundidad para cuando el caption
  es muy corto para que el filtro barato lo detecte, pero la imagen sí
  trae texto en otro idioma.
- **Virtual sin país**: antes, un evento virtual donde nunca se pudo
  determinar el país (ni el flyer, ni la cuenta) quedaba en
  `pendiente_confirmacion` para siempre sin activarse nunca — el
  filtro de "no-Argentina" solo disparaba cuando el país SÍ se sabía
  y no coincidía. Ahora se descarta directo: solo se publican
  virtuales de Argentina, y sin ninguna señal de país no hay forma de
  confirmarlo.
- **Agradecimiento post-evento**: el prompt de extracción no decía
  nada sobre distinguir una invitación a algo futuro de un
  agradecimiento/resumen de algo que ya pasó — un post tipo "¡Gracias
  a quienes vinieron al taller del sábado!" podía colar `es_evento=true`
  sin fecha futura y quedar dando vueltas en pendientes. Ahora el
  prompt lo pide explícito.

**Sobre `confianza`:** el campo existía en el schema hacía meses sin
que el prompt le explicara al modelo qué significaba cada nivel — lo
llenaba con criterio propio, sin instrucciones. Ahora el prompt define
los tres niveles en términos de qué tan explícitos están los datos
críticos (nombre, fecha con año, ubicación), no por impresión general —
ver `CLAUDE.md` para el texto exacto.

**Motivo de fondo de esta revisión:** evaluar si conviene clasificar
eventos con Jev (TypeSafe AI, modelo "System One" — ver acceso
confirmado el 21/09) en vez de o además de Gemini. Comparar Jev contra
un prompt de Gemini con estos agujeros no hubiera dicho nada útil — el
criterio tenía que quedar bien definido primero, para dárselo igual a
los dos lados de la comparación.

## Arnés de comparación Jev vs. Gemini (22/09)

Con el criterio ya definido, se armó `src/comparar_jev_gemini.py` para
correr el mismo texto contra los dos lados y ver si coinciden.

**Alcance acotado a clasificación, no a extracción completa:** lo único
que se probó funcionando de la API de Jev es preguntas tipo `choice`
sobre un texto (`state`) — el diagnóstico del 21/09 nunca mandó una
imagen. Las dos preguntas que se comparan (`es_evento`, `confianza`) son
exactamente las que `SYSTEM_PROMPT` ya define para Gemini, copiadas
palabra por palabra a los `criteria` de Jev — coherente con el motivo de
la revisión de arriba. Nombre/fecha/dirección (extracción de campos) queda
afuera: no hay evidencia de que Jev los soporte, y no es lo que dice el
ROADMAP que se quería evaluar ("clasificar eventos").

**Dataset, con una limitación real:** la Sheet no guarda el caption del
post (solo los campos ya extraídos, ver PATRONES.md), así que no hay
manera de recolectar una muestra histórica sin tocar el pipeline en vivo
para loguearlos. Los 7 casos de `CASOS` son ilustrativos, a mano: los dos
primeros son literalmente los captions del diagnóstico del 21/09, el
resto cubre bordes ya documentados (año no escrito → confianza media,
agradecimiento post-evento, evento vago, tema ajeno a bioconstrucción).
Sirve para una primera lectura cualitativa, no para un porcentaje de
acuerdo confiable — eso necesita captions reales, que quedan como
pendiente si esta primera pasada justifica seguir.

`src/jev_client.py` es el cliente mínimo (`TYPESAFE_API_KEY`, endpoint y
payload confirmados en el diagnóstico ya borrado). Corre con
`python -m src.comparar_jev_gemini` (`--guardar RUTA` para el JSON
completo) — no toca la Sheet ni publica nada, solo gasta las llamadas a
Gemini y Jev que hace.

### Primera corrida real, con hallazgos (22/09)

Se corrió dos veces contra las API keys reales (workflow de diagnóstico
temporal, mismo patrón de siempre, ya borrado). La primera corrida
destapó un bug real: la API de Jev no devuelve el string pelado que
asumía el diagnóstico del 21/09, sino un objeto por pregunta
(`{"type":"choice","choice":"si","confidence":0.99,"probabilities":{...}}`).
El script comparaba el string de Gemini contra ese dict entero — nunca
podían coincidir, el "0/3" de la primera corrida no significaba nada.
Corregido (`_jev_clasificar` ahora extrae `choice`), confirmado en la
segunda corrida.

**Cuota de Gemini, un hallazgo aparte:** las dos corridas pegaron en
`429 RESOURCE_EXHAUSTED` en la mayoría de los 7 casos (4/7 fallaron en la
primera, 6/7 en la segunda) — la cuota gratis se agotó entre una corrida
y la siguiente, unos minutos después. Este script comparte
`GEMINI_API_KEY` con el pipeline de producción; correrlo más de una vez
en poco tiempo (o el mismo día que ya corrió `hiker_pipeline`/
`email_intake`) se come la cuota gratuita del día. Para una corrida más
completa hace falta espaciarlo más, o correrlo con billing.

**Con los datos válidos combinados de las dos corridas** (4 de 7 casos
con respuesta de Gemini, los 7 con Jev — Jev nunca falló):

| caso | Gemini | Jev | es_evento | confianza |
|---|---|---|---|---|
| `alta_confianza_completa` | si/alta | si/alta (0.77) | coincide | coincide |
| `virtual_sin_anio` | si/media | si/media (0.92) | coincide | coincide |
| `diagnostico_evento` | si/**alta** | si/**media** (0.99) | coincide | **discrepan** |
| `diagnostico_no_evento` | no/alta | no/baja (0.78) | coincide | discrepan |

`es_evento` coincidió en los 4 casos con datos de los dos lados — señal
positiva, aunque la muestra es chica. `confianza` coincidió solo en los
2 casos "limpios" (todo explícito, o virtual con año faltante — ambos
géneros ya cubiertos por el criterio). Discrepa justo en el caso más
interesante: `diagnostico_evento` es el mismo caption real del
diagnóstico del 21/09 (sin año escrito) — por el criterio propio de
`SYSTEM_PROMPT` ("año no escrito → media"), la respuesta correcta es
media, y es la que dio Jev; Gemini dijo alta, inconsistente con su
propio criterio (el caso `virtual_sin_anio`, con el mismo defecto de
"sin año", sí le dio media). Es decir: en esta muestra chica, Jev aplicó
el criterio de confianza de forma más consistente que Gemini en el
mismo tipo de caso.

**Algo que Gemini no da y Jev sí:** una probabilidad numérica por
respuesta (`confidence`/`probabilities`). En `evento_vago` (el caption
deliberadamente ambiguo) Jev contestó `si` con confidence 0.61 — mucho
más bajo que el resto (0.97-1.0) — el propio modelo "duda" en el caso
diseñado para ser dudoso, una señal que Gemini simplemente no expone.

**No alcanza para decidir.** 4 comparaciones válidas de confianza es
poquísimo, y el dataset sigue siendo a mano, no captions reales. Lo que
sí queda: el arnés funciona, el parseo está corregido y confirmado, y
hay una primera señal (no una conclusión) de que Jev podría ser más
consistente que Gemini clasificando `confianza` en el borde "año no
escrito". Antes de decidir habría que ampliar la muestra sin volver a
pegarle a la cuota gratis de Gemini en el mismo día.

### Segunda corrida, con billing habilitado y muestra ampliada (22/09)

Con billing activado en el proyecto de `GEMINI_API_KEY` (decisión del
mantenedor tras confirmar que el tope de Tier 1 es un límite de gasto,
no un cargo — el costo real de esta corrida es centavos de dólar) y
`CASOS` ampliado de 7 a 11, se corrió de nuevo el mismo workflow
temporal. Sin ningún `429`: **los 11 casos respondieron de los dos
lados**, primera corrida sin ruido de cuota.

**`es_evento`: 9/11 coinciden.** Los 2 discordantes:
- `evento_vago` — caso deliberadamente ambiguo, sin respuesta correcta
  definida; Gemini descartó (`no`), Jev dejó pasar (`si`, confidence
  0.61, la más baja de toda la corrida — el propio modelo "duda" en el
  caso diseñado para dudar).
- `mixto_agradecimiento_y_proximo` — **este es un hallazgo real, no
  ambigüedad de diseño.** El caption agradece un evento pasado y anuncia
  uno futuro concreto ("el próximo para el 14 de noviembre"). Gemini
  clasificó `es_evento=false` con todos los campos en `null`, ignorando
  la mención del evento futuro — justo el borde para el que se escribió
  la instrucción de recap-vs-anuncio en `SYSTEM_PROMPT` (ver más arriba,
  22/09). Jev clasificó `si` (confidence 0.77, `confianza=media` por el
  año inferido). **Acción pendiente, independiente de la evaluación de
  Jev:** revisar `SYSTEM_PROMPT` para que la regla de recap-vs-anuncio
  cubra explícitamente el caso mixto (agradecimiento + anuncio en el
  mismo texto) — tal como está, un post real con esta forma se
  descartaría en producción y el evento nunca llegaría a
  `pendiente_confirmacion`. **Corregido** el mismo día: `SYSTEM_PROMPT`
  ahora dice explícitamente que si el texto agradece algo pasado PERO
  también anuncia un próximo evento concreto, `es_evento=true` con los
  datos de ese evento futuro — no se descarta el post entero. Las
  preguntas de Jev en este mismo script se actualizaron igual, para
  seguir dándole el mismo criterio a los dos lados de la comparación.

**`confianza`: 5/11 coinciden.** De las 6 discrepancias:
- **3 confirman el patrón de la primera corrida**, ahora con más
  evidencia: en `diagnostico_evento` y `virtual_sin_anio` el propio
  criterio de `SYSTEM_PROMPT` pide `media` cuando el año no está escrito
  y hay que inferirlo — Jev acertó las dos veces (`media`), Gemini marcó
  `alta` las dos veces, inconsistente con su propio criterio. Sumado a
  la primera corrida, son **3 de 3 oportunidades** donde Jev aplicó
  correctamente esa regla y Gemini no aplicó ninguna.
- **3 son ambigüedad del criterio, no error de ningún lado:**
  `diagnostico_no_evento`, `agradecimiento_post_evento` y `tema_ajeno`
  son casos con `es_evento=no` en ambos lados — `confianza` no tiene un
  significado definido en `SYSTEM_PROMPT` cuando no hay evento que
  describir (el criterio habla de "nombre, fecha, ubicación", que no
  aplican). Gemini tiende a `alta` (confianza en que no es un evento),
  Jev tiende a `baja`/`media`. Ninguna de las dos lecturas está mal; el
  criterio simplemente no cubre este caso y habría que definirlo si se
  quiere que `confianza` sea comparable también cuando `es_evento=no`.

**Lectura acumulada de las dos corridas:** la señal de la primera
corrida se sostiene y se refuerza con datos limpios (sin fallas de
cuota): en el borde "año no escrito", Jev es más fiel al criterio
explícito que la propia definición le exige a Gemini. Además, esta
corrida encontró un caso real de `es_evento` mal clasificado por Gemini
que **sí importa para producción** más allá de la pregunta Jev-sí/no.
Sigue sin alcanzar para decidir adoptar Jev — 11 casos a mano, no
captions reales — pero ya no es ruido: es la segunda corrida seguida
donde Jev es igual o más consistente que Gemini en el mismo tipo de
borde. Antes de un tercer paso (dataset con captions reales, o
adoptar Jev como segunda opinión en algún punto del pipeline) conviene
primero corregir el hallazgo de `mixto_agradecimiento_y_proximo` en el
prompt de Gemini, porque afecta a producción hoy, con o sin Jev de por
medio.

### Tercera corrida: muestra a 29 casos + prueba contra pendientes reales (22/09)

Con el prompt ya corregido, `CASOS` ampliado de 11 a 29 (más variedad de
técnicas, bordes de dominio, texto informal, datos críticos ausentes) y
un modo nuevo `--pendientes` que corre Jev contra eventos reales de la
Sheet. Sin fallas de cuota otra vez: 29/29 respondieron de los dos
lados.

**El fix del prompt funcionó:** `mixto_agradecimiento_y_proximo` ahora
da `si/media` en Gemini, coincidiendo con Jev — el caso que antes se
perdía entero ya se clasifica bien.

**El patrón "año no escrito" resultó ser inconsistencia, no una regla
rota siempre:** en esta corrida Gemini acertó `media` en 2 de 3 casos
de ese borde (`virtual_sin_anio`, `festival_multidia_sin_anio`) y
falló en el tercero (`diagnostico_evento`, otra vez `alta`). Sumado a
las corridas anteriores (0/3 y 0/2), el panorama real es que Gemini
aplica esta regla de forma no determinística, no que nunca la aplique
— matiza la lectura de las corridas 1 y 2.

**Hallazgo nuevo, y es una señal EN CONTRA de Jev:** en 3 casos sin
nombre de evento claro o sin modalidad explícita
(`nombre_vago_fecha_clara`, `virtual_lugar_generico_baja`,
`domain_permacultura_adyacente`), Jev respondió `es_evento=no` con
más convicción, mientras Gemini seguía diciendo `si` con confianza
`baja`. `PATRONES.md` pide exactamente lo contrario para este dominio
("blocklist, no allowlist, cuando no hay revisión humana después"): si
Jev descarta más fácil ante señal débil, es más probable que pierda
eventos reales en silencio, no menos.

**Bordes de dominio, sin ganador:** `domain_borderline_arquitectura_
sustentable` y `domain_permacultura_adyacente` prueban qué tan ancho
lee cada modelo "bioconstrucción". No hay una respuesta correcta
definida en `SYSTEM_PROMPT` hoy — si se quiere seguir esta línea habría
que definirla primero, igual que se hizo con `confianza` el 22/09.

**La prueba más importante — eventos reales frenados hoy:** `--pendientes
20` encontró solo 4 eventos en `pendiente_confirmacion` con
`confianza=baja` (cola chica, consistente con la meta de <10
pendientes por corrida). **Jev no subiría ninguno: 0/4.** Peor para la
hipótesis de adoptar Jev — en 3 de los 4, Jev directamente respondió
`es_evento=no`, más conservador que Gemini (que los mantiene como
evento, solo que con confianza baja). Contra los casos reales que hoy
dependen de revisión manual, Jev no ofrece ninguna ventaja.

**Conclusión, revisando las tres corridas juntas:** la señal optimista
de la corrida 2 (muestra chica y limpia) no se sostiene al ampliar la
muestra ni al probar contra datos reales. Con evidencia acumulada de
29 casos sintéticos + los 4 casos reales existentes, no hay caso para
adoptar Jev en el pipeline de producción por ahora: en el mejor de los
casos es comparable a Gemini, y en el peor (señal débil, sin revisión
humana después) es más propenso a descartar eventos reales, que es
justo el riesgo que este proyecto más quiere evitar. El resultado de
valor real de todo este ejercicio fue el bug de `SYSTEM_PROMPT`
(`mixto_agradecimiento_y_proximo`, ya corregido) — no Jev en sí. Se
frena la evaluación de Jev acá salvo que aparezca una razón nueva y
concreta para retomarla (por ejemplo, extracción de campos en vez de
solo clasificación, que Jev no soporta hoy).

## Reactivación de curar-fuentes.yml (25/09)

Cron reactivado, dos semanas después de apagarlo por el incidente del
12/09 (`descubrir_candidatos()` infló `cuentas_seguidas` de 137 a
3627 en dos corridas — ver esa entrada más arriba). En esas dos
semanas `cuentas_seguidas` se mantuvo estable en 137, confirmando que
el apagado realmente frenó el problema y no era otra cosa.

Antes de reactivar, se subió `MAX_ALTAS_POR_CORRIDA` de 15 a 25 —
decisión del mantenedor: quería que el descubrimiento avance más
rápido que 15 cuentas por corrida, pero sin volver a la falta de tope
que causó el incidente. `MIN_SUGERENCIAS_PARA_AGREGAR` se dejó en 3
(el piso que salió del fix post-incidente) a propósito: es el filtro
de *calidad* temática, tocarlo era el riesgo real la vez pasada; el
tope es solo el techo de *volumen*, y ahí hay margen para ir más
rápido sin repetir el problema — con 25 el peor caso semanal sigue
siendo chico y revisable a ojo en el diff del commit automático de
`config.json`.

De paso, corregido un desajuste menor de documentación: `CLAUDE.md`
todavía decía `MIN_SUGERENCIAS_PARA_AGREGAR=2` (el valor pre-incidente,
nunca actualizado tras el fix del 12/09 que lo subió a 3).

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
