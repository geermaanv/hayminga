import os
import unittest
from unittest.mock import Mock, patch

from src import scraper


def response(status=200, payload=None, text=""):
    result = Mock()
    result.status_code = status
    result.text = text
    result.json.return_value = payload if payload is not None else {}
    return result


class CaptionProviderTests(unittest.TestCase):
    @patch.dict(os.environ, {"SERPAPI_KEY": "serp", "SERPER_API_KEY": "backup"})
    @patch("src.scraper.requests.post")
    @patch("src.scraper.requests.get")
    def test_caption_uses_serpapi_without_fallback(self, get, post):
        link = "https://instagram.com/p/evento/"
        get.return_value = response(payload={"organic_results": [{
            "link": link.rstrip("/"),
            "snippet": "Taller de adobe en Córdoba",
        }]})

        self.assertEqual(
            scraper.fetch_caption(link),
            "Taller de adobe en Córdoba",
        )
        post.assert_not_called()

    @patch.dict(
        os.environ,
        {"SERPER_API_KEY": "backup"},
        clear=True,
    )
    @patch("src.scraper.requests.post")
    def test_caption_uses_serper_without_serpapi_key(self, post):
        link = "https://instagram.com/p/evento"
        post.return_value = response(payload={"organic": [{
            "link": f"{link}/",
            "snippet": "Encuentro de bioconstrucción",
        }]})

        self.assertEqual(
            scraper.fetch_caption(link),
            "Encuentro de bioconstrucción",
        )

    @patch.dict(os.environ, {"SERPER_API_KEY": "backup"}, clear=True)
    @patch("src.scraper.requests.post")
    def test_caption_includes_indexed_publication_date(self, post):
        link = "https://instagram.com/p/evento"
        post.return_value = response(payload={"organic": [{
            "link": link,
            "snippet": "Taller del 24 al 30 de noviembre",
            "date": "hace 9 meses",
        }]})

        self.assertEqual(
            scraper.fetch_caption(link),
            (
                "Fecha de publicación indexada: hace 9 meses\n"
                "Taller del 24 al 30 de noviembre"
            ),
        )


if __name__ == "__main__":
    unittest.main()
