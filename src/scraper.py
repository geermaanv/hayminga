"""
scraper.py
Busca imágenes en Google Images filtrando site:instagram.com
y descarga los flyers nuevos evitando duplicados.
"""

import os
import re
import time
import hashlib
import requests
from pathlib import Path
from urllib.parse import urlencode, quote_plus

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
    q = f"site:instagram.com #{hashtag} minga evento"
    return q


def fetch_image_urls(query: str, max_results: int = 20) -> list[str]:
    """
    Usa la API de búsqueda de imágenes de Google Custom Search.
    Si no tenés API key configurada, cae al método de scraping básico.
    """
    api_key = os.getenv("GOOGLE_API_KEY")
    cx = os.getenv("GOOGLE_CX")  # Custom Search Engine ID

    if api_key and cx:
        return _fetch_via_api(query, api_key, cx, max_results)
    else:
        return _fetch_via_scraping(query, max_results)


def _fetch_via_api(query: str, api_key: str, cx: str, max_results: int) -> list[str]:
    """Google Custom Search API — más estable y sin riesgo de bloqueo."""
    urls = []
    for start in range(1, max_results, 10):
        params = {
            "key": api_key,
            "cx": cx,
            "q": query,
            "searchType": "image",
            "num": min(10, max_results - len(urls)),
            "start": start,
            "imgType": "photo",
        }
        resp = requests.get(
            "https://www.googleapis.com/customsearch/v1",
            params=params,
            timeout=15
        )
        if resp.status_code != 200:
            print(f"[API] Error {resp.status_code}: {resp.text[:200]}")
            break
        data = resp.json()
        items = data.get("items", [])
        if not items:
            break
        for item in items:
            link = item.get("link")
            if link:
                urls.append(link)
        time.sleep(0.5)
    return urls


def _fetch_via_scraping(query: str, max_results: int) -> list[str]:
    """
    Fallback: scraping básico de Google Images.
    Menos estable — preferir la API cuando esté configurada.
    """
    search_url = (
        "https://www.google.com/search?"
        + urlencode({"q": query, "tbm": "isch", "num": max_results})
    )
    resp = requests.get(search_url, headers=HEADERS, timeout=15)
    if resp.status_code != 200:
        print(f"[Scraping] Error {resp.status_code}")
        return []

    # Extrae URLs de imágenes del HTML
    pattern = r'"(https?://[^"]+\.(?:jpg|jpeg|png|webp))"'
    urls = re.findall(pattern, resp.text)
    # Filtra miniaturas de Google y queda con imágenes reales
    urls = [u for u in urls if "gstatic" not in u and "google" not in u]
    return urls[:max_results]


def download_images(hashtag: str, max_new: int = 10) -> list[Path]:
    """
    Descarga imágenes nuevas para un hashtag.
    Retorna lista de paths de archivos descargados.
    """
    IMAGES_DIR.mkdir(exist_ok=True)
    seen = load_seen_hashes()
    query = build_query(hashtag)
    urls = fetch_image_urls(query, max_results=30)

    downloaded = []
    for url in urls:
        if len(downloaded) >= max_new:
            break
        try:
            resp = requests.get(url, headers=HEADERS, timeout=10)
            if resp.status_code != 200:
                continue
            data = resp.content
            h = image_hash(data)
            if h in seen:
                continue  # ya procesada
            ext = url.split(".")[-1].split("?")[0][:4]
            if ext not in ("jpg", "jpeg", "png", "webp"):
                ext = "jpg"
            filename = IMAGES_DIR / f"{hashtag}_{h[:12]}.{ext}"
            filename.write_bytes(data)
            save_hash(h)
            downloaded.append(filename)
            print(f"[scraper] Descargada: {filename.name}")
            time.sleep(0.3)
        except Exception as e:
            print(f"[scraper] Error descargando {url}: {e}")

    return downloaded


if __name__ == "__main__":
    for tag in HASHTAGS:
        print(f"\n=== #{tag} ===")
        files = download_images(tag)
        print(f"  {len(files)} imagen(es) nueva(s)")
