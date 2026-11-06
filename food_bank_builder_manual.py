import argparse
import random, time
from enum import Enum
from dataclasses import dataclass
from collections.abc import Sequence
from pathlib import Path
from urllib.parse import quote

# Optional Frameworks: Seleniumbase, Pydoll
from seleniumbase import sb_cdp

# Dedicated profile (never your personal Chrome one): it keeps the DataDome cookie between runs.
PROFILE_DIR = Path(__file__).resolve().with_name(".chrome-profile")

# DataDome draws its page in an iframe: t=bv is a hard block, t=fe is the slider CAPTCHA.
DATADOME_CHALLENGE = """(() => {
  const frame = document.querySelector('iframe[src*="captcha-delivery.com"]');
  return frame ? new URL(frame.src).searchParams.get('t') || 'unknown' : null;
})()"""
RESULT_TILE = "li.product-grid-cell"
TILE_COUNT = f"document.querySelectorAll('{RESULT_TILE}').length"
SHOW_MORE = "#show-more-button"

class AccessBlocked(RuntimeError):
    """The store's bot protection refused this browser."""

def is_datadome_challenge(sb) -> bool:
    """Check if DataDome challenge is active by checking for iframe with captcha-delivery.com"""
    try:
        # Check if the iframe exists that contains the DataDome CAPTCHA
        challenge = sb.evaluate(DATADOME_CHALLENGE)
        return challenge is not None and challenge != "unknown"
    except Exception:
        return False

def wait_for_access(sb, headless: bool) -> None:
    """Return once no DataDome challenge is showing; raise if it cannot be passed."""
    print("Checking for DataDome challenges...")
    deadline = time.monotonic() + 120
    prompted = False
    while is_datadome_challenge(sb):
        challenge = sb.evaluate(DATADOME_CHALLENGE)
        if challenge == "bv":
            raise AccessBlocked(
                "DataDome blocked this browser/IP ('Access is temporarily restricted'). "
                "Retrying right away will not help; wait a few hours or change networks."
            )
        if headless:
            raise AccessBlocked("DataDome wants a CAPTCHA. Rerun with --headed and complete it once.")
        if time.monotonic() > deadline:
            raise AccessBlocked("DataDome CAPTCHA was not completed within 120 seconds.")
        if not prompted:
            print("DataDome CAPTCHA: complete the slider in the browser window (remembered by the profile).")
            print("You can now manually complete the CAPTCHA. The script will wait for completion.")
            prompted = True
        sb.sleep(1)
    print("No DataDome challenge detected.")

class CollectionType(Enum):
    SCRAPE = "scrape"
    API = "api"

@dataclass(frozen=True)
class GroceryStore:
    endpoint: str
    method: CollectionType
    search_path: str | None = None  # "{}" is replaced by the URL-quoted search term

class StoreDefinition(str, Enum):
    FOODLION = "Food Lion"
    GIANT = "Giant Foods"
    SAMSCLUB = "Sams Club"
    WEGMANS = "Wegmans"
    TARGET = "Target"
    KROGER = "Kroger"
    GIANTEAGLE = "Giant Eagle"

GroceryStores = {
    StoreDefinition.FOODLION: GroceryStore(
        "https://foodlion.com", CollectionType.SCRAPE,
        "/product-search/{}?searchRef=&semanticSearch=false"
    ),
    StoreDefinition.GIANT: GroceryStore(
        "https://giantfood.com", CollectionType.SCRAPE,
        "/product-search/{}?searchRef=&semanticSearch=false"
    ),
    StoreDefinition.SAMSCLUB: GroceryStore(
        "https://www.samsclub.com", CollectionType.SCRAPE
    ),
    StoreDefinition.WEGMANS: GroceryStore(
        "https://www.wegmans.com", CollectionType.SCRAPE
    ),
    StoreDefinition.TARGET: GroceryStore(
        "https://www.target.com", CollectionType.SCRAPE
    ),
    StoreDefinition.KROGER: GroceryStore(
        "https://www.kroger.com", CollectionType.API
    ),
    StoreDefinition.GIANTEAGLE: GroceryStore(
        "https://www.gianteagle.com", CollectionType.SCRAPE
    )
}

def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """ Grabs the arguments from the command line.

    Args:
        argv (Sequence[str] | None, optional): _description_. Defaults to None.

    Returns:
        argparse.Namespace: _description_
    """
    parser = argparse.ArgumentParser(description="Saving all the public grocery search results.")    
    
    parser.add_argument("--store", choices=GroceryStores.keys(), help="retailer")
    parser.add_argument("--search", help="Search term")
    parser.add_argument("--output-dir", default="webpages", help="parent output directory")

    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--headed", action="store_const", const="headed", dest="browser_mode")
    mode.add_argument("--headless", action="store_const", const="headless", dest="browser_mode")

    parser.set_defaults(browser_mode="auto")
    return parser.parse_args(argv)

def search_with_browser(store: GroceryStore, search_term: str, headless: bool) -> str:
    """Load every search result (Show More until it disappears) and return the page HTML."""
    if store.search_path is None:
        raise NotImplementedError(f"No search URL for {store.endpoint} yet.")
    search_url = store.endpoint + store.search_path.format(quote(search_term, safe=""))

    # headed=True keeps SeleniumBase off Xvfb on Linux. No agent/locale options:
    # SeleniumBase applies them as a CDP user-agent override, which DataDome blocks outright.
    print(f"Opening browser for {store.endpoint}")
    sb = sb_cdp.Chrome(
        store.endpoint, headed=not headless, headless=headless, user_data_dir=str(PROFILE_DIR)
    )
    try:
        # A cookieless deep link to search is always blocked; the homepage lets DataDome validate the cookie first.
        print("Waiting for initial page load...")
        sb.sleep(random.uniform(4.0, 6.0))
        wait_for_access(sb, headless)
        
        print("Opening homepage...")
        sb.open(store.endpoint)
        sb.sleep(random.uniform(2.0, 3.0))
        wait_for_access(sb, headless)
        
        print(f"Opening search URL: {search_url}")
        sb.open(search_url)
        sb.sleep(random.uniform(2.0, 3.0))
        wait_for_access(sb, headless)
        
        print("Waiting for product results...")
        sb.wait_for_element_visible(RESULT_TILE, timeout=20)

        # Add extra wait to ensure page is fully loaded
        sb.sleep(2)
        
        result_count = sb.evaluate(TILE_COUNT)
        print(f"Found {result_count} products initially")
        
        while sb.is_element_visible(SHOW_MORE):
            shown = sb.evaluate(TILE_COUNT)
            print("Clicking 'Show More' button...")
            sb.click(SHOW_MORE)
            deadline = time.monotonic() + 30
            while sb.evaluate(TILE_COUNT) <= shown:
                wait_for_access(sb, headless)
                if time.monotonic() > deadline:
                    print(f"Show More stopped loading products after {shown}.")
                    raise RuntimeError(f"Show More stopped loading products after {shown}.")
                sb.sleep(1)
            print(f"Loaded {sb.evaluate(TILE_COUNT)} products")
            sb.sleep(random.uniform(1.0, 2.5))

        print(f"Loaded {sb.evaluate(TILE_COUNT)} products from {search_url}")
        return sb.get_page_source()
    finally:
        sb.quit()

def prompt_grocery_store() -> GroceryStore:
    """Grabs the grocery store the user wants, forces it be within the list

    Returns:
        GroceryStore: The name, website, and method to grab the food data
    """
    labels = list(GroceryStores)
    menu = ", ".join(
        f"{index + 1}: {store.value}"
        for index, store, in enumerate(labels)
    )
    while True:
        choice_text = input(f"Select a store ({menu}): ").strip()
        if choice_text.isdigit() and 1 <= int(choice_text) <= len(labels):
            return GroceryStores[labels[int(choice_text) - 1]]
        print(f"Please select a number between 1 and {len(labels)}.")

def run_search(store: GroceryStore, search_term: str, browser_mode: bool=False):
    # Default Geo-location for the search. TODO: This needs to be incorporated better to include 
    location = (36.06, -76.713)
    store_id = 1123

    if store.method == CollectionType.API:
        print("Do API stuff")

    if store.method == CollectionType.SCRAPE:
        print("Do Scraping stuff")
        result = search_with_browser(store, search_term, browser_mode)

def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv) 
    store = GroceryStores[args.store] if args.store else prompt_grocery_store()
    search_term = args.search.strip() if args.search else input("Enter a search term [Bread]: ").strip() or "Bread"

    try:
        headless = True if args.browser_mode == "headless" else False
        print(f"Running search for {store.endpoint} with term '{search_term}' in {'headless' if headless else 'headed'} mode")
        run_search(store, search_term, headless)
    
    except AccessBlocked as error:
        print(f"Blocked: {error}")
        return 1
    except KeyboardInterrupt:
        print("\nSearch canceled.")
    return 0
        
if __name__ == "__main__":
    raise SystemExit(main())