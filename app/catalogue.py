"""Ingredient knowledge base for South African kitchens.

Each ingredient knows: where it's normally kept, how long it lasts in each place,
what unit we count it in, a rough default amount when someone says "some", a rough
price per unit (for savings when the slip has no price), and words people use for it
(English, Afrikaans, slip abbreviations).

The user never sees categories or storage - this is all background.
Prices are rough 2026 estimates in cents per unit; slip prices override them.
"""
from dataclasses import dataclass, field
import re


@dataclass
class Ingredient:
    key: str
    name: str
    category: str                 # staple | long_life | perishable
    storage: str                  # default: fridge | freezer | cupboard | counter
    shelf: dict                   # days per storage place; missing = not stored there
    unit: str = "count"           # count | g | ml | pack
    default_qty: float = 1        # used for "some X"
    cents_per_unit: float = 0     # rough price per unit (per item, per g, per ml)
    aliases: list = field(default_factory=list)
    ask_storage: tuple = ()       # e.g. ("fridge", "freezer") -> ask user with buttons
    main: bool = False            # main ingredient: confirm before cooking if unsure
    daily_use: bool = False       # used outside dinners (milk, bread) - learn usage rate


def I(key, name, cat, store, shelf, unit="count", qty=1, cents=0, aliases=(), ask=(), main=False, daily=False):
    return Ingredient(key, name, cat, store, shelf, unit, qty, cents, list(aliases), tuple(ask), main, daily)


# Rough weight of one piece, for items we track in grams but people count
# ("4 chicken fillets", "6 chops", "2 blocks of cheese").
PIECE_G = {
    "chicken_fillet": 150, "chicken_pieces": 200, "chicken_thighs": 120, "chicken_drumsticks": 110,
    "pork_chops": 150, "lamb_chops": 100, "steak": 250, "beef_steak": 250, "fish_fillets": 150, "hake": 150,
    "boerewors": 500, "sausages": 60, "burger_patties": 100, "patties": 100, "mince": 500,
    "cheese": 400, "mushrooms": 250, "pasta": 500, "rice": 1000,
}


def piece_weight(key: str, ing) -> float:
    return PIECE_G.get(key) or (ing.default_qty if ing else 1)


Y = 3650  # "doesn't really expire" for practical purposes

CATALOGUE: dict[str, Ingredient] = {i.key: i for i in [
    # --- Staples: assumed always there unless they say it's finished ---
    I("salt", "Salt", "staple", "cupboard", {"cupboard": Y}, aliases=["sout"]),
    I("pepper", "Black pepper", "staple", "cupboard", {"cupboard": Y}, aliases=["peper"]),
    I("cooking_oil", "Cooking oil", "staple", "cupboard", {"cupboard": Y}, aliases=["oil", "olie", "sunflower oil", "sonneblom olie", "olive oil"]),
    I("sugar", "Sugar", "staple", "cupboard", {"cupboard": Y}, aliases=["suiker"]),
    I("flour", "Flour", "staple", "cupboard", {"cupboard": Y}, aliases=["meel", "koekmeel", "cake flour"]),
    I("garlic", "Garlic", "staple", "cupboard", {"cupboard": 30, "fridge": 30}, aliases=["knoffel", "garlic cloves"]),
    I("stock", "Stock cubes", "staple", "cupboard", {"cupboard": Y}, aliases=["stock cubes", "stock cube", "knorr", "oxo", "aftreksel"]),
    I("spices", "Spices", "staple", "cupboard", {"cupboard": Y}, aliases=["spice", "speserye", "curry powder", "kerrie", "paprika", "rajah", "braai spice", "aromat", "mixed herbs", "chicken spice"]),
    I("vinegar", "Vinegar", "staple", "cupboard", {"cupboard": Y}, aliases=["asyn"]),
    I("butter", "Butter / marge", "staple", "fridge", {"fridge": 60}, aliases=["botter", "margarine", "marge", "rama", "stork", "flora"]),
    I("tomato_sauce", "Tomato sauce", "staple", "cupboard", {"cupboard": Y}, aliases=["ketchup", "all gold", "tamatiesous"]),
    I("chutney", "Chutney", "staple", "cupboard", {"cupboard": Y}, aliases=["mrs balls", "blatjang"]),
    I("soy_sauce", "Soy sauce", "staple", "cupboard", {"cupboard": Y}, aliases=["soya sauce"]),
    I("worcester", "Worcestershire sauce", "staple", "cupboard", {"cupboard": Y}, aliases=["worcestershire", "worcester sauce", "lea and perrins"]),
    I("mayonnaise", "Mayonnaise", "staple", "fridge", {"fridge": 60, "cupboard": 180}, aliases=["mayo", "mayonaise", "b-well", "crosse"]),

    # --- Long life: counted, deducted when cooked ---
    I("pasta", "Pasta", "long_life", "cupboard", {"cupboard": 365}, "g", 500, 0.06, ["penne", "spaghetti", "macaroni", "fusilli", "noodles", "pasta shells", "spaghetti pasta"]),
    I("rice", "Rice", "long_life", "cupboard", {"cupboard": 365}, "g", 1000, 0.04, ["rys", "basmati", "tastic"]),
    I("maize_meal", "Maize meal", "long_life", "cupboard", {"cupboard": 180}, "g", 2500, 0.012, ["mealie meal", "mieliemeel", "pap", "white star", "iwisa", "ace maize"]),
    I("canned_tomatoes", "Tinned tomatoes", "long_life", "cupboard", {"cupboard": 540}, "count", 1, 1800, ["tinned tomatoes", "chopped tomatoes", "tomato tin", "tin tomatoes", "tamaties in blik", "blik tamaties", "koo tomato", "tomato and onion mix", "tamatie en uie", "tomato & onion"]),
    I("baked_beans", "Baked beans", "long_life", "cupboard", {"cupboard": 540}, "count", 1, 1700, ["beans in tomato sauce", "koo beans", "bake beans", "boontjies"]),
    I("tuna", "Tinned tuna", "long_life", "cupboard", {"cupboard": 720}, "count", 1, 2600, ["tuna", "tuna tin", "tuna chunks", "john west", "lucky star tuna"]),
    I("pilchards", "Pilchards", "long_life", "cupboard", {"cupboard": 720}, "count", 1, 3000, ["lucky star", "sardines", "pilchard"]),
    I("chakalaka", "Chakalaka", "long_life", "cupboard", {"cupboard": 540}, "count", 1, 1800, ["chakalaka tin"]),
    I("coconut_milk", "Coconut milk", "long_life", "cupboard", {"cupboard": 540}, "count", 1, 2500, ["coconut cream", "klappermelk"]),
    I("tomato_paste", "Tomato paste", "long_life", "cupboard", {"cupboard": 365}, "count", 1, 1200, ["tomato puree", "tamatiepasta", "paste"]),
    I("lentils", "Lentils", "long_life", "cupboard", {"cupboard": 365}, "g", 500, 0.06, ["lensies", "red lentils"]),
    I("samp_beans", "Samp and beans", "long_life", "cupboard", {"cupboard": 365}, "g", 1000, 0.03, ["samp", "stampmielies"]),
    I("oats", "Oats", "long_life", "cupboard", {"cupboard": 180}, "g", 1000, 0.04, ["hawermout", "jungle oats"]),
    I("breadcrumbs", "Breadcrumbs", "long_life", "cupboard", {"cupboard": 180}, "g", 200, 0.1, ["broodkrummels"]),
    I("cheese_sauce", "Cheese sauce packet", "long_life", "cupboard", {"cupboard": 365}, "count", 1, 1500, ["cheese sauce", "white sauce", "kaassous"]),
    I("gravy", "Gravy powder", "long_life", "cupboard", {"cupboard": 365}, "count", 1, 1500, ["bisto", "sous poeier", "gravy packet"]),
    I("peanut_butter", "Peanut butter", "long_life", "cupboard", {"cupboard": 180}, "g", 400, 0.08, ["grondboontjiebotter", "black cat"]),
    I("frozen_veg", "Frozen mixed veg", "long_life", "freezer", {"freezer": 240}, "g", 1000, 0.05, ["mixed veg", "frozen vegetables", "gemengde groente", "frozen peas", "peas", "ertjies", "stir fry veg"]),
    I("frozen_chips", "Frozen chips", "long_life", "freezer", {"freezer": 240}, "g", 1000, 0.05, ["oven chips", "mccain chips", "slap chips"]),
    I("fish_fingers", "Fish fingers", "long_life", "freezer", {"freezer": 180}, "count", 10, 650, ["fish sticks", "visvingers"]),
    I("wraps", "Wraps", "perishable", "cupboard", {"cupboard": 14, "fridge": 21, "freezer": 90}, "count", 6, 700, ["tortillas", "tortilla wraps"]),
    I("puff_pastry", "Puff pastry", "long_life", "freezer", {"freezer": 180, "fridge": 4}, "count", 1, 4500, ["pastry", "skilferkors"]),

    # --- Meat & fish: ask fridge or frozen ---
    I("chicken_fillet", "Chicken fillets", "perishable", "fridge", {"fridge": 2, "freezer": 120}, "g", 500, 0.16, ["chicken breast", "chicken fillet", "hoender filette", "chicken breasts", "hoenderborsies"], ask=("fridge", "freezer"), main=True),
    I("chicken_pieces", "Chicken pieces", "perishable", "fridge", {"fridge": 2, "freezer": 120}, "g", 1000, 0.09, ["chicken", "hoender", "chicken portions", "drumsticks", "thighs", "chicken thighs", "hoenderstukke", "whole chicken", "braaipak"], ask=("fridge", "freezer"), main=True),
    I("mince", "Beef mince", "perishable", "fridge", {"fridge": 2, "freezer": 90}, "g", 500, 0.17, ["maalvleis", "beef mince", "ground beef", "lean mince", "mince meat"], ask=("fridge", "freezer"), main=True),
    I("boerewors", "Boerewors", "perishable", "fridge", {"fridge": 3, "freezer": 90}, "g", 500, 0.15, ["wors", "sausage", "sausages", "boerie", "worsie"], ask=("fridge", "freezer"), main=True),
    I("beef_steak", "Steak", "perishable", "fridge", {"fridge": 3, "freezer": 120}, "g", 500, 0.25, ["steak", "rump", "sirloin", "biefstuk", "t-bone", "beef"], ask=("fridge", "freezer"), main=True),
    I("stewing_beef", "Stewing beef", "perishable", "fridge", {"fridge": 3, "freezer": 120}, "g", 1000, 0.15, ["stew meat", "bredie vleis", "beef cubes", "goulash", "stewing meat"], ask=("fridge", "freezer"), main=True),
    I("lamb_chops", "Lamb chops", "perishable", "fridge", {"fridge": 3, "freezer": 120}, "g", 500, 0.3, ["lamb", "chops", "tjops", "lamstjops", "skaaptjops", "lam"], ask=("fridge", "freezer"), main=True),
    I("pork_chops", "Pork chops", "perishable", "fridge", {"fridge": 3, "freezer": 120}, "g", 500, 0.14, ["pork", "varktjops", "vark", "pork chop"], ask=("fridge", "freezer"), main=True),
    I("bacon", "Bacon", "perishable", "fridge", {"fridge": 7, "freezer": 60}, "g", 250, 0.25, ["spek", "streaky bacon", "back bacon"], main=True),
    I("polony", "Polony / viennas", "perishable", "fridge", {"fridge": 7}, "g", 500, 0.1, ["viennas", "vienna", "frankfurters", "russians", "polony"], main=True),
    I("fish_fillet", "Fish fillets", "perishable", "freezer", {"fridge": 2, "freezer": 120}, "g", 500, 0.2, ["hake", "stokvis", "fish", "vis", "hake fillets"], ask=("fridge", "freezer"), main=True),
    I("ham", "Ham", "perishable", "fridge", {"fridge": 5}, "g", 200, 0.3, ["sliced ham", "ham slices"]),
    I("chicken_cooked", "Cooked chicken", "perishable", "fridge", {"fridge": 3}, "g", 500, 0.16, ["rotisserie chicken", "roast chicken", "leftover chicken"], main=True),

    # --- Dairy & eggs ---
    I("eggs", "Eggs", "perishable", "fridge", {"fridge": 28, "counter": 21}, "count", 6, 350, ["egg", "eiers", "eier", "large eggs", "dozen eggs"]),
    I("milk", "Milk", "perishable", "fridge", {"fridge": 7}, "ml", 2000, 0.012, ["melk", "fresh milk", "full cream milk", "low fat milk", "2l milk"], daily=True),
    I("cheese", "Cheddar cheese", "perishable", "fridge", {"fridge": 30}, "g", 400, 0.18, ["cheddar", "kaas", "gouda", "mozzarella", "cheese block", "grated cheese"]),
    I("cream", "Cream", "perishable", "fridge", {"fridge": 7}, "ml", 250, 0.12, ["room", "fresh cream", "cooking cream", "slagroom"]),
    I("yoghurt", "Yoghurt", "perishable", "fridge", {"fridge": 14}, "ml", 1000, 0.04, ["yogurt", "jogurt", "plain yoghurt", "double cream yoghurt"], daily=True),
    I("feta", "Feta", "perishable", "fridge", {"fridge": 14}, "g", 200, 0.25, ["feta cheese", "fetakaas"]),
    I("sour_cream", "Sour cream", "perishable", "fridge", {"fridge": 10}, "ml", 250, 0.1, ["suurroom", "maas", "amasi"]),

    # --- Bread ---
    I("bread", "Bread", "perishable", "counter", {"counter": 4, "freezer": 60}, "count", 1, 1900, ["brood", "loaf", "white bread", "brown bread", "bruinbrood", "witbrood", "albany", "sasko"], ask=("counter", "freezer"), daily=True),
    I("rolls", "Rolls", "perishable", "counter", {"counter": 3, "freezer": 60}, "count", 6, 400, ["bread rolls", "broodrolletjies", "hotdog rolls", "burger buns", "buns", "vetkoek"]),

    # --- Vegetables & fruit ---
    I("tomato", "Tomatoes", "perishable", "counter", {"counter": 6, "fridge": 10}, "count", 4, 500, ["tomatoes", "tamaties", "tamatie", "tom", "tomato loose", "cherry tomatoes", "rosa tomatoes"]),
    I("onion", "Onions", "perishable", "cupboard", {"cupboard": 30, "fridge": 30}, "count", 4, 300, ["onions", "uie", "ui", "red onion", "brown onion", "pocket onions"]),
    I("potato", "Potatoes", "perishable", "cupboard", {"cupboard": 21}, "g", 2000, 0.012, ["potatoes", "aartappels", "aartappel", "pocket potatoes", "spuds"]),
    I("sweet_potato", "Sweet potatoes", "perishable", "cupboard", {"cupboard": 14}, "g", 1000, 0.025, ["patats", "patat", "sweet potato"]),
    I("carrot", "Carrots", "perishable", "fridge", {"fridge": 21}, "g", 1000, 0.02, ["carrots", "wortels", "wortel"]),
    I("butternut", "Butternut", "perishable", "counter", {"counter": 30, "fridge": 7}, "count", 1, 2500, ["butternut squash", "botterskorsie", "pumpkin", "pampoen"]),
    I("cabbage", "Cabbage", "perishable", "fridge", {"fridge": 14}, "count", 1, 2000, ["kool", "green cabbage", "red cabbage", "coleslaw mix"]),
    I("spinach", "Spinach", "perishable", "fridge", {"fridge": 5}, "g", 300, 0.07, ["spinasie", "baby spinach", "swiss chard", "morogo"]),
    I("lettuce", "Lettuce", "perishable", "fridge", {"fridge": 5}, "count", 1, 2000, ["blaarslaai", "slaai", "salad", "iceberg", "salad leaves", "mixed leaves"]),
    I("cucumber", "Cucumber", "perishable", "fridge", {"fridge": 7}, "count", 1, 1500, ["komkommer", "english cucumber", "cucumbers"]),
    I("green_pepper", "Peppers", "perishable", "fridge", {"fridge": 10}, "count", 2, 900, ["green pepper", "red pepper", "yellow pepper", "soetrissie", "rissie", "peppers", "bell pepper", "sweet peppers"]),
    I("mushrooms", "Mushrooms", "perishable", "fridge", {"fridge": 5}, "g", 250, 0.12, ["sampioene", "button mushrooms", "brown mushrooms", "mushroom"]),
    I("baby_marrow", "Baby marrows", "perishable", "fridge", {"fridge": 7}, "g", 500, 0.08, ["courgettes", "zucchini", "murgpampoentjies", "baby marrow"]),
    I("green_beans", "Green beans", "perishable", "fridge", {"fridge": 7}, "g", 400, 0.08, ["groenboontjies", "beans", "fine beans"]),
    I("broccoli", "Broccoli", "perishable", "fridge", {"fridge": 7}, "g", 400, 0.1, ["brokkoli", "tenderstem"]),
    I("cauliflower", "Cauliflower", "perishable", "fridge", {"fridge": 7}, "count", 1, 3500, ["blomkool"]),
    I("corn", "Corn", "perishable", "fridge", {"fridge": 4}, "count", 4, 800, ["mealies", "mielies", "sweetcorn", "corn on the cob", "mielie"]),
    I("avocado", "Avocados", "perishable", "counter", {"counter": 4, "fridge": 7}, "count", 2, 1500, ["avo", "avos", "avocado pear"]),
    I("lemon", "Lemons", "perishable", "fridge", {"fridge": 21, "counter": 10}, "count", 2, 500, ["suurlemoen", "lemon", "lime"]),
    I("chilli", "Chillies", "perishable", "fridge", {"fridge": 10}, "count", 3, 200, ["chili", "chilli", "chillies", "green chilli", "brandrissie"]),
    I("ginger", "Ginger", "perishable", "fridge", {"fridge": 21}, "g", 100, 0.15, ["gemmer", "fresh ginger"]),
    I("coriander", "Coriander", "perishable", "fridge", {"fridge": 5}, "count", 1, 1500, ["dhania", "cilantro", "koljander"]),
    I("parsley", "Parsley", "perishable", "fridge", {"fridge": 7}, "count", 1, 1500, ["pietersielie", "fresh herbs", "basil", "basilikum"]),
    I("spring_onion", "Spring onions", "perishable", "fridge", {"fridge": 7}, "count", 1, 1200, ["spring onion", "sprietuie", "green onions"]),
    I("banana", "Bananas", "perishable", "counter", {"counter": 5}, "count", 6, 300, ["piesangs", "piesang", "banana"], daily=True),
    I("apple", "Apples", "perishable", "fridge", {"fridge": 30, "counter": 10}, "count", 6, 400, ["appels", "apple"], daily=True),
]}

# Words that mean "this storage place" in voice notes / corrections.
STORAGE_WORDS = {
    "freezer": ["freezer", "frozen", "vrieskas", "gevries", "vries"],
    "fridge": ["fridge", "yskas"],
    "cupboard": ["cupboard", "pantry", "kas", "spens"],
}

STORAGE_LABEL = {"fridge": "Fridge", "freezer": "Frozen", "cupboard": "Cupboard", "counter": "Counter"}


def _norm(s: str) -> str:
    s = s.lower()
    s = re.sub(r"[^a-z0-9&' -]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


# Build alias index once: longest phrases first so "chicken fillets" beats "chicken".
_ALIAS: list[tuple[str, str]] = []
for ing in CATALOGUE.values():
    for a in {ing.key.replace("_", " "), ing.name.lower(), *ing.aliases}:
        _ALIAS.append((_norm(a), ing.key))
_ALIAS.sort(key=lambda t: -len(t[0]))


def _singular(w: str) -> str:
    if w.endswith("oes"):
        return w[:-2]
    if w.endswith("ies") and len(w) > 4:
        return w[:-3] + "y"
    if w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def match(text: str) -> str | None:
    """Find the ingredient key mentioned in a short phrase, or None."""
    t = _norm(text)
    if not t:
        return None
    padded = f" {t} "
    padded_sing = " " + " ".join(_singular(w) for w in t.split()) + " "
    for alias, key in _ALIAS:
        if f" {alias} " in padded or f" {alias} " in padded_sing:
            return key
    return None


def get(key: str) -> Ingredient | None:
    return CATALOGUE.get(key)


def shelf_days(key: str, storage: str) -> float | None:
    ing = CATALOGUE.get(key)
    if not ing:
        return None
    if storage in ing.shelf:
        return ing.shelf[storage]
    return ing.shelf.get(ing.storage)
