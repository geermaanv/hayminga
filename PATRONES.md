# Patrones y restricciones clave

Lecciones operacionales extraídas de ROADMAP.md y experiencia en producción.
Patrones que afectan decisiones de código y arquitectura.

## Data & Sheets

**Image links from Instagram expire** — always upload to Drive, never store direct URLs.
- Real incident: 22/37 eventos (59%) con imagen rota después de semanas.
- Fix: `subir_imagen_a_drive()` en `hiker_pipeline.py`, `subir_imagen` en `Code.gs`.
- Si upload a Drive falla, fallback a link de Instagram (mejor algo temporal que nada).

**Sheets API calls can fail transiently** — implement retries (3 attempts, 2s wait).
- Real incident: `SSLEOFError` intermitente en `cargar_cuentas_ids()`.
- No es un error de datos, es red — reintentar es lo correcto.

**Formula injection risk** — any cell starting with `+`, `=`, or `-` gets interpreted as formula.
- Sanitize on write (pre-format as text, or prefix with `'`).

**GViz parsing is fragile** — needs `&headers=1`, numeric format consistency.
- Latitud/Longitud: inconsistent format → GViz returns `null` → fallback a centroid.
- Caption con 100% texto: header detection fails → use `&headers=1`.

**Adding a column to an existing sheet needs the header backfilled explicitly.**
- `getOrCreateSheetWithHeaders_` (Apps Script) originally wrote headers *only when creating* the sheet. Adding `Tecnicas`/`AnioDesde` to the existing `Directorio` wrote data into H/I with no header → GViz can't name the column → frontend reads `undefined`, silently.
- Both the Python (`src/sheets.py`) and Apps Script versions now backfill missing headers. Keep them in sync.
- Failure mode is invisible: the form says "¡Listo!" and the data is lost.

**Delimiter choice: check the values first.**
- `Intereses` was comma-separated until a value contained a comma ("Organizar mingas, talleres o eventos") and got split into two chips. Now `;`.
- `Tecnicas` uses `;` between pairs and `/` between relations (`quincha:hago/enseno`). Plain text on purpose — legible from the Sheet and no escaping, unlike JSON. The form strips `;`/`:` from technique names on write.

**A read immediately after a `batchUpdate` can be stale.** Verify a write with a separate later read, not the one in the same breath — it caused a false "I deleted the wrong rows" scare.

## Filtering & Validation

**Date filters interact — both needed, not redundant.**
- "Post age" (180 days): removes old content that announced future events.
- "Event already happened" (fecha_fin/inicio < today): catches events announced recently but happened already.
- Real case: 252-day post announced future event. Missed one filter, caught the other.
- If either alone, events slip through.

**Language detection before image download** — text-only regex more reliable than LLM.
- `_parece_ingles()` on caption: fast, free, no hallucinations.
- LLM `idioma` field: unreliable when flyer is ambiguous, arrives late (costs time/money).
- Trust regex first; use LLM output only as secondary confirmation (and only if needed).

**Pre-AI filters = cost control** — every cheap filter before IA call saves money.
- Dedup (shortcode), blacklist, age, language → run before download + extraction.
- Real: 33 hashtags + 140 accounts = ~4,200 posts; 80-90% filtered free.

**Country detection priority order:**
1. Text/caption (free, `_pais_desde_texto()`)
2. Phone prefix (free, `_pais_desde_telefono()`)
3. Flyer/image (LLM, expensive)
4. Account profile (`pais_cuenta`, weakest — only if nothing else worked)

Never let account profile override explicit country signals in caption or flyer.

## Operations & Reliability

**Incremental saves, never batch at end** — timeout kills whole batch otherwise.
- Real incident: 45min run lost entirely when GitHub killed process at timeout.
- `append_events()` called after each hashtag/account source, not once at the end.
- `FuentesStats`/`CuentasIds` saved at end (lower severity if lost).

**genai.Client hangs indefinitely without timeout** — must set `timeout=30_000`.
- Real incident: 44min silent hang; logs never arrived (PYTHONUNBUFFERED issue).
- Timeout required even on free tier, especially with network hiccups.

**Transient network errors need graceful fallback** — wrap high-risk sections.
- `SSLEOFError`, 504/503 from Gemini, HikerAPI timeouts are all transient.
- Try/except + retry on transient errors; log and skip on persistent ones.
- Don't let one failed source (cuentas_seguidas) kill the whole run (happened with hashtags already done).

**Gemini rate limits differ by tier.**
- Free tier: 15 calls/minute (default `GEMINI_MIN_INTERVAL_SECONDS=4.5`).
- Production (billing enabled): 0.5s interval, much higher ceiling.
- Configurable by env var — no code changes needed.

## Architecture Constraints

**Frontend ↔ Importer coupled via column order in Sheets** — always append, never reorder.
- Column positions are load-bearing for both frontend (GViz JSON) and importer (`sheets.py`).
- Existing positions: hard to move. New columns: always at the end.

**Apps Script mirrors must be manually deployed** — changes in repo don't auto-sync.
- `import/apps-script/Code.gs` is a mirror.
- Changes only take effect after copying into script.google.com and deploying (Implementar → Gestionar implementaciones → Nueva versión).

**REVISION_MANUAL flag gates auto-publish globally** — flip both places.
- `import/src/processor.py` AND `import/apps-script/Code.gs`.
- When true: everything lands as `Estado=pendiente_confirmacion`, waits for manual review at `hayminga.org/?pendientes`.
- When false: `confianza=alta` publishes directly, `media`/`baja` still goes to review.

**Dedup signals must widen the review net, never the discard net.** Three layers now (shortcode, exact key, fuzzy) and none of them ever deletes: an ambiguous match is inserted anyway as `pendiente_confirmacion` with a note pointing at the other Id.
- The fourth signal (same Instagram account + near-identical name, ignoring date and province) closes the gap left open in Etapa 9.8 — the account was the missing evidence and simply wasn't persisted.
- The danger it introduces is specific to this market: courses are routinely taught in modules or repeated several times a year. "Taller de Wood Frame" and "Taller de Wood Frame Módulo II" share every meaningful token of the shorter name, so the similarity ratio is 1.0 and they look identical. Hence `_MARCAS_DE_EDICION`: if what distinguishes the two names is an edition marker, it is not a duplicate.
- Tune this kind of rule with a **dry run against real rows** before turning it on. The threshold turned out to be almost irrelevant (9 pairs at 0.99, 10 at 0.6) — the false positive worth fixing only showed up by reading the actual pairs.

**The site does not rank people.** It shows what each person says about themselves and lets the searcher filter.
- This came up three times in one session, disguised each time: a `matrícula` field, a per-technique "nivel de experiencia", and an `ofrece`/`en camino` badge computed on the card. All three felt reasonable when proposed; all three sorted people into classes.
- Self-declared levels also mis-calibrate here: in a minga culture, declaring yourself "avanzado" is socially awkward, so the people who know most under-report.
- What replaced them: behavioural, checkable claims (*la enseño*, *la hago para otros*, *en obra propia*, *la estudio*) that carry the same information without a verdict.
- Rule of thumb: **filtering is an action of the person searching; labelling is a judgement about the other.** If a distinction is needed, put it in a filter above the grid, not as a stamp on the card.

**Evento `Activo` computed deterministically, never from LLM.**
- Requires: name + fecha_inicio + anio_confirmado + valid range + fecha >= today + pais == "Argentina".
- LLM output unreliable (especially on ambiguous flyers); validation is the source of truth.

## Every message to users must include CTA.

Telegram digest, Directorio email, form confirmations, WhatsApp copy: all must remind users how to contribute.
- Share by WhatsApp, send by mail, or tag `#hayminga` on Instagram.
- Standing product rule.
