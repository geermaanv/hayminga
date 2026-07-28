"""
scraper.py
Busca imágenes en Google Images vía SerpAPI y usa Serper como respaldo.
Filtra por último mes y tamaño grande, y descarga thumbnails evitando
duplicados.
"""

import os
import io
import time
import hashlib
import requests
import json
from pathlib import Path
from datetime import datetime, timezone
from PIL import Image

from src.state import image_hash, load_seen_hashes, load_seen_links

IMAGES_DIR  = Path("images")
CONFIG_FILE = Path("config.json")

# Filtro heurístico gratis (sin IA): descarta fotos de perfil/avatares antes
# de gastar cuota de Vision. Medido: avatares de Google bajan ~9-10KB,
# thumbnails de flyers reales ~36-45KB — el piso de bytes ya separa bastante.
MIN_IMAGE_BYTES = 15_000
MIN_IMAGE_DIM   = 200  # px, en el lado más largo

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
}


def _provider_error(provider: str, message: str) -> None:
    print(f"[{provider}] {message}")


def load_config() -> dict:
    return json.loads(CONFIG_FILE.read_text())


def get_queries_for_today(config: dict) -> list[str]:
    grupos = config.get("grupos", [])
    if not grupos:
        return []
    all_queries = [query for group in grupos for query in group]
    requested = max(1, int(config.get("consultas_por_dia", 3)))
    count = min(requested, len(all_queries))
    start = (datetime.now().timetuple().tm_yday * count) % len(all_queries)
    queries = [
        all_queries[(start + offset) % len(all_queries)]
        for offset in range(count)
    ]
    print(
        f"[scraper] {len(queries)}/{len(all_queries)} queries del ciclo "
        f"(config: consultas_por_dia={requested})"
    )
    return queries


def is_valid_image(data: bytes) -> tuple[bool, str]:
    for magic, ext in VALID_MAGIC.items():
        if data[:len(magic)] == magic:
            return True, ext
    return False, ''


def passes_quality_filter(data: bytes) -> bool:
    """Descarta imágenes demasiado chicas para ser un flyer legible
    (avatares, íconos) sin gastar ninguna llamada a IA."""
    if len(data) < MIN_IMAGE_BYTES:
        return False
    try:
        with Image.open(io.BytesIO(data)) as im:
            w, h = im.size
    except Exception:
        return False
    return max(w, h) >= MIN_IMAGE_DIM


def fetch_caption(link: str) -> str:
    """Busca el snippet de caption real del post vía Google Search normal
    (no Images) — es la copia cacheada por Google, no un pedido a Instagram.
    Cuesta una llamada de SerpAPI, así que processor.py la pide bajo demanda
    (solo para eventos reales con datos incompletos), no acá al descargar."""
    if not link:
        return ""

    serpapi_key = os.getenv("SERPAPI_KEY")
    if serpapi_key:
        try:
            resp = requests.get("https://serpapi.com/search", params={
                "engine": "google",
                "q":      link,
                "api_key": serpapi_key,
                "hl": "es", "gl": "ar",
            }, timeout=15)
            data = resp.json() if resp.status_code == 200 else {}
            if resp.status_code == 200 and not data.get("error"):
                for result in data.get("organic_results", []):
                    if result.get("link", "").rstrip("/") == link.rstrip("/"):
                        return result.get("snippet", "")
            else:
                detail = data.get("error") or f"HTTP {resp.status_code}"
                _provider_error("SerpAPI", f"caption no disponible: {detail}")
        except Exception as exc:
            _provider_error("SerpAPI", f"error buscando caption: {exc}")

    serper_key = os.getenv("SERPER_API_KEY")
    if not serper_key:
        return ""

    try:
        resp = requests.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": serper_key, "Content-Type": "application/json"},
            json={"q": link, "hl": "es", "gl": "ar"},
            timeout=15,
        )
        if resp.status_code != 200:
            _provider_error("Serper", f"caption no disponible: HTTP {resp.status_code}")
            return ""
        for result in resp.json().get("organic", []):
            if result.get("link", "").rstrip("/") == link.rstrip("/"):
                return result.get("snippet", "")
    except Exception as exc:
        _provider_error("Serper", f"error buscando caption: {exc}")
    return ""


def _fetch_images_serpapi(query: str, max_results: int) -> list[dict] | None:
    """Devuelve None si SerpAPI no está disponible; [] es una búsqueda válida."""
    api_key = os.getenv("SERPAPI_KEY")
    if not api_key:
        _provider_error("SerpAPI", "SERPAPI_KEY no configurada")
        return None

    params = {
        "engine":  "google_images",
        "q":       query,
        "api_key": api_key,
        "ijn":     0,
        "tbs":     "isz:l,qdr:m",  # large + último mes
        "hl":      "es",
        "gl":      "ar",
    }

    try:
        resp = requests.get("https://serpapi.com/search", params=params, timeout=20)
    except Exception as exc:
        _provider_error("SerpAPI", f"error de red: {exc}")
        return None

    if resp.status_code != 200:
        _provider_error("SerpAPI", f"error HTTP {resp.status_code}: {resp.text[:200]}")
        return None

    try:
        data = resp.json()
    except (ValueError, requests.exceptions.JSONDecodeError) as exc:
        _provider_error("SerpAPI", f"respuesta JSON inválida: {exc}")
        return None
    if data.get("error"):
        _provider_error("SerpAPI", f"error de API: {data['error']}")
        return None

    images   = data.get("images_results", [])
    results  = []

    for img in images[:max_results]:
        thumb = img.get("thumbnail") or img.get("original")
        if thumb:
            results.append({
                "thumbnail": thumb,
                "link":      img.get("link", ""),
                "caption":   img.get("title", ""),
            })
    return results


def _fetch_images_serper(query: str, max_results: int) -> list[dict]:
    api_key = os.getenv("SERPER_API_KEY")
    if not api_key:
        _provider_error("Serper", "SERPER_API_KEY no configurada")
        return []

    # El plan gratuito de Serper rechaza pedidos de 20 o más resultados con
    # "Query pattern not allowed for free accounts". Diez funciona y alcanza
    # para que el filtro local seleccione candidatos sin consumir otra búsqueda.
    request_limit = min(max_results, 10)

    try:
        resp = requests.post(
            "https://google.serper.dev/images",
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            json={
                "q": query,
                "hl": "es",
                "gl": "ar",
                "tbs": "isz:l,qdr:m",
                "num": request_limit,
            },
            timeout=20,
        )
    except Exception as exc:
        _provider_error("Serper", f"error de red: {exc}")
        return []

    if resp.status_code != 200:
        _provider_error("Serper", f"error HTTP {resp.status_code}: {resp.text[:200]}")
        return []

    try:
        data = resp.json()
    except (ValueError, requests.exceptions.JSONDecodeError) as exc:
        _provider_error("Serper", f"respuesta JSON inválida: {exc}")
        return []

    results = []
    for image in data.get("images", [])[:request_limit]:
        thumbnail = image.get("thumbnailUrl") or image.get("imageUrl")
        if thumbnail:
            results.append({
                "thumbnail": thumbnail,
                "link": image.get("link", ""),
                "caption": image.get("title", ""),
            })
    return results


def fetch_image_data(query: str, max_results: int = 20) -> list[dict]:
    """Busca imágenes con SerpAPI y activa Serper si el proveedor falla."""
    results = _fetch_images_serpapi(query, max_results)
    provider = "SerpAPI"
    if results is None:
        print("[scraper] Activando fallback de Serper")
        results = _fetch_images_serper(query, max_results)
        provider = "Serper"

    print(f"[scraper] '{query[:55]}' → {len(results)} imagen(es) vía {provider}")
    return results


def download_images_for_query(
    query: str, max_new: int, seen: set, seen_links: set
) -> list[tuple[Path, dict]]:
    IMAGES_DIR.mkdir(exist_ok=True)
    items = fetch_image_data(query, max_results=max_new * 3)

    downloaded = []
    for item in items:
        if len(downloaded) >= max_new:
            break

        link = item.get("link", "")
        if link and link in seen_links:
            continue  # mismo post ya descargado (esta corrida o una anterior)

        try:
            resp = requests.get(item["thumbnail"], headers=HEADERS, timeout=10)
            if resp.status_code != 200:
                continue

            data  = resp.content
            valid, ext = is_valid_image(data)
            if not valid:
                continue

            if not passes_quality_filter(data):
                continue

            h = image_hash(data)
            if h in seen:
                continue

            # el caption ya NO se busca acá — processor.py lo pide bajo demanda
            # solo para eventos reales con datos incompletos, para no gastar
            # una llamada de SerpAPI en cada imagen que después resulta basura
            slug     = hashlib.md5(query.encode()).hexdigest()[:6]
            filename = IMAGES_DIR / f"{slug}_{h[:12]}.{ext}"
            filename.write_bytes(data)
            # sidecar de metadata: permite reintentar más tarde sin perder el link original
            filename.with_suffix(filename.suffix + ".json").write_text(
                json.dumps({
                    "link": link,
                    "thumbnail": item.get("thumbnail", ""),
                    "caption": item.get("caption", ""),
                }, ensure_ascii=False)
            )

            # dedup dentro de esta corrida; se persiste recién si processor.py confirma un resultado
            seen.add(h)
            if link:
                seen_links.add(link)
            item["hash"] = h
            item["source"] = "google_images"
            item["query"] = query
            item["discovered_at"] = datetime.now(timezone.utc).isoformat()
            downloaded.append((filename, item))
            print(f"[scraper] ✓ {filename.name} — {link[:50]}")
            time.sleep(0.3)

        except Exception as e:
            print(f"[scraper] Error descargando: {e}")

    return downloaded


def download_all() -> list[tuple[Path, dict]]:
    config        = load_config()
    queries       = get_queries_for_today(config)
    max_por_query = config.get("max_imagenes_por_query", 10)

    seen       = load_seen_hashes()
    seen_links = load_seen_links()
    all_items  = []

    for query in queries:
        items = download_images_for_query(query, max_por_query, seen, seen_links)
        all_items.extend(items)
        print(f"      {len(items)} imagen(es) nueva(s)")
        time.sleep(1)

    return all_items


if __name__ == "__main__":
    items = download_all()
    print(f"\nTotal: {len(items)} imagen(es) descargada(s)")
