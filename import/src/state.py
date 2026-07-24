"""
state.py
Estado persistente compartido: qué imágenes/posts ya tuvieron un resultado
definitivo (evento extraído o confirmado que no es un flyer).
Solo se marca "vista"/"visto" después de un resultado definitivo — así una
falla transitoria (ej. sin cuota) no descarta la imagen para siempre.

Dos niveles de dedup:
- hash de imagen: evita reprocesar bytes idénticos.
- link del post: evita re-descargar el mismo post de Instagram cuando
  aparece en los resultados de varias queries distintas (muy frecuente).
"""

import hashlib
from pathlib import Path

SEEN_FILE       = Path("seen_hashes.txt")
SEEN_LINKS_FILE = Path("seen_links.txt")


def image_hash(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def load_seen_hashes() -> set:
    if not SEEN_FILE.exists():
        return set()
    return set(SEEN_FILE.read_text().splitlines())


def save_hash(h: str):
    with open(SEEN_FILE, "a") as f:
        f.write(h + "\n")


def load_seen_links() -> set:
    if not SEEN_LINKS_FILE.exists():
        return set()
    return set(SEEN_LINKS_FILE.read_text().splitlines())


def save_link(link: str):
    if not link:
        return
    with open(SEEN_LINKS_FILE, "a") as f:
        f.write(link + "\n")
