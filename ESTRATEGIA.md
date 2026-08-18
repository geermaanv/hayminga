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

| KPI | Actual | Meta | Cómo medir |
|-----|--------|------|-----------|
| **% eventos a pendientes** | ~15% | <12% | pendientes / eventos_importados |
| **Tasa de publicación** | ~85% | >80% | confirmados / (confirmados + descartados) |
| **Antigüedad pendientes** | ~1.5d | <2d | promedio días en estado pending |
| **Eventos activos** | 30-40 | 50+ | count(Activo=true, Estado=confirmado) |
| **% sin imagen necesaria** | TBD | >40% | eventos_resueltos_solo_caption / total_procesados |

---

## Estado actual (agosto 2026)

**Fase:** 1 (Importación automática)

**KPIs:**
- ✅ % a pendientes: ~15% (meta: <12%)
- ✅ Tasa de publicación: ~85% (meta: >80%)
- ✅ Antigüedad promedio: ~1.5 días (meta: <2d)
- ⏳ Eventos activos: 30-40 (meta: 50+)
- ❌ Sin imagen necesaria: TBD (medir próxima corrida)

**Directorio (segundo pilar):** 0 personas reales. El modelo de datos quedó rediseñado (técnicas con relación + intereses por actividad), así que lo que falta no es producto sino gente. La lista de invitación existe y es concreta: **~30 organizadores** identificados en los eventos ya publicados. El contacto es tibio, no frío — sus eventos ya están en el sitio, así que el pedido es "¿querés perfil?" y no "¿quién sos?". Y el mismo contacto sirve después para pedirles que carguen sus eventos (Fase 3).

Ojo con la secuencia: hasta que haya volumen, los filtros del Directorio no se muestran. Un filtro que siempre devuelve vacío es peor que no tenerlo.

**Foco AHORA:**
1. 🎯 **Mejorar % a pendientes** — reducir de 15% a <12%
   - Automatizar detección (país, idioma, fecha)
   - Reducir ruido en importación
2. 🔍 **Validar importancia de imagen** — medir si vale la pena descargar
3. 🔎 **Explorar Eventbrite** si Instagram se satura (probablemente 90% ahí)
4. 📊 **Medir tráfico** — agregar GA4 para entender usuarios

**NO hacer ahora:** Fase 2/3, refactor, features. Todo debe servir a mejorar KPIs F1.
