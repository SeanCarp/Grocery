# food_search.py
# This script goes through a list of food items (str) and returns a dictionary of the foods and what populates.

# Source: https://www.youtube.com/watch?v=R9HNsnbYh8o&list=TLPQMTgwNjIwMja9eQrylFDypg&index=1
# Great resource for SeleniumBase usage patterns
# Xvfb intergration for Linux systems that don't have a GUI

import os
import random
import re
from enum import Enum
from urllib.parse import urlsplit

from seleniumbase import SB


class GroceryStore(Enum):
    FOODLION = 0
    GIANT = 1
    SAMSCLUB = 2
    WEGMANS = 3
    TARGET = 4


def sanitize_filename(value: str) -> str:
    """Create a filesystem-safe name for captured HTML files."""
    return re.sub(r"[^a-zA-Z0-9._-]", "_", value)


def get_origin(url: str) -> str:
    """Return scheme://host for a URL (the site homepage to warm up on)."""
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


def is_datadome_blocked(sb: SB) -> bool:
    """Detect DataDome block/challenge markers using CDP-native reads.

    Reading via sb.cdp.* avoids reconnecting the WebDriver, which DataDome
    can fingerprint. Covers both the visible challenge iframe and the
    "Access Restricted" interstitial that appears with no visible captcha.
    """
    challenge_selectors = [
        'iframe[title*="DataDome"]',
        'iframe[src*="captcha-delivery.com"]',
        'script[src*="captcha-delivery.com"]',
    ]
    for selector in challenge_selectors:
        try:
            if sb.cdp.is_element_present(selector):
                return True
        except Exception:
            pass

    try:
        html = sb.cdp.get_page_source()
    except Exception:
        return False

    markers = ("geo.captcha-delivery.com", "DataDome CAPTCHA", "Access Denied")
    return any(marker in html for marker in markers)


def try_solve_datadome(sb: SB) -> bool:
    """If a DataDome *slider* captcha is present, let SeleniumBase solve it."""
    try:
        if sb.cdp._on_a_datadome_slider_page():
            print("DataDome slider detected -> solving...")
            sb.cdp.solve_captcha()
            sb.sleep(random.uniform(1.5, 2.5))
            return True
    except Exception as exc:
        print("Slider solve attempt failed:", exc)
        print("Not an error\n")
    return False


def human_like_activity(sb: SB, moves: int = 6) -> None:
    """Move the mouse and scroll like a human to satisfy behavioral checks.

    DataDome's *invisible* mode scores pointer/scroll behavior. Real cursor
    motion (PyAutoGUI via CDP) needs a headed display; on a headless Linux
    box this works because SB() is launched with xvfb=True.
    """
    try:
        rect = sb.cdp.get_window_rect()
        width = int(rect.get("width") or 1280)
        height = int(rect.get("height") or 800)
    except Exception:
        width, height = 1280, 800

    for _ in range(moves):
        x = random.randint(int(width * 0.15), int(width * 0.85))
        y = random.randint(int(height * 0.15), int(height * 0.85))
        try:
            sb.cdp.gui_hover_x_y(x, y, timeframe=random.uniform(0.3, 0.8))
        except Exception:
            pass
        sb.sleep(random.uniform(0.25, 0.8))

    for _ in range(random.randint(2, 4)):
        try:
            sb.cdp.scroll_down(random.randint(8, 20))
        except Exception:
            pass
        sb.sleep(random.uniform(0.4, 1.0))


def clear_datadome(sb: SB, label: str, attempts: int = 3) -> bool:
    """Try to get past DataDome on the current page. Returns True if clear."""
    for attempt in range(attempts):
        if not is_datadome_blocked(sb):
            return True
        print(f"[{label}] DataDome present (attempt {attempt + 1}/{attempts})")
        if not try_solve_datadome(sb):
            human_like_activity(sb, moves=4)
        sb.sleep(random.uniform(2.0, 4.0))
        sb.cdp.reload()
        sb.sleep(random.uniform(2.5, 4.5))
    return not is_datadome_blocked(sb)


def emulate_browser(url: str, search: str, webpage_path: str = "webpages"):
    # TODO: Set Geo location for better price tracking

    origin = get_origin(url)
    # Persist cookies between runs so DataDome treats us as a returning visitor.
    profile_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), ".uc_profile"
    )

    with SB(
        uc=True,
        test=True,
        ad_block=True,
        xvfb=True,                 # headed virtual display on Linux (needed for GUI mouse)
        locale_code="en-US",
        window_size="1280,800",
        user_data_dir=profile_dir,
    ) as sb:
        # 1) Warm the session on the homepage first -- do NOT deep-link to search.
        #    Hitting /product-search directly is a strong bot signal for DataDome.
        print(f"Warming session on {origin} ...")
        sb.activate_cdp_mode(origin)
        sb.sleep(random.uniform(3.0, 5.0))

        try_solve_datadome(sb)
        human_like_activity(sb)

        if not clear_datadome(sb, "home"):
            print("Still blocked on homepage. Retry later with this warmed profile.")
            return None

        # 2) Now navigate to the real search URL, carrying the clearance cookie.
        print(f"Navigating to search: {url}")
        sb.cdp.open(url)
        sb.sleep(random.uniform(3.0, 5.0))

        try_solve_datadome(sb)
        human_like_activity(sb, moves=4)

        if not clear_datadome(sb, "search", attempts=2):
            print("Blocked on search page. Retry later from a warmed browser session.")
            return None

        # Stay in CDP mode for every read below: switching back to the WebDriver
        # bridge here would reconnect and can re-trigger the DataDome block.

        # Some sites show a modal close button.
        close_button = 'button[id="close-button"]'
        if sb.cdp.is_element_visible(close_button):
            sb.cdp.gui_click_element(close_button)
            sb.sleep(0.6)

        # Bot detection came up for SAMS CLUB (PerimeterX press-and-hold).
        captcha_tag = "#px-captcha"
        if sb.cdp.is_element_visible(captcha_tag):
            sb.cdp.gui_click_and_hold(captcha_tag, 7.2)
            sb.sleep(4.2)

            if sb.cdp.is_element_visible(captcha_tag):
                sb.cdp.gui_click_and_hold(captcha_tag, 4.2)
                sb.sleep(3.2)

            if sb.cdp.is_element_visible(captcha_tag):
                return None

        # Save webpage for later
        print(f'({url}) Search for "{search}"')
        title = sb.cdp.get_title()
        safe_title = sanitize_filename(title)
        safe_search = sanitize_filename(search)
        html = sb.cdp.get_page_source()
        with open(f"{webpage_path}/{safe_search}_{safe_title}.html", "w", encoding="utf-8") as f:
            f.write(html)
            print(f"{title} html saved. ({webpage_path})")

        return html

    # TODO: Click "Show More" or Next Page to get ALL results
    """
    Food Lion: "Show More"
    Giant Foods: "Show More"
    Sams Club: Click next page "arrow"
    Wegmans: All of them
    Target: Click next page "arrow"
    """


def main():
    links = {
        GroceryStore.FOODLION: lambda search_term: f"https://foodlion.com/product-search/{search_term}?searchRef=&semanticSearch=false",
        GroceryStore.GIANT: lambda search_term: f"https://giantfood.com/product-search/{search_term}?searchRef=&semanticSearch=false",
        GroceryStore.SAMSCLUB: lambda search_term: f"https://www.samsclub.com/search?q={search_term}",
        GroceryStore.WEGMANS: lambda search_term: f"https://www.wegmans.com/shop/search?query={search_term}",
        GroceryStore.TARGET: lambda search_term: f"https://www.target.com/s?searchTerm={search_term}",
    }
    stores = list(GroceryStore)
    menu = ", ".join(f"{index + 1}: {store.name}" for index, store in enumerate(stores))

    while True:
        choice_text = input(f"Select a store ({menu}): ").strip()
        if not choice_text.isdigit():
            print("Please enter a number.")
            continue

        choice = int(choice_text)
        if 1 <= choice <= len(stores):
            break

        print(f"Please select a number between 1 and {len(stores)}.")

    search_term = input("Enter a search term [Bread]: ").strip() or "Bread"
    selected_store = stores[choice - 1]
    url = links[selected_store](search_term)
    emulate_browser(url, search_term)


if __name__ == "__main__":
    main()