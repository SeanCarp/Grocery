"""Save every public result for one grocery-store search.

Target and Wegmans use anonymous public search APIs. Food Lion, Giant Food,
and Sam's Club use an isolated SeleniumBase browser because their rendered
search pages are the public search interface.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import platform
import re
import sys
import time
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from urllib.parse import parse_qs, quote, urlencode, urlsplit

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().with_name(".env"))


def environment_integer(name: str, default: int) -> int:
    """Read and validate a positive integer setting."""
    raw_value = os.environ.get(name, str(default))
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer, not {raw_value!r}.") from exc
    if value < 1:
        raise RuntimeError(f"{name} must be greater than zero.")
    return value


HTTP_TIMEOUT_SECONDS = environment_integer("HTTP_TIMEOUT_SECONDS", 30)
TARGET_PAGE_SIZE = environment_integer("TARGET_PAGE_SIZE", 28)
WEGMANS_PAGE_SIZE = environment_integer("WEGMANS_PAGE_SIZE", 100)
TARGET_DEFAULT_STORE = os.environ.get("TARGET_DEFAULT_STORE", "3991")
WEGMANS_DEFAULT_STORE = os.environ.get("WEGMANS_DEFAULT_STORE", "133")
TARGET_REDSKY_KEY = os.environ.get("TARGET_REDSKY_KEY", "")
WEGMANS_ALGOLIA_APP_ID = os.environ.get("WEGMANS_ALGOLIA_APP_ID", "")
WEGMANS_ALGOLIA_KEY = os.environ.get("WEGMANS_ALGOLIA_KEY", "")
USER_AGENT = os.environ.get(
    "USER_AGENT", "grocery-search/0.2 (personal grocery price comparison)"
)


class SearchError(RuntimeError):
    """A search could not be completed without returning partial results."""


class GroceryStore(str, Enum):
    FOODLION = "foodlion"
    GIANT = "giant"
    SAMSCLUB = "samsclub"
    WEGMANS = "wegmans"
    TARGET = "target"


@dataclass(frozen=True)
class StoreDefinition:
    label: str
    homepage: str
    result_selector: str | None = None
    default_store_id: str | None = None


STORE_DEFINITIONS = {
    GroceryStore.FOODLION: StoreDefinition(
        "Food Lion", "https://foodlion.com", "li.product-grid-cell"
    ),
    GroceryStore.GIANT: StoreDefinition(
        "Giant Food", "https://giantfood.com", "li.product-grid-cell"
    ),
    GroceryStore.SAMSCLUB: StoreDefinition(
        "Sam's Club", "https://www.samsclub.com", '[data-testid="item-stack"] h3'
    ),
    GroceryStore.WEGMANS: StoreDefinition(
        "Wegmans",
        "https://www.wegmans.com",
        default_store_id=WEGMANS_DEFAULT_STORE,
    ),
    GroceryStore.TARGET: StoreDefinition(
        "Target", "https://www.target.com", default_store_id=TARGET_DEFAULT_STORE
    ),
}


@dataclass(frozen=True)
class BrowserLaunchPlan:
    headed: bool
    backend: str
    chromium_arg: str | None = None


@dataclass
class SearchResult:
    store: GroceryStore
    search_term: str
    products: list[dict[str, Any]]
    source: str
    reported_result_count: int | None = None
    store_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        definition = STORE_DEFINITIONS[self.store]
        return {
            "schema_version": 1,
            "store": self.store.value,
            "store_name": definition.label,
            "search_term": self.search_term,
            "searched_at": datetime.now(UTC).isoformat(),
            "source": self.source,
            "store_id": self.store_id,
            "product_count": len(self.products),
            "reported_result_count": self.reported_result_count,
            "products": self.products,
        }


def sanitize_filename(value: str) -> str:
    """Return a non-empty, portable filename fragment."""
    sanitized = re.sub(r"[^a-zA-Z0-9._-]+", "_", value).strip("._")
    return sanitized or "search"


def build_search_url(store: GroceryStore, search_term: str) -> str:
    """Build the retailer's normal public search URL."""
    encoded_path = quote(search_term, safe="")
    encoded_query = urlencode({"q": search_term})
    if store is GroceryStore.FOODLION:
        return (
            f"https://foodlion.com/product-search/{encoded_path}"
            "?searchRef=&semanticSearch=false"
        )
    if store is GroceryStore.GIANT:
        return (
            f"https://giantfood.com/product-search/{encoded_path}"
            "?searchRef=&semanticSearch=false"
        )
    if store is GroceryStore.SAMSCLUB:
        return f"https://www.samsclub.com/search?{encoded_query}"
    if store is GroceryStore.WEGMANS:
        return (
            f"https://www.wegmans.com/shop/search?{urlencode({'query': search_term})}"
        )
    return f"https://www.target.com/s?{urlencode({'searchTerm': search_term})}"


def resolve_browser_launch(
    mode: str = "auto",
    environ: Mapping[str, str] | None = None,
    system_name: str | None = None,
) -> BrowserLaunchPlan:
    """Choose a browser mode without assuming X11 or forcing Xvfb."""
    if mode not in {"auto", "headed", "headless"}:
        raise ValueError(f"Unknown browser mode: {mode}")

    env = os.environ if environ is None else environ
    operating_system = platform.system() if system_name is None else system_name
    is_linux = operating_system == "Linux"
    has_x11 = bool(env.get("DISPLAY"))
    has_wayland = bool(env.get("WAYLAND_DISPLAY"))
    has_display = not is_linux or has_x11 or has_wayland

    if mode == "headed" and not has_display:
        raise SearchError(
            "Headed mode needs DISPLAY or WAYLAND_DISPLAY on Linux. "
            "Use --headless on a displayless machine."
        )

    headed = has_display if mode == "auto" else mode == "headed"
    if not headed:
        return BrowserLaunchPlan(False, "headless")
    if is_linux and has_wayland:
        return BrowserLaunchPlan(
            True,
            "wayland",
            "--ozone-platform=wayland",
        )
    if is_linux:
        return BrowserLaunchPlan(True, "x11")
    return BrowserLaunchPlan(True, operating_system.lower())


def prepare_run_directory(
    output_root: str | Path, store: GroceryStore, search_term: str
) -> Path:
    """Create a new output directory so old pages cannot look like new results."""
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    name = f"{sanitize_filename(search_term)}_{store.value}_{timestamp}"
    run_directory = Path(output_root) / name
    suffix = 2
    while run_directory.exists():
        run_directory = Path(output_root) / f"{name}_{suffix}"
        suffix += 1
    (run_directory / "raw").mkdir(parents=True)
    return run_directory


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def save_result(run_directory: Path, result: SearchResult) -> None:
    """Save normalized JSON and a spreadsheet-friendly CSV."""
    write_json(run_directory / "results.json", result.as_dict())
    fields = [
        "id",
        "name",
        "brand",
        "price",
        "unit_price",
        "size",
        "url",
        "image",
        "availability",
        "raw_text",
    ]
    with (run_directory / "results.csv").open(
        "w", encoding="utf-8", newline=""
    ) as output:
        writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(result.products)


def request_json(
    session: requests.Session,
    method: str,
    url: str,
    *,
    retailer: str,
    **kwargs: Any,
) -> dict[str, Any]:
    """Make one contextualized JSON request."""
    try:
        response = session.request(method, url, timeout=HTTP_TIMEOUT_SECONDS, **kwargs)
    except requests.RequestException as exc:
        raise SearchError(f"{retailer} request failed: {exc}") from exc

    if response.status_code == 429:
        raise SearchError(f"{retailer} rate-limited the search (HTTP 429).")
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        raise SearchError(
            f"{retailer} search returned HTTP {response.status_code}."
        ) from exc
    try:
        payload = response.json()
    except requests.JSONDecodeError as exc:
        raise SearchError(f"{retailer} returned a non-JSON search response.") from exc
    if not isinstance(payload, dict):
        raise SearchError(f"{retailer} returned an unexpected search response.")
    return payload


def normalize_target_product(product: Mapping[str, Any]) -> dict[str, Any]:
    item = product.get("item") or {}
    description = item.get("product_description") or {}
    enrichment = item.get("enrichment") or {}
    image_info = enrichment.get("image_info") or {}
    primary_image = image_info.get("primary_image") or {}
    brand = item.get("primary_brand") or {}
    price = product.get("price") or {}
    fulfillment = item.get("fulfillment") or {}
    return {
        "id": product.get("tcin"),
        "name": description.get("title"),
        "brand": brand.get("name"),
        "price": price.get("formatted_current_price"),
        "unit_price": price.get("formatted_unit_price"),
        "size": None,
        "url": enrichment.get("buy_url"),
        "image": primary_image.get("url"),
        "availability": fulfillment.get("is_out_of_stock_in_all_store_locations"),
        "raw_text": None,
    }


def search_target(
    search_term: str,
    raw_directory: Path,
    store_id: str,
    session: requests.Session | None = None,
) -> SearchResult:
    """Fetch every Target RedSky result page."""
    client = session or requests.Session()
    client.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
    api_key = os.environ.get("TARGET_REDSKY_KEY", TARGET_REDSKY_KEY)
    if not api_key:
        raise SearchError("TARGET_REDSKY_KEY is missing from .env.")
    visitor_id = uuid.uuid4().hex[:16].upper()
    endpoint = "https://redsky.target.com/redsky_aggregations/v1/web/plp_search_v2"
    offset = 0
    page_number = 1
    total_results: int | None = None
    products: list[dict[str, Any]] = []

    while total_results is None or offset < total_results:
        params = {
            "key": api_key,
            "keyword": search_term,
            "channel": "WEB",
            "count": str(TARGET_PAGE_SIZE),
            "offset": str(offset),
            "page": f"/s/{search_term}",
            "platform": "desktop",
            "pricing_store_id": store_id,
            "store_id": store_id,
            "visitor_id": visitor_id,
        }
        payload = request_json(
            client, "GET", endpoint, retailer="Target", params=params
        )
        write_json(raw_directory / f"page-{page_number:03d}.json", payload)
        try:
            search = payload["data"]["search"]
            batch = search["products"]
            metadata = search["search_response"]["metadata"]
            total_results = int(metadata["total_results"])
        except (KeyError, TypeError, ValueError) as exc:
            raise SearchError(
                "Target changed its public search response format."
            ) from exc
        if not isinstance(batch, list):
            raise SearchError("Target returned an invalid product list.")
        if not batch and offset < total_results:
            raise SearchError(
                f"Target stopped after {offset} of {total_results} reported results."
            )
        products.extend(normalize_target_product(product) for product in batch)
        offset += len(batch)
        page_number += 1

    if total_results is not None and len(products) < total_results:
        raise SearchError(
            f"Target returned {len(products)} of {total_results} reported results."
        )
    return SearchResult(
        GroceryStore.TARGET,
        search_term,
        products,
        "anonymous Target RedSky API",
        total_results,
        store_id,
    )


def normalize_wegmans_product(product: Mapping[str, Any]) -> dict[str, Any]:
    price = product.get("price_inStore") or {}
    images = product.get("images") or []
    product_id = product.get("productId") or product.get("productID")
    slug = product.get("slug")
    return {
        "id": product_id,
        "name": product.get("productName"),
        "brand": product.get("consumerBrandName") or product.get("brand"),
        "price": f"${price['amount']:.2f}" if price.get("amount") is not None else None,
        "unit_price": price.get("unitPrice"),
        "size": product.get("packSize") or product.get("size"),
        "url": (
            f"https://www.wegmans.com/shop/product/{quote(str(slug))}" if slug else None
        ),
        "image": images[0] if images else None,
        "availability": product.get("isAvailable"),
        "raw_text": None,
    }


def search_wegmans(
    search_term: str,
    raw_directory: Path,
    store_id: str,
    session: requests.Session | None = None,
) -> SearchResult:
    """Fetch every page from Wegmans' public Algolia product index."""
    client = session or requests.Session()
    client.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
    app_id = os.environ.get("WEGMANS_ALGOLIA_APP_ID", WEGMANS_ALGOLIA_APP_ID)
    api_key = os.environ.get("WEGMANS_ALGOLIA_KEY", WEGMANS_ALGOLIA_KEY)
    if not app_id or not api_key:
        raise SearchError(
            "WEGMANS_ALGOLIA_APP_ID and WEGMANS_ALGOLIA_KEY are required in .env."
        )
    endpoint = f"https://{app_id.lower()}-dsn.algolia.net/1/indexes/*/queries"
    page = 0
    page_count: int | None = None
    total_results: int | None = None
    products: list[dict[str, Any]] = []
    filters = (
        f"storeNumber:{store_id} AND fulfilmentType:instore "
        "AND excludeFromWeb:false AND isSoldAtStore:true"
    )

    while page_count is None or page < page_count:
        algolia_params = urlencode(
            {
                "query": search_term,
                "hitsPerPage": WEGMANS_PAGE_SIZE,
                "page": page,
                "filters": filters,
            }
        )
        body = {"requests": [{"indexName": "products", "params": algolia_params}]}
        payload = request_json(
            client,
            "POST",
            endpoint,
            retailer="Wegmans",
            params={
                "x-algolia-application-id": app_id,
                "x-algolia-api-key": api_key,
            },
            json=body,
        )
        try:
            result_page = payload["results"][0]
            batch = result_page["hits"]
            total_results = int(result_page["nbHits"])
            page_count = int(result_page["nbPages"])
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise SearchError(
                "Wegmans changed its public search response format."
            ) from exc
        write_json(raw_directory / f"page-{page + 1:03d}.json", result_page)
        if not isinstance(batch, list):
            raise SearchError("Wegmans returned an invalid product list.")
        if not batch and page + 1 < page_count:
            raise SearchError(f"Wegmans stopped on page {page + 1} of {page_count}.")
        products.extend(normalize_wegmans_product(product) for product in batch)
        page += 1

    if total_results is not None and len(products) < total_results:
        raise SearchError(
            f"Wegmans returned {len(products)} of {total_results} reported results."
        )
    return SearchResult(
        GroceryStore.WEGMANS,
        search_term,
        products,
        "anonymous Wegmans Algolia API",
        total_results,
        store_id,
    )


AHOLD_PRODUCTS_SCRIPT = r"""
(() => [...document.querySelectorAll('li.product-grid-cell')].map(card => {
  const link = card.querySelector("a[id^='product-name-']") ||
               card.querySelector("a[href*='/product/']");
  if (!link) return null;
  const raw = (card.innerText || '').trim();
  const prices = raw.match(/\$\d+(?:\.\d{2})?/g) || [];
  const sizeLine = raw.split('\n').find(line => /\|\s*\$\d/.test(line));
  const href = link.href;
  return {
    id: href.split('/').filter(Boolean).pop(),
    name: (link.innerText || link.getAttribute('aria-label') || '').trim(),
    brand: null,
    price: prices[0] || null,
    unit_price: sizeLine ? sizeLine.split('|').slice(1).join('|').trim() : null,
    size: sizeLine ? sizeLine.split('|')[0].trim() : null,
    url: href,
    image: card.querySelector('img')?.src || null,
    availability: /out of stock/i.test(raw) ? 'out of stock' : null,
    raw_text: raw
  };
}).filter(Boolean))()
"""

SAMS_PRODUCTS_SCRIPT = r"""
(() => [...document.querySelectorAll('[data-testid="item-stack"] a[link-identifier]')]
  .filter(link => link.querySelector('h3'))
  .map(link => {
    const card = link.parentElement;
    const raw = (card?.innerText || link.innerText || '').trim();
    const listButton = card?.querySelector("button[aria-label^='Add to list ']");
    const name = listButton
      ? listButton.getAttribute('aria-label').replace(/^Add to list\s+/, '')
      : (link.querySelector('h3')?.innerText || '').replace(/\s+\$\d.*$/, '');
    const price = raw.match(/current price\s*(\$\d+(?:\.\d{2})?)/i) ||
                  (link.innerText || '').match(/(\$\d+(?:\.\d{2})?)/);
    const unit = raw.match(/(\$\d+(?:\.\d{2})?\/(?:ea|oz|lb|ct))/i);
    return {
      id: link.getAttribute('link-identifier'),
      name: name.trim(),
      brand: null,
      price: price ? price[1] : null,
      unit_price: unit ? unit[1] : null,
      size: null,
      url: link.href,
      image: card?.querySelector('img')?.src || null,
      availability: /out of stock/i.test(raw) ? 'out of stock' : null,
      raw_text: raw
    };
  }))()
"""


def cdp_evaluate(sb: Any, expression: str) -> Any:
    try:
        return sb.cdp.evaluate(expression)
    except Exception as exc:
        raise SearchError(f"Browser page evaluation failed: {exc}") from exc


def page_has_challenge(sb: Any) -> bool:
    expression = r"""
(() => {
  const challenge = document.querySelector(
    'iframe[title*="DataDome"], iframe[src*="captcha-delivery.com"]'
  );
  const px = document.querySelector('#px-captcha');
  const pxVisible = px && getComputedStyle(px).display !== 'none' &&
                    getComputedStyle(px).visibility !== 'hidden';
  return Boolean(challenge || pxVisible || /access denied|access restricted/i.test(document.title));
})()
"""
    return bool(cdp_evaluate(sb, expression))


def wait_for_challenge(sb: Any, headed: bool, retailer: str) -> None:
    """Allow normal manual verification, but never automate a CAPTCHA."""
    if not page_has_challenge(sb):
        return
    if not headed:
        raise SearchError(
            f"{retailer} refused the headless browser. Re-run this store with --headed."
        )
    print(
        f"{retailer} requested browser verification. Complete it in the isolated "
        "browser window; no account sign-in is needed."
    )
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        time.sleep(1)
        if not page_has_challenge(sb):
            return
    raise SearchError(
        f"{retailer} browser verification was not completed in 120 seconds."
    )


def wait_for_results(sb: Any, selector: str, retailer: str, headed: bool) -> None:
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        wait_for_challenge(sb, headed, retailer)
        state = cdp_evaluate(
            sb,
            f"""(() => ({{
              found: Boolean(document.querySelector({json.dumps(selector)})),
              text: (document.body?.innerText || '').slice(-3000)
            }}))()""",
        )
        if state.get("found"):
            return
        if re.search(
            r"\b(0 results|no results|no products found)\b",
            state.get("text", ""),
            re.IGNORECASE,
        ):
            return
        time.sleep(1)
    raise SearchError(
        f"{retailer} did not render its search results within 45 seconds."
    )


def canonicalize_sams_url(url: str) -> str:
    parsed = urlsplit(url)
    redirect = parse_qs(parsed.query).get("rd")
    return redirect[0] if redirect else url


def collect_ahold_products(
    sb: Any, retailer: str, raw_directory: Path
) -> list[dict[str, Any]]:
    """Click Show More until it disappears, accumulating every unique product."""
    products: dict[str, dict[str, Any]] = {}
    load_number = 1
    while True:
        batch = cdp_evaluate(sb, AHOLD_PRODUCTS_SCRIPT)
        for product in batch:
            key = str(product.get("id") or product.get("url"))
            products[key] = product

        button = cdp_evaluate(
            sb,
            r"""(() => {
              const button = document.querySelector('#show-more-button');
              return {
                available: Boolean(button && !button.disabled &&
                  button.getAttribute('aria-disabled') !== 'true'),
                count: document.querySelectorAll('li.product-grid-cell').length
              };
            })()""",
        )
        if not button["available"]:
            break

        before = int(button["count"])
        clicked = cdp_evaluate(
            sb,
            r"""(() => {
              const button = document.querySelector('#show-more-button');
              if (!button || button.disabled) return false;
              button.scrollIntoView({block: 'center'});
              button.click();
              return true;
            })()""",
        )
        if not clicked:
            raise SearchError(
                f"{retailer} exposed Show More but it could not be clicked."
            )

        deadline = time.monotonic() + 30
        progressed = False
        while time.monotonic() < deadline:
            time.sleep(1)
            progress = cdp_evaluate(
                sb,
                r"""(() => {
                  const button = document.querySelector('#show-more-button');
                  return {
                    count: document.querySelectorAll('li.product-grid-cell').length,
                    more: Boolean(button && !button.disabled &&
                      button.getAttribute('aria-disabled') !== 'true')
                  };
                })()""",
            )
            if int(progress["count"]) > before or not progress["more"]:
                progressed = True
                break
        if not progressed:
            raise SearchError(
                f"{retailer} stopped adding products while Show More was still available."
            )
        load_number += 1
        print(f"{retailer}: loaded {len(products)} products ({load_number} batches)")

    final_batch = cdp_evaluate(sb, AHOLD_PRODUCTS_SCRIPT)
    for product in final_batch:
        key = str(product.get("id") or product.get("url"))
        products[key] = product
    (raw_directory / "page-001.html").write_text(
        sb.cdp.get_page_source(), encoding="utf-8"
    )
    return list(products.values())


def collect_sams_products(
    sb: Any,
    initial_url: str,
    retailer: str,
    selector: str,
    headed: bool,
    raw_directory: Path,
) -> list[dict[str, Any]]:
    """Follow every Sam's Club Next Page link and retain each unique item."""
    products: dict[str, dict[str, Any]] = {}
    seen_pages: set[str] = set()
    current_url = initial_url
    page_number = 1

    while True:
        if current_url in seen_pages:
            raise SearchError(f"{retailer} repeated pagination URL {current_url}.")
        seen_pages.add(current_url)
        wait_for_results(sb, selector, retailer, headed)
        batch = cdp_evaluate(sb, SAMS_PRODUCTS_SCRIPT)
        for product in batch:
            product["url"] = canonicalize_sams_url(product["url"])
            key = str(product.get("id") or product.get("url"))
            products[key] = product
        (raw_directory / f"page-{page_number:03d}.html").write_text(
            sb.cdp.get_page_source(), encoding="utf-8"
        )
        print(f"{retailer}: saved page {page_number} ({len(products)} unique products)")

        next_page = cdp_evaluate(
            sb,
            r"""(() => {
              const link = document.querySelector('[data-testid="NextPage"]');
              if (!link || link.getAttribute('aria-disabled') === 'true') return null;
              return link.href || null;
            })()""",
        )
        if not next_page:
            break
        current_url = next_page
        page_number += 1
        sb.cdp.open(current_url)
        time.sleep(4)
        wait_for_challenge(sb, headed, retailer)

    return list(products.values())


def search_with_browser(
    store: GroceryStore,
    search_term: str,
    raw_directory: Path,
    browser_mode: str,
) -> SearchResult:
    """Run one anonymous browser search using disposable browser state."""
    definition = STORE_DEFINITIONS[store]
    if definition.result_selector is None:
        raise ValueError(f"No browser adapter for {store.value}")
    plan = resolve_browser_launch(browser_mode)
    search_url = build_search_url(store, search_term)
    print(
        f"Launching isolated {plan.backend} browser ({'headed' if plan.headed else 'headless'})"
    )

    try:
        from seleniumbase import SB
    except ImportError as exc:
        raise SearchError(
            "SeleniumBase is not installed. Run `uv sync` first."
        ) from exc

    with TemporaryDirectory(prefix="grocery-browser-") as profile_directory:
        options: dict[str, Any] = {
            "uc": True,
            "locale_code": "en-US",
            "window_size": "1280,900",
            "user_data_dir": profile_directory,
            "do_not_track": True,
        }
        if plan.headed:
            options["headed"] = True
            if plan.chromium_arg:
                options["chromium_arg"] = plan.chromium_arg
        else:
            options["headless2"] = True

        try:
            manager = SB(**options)
            with manager as sb:
                print(f"Warming anonymous session on {definition.homepage}")
                sb.activate_cdp_mode(definition.homepage)
                time.sleep(4)
                wait_for_challenge(sb, plan.headed, definition.label)
                sb.cdp.open(search_url)
                time.sleep(5)
                wait_for_challenge(sb, plan.headed, definition.label)
                wait_for_results(
                    sb, definition.result_selector, definition.label, plan.headed
                )
                if store in {GroceryStore.FOODLION, GroceryStore.GIANT}:
                    products = collect_ahold_products(
                        sb, definition.label, raw_directory
                    )
                else:
                    products = collect_sams_products(
                        sb,
                        search_url,
                        definition.label,
                        definition.result_selector,
                        plan.headed,
                        raw_directory,
                    )
        except SearchError:
            raise
        except Exception as exc:
            raise SearchError(
                f"{definition.label} browser search failed: {exc}"
            ) from exc

    return SearchResult(
        store,
        search_term,
        products,
        "anonymous isolated browser",
    )


def run_search(
    store: GroceryStore,
    search_term: str,
    *,
    output_root: str | Path = "webpages",
    store_id: str | None = None,
    browser_mode: str = "auto",
) -> Path:
    """Run a complete search and return the created output directory."""
    term = search_term.strip()
    if not term:
        raise SearchError("Search term cannot be empty.")
    definition = STORE_DEFINITIONS[store]
    selected_store_id = store_id or definition.default_store_id
    run_directory = prepare_run_directory(output_root, store, term)
    raw_directory = run_directory / "raw"

    if store is GroceryStore.TARGET:
        result = search_target(term, raw_directory, selected_store_id or "")
    elif store is GroceryStore.WEGMANS:
        result = search_wegmans(term, raw_directory, selected_store_id or "")
    else:
        result = search_with_browser(store, term, raw_directory, browser_mode)
    save_result(run_directory, result)
    return run_directory


def prompt_for_store() -> GroceryStore:
    stores = list(GroceryStore)
    menu = ", ".join(
        f"{index + 1}: {STORE_DEFINITIONS[store].label}"
        for index, store in enumerate(stores)
    )
    while True:
        choice_text = input(f"Select a store ({menu}): ").strip()
        if choice_text.isdigit() and 1 <= int(choice_text) <= len(stores):
            return stores[int(choice_text) - 1]
        print(f"Please select a number between 1 and {len(stores)}.")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Save all anonymous public grocery search results."
    )
    parser.add_argument(
        "--store", choices=[store.value for store in GroceryStore], help="retailer"
    )
    parser.add_argument("--search", help="search term")
    parser.add_argument(
        "--output-dir", default="webpages", help="parent output directory"
    )
    parser.add_argument(
        "--store-id",
        help=(
            "location-specific store ID (Target default: 3991; Wegmans default: 133)"
        ),
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--headed", action="store_const", const="headed", dest="browser_mode"
    )
    mode.add_argument(
        "--headless", action="store_const", const="headless", dest="browser_mode"
    )
    parser.set_defaults(browser_mode="auto")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    store = GroceryStore(args.store) if args.store else prompt_for_store()
    search_term = args.search
    if search_term is None:
        search_term = input("Enter a search term [Bread]: ").strip() or "Bread"

    try:
        output_directory = run_search(
            store,
            search_term,
            output_root=args.output_dir,
            store_id=args.store_id,
            browser_mode=args.browser_mode,
        )
    except SearchError as exc:
        print(f"Search failed: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nSearch cancelled.", file=sys.stderr)
        return 130

    print(f"Saved complete results to {output_directory}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
