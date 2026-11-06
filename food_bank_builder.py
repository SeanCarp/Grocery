import argparse
import csv
import json
import os
import random
import shutil
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any
from urllib.parse import quote

# Optional Frameworks: Seleniumbase, Pydoll
from mycdp import input_ as cdp_input  # Chrome DevTools Input domain, bundled with SeleniumBase
from seleniumbase import sb_cdp
from seleniumbase.core import detect_b_ver

# Target/Wegmans API adapters and the Food Lion/Giant product extraction script live here.
import food_search

# Dedicated profiles (.chrome-profile, .brave-profile) keep the DataDome cookie between runs.
PROJECT_DIR = Path(__file__).resolve().parent
BROWSERS = ["chrome", "brave"]

# Where each browser keeps your everyday profile. --use-my-profile copies it, never opens it directly.
PERSONAL_PROFILES = {
    "chrome": {
        "linux": "~/.config/google-chrome",
        "darwin": "~/Library/Application Support/Google/Chrome",
        "win32": "%LOCALAPPDATA%/Google/Chrome/User Data",
    },
    "brave": {
        "linux": "~/.config/BraveSoftware/Brave-Browser",
        "darwin": "~/Library/Application Support/BraveSoftware/Brave-Browser",
        "win32": "%LOCALAPPDATA%/BraveSoftware/Brave-Browser/User Data",
    },
}
PROFILE_COPY_DIR = Path.home() / ".cache" / "grocery"
# Caches and lock files: large, rebuilt on launch, or they would make the copy look already open.
PROFILE_COPY_SKIP = shutil.ignore_patterns(
    "Cache", "Code Cache", "GPUCache", "DawnGraphiteCache", "DawnWebGPUCache", "CacheStorage",
    "ScriptCache", "Singleton*", "LOCK", "lockfile",
)

# DataDome draws its page in an iframe: t=bv is a hard block, t=fe is the slider CAPTCHA.
DATADOME_CHALLENGE = """(() => {
  const frame = document.querySelector('iframe[src*="captcha-delivery.com"]');
  return frame ? new URL(frame.src).searchParams.get('t') || 'unknown' : null;
})()"""
RESULT_TILE = "li.product-grid-cell"
TILE_COUNT = f"document.querySelectorAll('{RESULT_TILE}').length"
SHOW_MORE = "#show-more-button"
NO_RESULTS = r"""/\b(0 results|no results|no products found)\b/i.test(document.body?.innerText || '')"""
RESULT_FIELDS = [
    "id", "name", "brand", "price", "unit_price", "size", "url", "image", "availability", "raw_text"
]

class AccessBlocked(RuntimeError):
    """The store's bot protection refused this browser."""

class HardBlock(AccessBlocked):
    """DataDome's 'Access is temporarily restricted' page; the profile's cookie is now flagged."""

def datadome_challenge(sb) -> str | None:
    """Return the DataDome challenge type ('bv' or 'fe'), or None when the page is clear."""
    try:
        challenge = sb.evaluate(DATADOME_CHALLENGE)
    except Exception:
        return None  # Page is mid-navigation; the next check will see the challenge.
    return None if challenge == "unknown" else challenge

def wait_for_access(sb, headless: bool) -> None:
    """Return once no DataDome challenge is showing; raise if it cannot be passed."""
    deadline = time.monotonic() + 120
    prompted = False
    while challenge := datadome_challenge(sb):
        if challenge == "bv":
            raise HardBlock(
                "DataDome blocked this browser/IP ('Access is temporarily restricted'). "
                "Retrying right away will not help; wait a few hours or change networks. "
                "The next run starts with a fresh browser profile."
            )
        if headless:
            raise AccessBlocked("DataDome wants a CAPTCHA. Rerun with --headed and complete it once.")
        if time.monotonic() > deadline:
            raise AccessBlocked("DataDome CAPTCHA was not completed within 120 seconds.")
        if not prompted:
            print("DataDome CAPTCHA: complete the slider in the browser window (remembered by the profile).")
            prompted = True
        sb.sleep(1)

class CollectionType(Enum):
    SCRAPE = "scrape"
    API = "api"

# (search term, raw output directory, store id or None for the default) -> normalized products
ApiSearch = Callable[[str, Path, str | None], list[dict[str, Any]]]

@dataclass(frozen=True)
class GroceryStore:
    endpoint: str
    method: CollectionType
    search_path: str | None = None  # "{}" is replaced by the URL-quoted search term
    api_search: ApiSearch | None = None

    @property
    def supported(self) -> bool:
        return self.search_path is not None or self.api_search is not None

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
        "https://www.wegmans.com", CollectionType.API,
        api_search=lambda term, raw, store_id: food_search.search_wegmans(
            term, raw, store_id or food_search.WEGMANS_DEFAULT_STORE
        ).products,
    ),
    StoreDefinition.TARGET: GroceryStore(
        "https://www.target.com", CollectionType.API,
        api_search=lambda term, raw, store_id: food_search.search_target(
            term, raw, store_id or food_search.TARGET_DEFAULT_STORE
        ).products,
    ),
    StoreDefinition.KROGER: GroceryStore(
        "https://www.kroger.com", CollectionType.API
    ),
    StoreDefinition.GIANTEAGLE: GroceryStore(
        "https://www.gianteagle.com", CollectionType.SCRAPE
    )
}

SUPPORTED_STORES = [name for name, store in GroceryStores.items() if store.supported]

def store_choice(text: str) -> StoreDefinition:
    """argparse type: accept a supported store name in any letter case."""
    for name in SUPPORTED_STORES:
        if text.strip().lower() == name.value.lower():
            return name
    raise argparse.ArgumentTypeError(
        f"{text!r} is not supported; choose from: {', '.join(name.value for name in SUPPORTED_STORES)}"
    )

def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """ Grabs the arguments from the command line.

    Args:
        argv (Sequence[str] | None, optional): Arguments to parse. Defaults to sys.argv.

    Returns:
        argparse.Namespace: store, search, output_dir, store_id and browser_mode
    """
    parser = argparse.ArgumentParser(description="Saving all the public grocery search results.")

    store_names = ", ".join(f'"{name.value}"' for name in SUPPORTED_STORES)
    parser.add_argument("--store", type=store_choice, help=f"retailer: {store_names}")
    parser.add_argument("--search", help="Search term")
    parser.add_argument("--output-dir", default="webpages", help="parent output directory")
    parser.add_argument(
        "--store-id",
        help=f"Target or Wegmans store number (defaults: Target {food_search.TARGET_DEFAULT_STORE}, "
             f"Wegmans {food_search.WEGMANS_DEFAULT_STORE})",
    )

    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--headed", action="store_const", const="headed", dest="browser_mode",
                      help="show the browser window (default when a display is available)")
    mode.add_argument("--headless", action="store_const", const="headless", dest="browser_mode",
                      help="hide the browser window (DataDome usually asks for a CAPTCHA then)")

    parser.add_argument("--browser", choices=BROWSERS, default="chrome",
                        help="browser for Food Lion and Giant Foods (default: chrome)")
    parser.add_argument("--use-my-profile", action="store_true",
                        help="start from a fresh copy of your everyday browser profile (its cookies "
                             "often pass DataDome); your real profile is never opened or changed")

    parser.set_defaults(browser_mode="auto")
    return parser.parse_args(argv)

def display_available() -> bool:
    """Linux needs an X11 or Wayland display for a visible browser; macOS and Windows always have one."""
    if not sys.platform.startswith("linux"):
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))

def browser_binary(browser: str) -> str:
    binary = detect_b_ver.get_binary_location(browser)
    if not binary or not os.path.exists(binary):
        raise RuntimeError(f"Could not find {browser.title()}. Install it or choose another --browser.")
    return binary

def personal_profile(browser: str) -> Path:
    platform = "linux" if sys.platform.startswith("linux") else sys.platform
    return Path(os.path.expandvars(os.path.expanduser(PERSONAL_PROFILES[browser][platform])))

def copy_personal_profile(browser: str) -> tuple[Path, str]:
    """Copy your last-used profile and 'Local State' (it holds the cookie key on Windows).

    Returns the copy's user data folder and the profile folder name inside it.
    """
    source = personal_profile(browser)
    if not (source / "Local State").is_file():
        raise RuntimeError(f"No {browser.title()} profile found in {source}.")
    local_state = json.loads((source / "Local State").read_text(encoding="utf-8"))
    profile = local_state.get("profile", {}).get("last_used") or "Default"

    destination = PROFILE_COPY_DIR / f"{browser}-profile"
    shutil.rmtree(destination, ignore_errors=True)
    shutil.copytree(source / profile, destination / profile, ignore=PROFILE_COPY_SKIP)
    shutil.copy2(source / "Local State", destination / "Local State")
    return destination, profile

def linux_password_store() -> str:
    """The keyring holding the cookie key. SeleniumBase passes --password-store=basic, which
    cannot read cookies saved by your everyday browser."""
    if "KDE" in os.environ.get("XDG_CURRENT_DESKTOP", "").upper():
        version = os.environ.get("KDE_SESSION_VERSION", "")
        return f"kwallet{version}" if version in ("5", "6") else "kwallet"
    return "gnome-libsecret"

def browser_launch(browser: str, use_my_profile: bool) -> tuple[Path, dict[str, Any]]:
    """Return the user data folder to use and the extra sb_cdp.Chrome options."""
    options: dict[str, Any] = {"browser_executable_path": browser_binary(browser)}
    if not use_my_profile:
        return PROJECT_DIR / f".{browser}-profile", options

    profile_dir, profile = copy_personal_profile(browser)
    options["browser_args"] = [f"--profile-directory={profile}"]
    if sys.platform.startswith("linux"):
        options["browser_args"].append(f"--password-store={linux_password_store()}")
    return profile_dir, options

def remove_profile(profile_dir: Path) -> None:
    """Delete a profile folder. The browser still writes its settings for a moment after quit()."""
    for _ in range(10):
        shutil.rmtree(profile_dir, ignore_errors=True)
        time.sleep(1)
        if not profile_dir.exists():
            return

def wait_for_results(sb, headless: bool) -> bool:
    """Wait for result tiles. Returns False if the store says nothing matched."""
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        wait_for_access(sb, headless)
        if sb.evaluate(TILE_COUNT):
            return True
        if sb.evaluate(NO_RESULTS):
            return False
        sb.sleep(1)
    raise RuntimeError("The search page did not show any results within 30 seconds.")

def send_mouse(sb, kind: str, x: float, y: float, **details) -> None:
    sb.loop.run_until_complete(sb.page.send(cdp_input.dispatch_mouse_event(kind, x=x, y=y, **details)))

def human_click(sb, selector: str, pointer: list[float]) -> None:
    """Wheel-scroll to the element, glide the pointer onto it, then press and release.

    sb.click() jumps the page, clicks the exact centre with no mouse movement, and flashes an
    overlay into the page. DataDome hard-blocked that on the first Show More click.
    pointer is the current [x, y] mouse position and is updated in place.
    """
    rect = f"""(() => {{
      const r = document.querySelector({json.dumps(selector)}).getBoundingClientRect();
      return [r.left, r.top, r.width, r.height, innerHeight, scrollY];
    }})()"""
    last_scroll = None
    for _ in range(60):
        left, top, width, height, view_height, scroll = sb.evaluate(rect)
        if 60 < top and top + height < view_height - 60 or scroll == last_scroll:
            break  # comfortably on screen, or the page cannot scroll any further
        last_scroll = scroll
        distance = top + height / 2 - view_height / 2
        step = random.uniform(200, 420)
        send_mouse(sb, "mouseWheel", *pointer, delta_x=0, delta_y=max(-step, min(step, distance)))
        sb.sleep(random.uniform(0.25, 0.6))
    sb.sleep(random.uniform(0.3, 0.9))
    left, top, width, height, _, _ = sb.evaluate(rect)

    # Eased, slightly curved path (quadratic Bezier) to a random point on the element.
    start = tuple(pointer)
    target = (left + width * random.uniform(0.25, 0.75), top + height * random.uniform(0.3, 0.7))
    bend = (
        (start[0] + target[0]) / 2 + random.uniform(-120, 120),
        (start[1] + target[1]) / 2 + random.uniform(-80, 80),
    )
    steps = random.randint(18, 34)
    for step_number in range(1, steps + 1):
        t = step_number / steps
        t = t * t * (3 - 2 * t)
        x = (1 - t) ** 2 * start[0] + 2 * (1 - t) * t * bend[0] + t ** 2 * target[0]
        y = (1 - t) ** 2 * start[1] + 2 * (1 - t) * t * bend[1] + t ** 2 * target[1]
        send_mouse(sb, "mouseMoved", x, y)
        sb.sleep(random.uniform(0.008, 0.03))
    pointer[:] = target

    sb.sleep(random.uniform(0.1, 0.35))
    press = {"button": cdp_input.MouseButton.LEFT, "click_count": 1}
    send_mouse(sb, "mousePressed", *target, buttons=1, **press)
    sb.sleep(random.uniform(0.06, 0.16))
    send_mouse(sb, "mouseReleased", *target, buttons=0, **press)

def search_with_browser(
    store: GroceryStore,
    search_term: str,
    headless: bool,
    browser: str = "chrome",
    use_my_profile: bool = False,
) -> tuple[list[dict[str, Any]], str]:
    """Load every search result (Show More until it disappears); return the products and the page HTML."""
    if store.search_path is None:
        raise NotImplementedError(f"No search URL for {store.endpoint} yet.")
    search_url = store.endpoint + store.search_path.format(quote(search_term, safe=""))
    profile_dir, launch_options = browser_launch(browser, use_my_profile)

    # headed=True keeps SeleniumBase off Xvfb on Linux. No agent/locale options:
    # SeleniumBase applies them as a CDP user-agent override, which DataDome blocks outright.
    try:
        sb = sb_cdp.Chrome(
            store.endpoint, headed=not headless, headless=headless, user_data_dir=str(profile_dir),
            **launch_options,
        )
    except BaseException:
        if use_my_profile:
            shutil.rmtree(profile_dir, ignore_errors=True)
        raise
    hard_blocked = False
    try:
        # A cookieless deep link to search is always blocked; the homepage lets DataDome validate the cookie first.
        sb.sleep(random.uniform(4.0, 6.0))
        wait_for_access(sb, headless)
        sb.open(store.endpoint)
        sb.sleep(random.uniform(2.0, 3.0))
        wait_for_access(sb, headless)
        sb.open(search_url)
        sb.sleep(random.uniform(2.0, 3.0))
        if not wait_for_results(sb, headless):
            print(f"No products matched {search_term!r}.")
            return [], sb.get_page_source()

        pointer = [random.uniform(300, 900), random.uniform(200, 500)]
        send_mouse(sb, "mouseMoved", *pointer)
        while sb.is_element_visible(SHOW_MORE):
            shown = sb.evaluate(TILE_COUNT)
            print(f"Loaded {shown} products so far...")
            human_click(sb, SHOW_MORE, pointer)
            deadline = time.monotonic() + 20
            while sb.evaluate(TILE_COUNT) <= shown:
                wait_for_access(sb, headless)
                if time.monotonic() > deadline:
                    raise RuntimeError(f"Show More stopped loading products after {shown}.")
                sb.sleep(random.uniform(1.0, 2.5))
            sb.sleep(random.uniform(2.0, 4.5))

        # Keyed by product id so a tile rendered twice is only saved once.
        products = {
            str(product.get("id") or product.get("url")): product
            for product in sb.evaluate(food_search.AHOLD_PRODUCTS_SCRIPT)
        }
        print(f"Loaded {len(products)} products from {search_url}")
        return list(products.values()), sb.get_page_source()
    except HardBlock:
        hard_blocked = True
        raise
    finally:
        sb.quit()
        # A blocked profile stays blocked (a fresh one got the slider minutes later), so start clean next run.
        # A copy of your own profile holds your logins, so it is never left behind.
        if hard_blocked or use_my_profile:
            remove_profile(profile_dir)

def prompt_grocery_store() -> StoreDefinition:
    """Grabs the grocery store the user wants, forces it be within the supported list

    Returns:
        StoreDefinition: The store's name, used as the key into GroceryStores
    """
    menu = ", ".join(
        f"{index + 1}: {name.value}"
        for index, name in enumerate(SUPPORTED_STORES)
    )
    while True:
        choice_text = input(f"Select a store ({menu}): ").strip()
        if choice_text.isdigit() and 1 <= int(choice_text) <= len(SUPPORTED_STORES):
            return SUPPORTED_STORES[int(choice_text) - 1]
        print(f"Please select a number between 1 and {len(SUPPORTED_STORES)}.")

def prepare_run_directory(output_dir: str | Path, store_name: StoreDefinition, search_term: str) -> Path:
    """Create a new <term>_<store>_<timestamp>/raw folder so old results are never overwritten."""
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    name = "_".join(food_search.sanitize_filename(part) for part in (search_term, store_name.value, timestamp))
    run_directory = Path(output_dir) / name
    suffix = 2
    while run_directory.exists():
        run_directory = Path(output_dir) / f"{name}_{suffix}"
        suffix += 1
    (run_directory / "raw").mkdir(parents=True)
    return run_directory

def save_results(
    run_directory: Path,
    store_name: StoreDefinition,
    search_term: str,
    store_id: str | None,
    products: list[dict[str, Any]],
) -> None:
    """Write results.json (with search details) and results.csv (one row per product)."""
    food_search.write_json(run_directory / "results.json", {
        "store": store_name.value,
        "search_term": search_term,
        "store_id": store_id,
        "searched_at": datetime.now(UTC).isoformat(),
        "product_count": len(products),
        "products": products,
    })
    with (run_directory / "results.csv").open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=RESULT_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(products)

def run_search(
    store_name: StoreDefinition,
    search_term: str,
    output_dir: str | Path = "webpages",
    headless: bool = False,
    store_id: str | None = None,
    browser: str = "chrome",
    use_my_profile: bool = False,
) -> Path:
    """Search one store, save every result, and return the folder they were saved in."""
    # TODO: Use a real location (e.g. 36.06, -76.713 / store 1123) for Food Lion and Giant pricing.
    store = GroceryStores[store_name]
    if not store.supported:
        raise NotImplementedError(f"{store_name.value} search is not built yet.")

    run_directory = prepare_run_directory(output_dir, store_name, search_term)
    try:
        if store.method == CollectionType.API:
            print(f"Searching {store_name.value} for {search_term!r} through its public API...")
            products = store.api_search(search_term, run_directory / "raw", store_id)
        else:
            print(f"Searching {store_name.value} for {search_term!r} in {browser.title()}...")
            products, page_html = search_with_browser(store, search_term, headless, browser, use_my_profile)
            (run_directory / "raw" / "page-001.html").write_text(page_html, encoding="utf-8")
        save_results(run_directory, store_name, search_term, store_id, products)
    except BaseException:
        shutil.rmtree(run_directory, ignore_errors=True)  # never leave a half-finished result folder
        raise
    return run_directory

def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        store_name = args.store or prompt_grocery_store()
        search_term = (args.search or "").strip() or input("Enter a search term [Bread]: ").strip() or "Bread"
        if args.browser_mode == "auto":
            headless = not display_available()
        else:
            headless = args.browser_mode == "headless"

        run_directory = run_search(
            store_name, search_term, args.output_dir, headless, args.store_id, args.browser, args.use_my_profile
        )
    except (RuntimeError, OSError) as error:  # also AccessBlocked, food_search.SearchError, profile copy errors
        print(f"Search failed: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nSearch canceled.", file=sys.stderr)
        return 130

    print(f"Saved results to {run_directory}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
