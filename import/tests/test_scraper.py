import os
import json
import unittest
from unittest.mock import Mock, patch

from src import scraper


def response(status=200, payload=None, text=""):
    result = Mock()
    result.status_code = status
    result.text = text
    result.json.return_value = payload if payload is not None else {}
    return result


class ImageProviderTests(unittest.TestCase):
    def test_config_can_use_all_twelve_queries_today(self):
        config = json.loads(scraper.CONFIG_FILE.read_text())

        queries = scraper.get_queries_for_today(config)

        self.assertEqual(len(queries), 12)
        self.assertEqual(len(set(queries)), 12)

    @patch.dict(os.environ, {"SERPAPI_KEY": "serp", "SERPER_API_KEY": "backup"})
    @patch("src.scraper.requests.post")
    @patch("src.scraper.requests.get")
    def test_serpapi_success_does_not_use_fallback(self, get, post):
        get.return_value = response(payload={"images_results": [{
            "thumbnail": "https://thumb.example/1",
            "link": "https://instagram.com/p/1",
            "title": "Taller de adobe en Córdoba",
        }]})

        actual = scraper.fetch_image_data("bioconstruccion", max_results=5)

        self.assertEqual(actual, [{
            "thumbnail": "https://thumb.example/1",
            "link": "https://instagram.com/p/1",
            "caption": "Taller de adobe en Córdoba",
        }])
        post.assert_not_called()

    @patch.dict(os.environ, {"SERPAPI_KEY": "serp", "SERPER_API_KEY": "backup"})
    @patch("src.scraper.requests.post")
    @patch("src.scraper.requests.get")
    def test_valid_empty_serpapi_result_does_not_use_fallback(self, get, post):
        get.return_value = response(payload={"images_results": []})

        self.assertEqual(scraper.fetch_image_data("sin resultados"), [])
        post.assert_not_called()

    @patch.dict(os.environ, {"SERPAPI_KEY": "serp", "SERPER_API_KEY": "backup"})
    @patch("src.scraper.requests.post")
    @patch("src.scraper.requests.get")
    def test_serpapi_429_uses_serper_and_maps_results(self, get, post):
        get.return_value = response(status=429, text="quota exhausted")
        post.return_value = response(payload={"images": [
            {
                "thumbnailUrl": "https://thumb.example/1",
                "imageUrl": "https://image.example/1",
                "link": "https://instagram.com/p/1",
                "title": "Taller uno",
            },
            {
                "imageUrl": "https://image.example/2",
                "link": "https://instagram.com/p/2",
                "title": "Taller dos",
            },
        ]})

        actual = scraper.fetch_image_data("bioconstruccion", max_results=2)

        self.assertEqual(actual, [
            {
                "thumbnail": "https://thumb.example/1",
                "link": "https://instagram.com/p/1",
                "caption": "Taller uno",
            },
            {
                "thumbnail": "https://image.example/2",
                "link": "https://instagram.com/p/2",
                "caption": "Taller dos",
            },
        ])
        request = post.call_args
        self.assertEqual(request.args[0], "https://google.serper.dev/images")
        self.assertEqual(request.kwargs["headers"]["X-API-KEY"], "backup")
        self.assertEqual(request.kwargs["json"]["q"], "bioconstruccion")
        self.assertEqual(request.kwargs["json"]["num"], 2)

    @patch.dict(os.environ, {"SERPER_API_KEY": "backup"}, clear=True)
    @patch("src.scraper.requests.post")
    def test_serper_caps_free_plan_request_at_ten_results(self, post):
        post.return_value = response(payload={"images": []})

        scraper.fetch_image_data("consulta", max_results=45)

        self.assertEqual(post.call_args.kwargs["json"]["num"], 10)

    @patch.dict(os.environ, {"SERPAPI_KEY": "serp", "SERPER_API_KEY": "backup"})
    @patch("src.scraper.requests.post")
    @patch("src.scraper.requests.get")
    def test_serpapi_api_error_uses_serper(self, get, post):
        get.return_value = response(payload={"error": "out of searches"})
        post.return_value = response(payload={"images": []})

        self.assertEqual(scraper.fetch_image_data("consulta"), [])
        post.assert_called_once()

    @patch.dict(os.environ, {"SERPAPI_KEY": "serp", "SERPER_API_KEY": "backup"})
    @patch("src.scraper.requests.post")
    @patch("src.scraper.requests.get")
    def test_invalid_serpapi_json_uses_serper(self, get, post):
        get.return_value = response()
        get.return_value.json.side_effect = ValueError("bad json")
        post.return_value = response(payload={"images": []})

        self.assertEqual(scraper.fetch_image_data("consulta"), [])
        post.assert_called_once()

    @patch.dict(
        os.environ,
        {"SERPER_API_KEY": "backup"},
        clear=True,
    )
    @patch("src.scraper.requests.post")
    def test_missing_serpapi_key_uses_serper(self, post):
        post.return_value = response(payload={"images": [{
            "thumbnailUrl": "https://thumb.example/1",
            "link": "https://example.com/1",
        }]})

        actual = scraper.fetch_image_data("consulta")

        self.assertEqual(len(actual), 1)
        post.assert_called_once()


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


if __name__ == "__main__":
    unittest.main()
