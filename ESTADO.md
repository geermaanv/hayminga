# Estado del proyecto (agosto 2026)

Resumen ejecutivo. El detalle línea por línea de cómo se llegó acá está en
`ROADMAP.md`; esto es la foto de "dónde estamos hoy" y "qué sigue".

## Arquitectura en una pasada

hayminga.org es un `index.html` estático (GitHub Pages) que lee eventos de
una Google Sheet vía GViz. La Sheet la alimenta un pipeline Python
(`import/src/hiker_pipeline.py`) que descubre flyers en Instagram por
hashtag y por cuenta seguida (HikerAPI), extrae los datos con Gemini Vision
(Claude como fallback pago) y escribe en la Sheet con dedup y cálculo
determinista de `Activo`. Dos canales más alimentan la misma Sheet: mail
con tag `HME` y el formulario web "+ Nuevo Evento" (Apps Script). Tres
workflows de GitHub Actions orquestan todo: `import-eventos.yml` (2x/día),
`curar-fuentes.yml` (diario, auto-baja/alta de fuentes) y
`enviar-resumen.yml` (semanal, Telegram + mail al Directorio).

## Qué funciona bien

- El pipeline de HikerAPI reemplazó por completo al de Google
  Images/SerpAPI y es notablemente más confiable: imagen completa, caption
  entero, fecha real de publicación, sin necesidad de scrapear Instagram
  sin sesión.
- Los filtros pre-IA (dedup por shortcode, blacklist, antigüedad, idioma
  por heurística de palabras) recortan el gasto en Gemini/Claude antes de
  llamarlos — barato y efectivo.
- La auto-curación de fuentes (`curar_fuentes.py`) funciona sola: da de
  baja hashtags/cuentas sin resultados y da de alta candidatas nuevas con
  un piso mínimo de señal (`MIN_SUGERENCIAS_PARA_AGREGAR`), sin intervención
  manual.
- Cobertura de tests razonable para el tamaño del proyecto: 39 tests,
  todas las llamadas a APIs externas mockeadas — se puede validar lógica
  sin gastar un centavo.
- El modelo `Activo`/`Estado` es simple y ya pasó por una ronda de
  simplificación (Etapa 9.5) que sacó ambigüedad real.

## Gaps conocidos, sin resolver

1. **País vacío en posts extranjeros** (ej. México confirmado en un caso
   real) — el filtro de idioma no ayuda cuando el post está en español
   pero de otro país. Sin heurística de reemplazo todavía.
2. **Duplicados del mismo evento con posts de Instagram distintos**: el
   dedup actual (shortcode exacto, o nombre+fecha+provincia) no agarra
   reposteos con texto/fecha ligeramente distintos del mismo organizador.
   El caso DeBarro (Etapa 9.5) fue el primero detectado; probablemente no
   el único. Pendiente: fuzzy matching o comparar por organizador/cuenta
   de origen en vez de solo por los campos extraídos.
3. **`SSLEOFError` intermitente en la Google Sheets API**: causó la
   pérdida de una corrida completa (ago 2026) antes de envolver la sección
   de cuentas seguidas en try/except. El fix actual es defensivo (loguear
   y seguir) pero no ataca la causa — sigue siendo un hiccup de red posible
   en cualquier otro punto del pipeline que no esté protegido igual.
4. **Costo de HikerAPI**: llegó a $4 en pocos días antes de los cortes
   (cron 3x→2x/día, caché de `user_id`). Estimado post-corte: ~$1.80/mes,
   pero el conteo de fuentes solo crece (auto-alta de cuentas vía
   `descubrir_candidatos()`), así que el costo real hay que vigilarlo, no
   asumirlo estable.
5. **`REVISION_MANUAL=true` sigue activo**: mientras dure, ningún evento
   se auto-publica — todo pasa por `?pendientes`. Es control de calidad
   deliberado durante la estabilización, pero es trabajo manual recurrente
   para Germán; no hay criterio documentado de cuándo se considera
   "estable" para desactivarlo.

## Recomendaciones, priorizadas

1. **Definir un criterio explícito para apagar `REVISION_MANUAL`** (ej.
   "N confirmaciones seguidas sin corrección manual" o "X semanas sin un
   falso positivo"). Es el mayor punto de fricción operativa recurrente
   ahora mismo y no depende de código nuevo, solo de una decisión.
2. **Atacar el duplicado por repost antes que el país vacío** — duplicados
   visibles en el sitio dañan la confianza del usuario final más que un
   evento con menos metadata. Una primera versión barata: comparar
   `username` de origen (ya se tiene, viene de HikerAPI) + ventana de fecha
   cercana, antes de meterse con fuzzy matching de texto.
3. **Instrumentar el costo de HikerAPI por corrida** (ya se loguea el
   conteo de llamadas informalmente en el roadmap, pero no hay un número
   por corrida visible en los logs de Actions) — así una expansión futura
   de `cuentas_seguidas` no repite el susto de los $4 en pocos días sin que
   nadie lo note hasta la factura.
4. **Repensar `hashtag/medias/top` en corridas repetidas**: cada corrida
   vuelve a pagar por los mismos 30 posts de siempre en hashtags de alto
   volumen (dedup por shortcode los descarta gratis, pero la llamada a
   HikerAPI ya se pagó). Si el costo sigue subiendo, evaluar si vale correr
   `top` con menos frecuencia que `recent`/cuentas seguidas — son señales
   con tasas de novedad muy distintas. **Esto es una propuesta, no se
   implementó** — el usuario tiene que confirmar el trade-off (menos
   cobertura de hashtags de alto volumen a cambio de menos costo).
5. **Considerar si los 3 workflows deberían ser 2**: `curar-fuentes.yml`
   corre diario "temporalmente, hasta tener más volumen" (según su propio
   comentario) — ya pasó un tiempo desde que se armó. Si el volumen de
   fuentes se estabilizó, bajarlo a semanal reduce superficie de fallos y
   ruido de Actions sin perder nada (la baja de una fuente mala no es
   urgente). **Propuesta, no implementada** — requiere confirmar que el
   ritmo de altas/bajas ya se asentó.

## Qué se tocó en esta auditoría, y qué no

- Se centralizó el parseo de fecha `DD/MM/YYYY`/`YYYY-MM-DD`, duplicado
  idéntico en `processor.py` y `enviar_resumen_telegram.py`, en
  `sheets.py.parse_fecha_flexible()`. Sin cambio de comportamiento.
- Se reescribió `import/README.md` (describía todavía el pipeline viejo de
  Google Images como si fuera el de producción) y el `README.md` raíz
  (era un stub de 2 líneas).
- **No se borró `main.py`, `src/scraper.py` (funciones de Google
  Images/SerpAPI/Serper) ni `src/candidates.py`**: confirmado contra los
  workflows reales que ningún cron los llama, pero se optó por dejarlos
  como referencia (mismo criterio que ya estaba documentado en
  `ROADMAP.md`) en vez de borrarlos — borrar código de un pipeline que
  costó varias iteraciones estabilizar es una decisión de producto, no de
  limpieza, y no había pedido explícito de borrarlo. Nota: `scraper.py` no
  está 100% muerto — `fetch_caption()` lo sigue usando `processor.py` como
  enriquecimiento opcional de contexto.
- No se tocó lógica de negocio, umbrales ni criterios de filtrado en
  ningún módulo — el pedido era refactor de forma, no de fondo.
- No se corrió ningún workflow de GitHub Actions ni se llamó a
  HikerAPI/Gemini/Claude con datos reales.

## Tests

27/27 pasando (`cd import && python -m unittest discover -s tests -q`).
El conteo bajó de 39 a 22 cuando se movió código a `import/legacy/` (los
tests de ese código se fueron con él); los 5 restantes son los nuevos de
`notificar_run.py`.
