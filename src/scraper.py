"""
scraper.py
Busca imágenes en Google Images usando queries configurables
y descarga los thumbnails evitando duplicados.
"""

import os
import time
import hashlib
import requests
import json
from pathlib import Path
from datetime import datetime, timedelta

IMAGES_DIR = Path("images")
SEEN_FILE = Path("seen_hashes.txt")
CONFIG_FILE = Path("config.json")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    )
}

VALID_MAGIC = {
    b'\xff\xd8\xff': 'jpg',
    b'\x89PNG':      'png',
    b'RIFF':         'webp',
    b'GIF8':         'gif',
}


def load_config() -> dict:
    return json.loads(CONFIG_FILE.read_text())


def get_queries_for_today(config: dict) -> list[str]:
    """Selecciona el grupo de queries según el día del año."""
    grupos = config.get("grupos", [])
    if not grupos:
        return []
    idx = datetime.now().timetuple().tm_yday % len(grupos)
    queries = grupos[idx]
    print(f"[scraper] Grupo {idx + 1}/{len(grupos)} — {len(queries)} queries")
    return queries


def build_query_with_date(query: str, dias_atras: int) -> str:
    """Agrega filtro after: a la query."""
    fecha = (datetime.now() - timedelta(days=dias_atras)).strftime("%Y-%m-%d")
    return f"{query} after:{fecha}"


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


def fetch_image_data(query: str, max_results: int = 10) -> list[dict]:
    """Usa SerpAPI con query estilo Google Images."""
    api_key = os.getenv("SERPAPI_KEY")
    if not api_key:
        print("[scraper] SERPAPI_KEY no configurada")
        return []

    params = {
        "engine": "google_images",
        "q": query,
        "api_key": api_key,
        "ijn": 0,
    }

    resp = requests.get("https://serpapi.com/search", params=params, timeout=20)

    if resp.status_code != 200:
        print(f"[SerpAPI] Error {resp.status_code}: {resp.text[:200]}")
        return []

    data = resp.json()
    images = data.get("images_results", [])

    results = []
    for img in images[:max_results]:
        if img.get("thumbnail"):
            results.append({
                "thumbnail": img.get("thumbnail", ""),
                "original": img.get("thumbnail", ""),
                "link": img.get("link", ""),
            })

    print(f"[scraper] '{query[:60]}...' → {len(results)} imagen(es)")
    return results


def download_images_for_query(query: str, max_new: int, seen: set) -> list[tuple[Path, dict]]:
    """Descarga thumbnails nuevos para una query."""
    IMAGES_DIR.mkdir(exist_ok=True)
    image_data = fetch_image_data(query, max_results=max_new * 3)

    downloaded = []
    for item in image_data:
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
            print(f"[scraper] Descargada: {filename.name}")
            time.sleep(0.3)

        except Exception as e:
            print(f"[scraper] Error: {e}")

    return downloaded


def download_all() -> list[tuple[Path, dict]]:
    """Corre todas las queries del grupo de hoy."""
    config = load_config()
    queries = get_queries_for_today(config)
    dias_atras = config.get("dias_atras", 30)
    max_por_query = config.get("max_imagenes_por_query", 10)

    seen = load_seen_hashes()
    all_items = []

    for query in queries:
        query_con_fecha = build_query_with_date(query, dias_atras)
        items = download_images_for_query(query_con_fecha, max_por_query, seen)
        all_items.extend(items)
        print(f"      {len(items)} imagen(es) nueva(s)")

    return all_items


if __name__ == "__main__":
    items = download_all()
    print(f"\nTotal: {len(items)} imagen(es) descargada(s)")
