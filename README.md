# hayminga.org — Pipeline de importación automática

Busca flyers de eventos de bioconstrucción en Google Images (filtrando Instagram),
extrae los datos con Claude Vision y los carga en Google Sheets → Glide.

## Arquitectura

```
Google Images (site:instagram.com + #minga #bioconstruccion)
        ↓
  scraper.py — descarga imágenes nuevas
        ↓
  processor.py — Claude Vision extrae fecha, lugar, nombre, contacto
        ↓
  sheets.py — escribe en Google Sheets
        ↓
  Glide lee el Sheet automáticamente → hayminga.org actualizado
```

Corre todos los días a las 8:00 AM (Argentina) vía GitHub Actions — gratis.

---

## Setup (una sola vez)

### 1. Clonar y subir a GitHub

```bash
git init
git add .
git commit -m "initial commit"
git remote add origin https://github.com/TU_USUARIO/hayminga-pipeline
git push -u origin main
```

### 2. Google Sheets

1. Creá un Google Sheet nuevo
2. Renombrá la primera hoja como `Eventos`
3. Copiá el ID del Sheet (está en la URL: `spreadsheets/d/ESTE_ES_EL_ID/edit`)

### 3. Google Service Account

1. Entrá a [Google Cloud Console](https://console.cloud.google.com)
2. Creá un proyecto nuevo (ej: "hayminga")
3. Activá la API: **Google Sheets API**
4. Creá una **Service Account** → descargá el JSON
5. Compartí el Google Sheet con el email de la service account (permiso Editor)

### 4. Conectar el Sheet a Glide

1. En Glide → Data Sources → Add Source → Google Sheets
2. Seleccioná el Sheet con la hoja `Eventos`
3. Listo — Glide va a sincronizar automáticamente

### 5. Secrets en GitHub

En tu repo → Settings → Secrets → Actions → New repository secret:

| Secret | Valor |
|--------|-------|
| `ANTHROPIC_API_KEY` | Tu API key de Anthropic |
| `GOOGLE_SPREADSHEET_ID` | ID del Google Sheet |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Contenido completo del JSON de la service account |

### 6. (Opcional) Google Custom Search API

Para búsqueda más estable y sin riesgo de bloqueo:

1. Activá **Custom Search API** en Google Cloud
2. Creá un Custom Search Engine en [cse.google.com](https://cse.google.com)
3. Configuralo para buscar en `instagram.com`
4. Agregá dos secrets más: `GOOGLE_API_KEY` y `GOOGLE_CX`

Sin estos secrets, el script usa scraping directo (funciona pero es menos estable).

---

## Correr manualmente

```bash
# Instalar dependencias
pip install -r requirements.txt

# Variables de entorno
export ANTHROPIC_API_KEY=...
export GOOGLE_SPREADSHEET_ID=...
export GOOGLE_SERVICE_ACCOUNT_JSON='{"type":"service_account",...}'

# Correr
python main.py
```

## Estructura del Sheet

| nombre | fecha | lugar | contacto | descripcion | confianza | imagen_fuente | fecha_importacion |
|--------|-------|-------|----------|-------------|-----------|---------------|-------------------|
| Minga de adobe | 15/04/2025 | Mendoza | @cuenta | ... | alta | hash.jpg | 28/03/2026 |

El campo `confianza` (alta/media/baja) te permite filtrar en Glide si querés moderar antes de publicar.
