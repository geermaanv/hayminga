# hayminga.org — Pipeline de importación automática

Busca flyers de eventos de bioconstrucción en Google Images (vía SerpAPI, filtrando Instagram),
extrae los datos con Claude Vision y los escribe en la misma Google Sheet que lee
[hayminga.org](../index.html) directamente (sin Glide de por medio).

## Arquitectura

```
Google Images (SerpAPI, site:instagram.com + queries de config.json)
        ↓
  scraper.py — descarga imágenes nuevas, evita duplicados por hash
        ↓
  processor.py — Claude Vision extrae nombre, fecha, lugar, tipo, etc.
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

### 4. Secrets en GitHub

En el repo `hayminga` → Settings → Secrets and variables → Actions → New repository secret.
Ver todos los detalles (variables usadas, cuáles quedaron obsoletas) en el
[README principal](../README.md).

| Secret | Valor |
|--------|-------|
| `ANTHROPIC_API_KEY` | Tu API key de Anthropic |
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

Claude Vision marca `activo=true` solo si el evento es en Argentina y la fecha de
inicio es futura; el resto entra con `Activo=false` (visible en la Sheet pero
oculto en el sitio, ya que el frontend filtra por `Activo='true'`). El campo
`confianza` (alta/media/baja) viaja en el JSON de salida de Claude pero **no**
se guarda en la Sheet ni se usa para moderar — si querés revisar antes de
publicar eventos de confianza baja, hay que agregarlo como columna.
