# food_search.py
# This script goes through a list of food items (str) and returns a dictionary of the foods and what populates.

# Source: https://www.youtube.com/watch?v=R9HNsnbYh8o&list=TLPQMTgwNjIwMja9eQrylFDypg&index=1
# Great resource for SeleniumBase usage patterns
# Xvfb intergration for Linux systems that don't have a GUI

from seleniumbase import SB
from enum import Enum
import re

class GroceryStore(Enum):
    FOODLION = 0
    GIANT = 1
    SAMSCLUB = 2
    WEGMANS = 3
    TARGET = 4

def sanitize_filename(value: str) -> str:
    """Create a filesystem-safe name for captured HTML files."""
    return re.sub(r"[^a-zA-Z0-9._-]", "_", value)

def emulate_browser(url:str, search:str, webpage_path:str="webpages"):
    # TODO: Set Geo location for better price tracking

    with SB(uc=True, test=True, ad_block=True) as sb:
        sb.activate_cdp_mode(url)
        print("Letting webpage load...")
        sb.sleep(5)

        # For FoodLion & GiantFoods
        restricted_button = 'p[class="captcha__human__title no-margin"]'
        for attempt in range(2):
            if not sb.is_element_visible(restricted_button):
                break
            print("Access Restricted")
            if attempt == 1:
                print("Blocked by anti-bot challenge. Stop and retry later from a warmed browser session.")
                return None
            sb.reload_page()
            print("Letting webpage reload...")
            sb.sleep(6)

        sb.wait_for_ready_state_complete()

        # Not sure if any websites have this
        close_button = 'button[id="close-button"]'
        if sb.is_element_visible(close_button):
            sb.cdp.gui_click_element(close_button)
            sb.sleep(0.6)


        # Bot detection came up for SAMS CLUB
        captcha_tag = "#px-captcha"
        if sb.is_element_visible(captcha_tag):
            sb.cdp.gui_click_and_hold(captcha_tag, 7.2)
            sb.sleep(4.2)

            if sb.is_element_visible(captcha_tag):
                sb.cdp.gui_click_and_hold(captcha_tag, 4.2)
                sb.sleep(3.2)

            if sb.is_element_visible(captcha_tag):
                return None

        
        # Save webpage for later
        print(f'({url}) Search for "{search}"')
        title = sb.get_page_title()
        safe_title = sanitize_filename(title)
        safe_search = sanitize_filename(search)
        html = sb.get_html()
        with open(f"{webpage_path}/{safe_search}_{safe_title}.html", 'w', encoding="utf-8") as f:
            f.write(html)
            print(f"{title} html saved. ({webpage_path})")

        return html
    
    #TODO: Click "Show More" or Next Page to get ALL results
    """
    Food Lion: "Show More"
    Giant Foods: "Show More"
    Sams Club: Click next page "arrow"
    Wegmans: All of them
    Target: Click next page "arrow"
    """




def main():
    LINKS = {
        'FOODLION': lambda search_term: f'https://foodlion.com/product-search/{search_term}?searchRef=&semanticSearch=false',
        'GIANT': lambda search_term: f'https://giantfood.com/product-search/{search_term}?searchRef=&semanticSearch=false',
        'SAMSCLUB': lambda search_term: f'https://www.samsclub.com/search?q={search_term}',
        'WEGMANS': lambda search_term: f'https://www.wegmans.com/shop/search?query={search_term}',
        'TARGET': lambda search_term: f'https://www.target.com/s?searchTerm={search_term}'
    }
    LINK = LINKS[GroceryStore(int(input(f"Enter a link to emulate browser (1: {LINKS.keys()[0]}, 2: {LINKS.keys()[1]}, 3: {LINKS.keys()[2]}, 4: {LINKS.keys()[3]}, 5: {LINKS.keys()[4]}): "))-1)]
    emulate_browser(LINK, "Bread")



if __name__ == "__main__":
    main()