"""
scraper.py
Busca imágenes en Google Images filtrando por última semana (qdr:w)
y tamaño grande (isz:l). Sin SerpAPI — usa requests directo.
"""

import os
import re
import time
import hashlib
import requests
import json
from pathlib import Path
from datetime import datetime

IMAGES_DIR = Path("images")
SEEN_FILE  = Path("seen_hashes.txt")
CONFIG_FILE = Path("config.json")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-AR,es;q=0.9",
}

VALID_MAGIC = {
    b'\xff\xd8\xff': 'jpg',
    b'\x89PNG':      'png',
    b'RIFF':         'webp',
}


def load_config() -> dict:
    return json.loads(CONFIG_FILE.read_text())


def get_queries_for_today(config: dict) -> list[str]:
    grupos = config.get("grupos", [])
    if not grupos:
        return []
    idx = datetime.now().timetuple().tm_yday % len(grupos)
    queries = grupos[idx]
    print(f"[scraper] Grupo {idx + 1}/{len(grupos)} — {len(queries)} queries")
    return queries


def load_seen_hashes() -> set:
    if not SEEN_FILE.exists():
        return set()
    return set(SEEN_FILE.read_text().splitlines())


def save_hash(h: str):
    with open(SEEN_FILE, "a") as f:
        f.write(h + "\n")


def image_hash(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def is_valid_image(data: bytes) -> tuple[bool, str]:
    for magic, ext in VALID_MAGIC.items():
        if data[:len(magic)] == magic:
            return True, ext
    return False, ''


def build_search_url(query: str) -> str:
    """
    Construye URL de Google Images con:
    - isz:l  → imágenes grandes (mejor resolución)
    - qdr:w  → última semana
    """
    import urllib.parse
    q = urllib.parse.quote(query)
    return (
        f"https://www.google.com/search"
        f"?q={q}&tbm=isch&tbs=isz:l,qdr:w&hl=es&gl=ar"
    )


def fetch_image_urls(query: str, max_results: int = 20) -> list[dict]:
    """Extrae URLs de imágenes y links fuente desde Google Images."""
    url = build_search_url(query)
    print(f"[scraper] GET {url[:80]}...")

    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
    except Exception as e:
        print(f"[scraper] Error de red: {e}")
        return []

    if resp.status_code != 200:
        print(f"[scraper] HTTP {resp.status_code}")
        return []

    html = resp.text

    # Google embebe los datos de imágenes en JSON dentro del HTML
    # Patrón para extraer thumbnail URLs y links fuente
    results = []

    # Extraer thumbnails (encrypted-tbn)
    thumbs = re.findall(r'https://encrypted-tbn0\.gstatic\.com/images\?[^"\'\\]+', html)
    # Extraer links de instagram
    links = re.findall(r'https://www\.instagram\.com/p/[A-Za-z0-9_\-]+/?', html)
    links += re.findall(r'https://www\.instagram\.com/reel/[A-Za-z0-9_\-]+/?', html)

    # Deduplicar manteniendo orden
    thumbs = list(dict.fromkeys(thumbs))
    links  = list(dict.fromkeys(links))

    print(f"[scraper] '{query[:50]}' → {len(thumbs)} thumbs, {len(links)} links IG")

    for i, thumb in enumerate(thumbs[:max_results]):
        link = links[i] if i < len(links) else ""
        results.append({"thumbnail": thumb, "link": link})

    return results


def download_images_for_query(query: str, max_new: int, seen: set) -> list[tuple[Path, dict]]:
    IMAGES_DIR.mkdir(exist_ok=True)
    items = fetch_image_urls(query, max_results=max_new * 3)

    downloaded = []
    for item in items:
        if len(downloaded) >= max_new:
            break
        try:
            resp = requests.get(item["thumbnail"], headers=HEADERS, timeout=10)
            if resp.status_code != 200:
                continue

            data = resp.content
            valid, ext = is_valid_image(data)
            if not valid:
                continue

            h = image_hash(data)
            if h in seen:
                continue

            slug = hashlib.md5(query.encode()).hexdigest()[:6]
            filename = IMAGES_DIR / f"{slug}_{h[:12]}.{ext}"
            filename.write_bytes(data)
            save_hash(h)
            seen.add(h)
            downloaded.append((filename, item))
            print(f"[scraper] ✓ {filename.name} — {item.get('link','')[:50]}")
            time.sleep(0.5)

        except Exception as e:
            print(f"[scraper] Error descargando: {e}")

    return downloaded


def download_all() -> list[tuple[Path, dict]]:
    config  = load_config()
    queries = get_queries_for_today(config)
    max_por_query = config.get("max_imagenes_por_query", 10)

    seen = load_seen_hashes()
    all_items = []

    for query in queries:
        items = download_images_for_query(query, max_por_query, seen)
        all_items.extend(items)
        print(f"      {len(items)} imagen(es) nueva(s)")
        time.sleep(1)

    return all_items


if __name__ == "__main__":
    items = download_all()
    print(f"\nTotal: {len(items)} imagen(es) descargada(s)")
