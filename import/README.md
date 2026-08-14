# hayminga.org — Pipeline de importación automática

Descubre flyers de eventos de bioconstrucción en Instagram (vía **HikerAPI**,
por hashtag y por cuenta seguida), extrae los datos con Gemini Vision
(gratis, con Claude como fallback pago) y los escribe en la misma Google
Sheet que lee [hayminga.org](../index.html) en vivo por GViz.

> Para el detalle de por qué se llegó a esta arquitectura (qué se probó
> antes, qué se descartó y por qué) ver `../ROADMAP.md` — es la fuente de
> verdad narrativa. Este README es la referencia operativa rápida.

## Arquitectura

```
HikerAPI — hashtag/medias/top (config.json.hashtags, ~40) y
           /v1/user/medias (config.json.cuentas_seguidas, ~140)
        ↓
  hiker_pipeline.py — filtros pre-IA (dedup por shortcode, blacklist de
                      cuentas, antigüedad del post, idioma por heurística
                      de palabras ES/EN) antes de gastar ninguna llamada
        ↓
  processor.py — extract_event_data(): Gemini Vision (imagen + caption)
                 extrae nombre, fecha, lugar, tipo, contacto, etc.
                 (si Gemini falla o se queda sin cuota, reintenta con
                 Claude, con tope MAX_CLAUDE_CALLS_PER_RUN por ser pago)
        ↓
  sheets.py — append_events(): dedup final por (nombre, fecha, provincia)
              y por shortcode de Instagram, calcula Activo de forma
              determinista (nunca confía en lo que devuelve la IA),
              escribe en la hoja "Eventos"
        ↓
  hayminga.org lee esa Sheet vía GViz JSON al cargar la página

En paralelo, dos canales de carga manual (mismo extractor de IA):

  mail con tag "HME" en el asunto → Apps Script lo encola en "Cola_Manual"
        → email_intake.py lo procesa con extract_event_data() (el cuerpo
          del mail hace de caption)

  formulario web "+ Nuevo Evento" → Apps Script escribe directo en
        "Eventos", sin IA — la persona organizadora ya completa los campos
```

Vive dentro del repo `hayminga-web` (junto al frontend). Tres workflows
en `.github/workflows/` lo orquestan — ver el cron y el detalle de cada
uno en `../CLAUDE.md` (sección "What actually runs in production").

---

## Setup (una sola vez)

### 1. Google Sheets

1. Creá un Google Sheet nuevo.
2. Renombrá la primera hoja como `Eventos`.
3. Copiá el ID del Sheet (está en la URL: `spreadsheets/d/ESTE_ES_EL_ID/edit`).
4. El resto de las hojas (`FuentesStats`, `CuentasConsultadas`, `CuentasIds`,
   `Cola_Manual`) las crea el pipeline solo la primera vez que las necesita
   — no hace falta crearlas a mano.

### 2. Google Service Account

1. Entrá a [Google Cloud Console](https://console.cloud.google.com).
2. Creá un proyecto (o usá uno existente).
3. Activá la API: **Google Sheets API**.
4. Creá una **Service Account** → descargá el JSON.
5. Compartí el Google Sheet con el email de la service account (permiso Editor).

### 3. HikerAPI (descubrimiento en Instagram, pago)

1. Creá una cuenta en [hikerapi.com](https://hikerapi.com) y copiá tu API key.
2. Es el proveedor de descubrimiento de producción — sin esta key,
   `hiker_pipeline.py` aborta al arrancar. Costo aproximado con el volumen
   actual (2 corridas/día, ~40 hashtags + ~140 cuentas con caché de
   `user_id`): del orden de $1-2/mes. Ver el incidente de costo en
   `../ROADMAP.md` antes de sumar más fuentes o subir la frecuencia del cron.

### 4. Gemini API (gratis/muy barato, proveedor principal de extracción)

1. Entrá a [aistudio.google.com/apikey](https://aistudio.google.com/apikey) con una cuenta de Google.
2. Creá una API key nueva — usá un proyecto de Google Cloud dedicado a hayminga
   (`haymingaorg`), no reutilices una key de otro proyecto, así el free tier
   y los límites de cuota no se comparten con nada más.
3. Con billing activado en el proyecto (recomendado — ver `../ROADMAP.md`)
   el límite de requests/minuto sube mucho y se puede bajar
   `GEMINI_MIN_INTERVAL_SECONDS` sin tocar código.

### 5. Claude API (fallback, opcional pero recomendado)

1. [console.anthropic.com](https://console.anthropic.com) → API Keys → creá una key
   y cargale algo de crédito. Se usa solo cuando Gemini falla o se queda sin
   cuota, con un tope de `MAX_CLAUDE_CALLS_PER_RUN` por corrida (es pago).

### 6. Telegram (resumen semanal)

1. Creá un bot con [@BotFather](https://t.me/BotFather) → copiá el token.
2. Mandale un mensaje al bot y consultá
   `https://api.telegram.org/bot<TOKEN>/getUpdates` para sacar el `chat_id`.

### 7. Secrets en GitHub

En el repo → Settings → Secrets and variables → Actions → New repository secret.

| Secret | Usado por |
|--------|-----------|
| `HIKERAPI_KEY` | `hiker_pipeline.py`, `curar_fuentes.py` (descubrimiento en Instagram) |
| `GEMINI_API_KEY` | extracción, proveedor primario |
| `ANTHROPIC_API_KEY` | extracción, fallback |
| `GOOGLE_SPREADSHEET_ID` | todos los módulos que tocan la Sheet |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | idem |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | `enviar_resumen_telegram.py` |

---

## Correr localmente

```bash
cd import
pip install -r requirements.txt
cp .env.example .env      # completá tus valores reales, nunca se commitea

python -m src.hiker_pipeline           # pipeline de producción (gasta HikerAPI + IA)
python -m src.enviar_resumen_telegram  # resumen semanal
python -m src.curar_fuentes            # curación de fuentes
```

`.env` se carga automáticamente con `python-dotenv`. En GitHub Actions no
hace falta — las variables vienen de los Secrets del repo.

**Antes de correr cualquiera de los comandos de arriba: gastan API paga real
(HikerAPI, y Claude si Gemini se queda sin cuota).** Para probar cambios de
lógica sin gastar nada, correr los tests (mockean todas las llamadas
externas):

```bash
python -m unittest discover -s tests -v     # todos
python -m unittest tests.test_scraper -v    # un módulo puntual
```

## Correr manualmente en GitHub (sin tocar el cron)

```bash
gh workflow run import-eventos.yml -R geermaanv/hayminga-web
gh run watch -R geermaanv/hayminga-web
```

## Configuración de fuentes (`config.json`)

- `hashtags`: hashtags de Instagram a consultar (`hashtag/medias/top`).
- `cuentas_seguidas`: usernames de cuentas a recorrer vía `/v1/user/medias`
  (timeline cronológico real, no rankeado por popularidad global).
- `cuentas_excluidas`: blacklist de usernames, se descartan antes de
  gastar ninguna llamada a la IA.
- `dias_atras`, `max_imagenes_por_query`, `max_por_hashtag`,
  `consultas_por_dia`, `grupos`: quedaron del pipeline viejo de Google
  Images (`main.py`/`scraper.py`), `hiker_pipeline.py` no los lee.

Las altas de hashtags nuevos siguen siendo manuales (necesitan criterio de
relevancia temática). Las altas de cuentas nuevas y las bajas de fuentes sin
resultados las hace solo `curar_fuentes.py` — ver `../ROADMAP.md` para el
detalle de cómo y los topes de seguridad (`MIN_SUGERENCIAS_PARA_AGREGAR`,
50 intentos sin hit).

## Estructura del Sheet (hoja "Eventos")

Columnas exactas en `src/sheets.py` (docstring del módulo): `Activo,
Nombre, Dirección, Periodo, Fecha_Inicio, Fecha_Fin, Es_Virtual, Provincia,
Descripción, Organizador, Link_Promocion, Tipo_Evento, img, procesado, Id,
Contacto, Estado, Pais, Confianza, Fuente, Fecha_Descubrimiento`. Las
columnas nuevas se agregan siempre al final — el frontend (`index.html`) y
el backend están acoplados solo por este orden, no lo cambies sin revisar
los dos lados.

- `Id`: identificador corto único por evento, generado al insertarse. Toda
  fila nueva lo necesita — la confirmación en `?pendientes` usa `fetch` con
  `no-cors` y falla en silencio si falta.
- `Contacto`: email o WhatsApp del organizador, si el extractor lo encontró.
- `Estado`: `confirmado`, `pendiente_confirmacion` (cola de revisión en
  `hayminga.org/?pendientes`) o `descartado` (sacado de circulación sin
  borrar la fila). Ver `../CLAUDE.md` — sección "The Estado model".
- `Confianza`: `alta`, `media` o `baja`, según la extracción de la IA.
- `Fuente`: origen del evento (`hikerapi`, `email` o `formulario_web`).
- `Fecha_Descubrimiento`: momento en que el pipeline recibió el candidato.

`Activo` lo calcula `sheets.py` de forma determinista (Argentina + evento
no terminado) — **nunca** se toma directo de lo que devuelve la IA.

## Flags activos

- **`REVISION_MANUAL = true`** en `src/processor.py` y en
  `apps-script/Code.gs` (mirror — hay que reimplementar en
  script.google.com para que tome efecto en producción). Mientras esté en
  `true`, nada se auto-publica: todo llega a `Activo=false` /
  `Estado=pendiente_confirmacion` y se confirma a mano en `?pendientes`.
  Detalle y motivo en `../ROADMAP.md`.

## Fallback de IA ante fallas

Por cada imagen, `processor.py` intenta primero con Gemini. Si esa llamada
falla (cuota agotada, error de red, respuesta no-JSON, timeout de 30s),
reintenta la misma imagen con Claude antes de darla por perdida, con un
tope de `MAX_CLAUDE_CALLS_PER_RUN` por corrida (Claude es pago). Si ambos
proveedores fallan, el post se loguea y se sigue — no hay cola de
reintentos persistente en el pipeline de HikerAPI (si falla un día, se
reintenta solo si HikerAPI lo vuelve a traer en una corrida futura y
todavía no fue descartado por dedup o antigüedad).

## Carga manual: formulario y mail

Ver [`apps-script/README.md`](apps-script/README.md) para el setup completo
del Apps Script (una sola vez, hay que pegar el script en
script.google.com — no se puede hacer por API).

- **Formulario** (modal "+ Nuevo Evento" en el sitio): campos ya
  estructurados + flyer subido directo. `doPost` sube la imagen a Drive y
  escribe la fila directo en "Eventos", sin IA.
- **Mail** (alternativa, mismo modal): un organizador manda un mail con
  `HME` en el asunto; Apps Script lo guarda en Drive y anota una fila en
  `Cola_Manual`; `email_intake.py` la procesa en la misma corrida diaria
  del pipeline, reusando `extract_event_data()` — el cuerpo del mail juega
  el rol del caption. También acepta que manden solo el link (sin
  adjuntar el flyer): se baja la imagen del post vía su `og:image`.

## Código legado, sin uso en producción

`main.py`, las funciones de Google Images/SerpAPI/Serper en `src/scraper.py`,
y `src/candidates.py` (cola persistente `Candidatos`) implementaban el
pipeline de descubrimiento anterior a HikerAPI. Ningún workflow los llama
hoy — `hiker_pipeline.py` los reemplazó por completo (ver
`../ROADMAP.md`, sección "Pipeline de producción: HikerAPI"). Se dejaron en
el repo a propósito, como referencia y por si hiciera falta volver atrás,
no porque sigan corriendo. `src/scraper.py` sí sigue vivo parcialmente:
`fetch_caption()` (caption vía Google cache) lo usa `processor.py` como
enriquecimiento opcional cuando falta contexto.
