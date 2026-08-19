# CLAUDE.md

Guidance for Claude Code when working on hayminga.org.

**Before making changes, read (in order):**
1. `ESTRATEGIA.md` — goal, phases, why each decision matters
2. `PATRONES.md` — critical patterns & constraints that affect code
3. `ROADMAP.md` — narrative history: what's been tried & learned

## Architecture

**Repo shape:**
- **Frontend** (`index.html`, `vendor/leaflet/`, `_headers`, `CNAME`): single static-page site on hayminga.org (GitHub Pages). Vanilla JS + Leaflet, no build. Reads events from a Google Sheet via GViz JSON at load time.
- **Importer** (`import/`): Python pipeline that populates the Sheet. Runs on GitHub Actions cron.
- **Apps Script** (`import/apps-script/Code.gs`): web form, mail intake queue, `?pendientes` review, weekly digest. **This file is a mirror** — changes only sync after manual deployment at script.google.com (Implementar → Gestionar implementaciones → Nueva versión).

**Frontend ↔ Importer coupling:** column layout in `src/sheets.py`. Always append new columns at the end; existing positions are load-bearing.

## Operations

**Four workflows in `.github/workflows/`:**

| Workflow | Schedule | Does |
|----------|----------|------|
| `import-eventos.yml` | ~08:07 daily | `python -m src.hiker_pipeline` — discovers events from HikerAPI (hashtags + followed accounts) |
| `email-intake.yml` | every 3h | `python -m src.email_intake` — processes mail queue (HME tag), then refreshes the Instagram content queue (`contenido_instagram.generar()`). Split out (15/08/2026) so 1x/day import didn't delay mail. Cheap: reads Sheet, exits if empty, only calls LLM on real mail. Shares concurrency group with import-eventos to queue safely. |
| `curar-fuentes.yml` | 09:00 daily | `src/curar_fuentes.py` — removes stale hashtags/accounts (50+ dry runs), adds new candidates from Instagram "sugeridas" (gated by `MIN_SUGERENCIAS_PARA_AGREGAR=2`) |
| `enviar-resumen.yml` | Tue 09:00 | `src/enviar_resumen_telegram.py` — sends weekly digest to Telegram + Directorio email |

**Legacy code (not used):** `main.py` and `src/scraper.py` (Google Images / SerpAPI). Kept for reference.

**Digest formatting rule:** put `https://hayminga.org` **first** — WhatsApp link preview uses first URL.

## Configuration & Commands

**Importer commands** (all from `import/`):

```bash
pip install -r requirements.txt
cp .env.example .env                              # secrets for local runs
python -m src.hiker_pipeline                      # production pipeline
python -m src.enviar_resumen_telegram             # weekly digest
python -m src.curar_fuentes                       # curation pass
python -m src.candidatos_hashtags                  # free: hashtag candidates from confirmed events
python -m src.candidatos_tecnicas                  # free: technique vocabulary from confirmed events (Directorio suggestions)
python -m src.mensajes_organizadores               # free: DM drafts to invite event organizers to the Directorio
python -m src.geocodificar                         # free: dry-run geocoding of rows without coordinates (--escribir to apply)
python -m src.contenido_instagram                  # free: refill the Instagram content queue (idempotent)
python -m unittest discover -s tests -v           # tests (all external calls mocked)
gh workflow run import-eventos.yml -R geermaanv/hayminga  # manual trigger
```

**Cost:** `hiker_pipeline`, `curar_fuentes`, and `enviar_resumen_telegram` spend real money (HikerAPI, Gemini/Claude). Validate code changes via tests instead (all external calls are mocked).

**Active configuration flags:**

- **`REVISION_MANUAL = true`** (in `processor.py` AND `Code.gs`) — everything lands as `Estado=pendiente_confirmacion`, waits for manual review at `hayminga.org/?pendientes`. Flip both to `false` to enable auto-publish (`confianza=alta` only).
- **`HIKERAPI_KEY`** — required for production. Local: `.env`. CI: GitHub Actions secret.
- **`GEMINI_MIN_INTERVAL_SECONDS`** — rate pacing. Default 4.5s (free tier: 15/min). Production: 0.5s (billing enabled).

## Pipeline: event discovery & extraction

**Discovery:** HikerAPI, two channels — hashtags (`config.json.hashtags`, ~30-40 curated) and followed accounts (`config.json.cuentas_seguidas`, 74+).

**Pre-AI filters (cheap, run before LLM):**
- Dedup by Instagram shortcode (`/p/`, `/reel/`, `/reels/` → same post)
- Blacklist (`config.json.cuentas_excluidas`)
- Post age > 180 days (dropped from 270; see PATRONES.md)
- Language: `_parece_ingles()` on caption (regex, reliable; LLM output unreliable on ambiguous flyers)

**Extraction strategy:**
1. Gemini text-only on caption (cheap, filters non-events)
2. If ambiguous/event: Gemini + image (recovers more fields)
3. Fallback to Claude if Gemini quota hit (capped by `MAX_CLAUDE_CALLS_PER_RUN`, Claude is paid)
4. Timeout: `genai.Client` must set `timeout=30_000` (real incident: 44min hang)

**Coordinates** (priority, top wins): location tagged on the post → geocoding of the extracted `direccion` via Nominatim (free) → nothing, and the frontend falls back to the province centroid. Most posts carry no tagged location, so without geocoding ~70% of events landed in the middle of their province.

**Post-extraction validation:**
- Drop already-happened events (fecha_fin/inicio < today)
- Drop non-Argentina
- Drop non-Spanish (redundant with pre-AI filter, for defense in depth)

**Write:** Dedup by `(nombre, fecha, provincia)`. Ambiguous match → `pendiente_confirmacion` with note linking to existing event (manual merge, no silent loss). `Activo` computed deterministically; never from LLM.

**Curation:** `FuentesStats` sheet tracks hits/misses per source. `curar_fuentes.py` auto-removes stale sources (50+ dry runs), auto-adds new candidates from Instagram.

## Data model

**Event state:** Two orthogonal fields per row:
- `Activo` (true/false) — controls visibility on site
- `Estado` — curation state: `confirmado`, `pendiente_confirmacion` (review queue), `descartado` (blacklisted, but dedup still tracks it)
  - Older values (`pendiente`, `revision_fuente`) collapsed into `pendiente_confirmacion` — don't reintroduce.

**Review queue** (`hayminga.org/?pendientes`): Manual actions via `Code.gs`.
- `confirmar_evento` — activates row, reopens form for edits
- `descartar_evento` — sets `Estado=descartado`
- `notificarPendientes()` — alerts `germanv@gmail.com`

**Intake channels:**
- **Web form** (`+ Nuevo Evento`): Posts to `doPost`, writes directly to Eventos (no AI). Goes to review queue while `REVISION_MANUAL=true`.
- **Mail intake** (tag `HME` in subject): Apps Script queues to `Cola_Manual`, pipeline processes with `extract_event_data` (email body = caption). Pulls image via `og:image` if only link sent. Separate from HikerAPI — runs from same `email-intake.yml` cron.

**Directorio** (sheet `Directorio`, written only by `Code.gs`, read by the frontend via GViz):

`Id, Nombre, Provincia, Intereses, Descripcion, Email, Whatsapp, Tecnicas, AnioDesde, RecibeNovedades`

- `Tecnicas` — up to 5 pairs, `quincha:hago/enseno; revoques:hago`. Relations: `hago` (for others), `enseno`, `estudio`, `propia` (own build); multi-select per technique. Free text with ~16 suggestions from `candidatos_tecnicas.py` — deliberately **not** a closed list: in Fase 1 the form is the instrument for discovering vocabulary.
- `Intereses` — `;`-separated (values contain commas). Interest in an **activity**, not a topic: "bioconstrucción" as an interest says nothing, everyone signing up has it.
- `RecibeNovedades` — `"true"`/`"false"` as text. Only an explicit `"false"` opts out, so rows predating the column keep receiving.
- Email and Whatsapp are never shown publicly — contact goes through the double opt-in flow.
- The card shows no computed ranking of people; see PATRONES.md.

**Instagram** (sheet `Instagram`, written by `contenido_instagram.py`): a work queue, not a report — one row per unit of Instagram work (`historia_evento`, `carrusel_semanal`, `dm_organizador`), with the text, the `@` to mention and the link already resolved.

- Runs from `email-intake.yml` (every 3h) rather than the daily import, so a confirmed event turns into a piece within hours instead of a day.
- Idempotent through a deterministic `Clave` (`historia:<Id>`, `carrusel:2026-W34`, `dm:<username>` — one invite per account ever, not one per event they post). Existing keys are skipped **in any state**, so `publicado` and `descartado` both block regeneration.
- **Rows must be marked `descartado`, never deleted** — deleting frees the key and the next run recreates the row.
- Only queues events that are `confirmado` and `Activo`: promoting something unreviewed is worse than not promoting.
- Hashtags are a fixed curated constant, deliberately not derived from `Hashtags_Post` — that field carries whatever the poster wrote, and is how a bioconstruction post ends up tagged `#fungi`.
- Nothing is published automatically: story mentions aren't supported by the Instagram API and automated DMs violate its terms. What is automated is the preparation.

## Cross-cutting rules

**Every user-facing message** (Telegram digest, Directorio email, form confirmations, WhatsApp) must include CTA: share via WhatsApp, send by mail, or tag `#hayminga` on Instagram.

**See PATRONES.md** for critical patterns: data integrity (image expiry, Sheet parsing), filtering (date interaction, language detection), operations (incremental saves, timeout handling), and architecture constraints (column coupling, Apps Script mirroring).
