# Grocery search findings

## Current repository findings

- `food_search.py` offers Food Lion, Giant Food, Sam's Club, Wegmans, and Target.
- The current run captured a valid anonymous Sam's Club search page, then failed while saving it because `webpages/` did not exist. The recorded exception is `FileNotFoundError` at `food_search.py:194`.
- The script always requests Xvfb and uses GUI-level mouse actions. That couples it to X11/Xvfb and explains the Wayland portability problem.
- The script stores cookies in `.uc_profile`. Even though that is a project-specific profile, a persistent profile is unnecessary for account-free searches and creates avoidable account/cookie coupling.
- A fresh, temporary SeleniumBase profile loaded Food Lion results anonymously in a headed Chrome session. The same fresh profile in headless Chrome received a DataDome challenge.
- Sam's Club search results also loaded anonymously. Some member-only prices remain hidden unless the retailer chooses to expose them; the scraper must not require a real account to reveal restricted prices.

## Retailer access findings

### Food Lion and Giant Food

Food Lion and Giant use closely related product-search pages. Their normal search pages expose a `Show More` button (`#show-more-button`) and product tiles (`li.product-grid-cell`) after a browser session is accepted. Direct/headless access can receive a DataDome challenge.

A recent independent Giant investigation documents browser-session product endpoints under `/api/v5.0/...`, but also confirms that direct requests are DataDome-protected. This makes normal anonymous browser navigation the least fragile account-free path for these two stores.

- [Giant API research and confirmed browser-session behavior](https://github.com/n0nnac/grocery-store-comparison/blob/main/GIANT_API_RESEARCH.md)
- [Giant Food robots.txt](https://giantfood.com/robots.txt)
- [Food Lion search](https://foodlion.com/search/)

### Sam's Club

The public search page works without signing in and provides ordinary product listings. Search results are paginated. Member-only prices can remain unavailable to an anonymous visitor, and the script should record that public state rather than use a personal account.

- [Sam's Club search](https://www.samsclub.com/search)
- [Official Sam's Club Catalog Item Search API](https://developer.samsclub.com/API/catalog-item-search/)

### Wegmans

Wegmans product search uses a public, search-only Algolia API. It supports explicit page numbers and reports the total number of pages, so the complete public result set can be fetched without a display or customer account. Prices are store-specific, so output must retain the selected/default store number.

- [Documented Wegmans public API surface](https://github.com/BrianVia/wegmans-mcp/blob/main/docs/api-reference.md)
- [Wegmans store locator API](https://www.wegmans.com/api/stores)

### Target

Target's public RedSky aggregation endpoint supports keyword search with `count` and `offset`, allowing complete pagination without a display or customer account. Results and prices are store-specific.

- [Target CLI using the public RedSky API](https://github.com/piekstra/target-cli)
- [RedSky request implementation](https://github.com/piekstra/target-cli/blob/main/src/client.rs)
- [Target developer portal](https://developer.target.com/)

## Implementation decisions

1. Use anonymous, isolated browser state. Never attach to a user's normal Chrome/Firefox profile and never require login credentials.
2. Prefer display-independent public search APIs for Wegmans and Target.
3. Use browser navigation for Food Lion, Giant Food, and Sam's Club, with DOM-level actions rather than desktop mouse automation.
4. Detect X11, Wayland, macOS, Windows, and no-display environments instead of forcing Xvfb everywhere. On Wayland, pass Chromium's native Wayland option; on machines without a display, use headless mode and report an upstream challenge clearly if the retailer refuses headless access.
5. Paginate until the retailer reports no next page or repeated attempts add no new products. Do not silently stop after one page.
6. Save structured JSON for use by later scripts and rendered HTML snapshots for diagnosis/recovery. Create output directories before writing.
7. Preserve public limitations in the output: location-dependent prices, unavailable prices, and retailer challenges must be explicit rather than filled with fake or account-only data.

## Constraints

- Retailer markup, public API keys, and anti-bot policies can change. Each adapter needs a clear failure message and independent selectors/pagination logic.
- “All results” means every result the retailer makes available to the anonymous search session for the selected term and store/location. It cannot include account-only inventory, member pricing, or results a retailer refuses to serve.
- Automated collection should remain at human-scale request rates and comply with each retailer's current terms and robots policy.

## Implemented verification

The completed adapters were exercised against the live retailers with the
search term `Bread`:

| Retailer | Pagination observed | Saved products |
|---|---:|---:|
| Food Lion | `Show More` until absent | 517 |
| Giant Food | `Show More` until absent | 521 |
| Sam's Club | 4 HTML pages | 136 unique |
| Wegmans | 5 Algolia pages | 459 of 459 reported |
| Target | 13 RedSky pages | 363 of 363 reported |

Counts are time- and location-dependent; they are evidence from the verification
run, not fixed expectations. Target and Wegmans now use endpoint pagination
because it is more display-independent and returns structured data. Each
adapter saves every raw response and compares the received product count with
the endpoint's reported total. Receiving fewer products than reported is an
error. Extra returned products are preserved because some totals are estimates.

The three browser adapters use a temporary profile, rendered-DOM pagination,
and no desktop mouse actions. A subsequent headed Food Lion smoke run started
without Xvfb and saved its result successfully.

- [Chromium Ozone overview and native Wayland launch flag](https://chromium.googlesource.com/chromium/src/+/main/docs/ozone_overview.md)
