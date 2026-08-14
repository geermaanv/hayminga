# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Read `ROADMAP.md` for the narrative history (why decisions were made, what's been tried and rejected). It's the source of truth for context that isn't in the code.

## Repo shape

- **Frontend** (`index.html`, `vendor/leaflet/`, `_headers`, `CNAME`): single static-page site on hayminga.org (GitHub Pages). Vanilla JS + Leaflet, no build. Reads events from a Google Sheet via GViz JSON at load time.
- **Importer** (`import/`): Python pipeline that populates the Sheet. Runs on GitHub Actions cron.
- **Apps Script** (`import/apps-script/Code.gs`): handles the web form (`+ Nuevo Evento`), the mail intake queue, the `?pendientes` review actions, and the weekly Directorio digest. **The file in the repo is a mirror** — changes only take effect after copying them into the project at script.google.com and cutting a new deployment (Implementar → Gestionar implementaciones → Nueva versión).

Frontend ↔ importer are coupled only through the column layout in `src/sheets.py`. Always append new columns at the end; existing positions are load-bearing for both sides.

## What actually runs in production

Three workflows in `.github/workflows/`:

- **`import-eventos.yml`** (08:00 and 20:00 Argentina) — runs `python -m src.hiker_pipeline`. **`main.py` and `src/scraper.py` are legacy** (Google Images / SerpAPI); kept in-repo for reference but no workflow calls them.
- **`curar-fuentes.yml`** (daily 09:00 Argentina, temporary cadence — becomes weekly once volume justifies it) — runs `src/curar_fuentes.py`: auto-removes hashtags/accounts with 50+ consecutive runs without a hit, and auto-adds new candidate accounts via Instagram's "sugeridas" endpoint (with `MIN_SUGERENCIAS_PARA_AGREGAR=2` gate to avoid the tangential-topic explosion — see roadmap).
- **`enviar-resumen.yml`** (Tue 09:00 Argentina) — runs `src/enviar_resumen_telegram.py`: sends the weekly digest to `@geermaanv_bot` on Telegram AND, via `Code.gs`'s `enviarResumenSemanalDirectorio()` trigger, to every email in the Directorio (opt-in was captured at signup).

Digest formatting rule: put `https://hayminga.org` **first** in the message body — WhatsApp builds its link preview from the first URL it sees, and if it's an Instagram post link the card covers the rest of the list.

## Importer commands

All from `import/`:

```bash
pip install -r requirements.txt
cp .env.example .env                              # secrets for local runs
python -m src.hiker_pipeline                      # production pipeline
python -m src.enviar_resumen_telegram             # weekly digest
python -m src.curar_fuentes                       # curation pass
python -m unittest discover -s tests -v           # tests (also in CI)
python -m unittest tests.test_scraper -v          # single module
python main.py                                    # legacy Google Images pipeline (do not use)
```

**`python -m src.hiker_pipeline`, `curar_fuentes`, and `enviar_resumen_telegram` all spend real money** (HikerAPI, and Claude when Gemini quota runs out) — never run them just to check a code change. The tests are the free way to validate logic: every external call (HikerAPI, Gemini, Claude, Sheets API, Telegram) is mocked in `tests/`, so `python -m unittest discover -s tests -v` exercises the real pipeline logic without touching any paid API. If you're validating a change to `hiker_pipeline.py`/`processor.py`/`sheets.py`, add or extend a test with a mocked response rather than doing a live run.

Trigger a manual production run:

```bash
gh workflow run import-eventos.yml -R geermaanv/hayminga
```

## Pipeline architecture (`src/hiker_pipeline.py`)

Discovery: **HikerAPI**, two channels — hashtags (`config.json.hashtags`, ~30-40 curated) and followed accounts (`config.json.cuentas_seguidas`, 74+). Hashtags use `hashtag/medias/top` (the `recent` endpoint returns empty in practice). Accounts use `/v1/user/medias` — a real cronological timeline, less biased toward high-volume countries than the global `top` ranking.

Pre-AI filters (cheap, run before any Gemini/Claude call to save quota and cost):

- Dedup by Instagram shortcode (see `sheets.py.instagram_shortcode()` — same post can appear as `/p/`, `/reel/`, or `/reels/`).
- Blacklist (`config.json.cuentas_excluidas`) — username-level exclusion.
- Post age: drop anything older than **180 days** by `taken_at_ts` (was 270; lowered after finding a 252-day post slipping through).
- Language: `_parece_ingles()` counts common ES vs EN words in the caption — the LLM's `pais`/`idioma` output is unreliable when the flyer is ambiguous, so this filter runs first. The LLM's `idioma` field stays as a secondary layer.

Extraction (Gemini Vision primary, Claude fallback):

1. First pass: text-only on the caption (cheap way to reject non-events).
2. If it's a real event: send the image too (with caption as context — usually recovers more fields).
3. Provider fallback: Claude picks up when Gemini reports quota exhausted, capped by `MAX_CLAUDE_CALLS_PER_RUN` (Claude is paid).
4. Gemini pacing: `GEMINI_MIN_INTERVAL_SECONDS` env var (default 4.5s for free tier; production runs at 0.5s because billing is enabled on the `haymingaorg` project).
5. `genai.Client` **must** set `http_options=types.HttpOptions(timeout=30_000)` — without it a hung call blocks the whole run indefinitely (real incident: 44 min silent hang). The workflow also sets `PYTHONUNBUFFERED=1` so `print()` logs survive cancellation.
6. Post-extraction filters: drop events already in the past (compare `fecha_fin`/`fecha_inicio`), drop non-Argentina, drop non-Spanish.

Write (`sheets.py.append_events`):

- Dedup by `(nombre, fecha, provincia)`. Ambiguous match (same event, different source post) → **inserts anyway but into `pendiente_confirmacion`** with an automatic note pointing at the existing Id, so the two can be merged manually rather than one silently lost.
- `Activo` computed here deterministically (Argentina + not-yet-ended). **Never set `Activo` from LLM output.**

Curation stats: each run appends to the `FuentesStats` sheet (`Tipo, Nombre, IntentosSinHit, UltimoHit`). `curar_fuentes.py` reads that and does auto-removal by pushing commits to `config.json` (needs `permissions: contents: write`). Auto-add of new candidates uses a separate `CuentasConsultadas` sheet to avoid re-querying "sugeridas" for the same account within 30 days, and a `CuentasIds` sheet caches `user_id` lookups (cost control — see roadmap for the $4-in-a-few-days incident).

## Currently active flags & switches

- **`REVISION_MANUAL = true`** in `import/src/processor.py` AND `import/apps-script/Code.gs`. While this is true, **nothing auto-publishes** — everything (HikerAPI, mail intake, web form) lands as `Activo=false` / `Estado=pendiente_confirmacion` and waits for manual confirmation at `hayminga.org/?pendientes`. To restore auto-publish, flip both files back to `false`. (For HikerAPI specifically, the intended behavior once the flag is off is: `confianza=alta` publishes directly, `media`/`baja` still goes to review.)
- **`HIKERAPI_KEY`** — required for the production pipeline. Local: put it in `.env`. CI: GitHub Actions secret.

## The `Estado` model

Two orthogonal fields on each event row:

- `Activo` (true/false) — the on/off switch that controls visibility on the site.
- `Estado` — curation state, one of: `confirmado`, `pendiente_confirmacion` (shows up in the `?pendientes` review queue), `descartado` (removed from circulation without deleting the row, so the shortcode-dedup still recognizes it if the pipeline finds it again).

Older values `pendiente` and `revision_fuente` were collapsed into `pendiente_confirmacion`. Don't reintroduce them.

## Review queue (`hayminga.org/?pendientes`)

Three actions, all backed by `Code.gs`: `confirmar_evento` (activates a row by Id and reopens the "Publicá tu evento" form pre-filled for edits), `descartar_evento` (sets `Activo=false` / `Estado=descartado`), and Skip. `notificarPendientes()` sends a mail to `germanv@gmail.com` when new pendings appear.

## Other stable intake channels

- **Web form** (`+ Nuevo Evento` modal in `index.html`): posts to Apps Script `doPost`, which writes straight to `Eventos` (no AI). While `REVISION_MANUAL=true`, still goes to review.
- **Mail intake** (`email_intake.py`, tag `HME` in subject): Apps Script queues to `Cola_Manual`, the pipeline processes with the same `extract_event_data` (email body plays the caption's role). If the sender only sends a link, the pipeline pulls the image via `og:image`. This runs from the same `import-eventos.yml` workflow but is not replaced by HikerAPI — it's a separate capability.

## Outbound-message rule

Every message that reaches end users (Telegram digest, Directorio mail, form confirmations, WhatsApp copy) must include the reminder for how to contribute events: share by WhatsApp, send by mail, or tag `#hayminga` on Instagram. This is a standing product rule.

## Gotchas worth remembering

- Google Sheet formula injection: any cell whose value starts with `+`, `=`, or `-` gets interpreted as a formula unless the cell is pre-formatted as plain text. Sanitize on write.
- Apps Script `doPost` writing booleans natively breaks GViz parsing — always write `"true"`/`"false"` as strings.
- GViz header detection is unreliable when a column is 100% text — always request with `&headers=1`.
- Latitud/Longitud columns must have a consistent numeric format across all rows or GViz returns `null` for some cells and the event falls back to province centroid.
- Every event row needs an `Id` — the `?pendientes` confirm fetch uses `no-cors` and swallows errors silently if `Id` is missing.
- HikerAPI images arrive as webp but `_download_image` names them `.jpg`. Claude rejects the call if the declared `media_type` doesn't match the actual bytes — detect format from magic bytes, not filename.
