# hayminga-web

Sitio estático de [hayminga.org](https://hayminga.org): calendario de eventos
de bioconstrucción en Argentina, con directorio de personas interesadas en el
tema. Un solo `index.html` (vanilla JS + Leaflet, sin build) que lee sus datos
en vivo de una Google Sheet vía GViz — no hay backend propio para el
frontend.

Los eventos se alimentan solos: un pipeline en Python (`import/`) descubre
flyers en Instagram, extrae los datos con IA y los escribe en la Sheet, todo
corriendo en GitHub Actions. Ver `import/README.md` para la arquitectura y el
setup del pipeline, y `ROADMAP.md` para el historial completo de decisiones
(por qué se hizo así, qué se probó y se descartó).

`CLAUDE.md` tiene la referencia operativa rápida para trabajar en el repo
(qué corre en producción, comandos, convenciones, gotchas conocidos).
