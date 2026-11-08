"""Recipe library and the dinner picker.

The picker scores every recipe the household can make tonight:
  + uses ingredients that are about to go off (biggest weight)
  + uses fresh perishables (better than leaving them)
  + the household liked it before
  - suggested or cooked recently (variety)
  - rejected before / takes very long on a weekday
Only the best one is sent. If a great meal is one cheap item away, we mention it.
"""
import json
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import catalogue, clock, pantry
from .models import Habit, Suggestion, User

_PATH = Path(__file__).parent / "data" / "recipes.json"
RECIPES: dict[str, dict] = {r["id"]: r for r in json.loads(_PATH.read_text())}


@dataclass
class Eval:
    recipe: dict
    missing: list[str] = field(default_factory=list)
    use_soon: list[str] = field(default_factory=list)
    used: list[tuple[str, float]] = field(default_factory=list)
    unsure_mains: list[str] = field(default_factory=list)
    score: float = 0.0

    @property
    def can_make(self) -> bool:
        return not self.missing


def people_factor(user: User | None, recipe: dict) -> float:
    """Scale a recipe to the household size ('we are only 2')."""
    people = (user.pending or {}).get("people") if user is not None else None
    if not people or not recipe.get("serves"):
        return 1.0
    return max(0.25, float(people) / float(recipe["serves"]))


def evaluate(recipe: dict, stock: dict, factor: float = 1.0) -> Eval:
    ev = Eval(recipe=recipe)
    for ing in recipe["ingredients"]:
        key, qty, optional = ing["key"], ing["qty"] * factor, ing.get("optional", False)
        info = catalogue.get(key)
        if info and info.unit == "count" and qty >= 1:
            qty = round(qty)
        info = catalogue.get(key)
        if info and info.category == "staple":
            continue
        have = stock.get(key)
        enough = have is not None and have["qty"] >= qty * 0.5
        if not enough:
            if not optional:
                ev.missing.append(key)
            continue
        ev.used.append((key, min(qty, have["qty"])))
        if have["status"] == "use_soon":
            ev.use_soon.append(key)
        if info and info.main and have["confidence"] < 0.75:
            ev.unsure_mains.append(key)
    return ev


def _recent(s: Session, user: User, days: int) -> dict[str, int]:
    since = clock.now() - timedelta(days=days)
    out: dict[str, int] = {}
    for sg in s.scalars(select(Suggestion).where(Suggestion.user_id == user.id, Suggestion.created_at >= since)):
        age = (clock.now() - sg.created_at).days
        out[sg.recipe_id] = min(out.get(sg.recipe_id, 99), age)
    return out


def recipe_likes(s: Session, user: User) -> dict[str, int]:
    rows = s.scalars(select(Habit).where(Habit.user_id == user.id, Habit.key.like("recipe:%")))
    return {h.key[7:]: h.likes for h in rows}


def score(ev: Eval, stock: dict, recent: dict, likes: dict) -> float:
    r = ev.recipe
    sc = 0.0
    for key in ev.use_soon:
        info = catalogue.get(key)
        sc += 6 if info and info.main else 4
    for key, _ in ev.used:
        if stock[key]["category"] == "perishable" and key not in ev.use_soon:
            sc += 1
    sc += 2 * likes.get(r["id"], 0)
    if r["id"] in recent:
        age = recent[r["id"]]
        sc -= 25 if age <= 2 else 8 if age <= 6 else 0
    weekday = clock.now().weekday() < 5
    if weekday and r["minutes"] > 90:
        sc -= 6
    elif weekday and r["minutes"] > 45:
        sc -= 1.5
    sc -= 0.5 * len(ev.unsure_mains)
    return sc


def pick(s: Session, user: User, exclude: set[str] | None = None) -> tuple[Eval | None, Eval | None]:
    """Returns (best meal they can make, best meal that is exactly one cheap item away)."""
    exclude = exclude or set()
    stock = pantry.stock(s, user)
    recent = _recent(s, user, 7)
    likes = recipe_likes(s, user)
    best, near = None, None
    for r in RECIPES.values():
        if r["id"] in exclude or likes.get(r["id"], 0) <= -3:
            continue
        ev = evaluate(r, stock, people_factor(user, r))
        ev.score = score(ev, stock, recent, likes)
        if ev.can_make:
            if best is None or ev.score > best.score:
                best = ev
        elif len(ev.missing) == 1:
            info = catalogue.get(ev.missing[0])
            if info and not info.main and (near is None or ev.score > near.score):
                near = ev
    if near and best and near.score <= best.score + 3:
        near = None
    return best, near


def needs(ev: Eval) -> list[tuple[str, float]]:
    return list(ev.used)


def recipe_of(sg) -> dict:
    """Built-in recipe, or the dish the AI made for this suggestion."""
    if getattr(sg, "recipe_json", None):
        import json as _json
        return _json.loads(sg.recipe_json)
    return RECIPES[sg.recipe_id]


def eval_for(s: Session, user: User, recipe_id, sg=None) -> Eval:
    r = recipe_of(sg) if sg is not None else RECIPES[recipe_id]
    return evaluate(r, pantry.stock(s, user), people_factor(user, r))


def price_hint(key: str) -> str:
    info = catalogue.get(key)
    if not info or not info.cents_per_unit:
        return ""
    cents = info.cents_per_unit * (info.default_qty if info.unit in ("g", "ml") else 1)
    rands = round(cents / 100)
    return f" (about R{rands:d})" if rands >= 1 else ""
