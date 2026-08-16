# Estrategia de hayminga.org

## Objetivo

Ser el **portal de referencia del mercado de bioconstrucción en Argentina**: lugar donde encontrar eventos y profesionales de la industria.

## Por qué importa

La bioconstrucción es dispersa (eventos anunciados en Instagram, profesionales sin presencia centralizada, sin "punto de entrada" único). Sin un lugar que aglutine oferta + demanda, no hay mercado visible. Sin mercado visible, no hay crecimiento.

## Fases

### 🏗️ Fase 1: Importación agresiva (HOY)

**Meta:** Llenar el portal con suficientes eventos + profesionales para que sea **referencia útil** (masa crítica).

**Cómo funciona:**
- **Eventos:** Importación automática desde Instagram (HikerAPI + hashtags + cuentas seguidas)
- **Profesionales:** Directorio manual (formulario de alta con opt-in)

**Por qué importación agresiva:**
- Sin eventos no hay atracción, sin atracción no hay usuarios
- Sin usuarios no hay organizadores dispuestos a aportar
- Necesitamos "priming" del mercado

**Trade-offs en esta fase:**
- **Cobertura > Precisión:** Mejor tener un evento mediocre que ninguno
- **Auto-descubrimiento > Control:** Aceptamos ruido (cuentas malas, países extranjeros) porque el filtro de revisión manual los atrapa
- **Rapidez de iteración > Perfección:** Cambios de criterio sin miedo (antigüedad 270→180 días, cambio de endpoint, etc.)

**Validación de éxito:**
- Eventos activos: meta inicial es 50+
- Usuarios que visitan el sitio regularmente
- Organizadores que empiezan a aportar sin ser pedidos

---

### 🌱 Fase 2: Transición a contribución orgánica (PRÓXIMA)

**Meta:** Que la mayoría de eventos nuevos vengan de organizadores directamente, no de importación automática.

**Cómo funciona:**
- **Eventos:** Organizadores publican directamente (formulario web + WhatsApp + mail)
- **Importación:** Pasa a ser red de seguridad (catch-all para eventos que no se enteran del portal)
- **Profesionales:** Directorio auto-actualizable por los mismos profesionales

**Trade-offs en esta fase:**
- **Precisión > Cobertura:** Cada evento es verificado por origen
- **Control > Rapidez:** Cambios son más cuidadosos (impactan menos volumen)
- **Costo operacional:** Baja (menos importación = menos llamadas a APIs)

**Señales de que estamos listos:**
- 30%+ de eventos nuevos vienen de contribución directa
- Organizadores aportan sin necesidad de notificación (pull, no push)
- Sitio tiene tráfico orgánico (usuarios regresan)

---

## Decisiones clave en cada fase

| Decisión | Fase 1 | Fase 2 | Rationale |
|----------|--------|--------|-----------|
| **Auto-publicar o revisar?** | Revisar (`REVISION_MANUAL=true`) | Auto-publicar (confianza alta) | F1: Aprendemos criterios. F2: Confiamos en origen |
| **Cobertura de eventos** | 33 hashtags + 74 cuentas | 10-15 hashtags curados | F1: Necesitamos volumen. F2: Ruido es caro |
| **Costo de importación** | Optimizar para rapidez/volumen | Optimizar para eficiencia | F1: La urgencia justifica costo. F2: No hay urgencia |
| **Re-intentos/Reintentos** | 3 intentos, reintentos agresivos | Sin reintentos, "fail fast" | F1: No queremos perder nada. F2: Confiamos en origen |
| **Curación de fuentes** | Auto (50+ intentos = baja) | Manual (revisar semanal) | F1: Automatizar todo. F2: Control |

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

## Cuándo pasar a Fase 2

**No es una fecha, es un estado:**

1. ✅ Sitio tiene 50+ eventos activos públicos
2. ✅ Mínimo 10 organizadores aportando voluntariamente
3. ✅ Tráfico mensual: 500+ visitantes únicos
4. ✅ Importación automática es estable (no requiere ajustes semanales)
5. ✅ El 20%+ de eventos nuevos vienen de aporte directo

Cuando se cumplan estos criterios, **flip `REVISION_MANUAL = false`** y reduce cron de importación.

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

## Estado actual (agosto 2026)

**Dónde estamos:** Mitad de Fase 1
- ✅ 30-40 eventos activos (meta: 50)
- ✅ Sistema de importación automática estable
- ⏳ Aporte voluntario de organizadores: incipiente
- ⏳ Tráfico: no medido aún (TODO: agregar GA4 tracking)

**Foco ahora:** Escalar a 50+ eventos, refinar criterios de calidad
