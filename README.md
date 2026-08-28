# Grocery
**The purpose of this repo is to be able to track and improve food eating habits at the same time reducing the amount of money spent at the grocery store**

## `food_search.py`

Searches one selected retailer and saves every result made available to an
anonymous visitor. Supported retailers:

- Food Lion
- Giant Food
- Sam's Club
- Wegmans
- Target

### Setup

```bash
uv sync
```

Configuration is loaded automatically from the `.env` file beside
`food_search.py`. Existing process environment variables take precedence over
the file. Copy the same `.env` file when running the project on another device.

Food Lion, Giant Food, and Sam's Club require Chrome or Chromium. Target and
Wegmans use public, account-free search APIs and do not launch a browser.

### Run interactively

```bash
uv run python food_search.py
```

The script prompts for the retailer and search term. It creates a timestamped
directory under `webpages/` containing:

- `results.json`: complete normalized result list and search metadata
- `results.csv`: the same product list in spreadsheet-friendly form
- `raw/`: every source API response or rendered HTML page

The output directory is created automatically. Endpoint adapters follow every
reported page and fail rather than save a shortened result set when fewer
products are received than the retailer reports. Any extra returned products
are retained because retailer totals can be estimates.

### Run non-interactively

```bash
uv run python food_search.py --store target --search "whole wheat bread"
uv run python food_search.py --store wegmans --search apples --store-id 133
uv run python food_search.py --store foodlion --search milk --headed
```

Store values are `foodlion`, `giant`, `samsclub`, `wegmans`, and `target`.
`--store-id` controls location-specific Target or Wegmans results. Defaults are
Target `3991` and Wegmans `133`.

### Displays, Wayland, and accounts

Browser searches use a new temporary profile for every run. The script never
opens the user's normal browser profile, reads existing cookies, or requires a
retailer login. Temporary browser state is deleted when the run ends.

Display mode is automatic:

- Linux Wayland: native Chromium Wayland mode
- Linux X11: the current X11 display
- macOS and Windows: the native display
- Linux without a display: headless Chromium

No Xvfb or desktop-level mouse automation is required. `--headed` and
`--headless` override automatic selection. Some retailers reject headless
browsers; in that case, run headed. If a retailer presents a verification
screen, complete it in the isolated window without signing in.

Prices and inventory can depend on location. Anonymous Sam's Club searches may
omit member-only prices; the script records the public result instead of using
a personal account. Technical research and source links are in
[`GPT-findings.md`](GPT-findings.md).


## price_compare.py
**Desc:** After given a "database" (dictionary), it will compare the best price of each against each ottehr to see which store has the best price.
Returns:
* Total difference
* Itemized Recipt
* Category price difference

>[!NOTE]
> 
>TODO: Map products by price & health. Example: FoodLion/GiantFoods corners with Price/Health Axis

## clip_coupons.py
**Desc:** Using the list of foods that the selected store has it goes through the list of coupons and selects eligble items.
Returns:
* List of coupons to clip

>[!Note]
>TODO: Clips coupons for use on user account.
>
>TODO: Recommend coupons that are close to completion (Need Recommendation algorithm)

## foodHealth_API.py
**Desc:** Using the OpenFoodFacts API, add nutrient facts to food quer. Tries to be specific to brand but defaults to the generic food, if not available.

For new foods there will be no sku, this will need to be added after doing a product search. (May require human verification depending on search results and accurary)

There is a nutritional_quality, not as good as Yuka, but there is also an allergen section.

## create_meals.py
**Desc:** Now that we have a complete database, we can generate recipes based on a value score: {time, cost, protien}

>[!Note]
>TODO: Still need to create a database of meals.

