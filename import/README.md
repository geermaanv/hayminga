# hayminga.org — Pipeline de importación automática

Busca flyers de eventos de bioconstrucción en Google Images (vía SerpAPI, filtrando Instagram),
extrae los datos con Gemini Vision (gratis, con Claude como fallback) y los escribe en la
misma Google Sheet que lee [hayminga.org](../index.html) directamente (sin Glide de por medio).

## Arquitectura

```
Google Images (SerpAPI/Serper, site:instagram.com + queries de config.json)
        ↓
  scraper.py — descarga imágenes nuevas, filtra avatares/íconos por
               peso+dimensión antes de gastar cuota de IA, dedup por hash
               y por link; conserva el texto indexado junto a la imagen
        ↓
  candidates.py — registra cada resultado en la hoja "Candidatos" ANTES
                  de llamar a la IA; conserva estado, intentos y errores
                  para poder reanudarlo en otra corrida
        ↓
  processor.py — Gemini Vision (imagen + caption) extrae nombre, fecha,
                 lugar, tipo, contacto, etc.
                 (si falla o se queda sin cuota, reintenta esa imagen con Claude)
        ↓
  sheets.py — escribe en la Google Sheet "Eventos"
        ↓
  hayminga.org lee esa Sheet vía GViz JSON al cargar la página

En paralelo, carga manual por mail:
  organizador manda un mail con el flyer adjunto
        ↓
  Apps Script (apps-script/Code.gs) lo guarda en Drive + anota en "Cola_Manual"
        ↓
  email_intake.py (paso 4/4 de main.py) lo procesa con el MISMO extractor
  de arriba — el cuerpo del mail hace el papel del caption
        ↓
  sheets.py — valida fecha/país igual que el scraping; solo los eventos
               vigentes de Argentina quedan Activo=true
```

Vive dentro del repo `hayminga` (junto al frontend) y corre todos los días a las
8:00 AM (Argentina) vía GitHub Actions — ver `.github/workflows/import-eventos.yml`
en la raíz del repo.

---

## Setup (una sola vez)

### 1. Google Sheets

1. Creá un Google Sheet nuevo
2. Renombrá la primera hoja como `Eventos`
3. Copiá el ID del Sheet (está en la URL: `spreadsheets/d/ESTE_ES_EL_ID/edit`)

### 2. Google Service Account

1. Entrá a [Google Cloud Console](https://console.cloud.google.com)
2. Creá un proyecto (o usá uno existente)
3. Activá la API: **Google Sheets API**
4. Creá una **Service Account** → descargá el JSON
5. Compartí el Google Sheet con el email de la service account (permiso Editor)

### 3. SerpAPI

1. Creá una cuenta en [serpapi.com](https://serpapi.com) y copiá tu API key del dashboard.
2. Como respaldo, creá una cuenta en [serper.dev](https://serper.dev/) y copiá
   su API key. El importador usa Serper automáticamente si SerpAPI no está
   configurado, devuelve un error o se queda sin búsquedas. Una respuesta válida
   sin resultados no consume el respaldo.

### 4. Gemini API (gratis, proveedor principal)

1. Entrá a [aistudio.google.com/apikey](https://aistudio.google.com/apikey) con una cuenta de Google.
2. Creá una API key nueva — usá un proyecto de Google Cloud dedicado a hayminga,
   no reutilices una key de otro proyecto (así el free tier y los límites de
   cuota no se comparten con nada más).

### 5. Claude API (fallback, opcional pero recomendado)

1. [console.anthropic.com](https://console.anthropic.com) → API Keys → creá una key
   y cargale algo de crédito. Se usa solo cuando Gemini falla o se queda sin
   cuota gratuita, así que el consumo esperado es bajo.

### 6. Secrets en GitHub

En el repo `hayminga` → Settings → Secrets and variables → Actions → New repository secret.

| Secret | Valor |
|--------|-------|
| `GEMINI_API_KEY` | Tu API key de Gemini (gratis, aistudio.google.com/apikey) |
| `ANTHROPIC_API_KEY` | Tu API key de Claude (fallback) |
| `SERPAPI_KEY` | Tu API key de SerpAPI |
| `SERPER_API_KEY` | Tu API key de Serper (fallback de búsqueda) |
| `GOOGLE_SPREADSHEET_ID` | ID del Google Sheet |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Contenido completo del JSON de la service account |

---

## Correr localmente (desde VSCode o terminal)

```bash
cd import
pip install -r requirements.txt

# Copiá .env.example a .env y completá tus valores reales (nunca se commitea)
cp .env.example .env

python main.py
```

`main.py` carga `.env` automáticamente con `python-dotenv`. En GitHub Actions no
hace falta `.env` — las variables vienen de los Secrets del repo.

## Correr manualmente en GitHub (sin tocar el cron)

```bash
gh workflow run import-eventos.yml -R geermaanv/hayminga
gh run watch -R geermaanv/hayminga
```

## Estructura del Sheet (hoja "Eventos")

Columnas exactas en `src/sheets.py`: `Activo, Nombre, Dirección, Periodo, Fecha_Inicio,
Fecha_Fin, Es_Virtual, Provincia, Descripción, Organizador, Link_Promocion, Tipo_Evento,
img, procesado, Id, Contacto, Estado, Pais, Confianza, Fuente, Fecha_Descubrimiento`.
Las columnas nuevas se agregan al final a propósito para no correr de letra
las columnas existentes; la deduplicación reconstruye su clave leyendo
nombre, fecha y provincia de las filas ya guardadas.

- `Id`: identificador corto único por evento, generado al insertarse.
- `Contacto`: email o WhatsApp del organizador, si el extractor lo encontró
  en la imagen o el caption/cuerpo del mail.
- `Estado`: `confirmado` para eventos activos y `pendiente` para eventos
  pasados, fuera de Argentina, con fecha inválida o sin fecha determinable.
- `Confianza`: `alta`, `media` o `baja`, según la extracción.
- `Fuente`: origen del evento (`google_images`, `email` o `formulario_web`).
- `Fecha_Descubrimiento`: momento en que el pipeline recibió el candidato.

Gemini extrae país, provincia y fechas, pero `processor.py` normaliza esos
campos y calcula `activo` de manera determinista. Un evento queda activo si
es de Argentina y todavía no terminó; esto incluye eventos que empiezan hoy
o que ya comenzaron pero tienen una fecha de finalización futura. El resto
entra con `Activo=false`, visible en la Sheet pero oculto en el sitio.

## Cola persistente (hoja "Candidatos")

`candidates.py` crea automáticamente una hoja `Candidatos` en el mismo
Google Sheet. Cada imagen encontrada por Google se registra ahí antes de
llamar a Gemini, de modo que una caída del runner, de Sheets o de un
proveedor no haga desaparecer el descubrimiento.

Columnas: `Id, Descubierto, Fuente, Consulta, URL_Publicacion, URL_Imagen,
Hash, Estado, Intentos, Confianza, Motivo, Ultimo_Error, Nombre_Extraido,
Fecha_Extraida, Provincia_Extraida, Evento_Id, Caption`.

Estados:

- `nuevo`: registrado, todavía sin procesar.
- `procesando`: la corrida actual inició un intento.
- `extraido`: Gemini/Claude obtuvo un evento; falta confirmar su escritura.
- `publicado`: se insertó una fila nueva en `Eventos`.
- `duplicado`: el evento ya existía por nombre + fecha + provincia.
- `descartado`: la imagen fue clasificada de forma definitiva como no evento.
- `reintentar`: hubo una falla transitoria de descarga, cuota o proveedor.

Al comenzar cada corrida se recuperan los estados reintentables. La imagen
se vuelve a descargar desde la URL guardada y se intenta hasta tres veces.
Después del tercer fallo el candidato queda visible en la hoja para
revisión manual, pero no consume llamadas indefinidamente.

## Fallback y reintentos ante fallas

Por cada imagen, `processor.py` intenta primero con Gemini. Si esa llamada
falla (cuota agotada, error de red, respuesta no-JSON), reintenta la misma
imagen con Claude antes de darla por perdida. Una vez que un proveedor
reporta cuota/crédito agotado, se deja de intentarlo para el resto del batch
(evita seguir mandando llamadas condenadas a fallar).

Solo se marca una imagen como "vista" (`seen_hashes.txt`) cuando algún
proveedor da un resultado definitivo (evento extraído, o confirmó que no es
un flyer). Si ambos proveedores fallan para una imagen, no se marca, así una
corrida futura la recupera desde `Candidatos` en vez de perderla para
siempre. Y si ambos
terminan sin cuota/crédito a mitad de un batch, el resto de las imágenes de
esa corrida conserva estado `nuevo` para el día siguiente.

Cada imagen descargada guarda un sidecar `<archivo>.json` con su `link` y
caption indexado de
Instagram — permite reintentar manualmente imágenes que quedaron sin
procesar (ej. `images/*.jpg` sin marcar en `seen_hashes.txt`) sin perder el
link promocional.

## Dedup por post, no solo por imagen

El mismo post de Instagram aparece seguido en los resultados de varias
queries distintas de `config.json` en la misma corrida (medido: alrededor de
un tercio de las descargas eran reapariciones del mismo post). Por eso,
además del hash de imagen, `scraper.py` deduplica por `link` del post
(`seen_links.txt`, mismo mecanismo que `seen_hashes.txt`: se marca recién
cuando `processor.py` confirma un resultado definitivo).

## Filtro heurístico y caption real (sin gastar IA de más)

Antes de pasar cualquier imagen a Gemini/Claude, `scraper.py` descarta las
que claramente no son un flyer: menos de `MIN_IMAGE_BYTES` (15KB — medido:
avatares de Google bajan ~9-10KB, thumbnails de flyers reales ~36-45KB) o
menos de `MIN_IMAGE_DIM` (200px) en el lado más largo. Es gratis (no llama a
ninguna IA) y en una prueba real bajó 24 resultados crudos a 6 candidatos.

El título que Google Images/Serper devuelve junto al resultado suele contener
gran parte del caption indexado de Instagram. `scraper.py` lo conserva en
`Candidatos` y Gemini lo recibe en la primera pasada sin gastar otra búsqueda.

Si ese texto no está disponible, el **caption real del post** (vía una búsqueda de Google Search normal,
`engine: google` no `google_images`, usando el link exacto del post como
query — misma categoría "segura" que el thumbnail, copia cacheada por
Google, no un pedido en vivo a Instagram) **cuesta una llamada extra de
SerpAPI**, así que `processor.py` lo pide bajo demanda en vez de buscarlo
para toda imagen que sobrevive el filtro de peso/dimensión:

1. Primera pasada: Gemini/Claude ve la imagen y el caption indexado cuando
   existe (gratis, sin una búsqueda adicional).
2. Si el resultado es `"no es evento"`, listo — nunca se gasta una
   llamada de caption en algo que iba a descartarse igual (~90-95% de los
   casos medidos).
3. Si es un evento real pero con `confianza` media/baja, o le falta
   `fecha_inicio`/`direccion`, ahí sí se busca el caption y se reintenta
   la extracción con ese contexto extra.

Se descubrió el problema al revés primero: la versión original pedía el
caption para *toda* imagen que pasaba el filtro (antes de saber si era
evento), lo que agotó la cuota de SerpAPI en un solo día (~250 búsquedas,
la mayoría gastadas en imágenes que terminaban siendo "no es evento"). El
campo `contacto` del JSON de salida (email o WhatsApp) sigue saliendo del
caption cuando está disponible, y se guarda en la columna `Contacto` del
Sheet.

## Volumen temporal de descubrimiento

`config.json` controla `consultas_por_dia`. La carga inicial se ejecutó una vez
con `12` y luego volvió a `3` para que Gemini pueda vaciar la cola persistente
sin generar costos. La ventana de Google Images es de un mes porque Instagram
suele indexarse con demora y una semana dejaba afuera anuncios publicados con
anticipación.

Cada consulta descarga como máximo cinco candidatos legibles. Si Gemini agota
su cuota, Claude tiene un límite de seguridad de una llamada por corrida
(`MAX_CLAUDE_CALLS_PER_RUN=1`); el resto queda en `Candidatos` para otro día.

## Carga manual: formulario y mail

Ver [`apps-script/README.md`](apps-script/README.md) para el setup completo
(una sola vez, hay que pegar un script en script.google.com — no se puede
hacer por API). Dos caminos, mismo Apps Script:

- **Formulario** (modal "+ Nuevo Evento" en el sitio): campos ya
  estructurados + flyer subido directo. El Apps Script (`doPost`) sube la
  imagen a Drive y escribe la fila **directo en "Eventos"**, sin IA ni
  espera — se publica al instante.
- **Mail** (alternativa, dentro del mismo modal): un organizador manda un
  mail con `HME` en el asunto y el flyer adjunto; el Apps
  Script lo guarda en Drive y anota una fila en `Cola_Manual`; `main.py`
  la procesa en la corrida diaria reusando el mismo `extract_event_data`
  del scraping — el cuerpo del mail juega el rol del caption. Pensado para
  texto libre en vez de completar campos.

El formulario web escribe campos estructurados directo porque la persona
organizadora completa la fecha y el país está fijado en Argentina. Los
eventos recibidos por email sí pasan por la misma normalización de fecha,
país y provincia que el scraping antes de decidir si quedan activos.

## Por qué no usamos la imagen "original" ni Bing Images

- **`original` de SerpAPI/Google para posts de Instagram no es descargable**:
  apunta a `lookaside.instagram.com/seo/google_widget/...`, que devuelve HTML,
  no una imagen. El único dato descargable es el `thumbnail` de Google
  (~10-45KB, bien por debajo de la resolución real del flyer). Ir directo a
  la página del post de Instagram para sacar la imagen real es una opción,
  pero implica scrapear Instagram sin sesión — se descartó a propósito por
  el riesgo de bloqueos, sobre todo corriendo desde IPs de GitHub Actions.
- **Bing Images (mismo SerpAPI, `engine: bing_images`) da imágenes de mayor
  resolución y sí directamente descargables**, pero **el filtro
  `site:instagram.com` no funciona en Bing** — probado con varias queries,
  la gran mayoría de los resultados eran bancos de imágenes genéricos
  (Shutterstock, clipart, etc.), no posts de Instagram. Sin poder acotar a
  Instagram, no sirve para este caso.
