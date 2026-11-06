# Grocery
**The purpose of this repo is to be able to track and improve food eating habits at the same time reducing the amount of money spent at the grocery store**

## `food_bank_builder.py`

Searches one store and saves every result an anonymous visitor can see.

| Store | How | Needs |
|---|---|---|
| Food Lion | Chrome or Brave (SeleniumBase CDP mode) | Google Chrome or Brave installed |
| Giant Foods | Chrome or Brave (SeleniumBase CDP mode) | Google Chrome or Brave installed |
| Target | public search API | keys in `.env` |
| Wegmans | public search API | keys in `.env` |

Sam's Club, Kroger, and Giant Eagle are not built yet.

### Setup

1. Install [uv](https://docs.astral.sh/uv/getting-started/installation/) and Google Chrome.
2. In this folder run:
   ```bash
   uv sync
   ```
   uv installs Python 3.12 and the dependencies for you.
3. For Target and Wegmans, copy the `.env` file into this folder (it is not in git).

### Run

```bash
uv run python food_bank_builder.py
```

It asks for the store and search term. Or pass them directly:

```bash
uv run python food_bank_builder.py --store "Food Lion" --search bread
uv run python food_bank_builder.py --store "giant foods" --search "whole milk"
uv run python food_bank_builder.py --store target --search apples --store-id 3991
uv run python food_bank_builder.py --store "Food Lion" --search bread --browser brave --use-my-profile
```

- `--browser chrome|brave`: which browser opens Food Lion and Giant (default: chrome).
- `--use-my-profile`: start from a copy of your everyday Chrome/Brave profile. A profile you
  browse with normally already has DataDome's "trusted" cookie, so it gets fewer puzzles and
  blocks. The copy is made fresh in `~/.cache/grocery/` for each run and deleted afterwards;
  your real profile is only read, never opened or changed, and your browser can stay open.

Each run creates a new folder such as `webpages/bread_Food_Lion_20261106T053327Z/` with:

- `results.csv`: one row per product (name, price, unit price, size, link, ...), opens in Excel
- `results.json`: the same products plus the search details
- `raw/`: the original page HTML or API responses

A failed search prints `Search failed: <reason>`, exits with code 1, and leaves no folder behind.

### Food Lion and Giant: bot protection (DataDome)

Both sites use DataDome, so the script drives a real, visible browser window:

- **First run:** DataDome may show a slider puzzle. Complete it in the browser window within
  120 seconds. The script keeps its own browser profile in `.chrome-profile/` (or
  `.brave-profile/`), so it is remembered for later runs.
- **"Access is temporarily restricted":** DataDome has blocked this network for now. Retrying
  right away makes it worse; wait a few hours or try another network. The script deletes its
  profile after a block so the next run starts clean. With `--use-my-profile` the block can
  also follow your everyday browser on that site for a while.
- Keep the browser window visible (the default). `--headless` hides it, but DataDome then
  usually wants a CAPTCHA that can't be solved, and the search fails.
- Run one search at a time; searches share the profile folder.
- Prices are for the store's default location, not a specific store.
- `--use-my-profile` is tested on Linux (KDE). On Linux the cookies are unlocked with your
  desktop keyring (KWallet on KDE, GNOME Keyring elsewhere), so run it from your desktop
  session, not over SSH. macOS may ask for Keychain access. Windows is untested.

### Tests

```bash
uv run python -m unittest discover -s tests
```

## `food_search.py`

The earlier all-in-one search script. `food_bank_builder.py` reuses its Target/Wegmans API
code and its Food Lion/Giant product extraction. Run it with
`uv run python food_search.py --store target --search bread`. Its browser mode uses a new
profile and a locale override on every run, which DataDome blocks, so use
`food_bank_builder.py` for Food Lion and Giant.

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
