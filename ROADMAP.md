# Roadmap / historial de hayminga.org

Reconstruido a partir de `git log` — sirve para que cualquiera (Germán,
Claude, Codex) entienda de un vistazo qué existe, por qué, y qué está en
un estado temporal/no definitivo. El detalle línea por línea siempre está
en los commits (`git log`); esto es el resumen narrativo.

## 🚧 En curso: pipeline nuevo basado 100% en HikerAPI

`import/src/hiker_pipeline.py` — reemplazo del pipeline viejo (Google
Images/SerpAPI/Serper), todavía **sin activar en producción** (corre
solo desde el workflow manual `[TEST] Pipeline nuevo con HikerAPI`, no
desde el cron diario). Diferencias clave:

- Descubre por **hashtag** (`config.json` → `hashtags`) en vez de
  búsquedas de texto en Google Images — una llamada trae hasta 50 posts
  recientes, cada uno con imagen completa, caption entero, fecha real de
  publicación y ubicación (lat/lng si el que publicó la etiquetó).
- Extracción **texto primero** (más rápido/liviano); solo pide la imagen
  si el texto solo no alcanza para nombre/fecha.
- Sin filtro de calidad por bytes, sin filtro de links ambiguos, sin
  `source_matches_event()` — esos existían para compensar problemas
  específicos de Google Images que HikerAPI no tiene (el link y la
  imagen siempre vienen del mismo post).
- Sin cola de reintentos persistente (`Candidatos`/`CandidateStore`): si
  falla un post puntual, se loguea y se sigue. "No pasa nada si falla un
  día."
- Dedup: por link exacto (antes de gastar una llamada a la IA) y por
  nombre+fecha+provincia (`append_events`, agarra reposteos con link
  distinto del mismo evento).
- **Confianza alta → se publica solo. Media/baja → `pendiente_confirmacion`**
  (ya no todo pasa por revisión manual, a diferencia del resto del
  pipeline viejo mientras `REVISION_MANUAL=true`).
- Mail de error: por ahora se apoya en la notificación nativa de GitHub
  Actions cuando falla el workflow (revisar que esté activada en
  Settings → Notifications de la cuenta). No hay mailer propio todavía.

Pendiente antes de reemplazar `import-eventos.yml` (el cron real): correr
el workflow de prueba con datos reales, revisar calidad de los eventos
que entra, y decidir si se retira `main.py`/`scraper.py` viejos del todo
o quedan como referencia.

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
