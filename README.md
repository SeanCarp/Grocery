# Grocery
**The purpose of this repo is to be able to track and improve food eating habits at the same time reducing the amount of money spent at the grocery store**

## food_search.py
**Desc:** This script goes through a list of food items and returns a dictioanry of the foods and what populates on the website.

Grocery Stores:
- FoodLion
- Giant Foods
- Sams Club
- Wegmans
- Target


```python
example_dict =
{"Ground Turkey":
    [
        {"Brand": "Butterball...",
        "Link": "<a>",
        "Unit Price": "$4.99/lb"},

        {"Brand": "Honey Farms...",
        "Link": "<a>",
        "Unit Price": "$5.49/lb"}
    ],
"Rice": ...
}
```
>[!NOTE]
>
>TODO: This definitly will need to be improved into a database but good enough for now.
>
>TODO: Can get more accurate price results if user sets the Geolocation

>[!NOTE]
>
>TODO: There are more items that populate on the website need to use interactive tools to select next page.
>
>TODO: Not all results match what the search term says. Need to think of way to determine match. Might need a NLP to section them off. (Embedding Space -> Euclidean distance)


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

