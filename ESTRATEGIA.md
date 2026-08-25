# Estrategia de hayminga.org

## Objetivo

Ser el **portal de referencia del mercado de bioconstrucción en Argentina**: lugar donde encontrar eventos y profesionales de la industria.

## Por qué importa

La bioconstrucción es dispersa (eventos anunciados en Instagram, profesionales sin presencia centralizada, sin "punto de entrada" único). Sin un lugar que aglutine oferta + demanda, no hay mercado visible. Sin mercado visible, no hay crecimiento.

## Fases

### 🏗️ Fase 1: Importación automática (HOY)

**Meta:** Llenar el portal con suficientes eventos para que sea **referencia útil** (masa crítica).

**Cómo funciona:**
- **Eventos:** Importación 100% automática desde Instagram (HikerAPI + hashtags + cuentas seguidas)
- **Validación:** TODO a revisión manual (`REVISION_MANUAL=true`)
- **Profesionales:** Directorio manual (formulario de alta con opt-in)

**KPI principal:** Bajar cantidad de pendientes por corrida (menos ruido → menos revisión manual)

**Trade-offs en esta fase:**
- **Cobertura > Precisión:** Mejor tener un evento mediocre que ninguno
- **Auto-descubrimiento > Control:** Aceptamos ruido porque filtro de revisión lo atrapa
- **Rapidez de iteración > Perfección:** Cambios sin miedo (antigüedad, endpoints, etc.)

---

### 🔍 Fase 2: Validación por organizador (PRÓXIMA)

**Meta:** Reducir carga manual, dejar que origen valide.

**Cómo funciona:**
- **Eventos:** Importación automática SIGUE igual (Instagram + otras fuentes)
- **Validación:** El **organizador que originó el evento** lo valida (app/email/WhatsApp)
  - "¿Es correcto este evento? Sí → Publica | No → Rechaza"
  - Si no responde en X días → fallback a revisión manual
- **Profesionales:** Igual

**KPI:** 70%+ de eventos validados por origen sin intervención manual

**Trade-offs:**
- **Automatización > Control:** Confiamos en que el organizador valide su propio evento
- **Velocidad de publicación:** Baja de 24h a minutos

---

### 🌱 Fase 3: Aporte directo (FUTURA)

**Meta:** Organizadores pueblan la base de datos.

**Cómo funciona:**
- **Eventos:** Organizadores publican directo (formulario web + WhatsApp + mail)
- **Importación automática:** Red de seguridad (catch-all)
- **Meta de aporte:** 30%+ de eventos nuevos vienen de organizadores directamente

**Trade-offs:**
- **Control > Automatización:** Cada evento es verificado en origen
- **Costo operacional:** Baja (menos importación = menos APIs)

**Señales de transición a esta fase:**
- 30%+ de eventos nuevos vienen de aporte directo
- Organizadores contribuyen sin necesidad de notificación (pull, no push)
- Sitio tiene tráfico orgánico consistente

---

## Decisiones clave en cada fase

| Decisión | Fase 1 | Fase 2 | Fase 3 | Rationale |
|----------|--------|--------|--------|-----------|
| **¿Quién valida?** | Revisión manual (100%) | Organizador origin (automatizado) | Organizador (al publicar) | F1: Aprendemos. F2: Confiamos en origen. F3: Origen publica |
| **Cobertura de eventos** | 33 hashtags + 74 cuentas | 33+ hashtags (mejorar calidad) | 10-15 hashtags + aporte directo | F1: Volumen. F2: Mejorar imports. F3: Reducir imports |
| **KPI principal** | Bajar pendientes/corrida | 70% validado sin manual | 30% de aporte directo | F1: Automatización. F2: Confianza. F3: Contribución |
| **Costo de importación** | Optimizar rapidez/volumen | Optimizar eficiencia | Mínimo (red de seguridad) | F1: Urgencia justifica costo. F2/3: Bajo ROI |
| **Explorar nuevas fuentes** | Enfocarse en Instagram (90%) | Sí, si baja costo | Solo si insuficiente F3 | F1: Instagram es suficiente. F2: Exploración. F3: Decide data |

---

## Criterios para cada tipo de cambio

### Feature (nueva funcionalidad)
**Pregunta:** ¿Acerca al portal a ser referencia?
- **Sí:** Hacer (puede esperar a fase 2 si no es urgente)
- **No:** Rechazar

**Ejemplos:** 
- ✅ Contador de pendientes en header (ayuda a gestión)
- ✅ Directorio de profesionales (segundo pilar del portal)
- ❌ Sistema de comentarios (bonito pero no resuelve problema de mercado)

### Optimización (mejorar lo que existe)
**Pregunta:** ¿Achica costo/tiempo sin sacrificar volumen en Fase 1?
- **Sí:** Priorizar
- **No:** Posponer a Fase 2

**Ejemplos:**
- ✅ Detección temprana de país (evita descargas inútiles)
- ✅ Descarga diferida de imagen (ahorra tiempo)
- ❌ Refactoring de código (limpieza de tech-debt)

### Bug (algo roto)
**Siempre prioritario si:**
- Afecta importación de eventos (data loss, crashes)
- Afecta visualización en sitio (UX pública)
- Es fácil de arreglar

**Puede esperar si:**
- Afecta solo UX admin
- Es workaround temporal (ej. email manual vs automático)

---

## Criterios de transición

### Fase 1 → Fase 2
**Cuándo:** Importación es estable + volumen suficiente

1. ✅ Sitio tiene 50+ eventos activos públicos
2. ✅ Cantidad de pendientes por corrida: <10 (ruido bajo)
3. ✅ Importación no requiere ajustes semanales
4. ✅ El 10%+ de eventos nuevos vienen de aporte directo

**Acción:** Implementar validación por organizador (notificar al origen)

### Fase 2 → Fase 3
**Cuándo:** Validación automática funciona + aporte directo crece

1. ✅ 70%+ de eventos validados por origen sin intervención manual
2. ✅ El 30%+ de eventos nuevos vienen de aporte directo
3. ✅ Sitio tiene tráfico orgánico consistente
4. ✅ Organizadores contribuyen sin notificación (pull, no push)

**Acción:** Reducir cron de importación, priorizar canal de aporte directo

---

## Principios transversales

**1. Medir antes de decidir**
- No "creo que...", sino "medí y..."
- Ejemplos: recent vs top (tabla con números), país vacío (casos reales)

**2. No optimizar lo que no importa**
- Fase 1: Importar es lo que importa
- No perder tiempo en código limpio si el cambio logra volumen
- Deuda técnica = costo aceptado

**3. Mantener reversibilidad**
- Todo debería poder cambiar sin romper (flags, configs, no hardcode)
- Ejemplo: `REVISION_MANUAL`, `USAR_TOP`, `config.json`

**4. Documentar decisión + rationale**
- No solo "qué hicimos" sino "por qué en ese momento"
- Ej. ROADMAP.md: problema → datos → decisión

**5. Contacto directo con usuarios reales**
- No decisiones por intuición
- Organizadores, profesionales, visitantes dicen qué necesitan

---

## KPIs por fase

### Fase 1 (HOY): Importación automática

| KPI | Actual (25/8, ventana 7 días) | Meta | Cómo medir |
|-----|------|------|-----------|
| **Tasa de publicación** | **44%** | >80% | confirmados / (confirmados + descartados) |
| **% a pendientes (backlog actual)** | 0% | — | ver nota: métrica a redefinir |
| **Eventos activos** | **66** ✅ | 50+ | count(Activo=true) |
| **% sin imagen necesaria** | 9.4% (resuelto) | — | la imagen es crítica, no tocar esa parte del pipeline |

**La tasa de publicación bajó, no subió — y no está claro por qué todavía.** El número viejo (~85%) nunca se recalculó con datos reales; el 44% de esta semana es la primera medición real de este KPI. Antes de asumir que el pipeline empeoró: puede ser que haya crecido el volumen de fuentes (más hashtags/cuentas = más ruido de otros temas), o que el criterio de descarte se haya vuelto más estricto sin querer. **Pendiente: mirar qué se está descartando esta semana y por qué**, con el mismo criterio con que se midió caption-vs-imagen (leer los casos reales, no solo el número).

**"% a pendientes" tal como estaba definido ya no mide lo que se quería medir.** Da 0% ahora mismo, pero es porque se revisa `?pendientes` el mismo día, no porque haya menos ambigüedad en la importación — un snapshot de backlog en un momento dado no es lo mismo que una tasa de ruido. Repensar esta métrica antes de seguir reportándola.

---

## Estado actual (25 de agosto, 2026)

**Fase:** 1 (Importación automática)

**Eventos activos: 66 — superó la meta de F1 (50+).** La importación viene mejor de lo que este documento reflejaba (decía 30-40 hace una semana). Vale la pena discutir si la meta de F1 debería subirse, o si el foco ya puede empezar a correrse hacia F2.

**Directorio (segundo pilar): 1 fila (de prueba), 0 organizadores reales.** El modelo de datos y el formulario ya están resueltos (texto libre + disponibilidad para trabajos). Lo que falta **no es más producto — es ejecutar el contacto que ya está preparado**: 35 mensajes de invitación, uno por cuenta que organizó un evento ya publicado, esperando en la hoja `Instagram` desde hace varios días sin que se haya mandado ninguno. Es la acción pendiente más importante del proyecto hoy.

Ojo con la secuencia: hasta que haya volumen, los filtros del Directorio no se muestran. Un filtro que siempre devuelve vacío es peor que no tenerlo.

**Foco AHORA:**
1. 🎯 **Mandar los primeros DM de la cola de Instagram** — es lo único que falta para que el Directorio deje de estar vacío. Ver `INSTAGRAM.md` para el ritmo seguro (5-8 por día, cuenta nueva).
2. 🔍 **Investigar por qué bajó la tasa de publicación** (85% asumido → 44% medido) antes de tocar el pipeline a ciegas.
3. 📊 **Medir tráfico** — agregar GA4 para entender usuarios, sigue pendiente desde la primera versión de este documento.
4. 🔎 Explorar Eventbrite u otras fuentes: baja prioridad — la imagen resultó crítica y el caption solo no alcanza, así que el foco de eficiencia ya no está ahí.

**NO hacer ahora:** Fase 2/3, refactor, features. Todo debe servir a mejorar KPIs F1.
