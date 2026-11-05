import argparse
import random, time
from enum import Enum
from dataclasses import dataclass
from collections.abc import Sequence

# Optional Frameworks: Seleniumbase, Pydoll
from seleniumbase import sb_cdp, SB

class CollectionType(Enum):
    SCRAPE = "scrape"
    API = "api"

@dataclass(frozen=True)
class GroceryStore:
    endpoint: str
    method: CollectionType

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
        "https://foodlion.com", CollectionType.SCRAPE
    ),
    StoreDefinition.GIANT: GroceryStore(
        "https://giantfood.com", CollectionType.SCRAPE
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

def search_with_browser(store: GroceryStore, search_term: str, headless: bool):
    # TODO: Is this better or worse to add these flags
    # options.add_argument("--disable-blink-features=AutomationControlled")
    # options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    # TODO: Can you do this using `with`

    # sb = sb_cdp.Chrome(headless=headless)
    # sb.goto(store.endpoint)
    # sb.sleep(random.uniform(2.0, 3.0))

    # print("Solving the CAPTCHA")
    # sb.solve_captcha()

    # print("Clicking the input bar")
    # sb.click("#typeahead-input") # TODO: Should be parameter
    # sb.sleep(random.uniform(0.5, 1.0))

    # sb.press_keys("#typeahead-input") # TODO: Should be parameter
    # sb.sleep(random.uniform(2.0, 3.0))

    BUTTON = "#typeahead-input"
    with SB(uc=True, test=True, headless=False, user_data_dir="/home/swcar/.config/google-chrome/Default", agent="Chrome") as sb:
        sb.uc_open_with_reconnect(store.endpoint, reconnect_time=3)
        for _ in range(3):
            sb.scroll_down(amount=random.randint(200, 500))
            sb.sleep(random.uniform(0.5, 1.5))

        for _ in range(3):
            if "captcha-delivery.com" in sb.get_current_url():
                try:
                    sb.solve_captcha(timeout=20)
                    break
                except Exception:
                    print("Challenge appeared - solve manually in the window")
                    sb.sleep(15)

        clicks = 0
        while clicks < 50:
            if "captcha-delivery.com" in sb.get_current_url():
                try:
                    sb.solve_captcha(timeout=15)
                except Exception:
                    sb.sleep(10)
                continue

            if sb.is_element_visible(BUTTON):
                sb.scroll_to_click(BUTTON)
                clicks += 1
                sb.sleep(random.uniform(1.5, 4.0))
            else:
                try:
                    sb.wait_for_element_visible(BUTTON, timeout=3)
                    continue
                except Exception:
                    break

        sb.wait_for_element_absent(BUTTON, timeout=5)
        print(f"Clicked {clicks} time(s).")

    #     sb.press_keys("input#typeahead-input", search_term + "\n")
    #     sb.sleep(random.uniform(2.0, 3.0))
    #     n = click_until_gone(driver, Button)
    # finally:
    #     driver.quit()

    # quit()
    # with uc.Chrome(options=options, executable_path="/usr/bin/google-chrome-stable",
    #                driver_executable_path="/home/swcar/Projects/Grocery/.venv/lib/python3.12/site-packages/seleniumbase/drivers/uc_driver"
    #         ) as sb:


    #     # Scroll all the way down to page and click "Show More", until "Show More" stops showing up
    #     # Applies: FOOD LION, GIANT FOODS, 
    #     food_lion_sm_button = "button#show-more-button"
    #     MAX_CLICKS = 20
    #     clicks = 0
    #     while clicks < MAX_CLICKS:
    #         if sb.is_element_visible(food_lion_sm_button):
    #             print("Scrolling/Clicking Show More Button")
    #             sb.scroll_to_click(food_lion_sm_button)
    #             clicks += 1
    #             sb.sleep(random.uniform(0.5, 1.5))
    #         else:
    #             try:
    #                 print("Waiting for the button to render (~3secs)")
    #                 sb.wait_for_element_visible(food_lion_sm_button, timeout=3)
    #                 continue
    #             except Exception:
    #                 break
        
        



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
        run_search(store, search_term, headless)
    
    except KeyboardInterrupt:
        print("\nSearch canceled.")
        
if __name__ == "__main__":
    main()