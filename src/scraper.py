"""
scraper.py
Busca imágenes en Google Images sobre eventos de bioconstrucción
usando SerpAPI y descarga los thumbnails evitando duplicados.
"""

import os
import time
import hashlib
import requests
from pathlib import Path

HASHTAGS = ["minga", "bioconstruccion"]
IMAGES_DIR = Path("images")
SEEN_FILE = Path("seen_hashes.txt")

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


def build_query(hashtag: str) -> str:
    return f"#{hashtag} (minga OR bioconstruccion OR adobe OR taller) evento"


def fetch_image_data(query: str, max_results: int = 30) -> list[dict]:
    """
    Usa SerpAPI y retorna lista de dicts con thumbnail, original y link.
    """
    api_key = os.getenv("SERPAPI_KEY")
    if not api_key:
        print("[scraper] SERPAPI_KEY no configurada")
        return []

    params = {
        "engine": "google_images",
        "q": query,
        "api_key": api_key,
        "ijn": 0,
        "tbs": "qdr:m",
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
                "original": img.get("thumbnail", ""),  # usar thumbnail como imagen
                "link": img.get("link", ""),
            })
    })
    print(f"[scraper] SerpAPI devolvió {len(results)} imagen(es)")
    return results


def download_images(hashtag: str, max_new: int = 10) -> list[tuple[Path, dict]]:
    """
    Descarga thumbnails nuevos para un hashtag.
    Retorna lista de (path, metadata) donde metadata tiene original y link.
    """
    IMAGES_DIR.mkdir(exist_ok=True)
    seen = load_seen_hashes()
    query = build_query(hashtag)
    image_data = fetch_image_data(query, max_results=40)

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

            filename = IMAGES_DIR / f"{hashtag}_{h[:12]}.{ext}"
            filename.write_bytes(data)
            save_hash(h)
            downloaded.append((filename, item))
            print(f"[scraper] Descargada: {filename.name}")
            time.sleep(0.3)

        except Exception as e:
            print(f"[scraper] Error: {e}")

    return downloaded


if __name__ == "__main__":
    for tag in HASHTAGS:
        print(f"\n=== #{tag} ===")
        files = download_images(tag)
        print(f"  {len(files)} imagen(es) nueva(s)")
