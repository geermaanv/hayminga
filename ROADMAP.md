# Roadmap / historial de hayminga.org

Reconstruido a partir de `git log` — sirve para que cualquiera (Germán,
Claude, Codex) entienda de un vistazo qué existe, por qué, y qué está en
un estado temporal/no definitivo. El detalle línea por línea siempre está
en los commits (`git log`); esto es el resumen narrativo.

## ✅ Fix urgente: un fallo de red tiraba todo el trabajo del día (ago 2026)

Las dos corridas del 10/08 fallaron con el mismo `SSLEOFError` (hiccup
de red transitorio) justo en `cargar_cuentas_ids()`, al arrancar la
sección de cuentas seguidas — **después** de terminar los 33 hashtags.
Como no estaba protegido con try/except, el script moría entero ahí y
nunca llegaba a `append_events()`: se perdían todos los eventos ya
encontrados por hashtag en esa corrida, no solo lo de cuentas. Se
envolvió toda la sección de cuentas seguidas en un try/except — un
fallo ahí ahora se loguea y sigue, sin perder lo ya encontrado.

## ✅ Ajustes de filtrado (ago 2026)

- **Umbral de antigüedad de posteo bajado de 270 a 180 días**: caso real
  encontrado revisando `?pendientes` — un post de 252 días (36 semanas,
  visible en el primer comentario) anunciaba un "curso online" sin
  fecha de inicio extraída. Sobrevivió los dos filtros de fecha: el de
  "evento ya pasado" no tenía nada para comparar (sin `fecha_inicio`),
  y el de antigüedad del posteo todavía no llegaba a los 270 días.
- Sumadas a `cuentas_excluidas`: `academia_echeverria`, `ceramicakecheu`.

## ✅ Reintentos en llamadas a Sheets que fallaban seguido (ago 2026)

El `SSLEOFError` intermitente pegaba siempre en el mismo lugar
(`cargar_cuentas_ids()`, justo al arrancar la sección de cuentas
seguidas) — 2 de las últimas 3 corridas reales. El fix de guardado
incremental evita que tire todo el run a la basura, pero seguía
bloqueando esa sección entera cada vez. Se agregó `_con_reintentos()`
(3 intentos, 2s de espera) aplicado a esa llamada y a `_sheet_existe()`
— son fallos de red transitorios, no de datos, así que reintentar es lo
correcto en vez de solo loguear y perder la sección.

## ✅ Fix crítico: guardado incremental, no todo al final (ago 2026)

Un run real (14/08) quedó **cancelado por el timeout de 45min** del
workflow, atascado en la sección de cuentas seguidas por un día
particularmente malo de red (timeouts de HikerAPI, 504/503 de Gemini,
más el volumen extra de `recent`). Como `append_events()` se llamaba
una sola vez al final de `run()`, cuando GitHub mató el proceso **se
perdieron los 45 minutos completos de trabajo** — ni un evento se
guardó. Es peor que el `SSLEOFError` de antes (ese se podía atrapar con
try/except; un kill externo por timeout no se puede atrapar en Python
de ninguna forma).

Fix: ahora se llama a `append_events()` **después de cada hashtag y
cada cuenta**, no al final. Si el proceso muere a mitad de camino, se
pierde como mucho lo de la fuente que estaba procesando en ese momento,
no todo el run. `FuentesStats`/`CuentasIds` siguen guardándose solo al
final (menor severidad si se pierden — es solo recalcular en la
próxima corrida, no perder eventos reales).

## ✅ Descubrimiento de posts realmente recientes por hashtag (ago 2026)

`hashtag/medias/top` mezcla popularidad histórica con lo nuevo — la
queja recurrente de "por qué no aparecen eventos nuevos" tenía una
causa de fondo real. `v1/hashtag/medias/recent` (que se había probado
antes) siempre devuelve vacío, pero **`v2/hashtag/medias/recent` sí
funciona** — confirmado con datos reales: 27 posts de `#bioconstruccion`,
todos de los últimos 1-3 días. Estructura de respuesta distinta (anidada
en `sections`), se agregó `fetch_hashtag_posts_recent()` +
`_item_v2_a_post()` como parser aparte. Ahora cada hashtag se consulta
por las dos vías (recent primero, top como respaldo) — no reemplaza a
`top`, lo complementa.

De paso, fix de un bug de eficiencia (no de datos) encontrado al revisar
esto: el chequeo temprano por shortcode en `procesar_post()` comparaba
un shortcode pelado contra una lista de links completos — nunca hacía
match, así que no ahorraba la llamada a la IA que debía. Se agregan los
shortcodes al set de links conocidos.

Sumados 2 hashtags más de la revisión de `Hashtags_Post` (ahora con 35
eventos activos de muestra, antes 10): `aulaabierta`, `arteytierra`.
Se encontró también un cluster de 6 hashtags de cultivo de hongos
(`#fungi`, `#hongos`, `#micelio`, etc.) de un solo evento que mezcló
bioconstrucción con micología — no se sumaron, traerían contenido de
otro tema.

## ✅ Extracción de texto narrativo + contador en el header (ago 2026)

- **Prompt mejorado para texto narrativo largo**: caso real por mail —
  un evento con fecha y teléfono presentes en el cuerpo del mail
  (estilo conversacional, no flyer estructurado) salió con confianza
  baja e inactivo porque el modelo no los detectó "enterrados" en un
  párrafo largo. Se agregó instrucción explícita al `SYSTEM_PROMPT` de
  leer el texto completo buscando estos datos en cualquier parte, y se
  agregó una **fecha de referencia** (fecha de recepción del mail/
  descubrimiento) al prompt del path de `processor.py` — antes solo
  `hiker_pipeline.py` se la daba al modelo, así que emails/scraping sin
  año explícito en el texto no tenían forma de anclar "22 de agosto" a
  un año concreto.
- **Contador pendientes/total en el header** (`index.html`): texto
  chico tipo "2/80" al lado del logo, referencia rápida para revisar
  si hay algo en `?pendientes` sin tener que entrar — no es información
  sensible, se calcula en el cliente con los datos que ya se cargan.

## ✅ Fix: el resumen semanal por Telegram fallaba en producción (ago 2026)

El primer envío real (martes 11/08) falló con `400 Bad Request` —
`parse_mode: Markdown` de Telegram necesita `*`/`_` en pares para
negrita/itálica, y un link real de Instagram tenía un solo `_` suelto
(`Dbq_cDrsRhl`), rompiendo el parseo de todo el mensaje. Como los
títulos y links son texto arbitrario que no controlamos, se sacó
`parse_mode` del todo — el mensaje va en texto plano (los links siguen
siendo clickeables igual, Telegram los detecta solo). El mail al
Directorio (Apps Script, sin este problema) llegó bien esa misma vez.

## ✅ Resumen semanal por Telegram (ago 2026)

`enviar-resumen.yml` (martes 09:00 hora Argentina) corre
`enviar_resumen_telegram.py`: arma un resumen de los próximos eventos
activos (hasta 60 días adelante, tope 15 eventos) y lo manda al bot de
Telegram `@geermaanv_bot`. De ahí el usuario lo reenvía a mano por
WhatsApp — todavía no hay Comunidad de WhatsApp armada ni API de
WhatsApp Business (decisión explícita: con 2 suscriptores no vale la
pena la fricción de armar la Comunidad todavía; se arma cuando el
volumen lo justifique).

Formato del mensaje: `📅 fecha | Provincia - Tipo — *Título*` + link al
posteo original (no a hayminga.org — el sitio no tiene páginas
individuales por evento, así que el link de origen es lo único que
lleva directo al flyer). El link a `https://hayminga.org` va **primero**
en el mensaje a propósito: WhatsApp arma la vista previa grande con el
primer link que encuentra en todo el texto — si no, agarra el link de
Instagram del primer evento y la tarjeta tapa el resto de la lista
(confirmado con una prueba real).

Todo mensaje saliente a usuarios finales tiene que incluir el
recordatorio de cómo aportar eventos (compartir captura/link por WA,
mandar por mail, o taggear `#hayminga` si publican ellos en Instagram)
— pedido explícito del usuario, guardado también en memoria para
sesiones futuras.
- **Mismo resumen, por mail al Directorio**: `Code.gs` ahora tiene
  `enviarResumenSemanalDirectorio()` (trigger semanal, martes 09:00,
  instalado corriendo `configurarTriggerResumenSemanal()` una vez desde
  el editor de Apps Script) — manda el mismo contenido que el mensaje
  de Telegram a cada email del Directorio. No hizo falta pedir opt-in
  retroactivo: el formulario de alta del Directorio ya tiene desde
  siempre un checkbox de consentimiento fijo ("Autorizo a que me manden
  novedades y avisos de hayminga"), así que todos los que ya están
  anotados ya lo autorizaron.

## ✅ Pipeline de producción: HikerAPI (reemplazó a Google Images)

`import-eventos.yml` (el cron diario, 08:00 hora Argentina) corre ahora
`import/src/hiker_pipeline.py` en vez de `main.py`. Diferencias clave:

- Descubre por **hashtag** (`config.json` → `hashtags`, 24 validados
  contra la API real) en vez de búsquedas de texto en Google Images —
  una llamada trae hasta 30 posts (usa `hashtag/medias/top`; el endpoint
  `recent` está más restringido y devuelve siempre vacío), cada uno con
  imagen completa, caption entero, fecha real de publicación y ubicación
  (lat/lng si el que publicó la etiquetó).
- Extracción: primera pasada solo con texto (filtra gratis lo que no es
  evento); si sí es evento, siempre se manda también la imagen (ya
  recibe el caption como contexto, casi siempre saca más datos que el
  texto solo).
- Fallback a Claude tanto en el paso de texto como en el de imagen si
  Gemini se queda sin cuota (con techo de `MAX_CLAUDE_CALLS_PER_RUN` por
  corrida — Claude es pago).
- **Facturación activada en el proyecto de Gemini (`haymingaorg`)**
  (ago 2026): el free tier limitaba a ~15 requests/minuto, lo que forzaba
  un pacing de 4.5s entre llamadas y hacía que una corrida de 24 hashtags
  tardara ~37 minutos. Con billing habilitado el límite sube muchísimo,
  así que el intervalo bajó a 0.5s vía la env var
  `GEMINI_MIN_INTERVAL_SECONDS` (configurable sin tocar código, default
  4.5s si algún día corre sin billing). Costo esperado: centavos por mes
  con el volumen actual (Gemini Flash es muy barato por request).
- **Fix de cuelgue indefinido** (ago 2026): un run de prueba con el
  pacing más rápido procesó 2 hashtags en 30s y después quedó **colgado
  44 minutos sin ningún log**, hasta que lo canceló el timeout de 45min
  del workflow. Causa: `genai.Client` no tenía timeout HTTP configurado
  — si una sola llamada a Gemini se cuelga (red/servidor), el proceso
  espera indefinidamente en vez de fallar y seguir. Se agregó
  `http_options=types.HttpOptions(timeout=30_000)` (30s). De paso se
  activó `PYTHONUNBUFFERED=1` en el workflow — sin eso, un cuelgue como
  este no deja ningún log (los `print()` quedan en el buffer y se
  pierden si el proceso es cancelado antes de flushearlos).
- **Hashtag propio `#hayminga`** (ago 2026): sumado a `config.json` como
  canal de descubrimiento 100% confiable y controlado por la comunidad
  (no depende de hashtags genéricos que también usa cualquiera). Se
  comunica con un tip en el formulario "Publicá tu evento": "si lo
  compartís en Instagram, taggeá #hayminga y la próxima vez lo
  detectamos automático".
- **Fix: teléfono y email mezclados en `Contacto`**: la IA a veces
  extrae ambos en un solo string ("+54 911 ..., mail@x.com"). Antes,
  con un "@" en cualquier parte del campo se descartaba todo como email
  y no aparecía el botón de WhatsApp aunque el teléfono estuviera ahí.
  Ahora `contactoWhatsAppUrl()` separa por coma/slash y usa el pedazo
  sin "@" para el teléfono.
- **Filtro de antigüedad del posteo**: `hashtag/medias/top` trae los
  posteos con más likes/comentarios históricamente, no los recientes —
  mezcla contenido evergreen viejo (detectado con un caso real: un
  posteo con comentarios de "hace 122 semanas") con eventos nuevos.
  Ahora se descarta directo, antes de gastar una llamada a la IA,
  cualquier post publicado hace más de 270 días (`taken_at_ts` de
  HikerAPI) — casi ningún evento real se anuncia con tanta
  anticipación.
- **Columna `Hashtags_Post`**: se guardan todos los hashtags del caption
  de cada post descubierto (no solo el que lo trajo) — los posts suelen
  traer muchos más hashtags de los que buscamos nosotros. Por ahora solo
  se acumula el dato; falta armar el proceso de revisión periódica para
  ver cuáles conviene sumar a `config.json`.
- Primera pasada de revisión (con solo 10 eventos activos como muestra,
  chica pero un comienzo): se sumaron `construccionentierra`,
  `construccioncontierra` y `naturalbuilding` — temáticamente
  relevantes y no específicos de un evento puntual (a diferencia de
  nombres propios/lugares que también aparecieron, esos se descartaron).
- **Fix: media_type de imagen detectado por contenido, no por nombre de
  archivo**: `_download_image` siempre guarda como `.jpg` sin importar
  el formato real — Instagram sirve varios thumbnails en webp. Cuando
  Gemini fallaba y caía a Claude, éste rechazaba la llamada porque el
  media_type declarado (jpeg) no coincidía con los bytes reales
  (confirmado con un error real de un run). Ahora se detecta el formato
  mirando los magic bytes de la imagen.
- **Hashtags con tilde**: `/v1/search/hashtags` reveló que Instagram
  trata `bioconstrucción` (con tilde) y `bioconstruccion` (sin tilde)
  como hashtags completamente distintos, con pools de posts separados
  — el primero con **58 mil posts propios** que no estábamos mirando.
  Se sumaron las variantes con tilde de volumen real (58k, 43k, 11k,
  5.7k, etc. — se descartaron las de 1-2 posts, típicos typos). También
  se probaron `/v1/hashtag/medias/clips` (feed separado de Reels) y
  `/v1/search/users` (buscar cuentas por palabra clave) como
  alternativas a `top`/`recent` — quedan para una vuelta futura si hace
  falta más cobertura; la idea con más potencial ahí es trackear
  directamente las cuentas de organizadores ya conocidos en vez de
  depender solo de hashtags.
- **Filtro de idioma**: hashtags en español también traen resultados de
  cuentas que postean en inglés (comunidad internacional de
  bioconstrucción/permacultura) — hayminga es en español, no tiene
  sentido publicarlos. Se sumó `idioma` al schema de extracción
  (`es`/`en`/`otro`) y se descarta directo si es `en`, mismo criterio
  que el filtro de país (solo descarta con señal positiva, no si vino
  vacío).
- **Blacklist de cuentas** (`config.json` → `cuentas_excluidas`): a
  veces país e idioma no alcanzan (ej. una cuenta de España que postea
  en español). Se agregó una lista de usernames de Instagram a excluir
  directo, antes de gastar cualquier llamada — primer caso: `okambuva`.
- **3 corridas por día** en vez de 1 (08:00, 14:00, 20:00 hora
  Argentina) — el dedup por shortcode descarta lo ya visto antes de
  gastar IA, así que el costo extra es mínimo (~$0.02/corrida en
  llamadas de descubrimiento a HikerAPI, más solo lo que haga falta de
  Gemini/Claude para lo genuinamente nuevo).
- **Filtro de idioma por código, no por la IA**: confirmado con casos
  reales (`4-day cob course`, `Bamboo Anatomy Workshop`) que la IA no
  marca `pais`/`idioma` de forma confiable cuando el flyer no lo dice
  explícito — quedaban con esos campos vacíos y pasaban el filtro,
  obligando a descartarlos a mano. Se agregó `_parece_ingles()`: cuenta
  palabras comunes en español vs inglés directo sobre el caption real
  del post, **antes** de gastar la llamada a la IA — más confiable y
  ahorra costo. El filtro de `idioma` que devuelve la IA se mantiene
  como capa adicional, no se sacó.
- **Descubrimiento por cuenta seguida** (`config.json` →
  `cuentas_seguidas`), además de hashtags: los hashtags genéricos
  compiten por popularidad global (`top`), y la comunidad de
  bioconstrucción argentina termina eclipsada por países con más
  volumen online (España, México). `fetch_user_posts()` usa
  `/v1/user/medias` — el timeline real y cronológico de una cuenta
  puntual, sin ese sesgo. Sembrado con `redprotierraargentina` y ~26
  cuentas de organizaciones/practicantes argentinos conocidos (filtradas
  a mano de una lista de seguidores mucho más grande — se descartaron
  cuentas personales sin actividad de bioconstrucción visible). Mismos
  filtros que los hashtags (dedup, antigüedad, idioma, país, blacklist).
  No reemplaza los hashtags, es una fuente adicional.
- **Curación de cuentas inactivas**: no se dan de baja solas — el
  pipeline solo marca en el log cuando una cuenta seguida no publicó en
  más de 180 días, mismo criterio que la curación de hashtags (juntar
  el dato, decidir a mano con más contexto).
- **Auto-curación de fuentes** (ago 2026): en vez de revisar hashtags y
  cuentas a mano, `hiker_pipeline.py` ahora registra en una hoja nueva
  (`FuentesStats`: Tipo, Nombre, IntentosSinHit, UltimoHit) si cada
  hashtag/cuenta produjo al menos 1 evento en la corrida — el contador
  se resetea a 0 con cualquier hit, suma 1 si no hubo nada. Un workflow
  nuevo (`curar-fuentes.yml`, diario 09:00 Arg — temporal, hasta tener
  más volumen; después pasa a semanal) corre
  `curar_fuentes.py`: cualquier fuente con **50+ intentos seguidos sin
  producir nada** se saca sola de `config.json`, con commit y push
  automático (permissions: contents: write). Solo automatiza la
  **baja** — las altas de candidatos nuevos siguen siendo manuales
  porque necesitan criterio de calidad, no solo un número (ver el
  ejemplo de hashtags descartados por ser nombres propios/lugares).
- **Más cuentas seguidas**: sumadas `maxipermacultura`,
  `permacultura.naturalia`, `arteytierrabioconstruccion`,
  `tierraarquitectura`, `tribudelatierra`, `vuelta_tierra`,
  `ecovilla_gaia` — referentes argentinos identificados por el usuario
  (no solo seguidores genéricos de una cuenta, sino divulgadores y
  estudios con alcance real). Se sumaron 39 más vía
  `v2/user/suggested/profiles` (cuentas similares a De Barro según el
  propio algoritmo de Instagram — señal mucho mejor que revisar lista
  de seguidores: ~30 de 39 eran relevantes, contra ~15 de 400 de la
  lista de seguidores cruda). Total: 74 cuentas.
- **Descubrimiento automático de candidatas, con alta automática**
  (`descubrir_candidatos()` en `curar_fuentes.py`): consulta "sugeridas"
  para cada cuenta seguida y **agrega directo a `config.json`** las que
  no estén ya — a diferencia de los hashtags, esto sí quedó full-auto
  (decisión explícita del usuario: "prefiero arriesgarme" — el riesgo
  es bajo porque la baja automática de 50 intentos sin hit se encarga
  de sacar sola cualquier alta mala). Para no repetir la misma consulta
  de "sugeridas" en cada corrida, se registra en una hoja nueva
  (`CuentasConsultadas`: Username, FechaConsulta) cuándo se consultó
  cada cuenta — solo se vuelve a consultar después de 30 días.
- **Filtro de eventos ya pasados**: el filtro de antigüedad existente
  mira cuándo se publicó el POST, no la fecha del EVENTO — un posteo
  reciente puede anunciar algo que ya pasó (confirmado con casos
  reales: "Bioferia Festival" con fecha abril 2026, descubierto en
  agosto). Ahora se descarta directo si `fecha_fin`/`fecha_inicio` ya
  quedó en el pasado — a diferencia de país/idioma, acá no hay
  ambigüedad posible.
- **Gaps conocidos, sin resolver todavía**: (1) país sigue quedando
  vacío para algunos posts de fuera de Argentina (México confirmado en
  un caso real) — el filtro de idioma no ayuda porque el post estaba en
  español; (2) el mismo curso/evento real promocionado con varios posts
  de Instagram distintos (mismo organizador, texto/fecha ligeramente
  distinto en cada uno) genera duplicados que el dedup por
  nombre+fecha+provincia no siempre agarra — mismo patrón que el caso
  DeBarro de la Etapa 9.5, pendiente de una solución más robusta
  (fuzzy matching o comparar por organizador).
- **Control de costo de HikerAPI** (ago 2026): llegado a $4 gastados en
  pocos días, se hizo el cálculo — 3 corridas/día × (33 hashtags + 74
  cuentas × 2 llamadas c/u para resolver el `user_id`) ≈ 543
  llamadas/día ≈ $10/mes, por arriba del presupuesto original de
  $5/mes. Dos cortes: (1) cron bajado de 3x a **2x/día** (08:00 y 20:00
  Arg); (2) **cache de `user_id` por username** (hoja nueva
  `CuentasIds`) — antes se resolvía en cada corrida así ya se conociera
  la cuenta, ahora solo la primera vez. Usado tanto en el pipeline
  diario como en el descubrimiento de candidatas del curador. Costo
  estimado después de los cortes: ~$1.80/mes.
- **Fix urgente: `descubrir_candidatos()` sin filtro de calidad casi
  agrega 900 cuentas de una** — al sacar el umbral de "sugerida por 2+
  cuentas nuestras" (para que fuera full-auto), la primera corrida real
  encontró que `suggested/profiles` de Instagram no es puramente
  temático: devolvió surf en Francia, acroyoga en los Alpes y cientos
  de cuentas sin relación. No llegó a commitearse (falló el push por
  una carrera con otro commit en paralelo, suerte). Se repuso el umbral
  (`MIN_SUGERENCIAS_PARA_AGREGAR = 2`) — sigue siendo full-auto, solo
  con un piso mínimo de señal real antes de agregar.
- Se descartan directo (sin escribir fila) los eventos de otros países —
  los hashtags son globales, no hay forma de filtrar por país en la
  búsqueda misma.
- Sin filtro de calidad por bytes, sin filtro de links ambiguos, sin
  `source_matches_event()` — esos existían para compensar problemas
  específicos de Google Images que HikerAPI no tiene (el link y la
  imagen siempre vienen del mismo post).
- Sin cola de reintentos persistente (`Candidatos`/`CandidateStore`): si
  falla un post puntual, se loguea y se sigue. "No pasa nada si falla un
  día."
- Dedup: por link exacto (antes de gastar una llamada a la IA) y por
  nombre+fecha+provincia (`append_events`, agarra reposteos con link
  distinto del mismo evento). Verificado con dos corridas seguidas: no
  duplica.
- **Confianza alta → se publica solo. Media/baja → `pendiente_confirmacion`**
  (ya no todo pasa por revisión manual, a diferencia de lo que entra por
  mail/formulario mientras `REVISION_MANUAL=true`).
- Mail de error: por ahora se apoya en la notificación nativa de GitHub
  Actions cuando falla el workflow (revisar que esté activada en
  Settings → Notifications de la cuenta). No hay mailer propio todavía.
- La carga por **mail** (`email_intake.py`, tag `HME`) sigue corriendo
  en el mismo workflow, sin cambios — es una capacidad separada que
  HikerAPI no reemplaza.

**`main.py`, `src/scraper.py` (funciones de Google Images/SerpAPI/Serper),
`src/candidates.py` y `seen_hashes.txt`/`seen_links.txt` quedan sin usar**
en producción — no se borraron del repo (por si hace falta volver atrás
o como referencia), pero ya no corren desde ningún workflow.

## ⚠️ Flags temporales activos ahora mismo

- **`REVISION_MANUAL = true`** en `import/src/processor.py` y en
  `import/apps-script/Code.gs`. Mientras esté en `true`, **ningún evento
  se publica solo** — scraping, mail y formulario web quedan todos con
  `Activo=false` / `Estado=pendiente_confirmacion` hasta que se confirman
  a mano en `hayminga.org/?pendientes`. Para volver al comportamiento
  normal (auto-publicación), poner el flag en `false` en los dos
  archivos. Motivo: control de calidad de datos mientras se estabiliza
  el pipeline.
- Antes de tocar `Code.gs`, recordar: **el archivo del repo es un
  espejo**. Los cambios no toman efecto en producción hasta copiarlos al
  proyecto real en script.google.com y hacer una nueva implementación
  (Implementar → Gestionar implementaciones → Nueva versión).
- **`HIKERAPI_KEY`** (opcional): si está seteada (`.env` local o secret de
  GitHub Actions), el pipeline usa HikerAPI para bajar la imagen completa
  del post (sin el recorte cuadrado de `og:image`), el caption entero, y
  la fecha real de publicación del post — todo esto mejora la extracción
  y resuelve años faltantes en la fecha del evento. Si no está seteada,
  cae a los métodos gratuitos de siempre (og:image + SerpAPI/Serper). Es
  pago (~$0.0006/request); con el volumen actual del pipeline el costo
  estimado es de centavos por mes. Falta que Germán se registre en
  hikerapi.com y cargue la key como secret `HIKERAPI_KEY` en GitHub y en
  `.env` local.

## Etapa 1 — Sitio estático solo (pre-unificación)

El sitio (`index.html` + `CNAME`, GitHub Pages) y el pipeline de
scraping (`hayminga-pipeline`, entonces un repo aparte) vivían separados.
El pipeline ya hacía scraping de Instagram vía SerpAPI + extracción con
IA (Claude al principio) y escribía a un Google Sheet que el sitio leía
en vivo por GViz.

## Etapa 2 — Unificación de repos

- `a054fb4` / `ece849f` — se importó `hayminga-pipeline` a este repo,
  bajo `import/`. Un solo repo, un solo lugar para todo.
- `58acfa1` — soporte de `.env` para correr el pipeline en local.

## Etapa 3 — Confiabilidad del pipeline (proveedor de IA, dedup, cuota)

- `206655f` — cambio de Claude-only a **Gemini como primario (gratis)**
  con Claude de respaldo cuando se agota la cuota de Gemini.
- `2700c47` — filtro heurístico de calidad + enriquecimiento con caption
  real del post antes de mandarlo a la IA (menos gasto en imágenes que
  obviamente no son eventos).
- `072a551` — el punto anterior generaba demasiadas llamadas a SerpAPI
  (una por imagen). Se cambió a pedir el caption solo cuando hace falta
  (evento con confianza floja o datos faltantes), no por cada imagen.
- `99e0715` — cola de candidatos persistente (hoja `Candidatos`): cada
  resultado se registra antes de llamar a la IA, así un run de GitHub
  Actions que se corta no pierde el candidato — se reintenta después.
- `b215692` / `aa696ee` — Serper.dev como fallback cuando SerpAPI se
  queda sin cuota.
- `c0c262e` — **fix del bug de link/imagen cruzados**: Google a veces
  asocia el mismo link de Instagram a imágenes de eventos distintos.
  Ahora se descartan los links ambiguos al momento de scrapear, y
  además se verifica que el nombre/fecha/lugar extraído coincida con el
  caption indexado del post antes de publicar — si no coincide, queda
  en revisión (`Estado=revision_fuente`) con el link vacío.

## Etapa 4 — Canales de carga manual

- `ca88b4f` — formulario web estructurado ("+ Evento"), publica directo
  a la hoja `Eventos` sin pasar por IA.
- `f888f7f` — carga por mail: alguien manda un flyer con un tag en el
  asunto, un Apps Script lo detecta y lo encola en `Cola_Manual`, el
  pipeline de Python lo procesa con el mismo extractor de IA que el
  scraping (el cuerpo del mail hace de caption).
- `f5e059d` — el tag de asunto se acortó de `HAYMINGAEVENTO` a `HME`
  (el original era incómodo de escribir a mano).
- `5c4d628` / `2f748ae` — el mail-intake ahora también acepta que
  alguien mande **solo el link** (sin adjuntar el flyer): se baja la
  imagen del post público de Instagram automáticamente vía su etiqueta
  `og:image` (lo mismo que usa WhatsApp para armar la vista previa).
- `323ab0b` y los commits de agosto 2026 sobre WhatsApp — número de
  WhatsApp propio de hayminga para que cualquiera comparta un flyer que
  ve en Instagram sin fricción; se evaluó lista de difusión (tope 256,
  requiere que te tengan guardado) vs. Comunidad de WhatsApp (sin tope,
  no depende de tener el número guardado) — se optó conceptualmente por
  Comunidad para el broadcast del calendario mensual (ver mensajes al
  equipo, no implementado en código todavía).

## Etapa 5 — Directorio de personas

- `1bf3747` — alta pública de personas interesadas en bioconstrucción,
  con filtro por provincia e intereses, y **contacto por doble opt-in**
  (nunca se expone el email/WhatsApp directo — se manda un pedido, si la
  persona acepta recién ahí se comparten los datos a los dos).
- `83c98cf` — ronda de feedback: bug de refresh, WhatsApp opcional en el
  alta, lista fija de provincias, categorías de interés.

## Etapa 6 — Bugs de datos/infra descubiertos y corregidos

- `7f246d1` — Apps Script escribía booleans nativos en vez de texto,
  rompiendo el parseo de GViz (que espera `"true"`/`"false"` como texto).
- `69e168e` — detección de header de GViz poco confiable cuando una
  columna es 100% texto; se fuerza con `&headers=1`.
- `d3bd135` — inyección de fórmulas: cualquier texto que empezara con
  `+`, `=` o `-` se interpretaba como fórmula de Sheets si la celda no
  estaba pre-formateada como texto plano.
- `6c6fe30` — bug de búsqueda de Gmail: `[Evento]` como tag hacía que
  Gmail ignorara los corchetes y buscara la palabra suelta "evento" en
  cualquier lado, colando mail de 2007-2018 sin relación.
- `87a4f5d` (ago 2026) — la columna Latitud/Longitud tenía formato mixto
  (mayoría vacía + algunas filas numéricas), lo que hacía que GViz
  devolviera `null` para esas celdas puntuales y el evento cayera al
  centroide aproximado de la provincia en vez de su ubicación real.
- `cea27f5` (ago 2026) — eventos viejos sin `Id` hacían fallar la
  confirmación en silencio (el fetch usa `no-cors`, no se puede leer el
  error). Se backfillearon ~456 filas sin Id y se agregó validación
  previa en el frontend.

## Etapa 7 — Rediseño de UI (agosto 2026)

Varias rondas de pulido de header/filtros iterando con prototipos
(Claude Artifacts) antes de tocar `index.html`:

- Toggle Eventos/Directorio como nav primaria de color sólido; controles
  de vista (Lista/Mapa, meses) bajados a un tinte suave para no competir
  visualmente con la navegación.
- Filtros unificados en una sola fila con dropdown de "Filtros" para los
  secundarios (Modalidad, Tipo, búsqueda).
- Vista por defecto: Lista (no Mapa), filtrado al mes actual.
- Mapa (`814df3c`): eventos agrupados por mes con Leaflet, pin ahora
  muestra abreviatura de mes ("Oct") en vez del número (se confundía
  con el día).

## Etapa 8 — Analytics y canal de WhatsApp

- `2f57261` — 8 eventos de GA4 para medir el funnel (abrir formularios,
  publicaciones, contacto del directorio, clicks a Instagram, etc.)
- Footer + header con link de WhatsApp para recibir novedades
  ("Recibí novedades por WA"), separado del canal de compartir flyers.

## Etapa 9.5 — Curación de duplicados y ajustes a la cola de revisión (ago 2026)

- **Botón "Descartar"** en `?pendientes`: antes solo se podía Aprobar o
  Saltar; ahora también se puede sacar un evento de circulación sin
  borrar la fila (`Activo=false` / `Estado=descartado`, reversible a
  mano en la Sheet). Nueva acción `descartar_evento` en `Code.gs`.
- **Dedup por shortcode de Instagram** (`sheets.py`,
  `instagram_shortcode()`): el mismo posteo puede compartirse como
  `/p/`, `/reel/` o `/reels/` — comparar el link exacto no alcanza.
  Detectado con un caso real: "Escuela de verano - DeBarro" (cargado a
  mano) y "Formación Práctica en Arquitectura Biológica..." (descubierto
  por HikerAPI) eran el mismo posteo con títulos distintos — ninguno de
  los dos dedups existentes lo agarró. Ahora `append_events` compara
  primero por shortcode (duplicado cierto → se descarta) y, si eso no
  matchea pero sí matchea nombre+fecha+provincia (duplicado ambiguo:
  mismo evento, posteo de origen distinto), **inserta igual pero a
  revisión** (`pendiente_confirmacion`) con una nota automática en la
  Descripción señalando el posible duplicado y el Id del existente, para
  que se fusionen los datos a mano en vez de perderlos o pisarlos en
  silencio. `hiker_pipeline.py` también compara por shortcode antes de
  gastar la primera llamada a la IA.
- **Fix de UI**: el mensaje "¡No quedan más eventos pendientes!" vivía
  dentro del `<form>` que se oculta cuando la cola está vacía, así que
  nunca se veía — se movió afuera del form.
- **Simplificación de `Estado`** (ago 2026): había 5 valores posibles,
  dos de ellos (`pendiente` y `pendiente_confirmacion`) sonaban casi
  igual pero significaban cosas distintas — el primero era el fallback
  genérico para eventos con datos incompletos, y no entraba a la cola de
  `?pendientes` (quedaban invisibles). Se unificaron en uno solo:
  **`pendiente_confirmacion`** — ahora cualquier evento inactivo entra a
  revisión, sin excepción. Se sacó **`revision_fuente`** (específico del
  pipeline viejo de Google Images, que ahora usa la misma etiqueta). El
  modelo final:
  - `Activo` (true/false): si se muestra en el sitio — el on/off rápido.
  - `Estado`: complementario, para curación — `confirmado`,
    `pendiente_confirmacion` (candidato a revisar en `?pendientes`),
    `descartado` (no se borra la fila, solo se saca de circulación —
    así el dedup por shortcode lo sigue reconociendo si el pipeline lo
    vuelve a encontrar y no lo reinserta).

## Etapa 9 — Paso de revisión manual (agosto 2026, EN CURSO)

Ver el flag `REVISION_MANUAL` arriba. Se agregó:

- `confirmar_evento` en `Code.gs`: actualiza una fila existente por Id y
  la activa (reusa el mismo formulario "Publicá tu evento", pre-cargado).
- `hayminga.org/?pendientes`: abre la cola de eventos pendientes uno por
  uno, con botones "Aprobar y ver el próximo" y "Saltar".
- `notificarPendientes()` + `configurarTriggerNotificaciones()`: mail a
  `germanv@gmail.com` cuando hay pendientes nuevos.
- Campos de Latitud/Longitud opcionales agregados al formulario de
  evento para poder ubicar con precisión al revisar.

## Ideas evaluadas y descartadas (por ahora)

- **Botón "Extraer datos con IA" al subir una imagen nueva en el
  formulario de revisión**: descartado por ahora — requeriría exponer
  lógica de extracción vía un endpoint nuevo en Apps Script (para no
  filtrar la API key de Gemini al cliente). Ver la sección siguiente
  para una versión más chica de esta idea, pensada solo para
  aprendizaje/prueba, no para producción.
