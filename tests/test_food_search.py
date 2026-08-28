import json
import tempfile
import unittest
from pathlib import Path

from food_search import (
    BrowserLaunchPlan,
    GroceryStore,
    SearchResult,
    prepare_run_directory,
    resolve_browser_launch,
    save_result,
    search_target,
    search_wegmans,
)


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload
        self.status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, payloads):
        self.payloads = iter(payloads)
        self.headers = {}
        self.requests = []

    def request(self, method, url, **kwargs):
        self.requests.append((method, url, kwargs))
        return FakeResponse(next(self.payloads))


def target_product(product_id):
    return {
        "tcin": product_id,
        "item": {
            "product_description": {"title": f"Product {product_id}"},
            "enrichment": {
                "buy_url": f"https://example.test/{product_id}",
                "image_info": {"primary_image": {"url": "https://image.test"}},
            },
            "primary_brand": {"name": "Test Brand"},
        },
        "price": {"formatted_current_price": "$1.00"},
    }


def target_page(products, total):
    return {
        "data": {
            "search": {
                "products": products,
                "search_response": {"metadata": {"total_results": total}},
            }
        }
    }


def wegmans_product(product_id):
    return {
        "productId": product_id,
        "productName": f"Product {product_id}",
        "consumerBrandName": "Test Brand",
        "price_inStore": {"amount": 1.0, "unitPrice": "$0.10/oz"},
        "images": ["https://image.test"],
        "isAvailable": True,
        "slug": f"{product_id}-product",
    }


def wegmans_page(products, page, page_count, total):
    return {
        "results": [
            {
                "hits": products,
                "page": page,
                "nbPages": page_count,
                "nbHits": total,
            }
        ]
    }


class BrowserLaunchTests(unittest.TestCase):
    def test_wayland_uses_native_chromium_backend_without_xvfb(self):
        plan = resolve_browser_launch(
            "auto",
            {"WAYLAND_DISPLAY": "wayland-0", "XDG_SESSION_TYPE": "wayland"},
            "Linux",
        )

        self.assertEqual(
            plan,
            BrowserLaunchPlan(
                headed=True,
                backend="wayland",
                chromium_arg="--ozone-platform=wayland",
            ),
        )
        self.assertNotIn("xvfb", (plan.chromium_arg or "").lower())

    def test_displayless_linux_uses_headless_mode(self):
        self.assertEqual(
            resolve_browser_launch("auto", {}, "Linux"),
            BrowserLaunchPlan(headed=False, backend="headless"),
        )


class CompletePaginationTests(unittest.TestCase):
    def test_target_follows_reported_result_count(self):
        session = FakeSession(
            [
                target_page([target_product("1"), target_product("2")], 3),
                target_page([target_product("3")], 3),
            ]
        )
        with tempfile.TemporaryDirectory() as directory:
            result = search_target("bread", Path(directory), "3991", session)
            raw_pages = sorted(Path(directory).glob("page-*.json"))

        self.assertEqual(
            [product["id"] for product in result.products], ["1", "2", "3"]
        )
        self.assertEqual(result.reported_result_count, 3)
        self.assertEqual(len(raw_pages), 2)
        self.assertEqual(
            [request[2]["params"]["offset"] for request in session.requests],
            ["0", "2"],
        )

    def test_target_keeps_results_beyond_the_reported_estimate(self):
        session = FakeSession(
            [
                target_page([target_product("1"), target_product("2")], 3),
                target_page([target_product("3"), target_product("4")], 3),
            ]
        )
        with tempfile.TemporaryDirectory() as directory:
            result = search_target("saffron", Path(directory), "3991", session)

        self.assertEqual(
            [product["id"] for product in result.products], ["1", "2", "3", "4"]
        )
        self.assertEqual(result.reported_result_count, 3)

    def test_wegmans_follows_every_reported_page(self):
        session = FakeSession(
            [
                wegmans_page([wegmans_product("1"), wegmans_product("2")], 0, 2, 3),
                wegmans_page([wegmans_product("3")], 1, 2, 3),
            ]
        )
        with tempfile.TemporaryDirectory() as directory:
            result = search_wegmans("bread", Path(directory), "133", session)
            raw_pages = sorted(Path(directory).glob("page-*.json"))

        self.assertEqual(
            [product["id"] for product in result.products], ["1", "2", "3"]
        )
        self.assertEqual(result.reported_result_count, 3)
        self.assertEqual(len(raw_pages), 2)
        request_params = [
            request[2]["json"]["requests"][0]["params"] for request in session.requests
        ]
        self.assertIn("page=0", request_params[0])
        self.assertIn("page=1", request_params[1])


class OutputTests(unittest.TestCase):
    def test_output_directory_and_both_result_formats_are_created(self):
        product = {
            "id": "1",
            "name": "Bread",
            "brand": "Bakery",
            "price": "$2.00",
            "unit_price": "$0.10/oz",
            "size": "20 oz",
            "url": "https://example.test/bread",
            "image": None,
            "availability": True,
            "raw_text": None,
        }
        result = SearchResult(
            GroceryStore.TARGET,
            "bread",
            [product],
            "test",
            reported_result_count=1,
            store_id="3991",
        )
        with tempfile.TemporaryDirectory() as directory:
            run_directory = prepare_run_directory(
                directory, GroceryStore.TARGET, "bread"
            )
            save_result(run_directory, result)
            saved = json.loads((run_directory / "results.json").read_text())
            csv_text = (run_directory / "results.csv").read_text()

        self.assertEqual(saved["product_count"], 1)
        self.assertEqual(saved["products"][0]["name"], "Bread")
        self.assertIn("Bread", csv_text)


if __name__ == "__main__":
    unittest.main()
