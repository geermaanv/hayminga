# Código archivado

Nada acá corre en producción ni se importa desde `src/` — es referencia
histórica del pipeline original (Google Images vía SerpAPI/Serper),
reemplazado por `src/hiker_pipeline.py`. El detalle de por qué y cuándo
está en `ROADMAP.md` (raíz del repo).

- `main.py` — entrypoint del pipeline viejo.
- `scraper_google_images.py` — búsqueda/descarga de imágenes vía Google
  Images (SerpAPI + Serper de respaldo).
- `candidates.py` — cola de reintentos persistente (hoja `Candidatos`
  del Sheet). `hiker_pipeline.py` no tiene equivalente a propósito.
- `test_candidates.py` — tests de `candidates.py`, movidos acá junto
  con el código que prueban (no corren como parte de la suite activa).

Estos archivos ya no se mantienen actualizados contra el resto del
código (ej. sus imports a `src.scraper` pueden no resolver, esas
funciones se movieron acá mismo). Si algún día hace falta reactivar
algo de esto, hay que revisarlo con cuidado, no asumir que anda tal
cual.
