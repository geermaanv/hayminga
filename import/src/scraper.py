"""
scraper.py
Funciones que siguen en uso por el pipeline actual (hiker_pipeline.py /
processor.py / email_intake.py): traer el post real de Instagram vía
HikerAPI y buscar el caption indexado como respaldo.

El resto de este archivo (descubrimiento vía Google Images/SerpAPI/
Serper, ya reemplazado por hiker_pipeline.py) se archivó en
import/legacy/scraper_google_images.py — ver ROADMAP.md.
"""

import os
import requests
from datetime import datetime, timezone


def _provider_error(provider: str, message: str) -> None:
    print(f"[{provider}] {message}")


def fetch_hikerapi_media(link: str) -> dict | None:
    """Post real de Instagram vía HikerAPI (https://hikerapi.com):
    caption completo, imagen sin recortar y fecha real de publicación
    (taken_at_ts). Paga (~$0.0006/request), key en HIKERAPI_KEY — si no
    está configurada o la llamada falla, quien invoca cae a su propio
    fallback (og:image / SerpAPI / Serper)."""
    api_key = os.getenv("HIKERAPI_KEY")
    if not api_key or not link:
        return None
    try:
        resp = requests.get(
            "https://api.hikerapi.com/v1/media/by/url",
            params={"url": link},
            headers={"x-access-key": api_key},
            timeout=20,
        )
        if resp.status_code != 200:
            _provider_error("HikerAPI", f"HTTP {resp.status_code}")
            return None
        data = resp.json()
        return {
            "caption": data.get("caption_text") or "",
            "taken_at_ts": data.get("taken_at_ts"),
            "image_url": data.get("thumbnail_url") or "",
        }
    except Exception as exc:
        _provider_error("HikerAPI", f"error: {exc}")
        return None


def fetch_caption(link: str) -> str:
    """Busca el caption real del post. Primero intenta HikerAPI (caption
    completo + fecha real de publicación); si no está configurada o falla,
    cae al snippet indexado por Google Search vía SerpAPI/Serper — la
    copia cacheada por Google, no un pedido a Instagram. Cuesta una
    llamada, así que processor.py la pide bajo demanda (solo para eventos
    reales con datos incompletos), no al descargar."""
    if not link:
        return ""

    hiker = fetch_hikerapi_media(link)
    if hiker and hiker.get("caption"):
        partes = []
        if hiker.get("taken_at_ts"):
            fecha_pub = datetime.fromtimestamp(hiker["taken_at_ts"], tz=timezone.utc).date().isoformat()
            partes.append(f"Fecha de publicación indexada: {fecha_pub}")
        partes.append(hiker["caption"])
        return "\n".join(partes).strip()

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
                        snippet = result.get("snippet", "")
                        published = result.get("date", "")
                        if published:
                            return (
                                f"Fecha de publicación indexada: {published}\n"
                                f"{snippet}"
                            ).strip()
                        return snippet
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
                snippet = result.get("snippet", "")
                published = result.get("date", "")
                if published:
                    return (
                        f"Fecha de publicación indexada: {published}\n"
                        f"{snippet}"
                    ).strip()
                return snippet
    except Exception as exc:
        _provider_error("Serper", f"error buscando caption: {exc}")
    return ""
