# hayminga.org — Pipeline de importación automática

Busca flyers de eventos de bioconstrucción en Google Images (vía SerpAPI, filtrando Instagram),
extrae los datos con Gemini Vision (gratis, con Claude como fallback) y los escribe en la
misma Google Sheet que lee [hayminga.org](../index.html) directamente (sin Glide de por medio).

## Arquitectura

```
Google Images (SerpAPI, site:instagram.com + queries de config.json)
        ↓
  scraper.py — descarga imágenes nuevas, evita duplicados por hash
        ↓
  processor.py — Gemini Vision extrae nombre, fecha, lugar, tipo, etc.
                 (si falla o se queda sin cuota, reintenta esa imagen con Claude)
        ↓
  sheets.py — escribe en la Google Sheet "Eventos"
        ↓
  hayminga.org lee esa Sheet vía GViz JSON al cargar la página
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
img, procesado`.

Gemini marca `activo=true` solo si el evento es en Argentina y la fecha de
inicio es futura; el resto entra con `Activo=false` (visible en la Sheet pero
oculto en el sitio, ya que el frontend filtra por `Activo='true'`). El campo
`confianza` (alta/media/baja) viaja en el JSON de salida de Gemini pero **no**
se guarda en la Sheet ni se usa para moderar — si querés revisar antes de
publicar eventos de confianza baja, hay que agregarlo como columna.

## Fallback y reintentos ante fallas

Por cada imagen, `processor.py` intenta primero con Gemini. Si esa llamada
falla (cuota agotada, error de red, respuesta no-JSON), reintenta la misma
imagen con Claude antes de darla por perdida. Una vez que un proveedor
reporta cuota/crédito agotado, se deja de intentarlo para el resto del batch
(evita seguir mandando llamadas condenadas a fallar).

Solo se marca una imagen como "vista" (`seen_hashes.txt`) cuando algún
proveedor da un resultado definitivo (evento extraído, o confirmó que no es
un flyer). Si ambos proveedores fallan para una imagen, no se marca, así una
corrida futura la reintenta en vez de perderla para siempre. Y si ambos
terminan sin cuota/crédito a mitad de un batch, el resto de las imágenes de
esa corrida ni siquiera se intenta.

Cada imagen descargada guarda un sidecar `<archivo>.json` con su `link` de
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
