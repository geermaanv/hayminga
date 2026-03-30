"""
scraper.py
Busca imágenes en Google Images filtrando site:instagram.com
usando SerpAPI y descarga los flyers nuevos evitando duplicados.
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


def load_seen_hashes() -> set:
    if not SEEN_FILE.exists():
        return set()
    return set(SEEN_FILE.read_text().splitlines())


def save_hash(h: str):
    with open(SEEN_FILE, "a") as f:
        f.write(h + "\n")


def image_hash(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def build_query(hashtag: str) -> str:
    """Construye la query para Google Images."""
    return f"site:instagram.com #{hashtag} (minga OR bioconstruccion OR adobe OR taller) evento"


def fetch_image_urls(query: str, max_results: int = 20) -> list[str]:
    """Usa SerpAPI para buscar imágenes en Google Images."""
    api_key = os.getenv("SERPAPI_KEY")
    if not api_key:
        print("[scraper] SERPAPI_KEY no configurada")
        return []

    params = {
        "engine": "google_images",
        "q": query,
        "num": min(max_results, 100),
        "api_key": api_key,
        "ijn": 0,
        "tbs": "qdr:m",  # solo imágenes del último mes
    }

    resp = requests.get(
        "https://serpapi.com/search",
        params=params,
        timeout=20
    )

    if resp.status_code != 200:
        print(f"[SerpAPI] Error {resp.status_code}: {resp.text[:200]}")
        return []

    data = resp.json()
    images = data.get("images_results", [])
    urls = [img["original"] for img in images[:max_results] if img.get("original")]
    print(f"[scraper] SerpAPI devolvió {len(urls)} URL(s)")
    return urls


def download_images(hashtag: str, max_new: int = 10) -> list[Path]:
    """
    Descarga imágenes nuevas para un hashtag.
    Retorna lista de paths de archivos descargados.
    """
    IMAGES_DIR.mkdir(exist_ok=True)
