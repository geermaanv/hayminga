# CLAUDE.md

Guidance for Claude Code when working on hayminga.org.

**Idioma:** responder siempre en español en esta conversación/repo — es como se habla con el mantenedor.

**Before making changes, read (in order):**
1. `ESTRATEGIA.md` — goal, phases, why each decision matters
2. `PATRONES.md` — critical patterns & constraints that affect code
3. `ROADMAP.md` — narrative history: what's been tried & learned

**Keep the docs current, not per-commit.** A `pre-commit` hook (`.githooks/pre-commit`, enabled via `git config core.hooksPath .githooks`) blocks commits that touch `import/src/*.py`, `index.html`, `Code.gs`, or workflow files once 4+ commits have passed since `ROADMAP.md` was last touched. This isn't "one entry per commit" — that would turn ROADMAP into a git-log mirror, which defeats its purpose as a narrative. It's a forced checkpoint: before the 5th commit in a row without touching it, stop and ask "does anything here deserve a paragraph?" Real failure this caught: 17 commits (favicon, WhatsApp community migration, geocoding, dedup by account, the whole Instagram content queue) landed before anyone went back to ROADMAP. Bypass with `git commit --no-verify` only when the user explicitly says the change is minor — don't reach for it by reflex.

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
python -m src.backfill_cuentas_email               # one-off, costs HikerAPI calls: backfill País/Email for cuentas_seguidas cached before those fields existed (--escribir to apply)
python -m src.avisar_organizadores_retroactivo     # one-off, costs HikerAPI calls + sends real email: notify organizers of already-published events that never got avisar_evento_publicado (e.g. hashtag events before 16/09) — dry-run by default, --escribir to send, --limite=N to cap, --desde=YYYY-MM-DD to widen the window (default: this week), --uno-por-cuenta to send only the most recent event per account (avoids bombarding an org with several mails in one batch)
python -m unittest discover -s tests -v           # tests (all external calls mocked)
gh workflow run import-eventos.yml -R geermaanv/hayminga  # manual trigger
```

**Cost:** `hiker_pipeline`, `curar_fuentes`, and `enviar_resumen_telegram` spend real money (HikerAPI, Gemini/Claude). Validate code changes via tests instead (all external calls are mocked).

**Active configuration flags:**

- **`CONFIANZA_PUBLICABLE = {"alta", "media"}`** (`processor.py`) — the single publish-vs-review threshold for the whole Python pipeline: an extracted event with `activo=True` (name+date+location resolved) publishes straight away (`Estado=confirmado`) only if `confianza` is in this set; `"baja"` always lands in `pendiente_confirmacion` for review at `hayminga.org/?pendientes`. See "Corrección" entry, ROADMAP.md 22/09 — there used to be a `REVISION_MANUAL` flag documented as gating *everything*, but it only ever applied to the mail-intake path (`extract_event_data`, used by `email_intake.py`); the HikerAPI path (`hiker_pipeline.py`, the actual high-volume channel) never checked it and has been auto-publishing on high confidence in production regardless of what this doc said. `REVISION_MANUAL` is gone; both paths now share `CONFIANZA_PUBLICABLE`.
- **`Code.gs`'s own `REVISION_MANUAL`** (web form `+ Nuevo Evento` only) is unrelated and unchanged — that channel has no AI/no confianza score (a person types the form), so it keeps its own manual-review gate.
- **`HIKERAPI_KEY`** — required for production. Local: `.env`. CI: GitHub Actions secret.
- **`GEMINI_MIN_INTERVAL_SECONDS`** — rate pacing. Default 4.5s (free tier: 15/min). Production: 0.5s (billing enabled).

## Pipeline: event discovery & extraction

**Discovery:** HikerAPI, two channels — hashtags (`config.json.hashtags`, ~30-40 curated) and followed accounts (`config.json.cuentas_seguidas`, 74+).

**Pre-AI filters (cheap, run before LLM):**
- Dedup by Instagram shortcode (`/p/`, `/reel/`, `/reels/` → same post)
- Blacklist (`config.json.cuentas_excluidas`)
- Post age > 180 days (dropped from 270; see PATRONES.md) — this is about when the *Instagram post* was published, a cost-control heuristic; it's separate from and looser than the post-extraction "event date already passed" check below, which is the actual correctness gate once a date is known.
- Language: `_parece_extranjero()` on caption (regex word-lists for English **and Portuguese**, added 22/09) — blocklist, not allowlist: with <6 words to judge (common when all the real info is in the flyer image, not the caption) it lets the post through rather than guessing, because there's no human review downstream if this drops something wrong.

**Extraction strategy:**
1. Gemini text-only on caption (cheap, filters non-events)
2. If ambiguous/event: Gemini + image (recovers more fields)
3. Fallback to Claude if Gemini quota hit (capped by `MAX_CLAUDE_CALLS_PER_RUN`, Claude is paid)
4. Timeout: `genai.Client` must set `timeout=30_000` (real incident: 44min hang)
5. `es_evento` (22/09): the prompt also marks `false` for a post that thanks/recaps something already past ("gracias a quienes vinieron...") with no future date invited, even if it's clearly about bioconstrucción — otherwise these sat in `pendiente_confirmacion` forever with no date to filter on.
6. `confianza` (22/09): the prompt now spells out what each level means instead of leaving it to the model's judgment — **alta**: name, date (year explicit, not inferred) and location all stated outright; **media**: real and clear event but something secondary is missing/imprecise, or the year was inferred from the reference date; **baja**: something critical is ambiguous (vague name, unclear date, unsure it's even a bioconstrucción event).

**Coordinates** (priority, top wins): location tagged on the post → geocoding of the extracted `direccion` via Nominatim (free) → nothing, and the frontend falls back to the province centroid. Most posts carry no tagged location, so without geocoding ~70% of events landed in the middle of their province.

**Post-extraction validation** (`hiker_pipeline.py`'s `procesar_post`, deterministic, no AI):
- Drop already-happened events (fecha_fin/inicio < today)
- Drop non-Argentina (only once `pais` is actually resolved — see `_pais_desde_texto`/`_pais_desde_telefono` fallbacks)
- Drop virtual events where `pais` was never resolved anywhere (flyer, contact, or account) — added 22/09; previously these just sat in `pendiente_confirmacion` forever without ever activating, since "virtual" alone was never enough to publish without knowing the country.
- Drop non-Spanish (`idioma` extracted by the AI ≠ `"es"`) — added 22/09 as defense-in-depth alongside the pre-AI `_parece_extranjero()`; this was documented before but never actually implemented.

**Write:** Dedup by `(nombre, fecha, provincia)`. Ambiguous match → `pendiente_confirmacion` with note linking to existing event (manual merge, no silent loss). `Activo` computed deterministically; never from LLM.

**Curation:** `FuentesStats` sheet tracks hits/misses per source. `curar_fuentes.py` auto-removes stale sources (50+ dry runs), auto-adds new candidates from Instagram.

## Data model

**Event state:** Two orthogonal fields per row:
- `Activo` (true/false) — controls visibility on site
- `Estado` — curation state: `confirmado`, `pendiente_confirmacion` (review queue), `descartado` (blacklisted, but dedup still tracks it)
  - Older values (`pendiente`, `revision_fuente`, `pendiente_organizador`) collapsed into `pendiente_confirmacion` or removed — don't reintroduce.

**Organizer notification by email** (09/2026, see ROADMAP.md): manual review doesn't scale, so when HikerAPI's profile lookup returns a `public_email` for the account that posted the event, `hiker_pipeline.py` publishes it straight away (`Estado=confirmado`, `Activo=true`, skipping `pendiente_confirmacion` entirely) — having a public business email is treated as enough of a trust signal on its own. It then calls `Code.gs` (`avisar_evento_publicado`, same shared-secret channel as `subir_imagen`) to email the organizer that their event is live, with two CTAs: join the Directorio (explained, not just linked) and tag `@hayminga` next time so it gets picked up automatically. No confirm/reject click, no token, no separate tracking sheet — if something's wrong the organizer just replies to the mail and it gets fixed by hand. Capped at `_MAX_VALIDACIONES_ORGANIZADOR_POR_CORRIDA` (10) mails per run — a trickle, not a blast, same reasoning as `MAX_ALTAS_POR_CORRIDA` in `curar_fuentes.py`; the cap only throttles the mail, never the publication.
- Email cached per account in `CuentasIds!EmailPublico` (same free-lookup, partial-coverage pattern as `PaisTelefono`) — `sheets.cargar_cuentas_email()`.
- **Runs for every event, hashtag- or `cuentas_seguidas`-sourced** (16/09/2026) — `_intentar_publicar_con_email()` is the shared check both discovery loops call right after `procesar_post()` returns an event. For `cuentas_seguidas` the email is already known for free (same call that resolves the account's `user_id`). For hashtags there's no free per-account lookup, so it pays one `resolver_user_id_pais_y_email()` call per *event that survived extraction* (`resolver_si_falta=True`) — cheap because it's gated on real candidates, not the ~800 raw posts a hashtag run pulls before filtering.
- No dedup by account: an org that already got a mail (this run or a previous one) still gets a new one for a new event — each event is its own notification, by design.
- The mail is conditional, not always the same text: `sheets.cargar_emails_directorio()` skips the Directorio paragraph if that email is already registered, and `ya_taggeado_hayminga` (regex over the post caption for `#hayminga`/`@hayminga`) swaps the "tag us next time" line for a thank-you when the post already did.
- The Directorio CTA links to `hayminga.org?directorio=1`, which opens the signup form directly (mirrors the `?pendientes` deep link).
- The email lookup only runs `if user_id is None` (to avoid a paid call per account per run), so accounts already cached in `CuentasIds` before this feature existed never get `EmailPublico` backfilled by the daily pipeline itself. Fixed with a one-off manual script, not a pipeline change (see `backfill_cuentas_email.py` above) — it's a static profile field, doesn't need to be re-checked daily.

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
