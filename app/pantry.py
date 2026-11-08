"""The pantry engine: keeps a 'good enough' picture of what's in the kitchen.

Ideas:
- Staples are assumed present. Long-life items are counted. Perishables run on a
  shelf-life clock and a confidence score.
- Status: fresh -> use_soon -> gone. 'gone' items are never used in suggestions.
- Items added during first-time setup start part-way through their clock,
  because we don't know when they were bought.
- A new slip with the same item means the older stock is probably low or finished.
- 'Cooked' deducts recipe amounts, using 'use soon' stock first; that value is
  counted as money rescued.
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import catalogue, clock
from .models import Habit, PantryItem, SavingsEvent, User

SETUP_AGE_FRACTION = 0.4      # setup items start 40% through their shelf life
GONE_GRACE_DAYS = 1.0
MIN_CONFIDENCE = 0.3


@dataclass
class ParsedItem:
    """One item read from a slip, voice note or text."""
    name: str
    key: str | None = None
    qty: float | None = None
    unit: str | None = None
    storage: str | None = None
    price_cents: int | None = None       # total price on slip for this line
    raw: str = ""
    # guesses for unknown items (from AI)
    category: str | None = None
    shelf_days: float | None = None


@dataclass
class AddResult:
    added: list[PantryItem] = field(default_factory=list)
    ask_storage: list[PantryItem] = field(default_factory=list)   # need fridge/frozen answer
    skipped_staples: int = 0


# ---------- habits ----------

def habit(s: Session, user: User, key: str) -> Habit:
    h = s.scalar(select(Habit).where(Habit.user_id == user.id, Habit.key == key))
    if not h:
        h = Habit(user_id=user.id, key=key, shelf_factor=1.0, likes=0)
        s.add(h)
        s.flush()
    return h


def _expiry(s: Session, user: User, key: str, storage: str, added_at: datetime, fallback_days: float | None) -> datetime | None:
    days = catalogue.shelf_days(key, storage)
    if days is None:
        days = fallback_days
    if days is None or days >= 3650:
        return None
    h = habit(s, user, key)
    days *= h.shelf_factor
    ing = catalogue.get(key)
    if ing and ing.daily_use and h.repurchase_days:
        days = min(days, h.repurchase_days * 1.1)
    return added_at + timedelta(days=days)


# ---------- status ----------

def status(item: PantryItem, now: datetime | None = None) -> str:
    now = now or clock.now()
    if not item.active:
        return "gone"
    if item.category == "staple" or item.expires_at is None:
        return "fresh" if item.confidence >= MIN_CONFIDENCE else "gone"
    if confidence(item, now) < MIN_CONFIDENCE:
        return "gone"
    if now > item.expires_at + timedelta(days=GONE_GRACE_DAYS):
        return "gone"
    total = (item.expires_at - item.added_at).total_seconds() / 86400
    window = max(1.0, 0.3 * total)
    if now >= item.expires_at - timedelta(days=window):
        return "use_soon"
    return "fresh"


def confidence(item: PantryItem, now: datetime | None = None) -> float:
    """Stored confidence, decaying after the expiry date."""
    now = now or clock.now()
    c = item.confidence
    if item.expires_at and now > item.expires_at:
        days_over = (now - item.expires_at).total_seconds() / 86400
        c *= max(0.0, 1 - 0.5 * days_over)
    return c


def active_items(s: Session, user: User) -> list[PantryItem]:
    return list(s.scalars(select(PantryItem).where(PantryItem.user_id == user.id, PantryItem.active.is_(True))))


def stock(s: Session, user: User, now: datetime | None = None) -> dict[str, dict]:
    """key -> {qty, status (best), confidence (max), items} for everything not gone."""
    now = now or clock.now()
    out: dict[str, dict] = {}
    for it in active_items(s, user):
        st = status(it, now)
        if st == "gone":
            continue
        d = out.setdefault(it.key, {"qty": 0.0, "status": "fresh", "confidence": 0.0, "items": [], "unit": it.unit, "category": it.category})
        d["qty"] += it.qty
        d["items"].append(it)
        d["confidence"] = max(d["confidence"], confidence(it, now))
        if st == "use_soon":
            d["status"] = "use_soon"
    # staples are assumed present even if never mentioned
    for ing in catalogue.CATALOGUE.values():
        if ing.category == "staple" and ing.key not in out and not _staple_marked_out(s, user, ing.key):
            out[ing.key] = {"qty": 1, "status": "fresh", "confidence": 1.0, "items": [], "unit": ing.unit, "category": "staple"}
    return out


def _staple_marked_out(s: Session, user: User, key: str) -> bool:
    it = s.scalar(select(PantryItem).where(PantryItem.user_id == user.id, PantryItem.key == key)
                  .order_by(PantryItem.id.desc()))
    return bool(it and not it.active and it.removed_reason == "finished")


# ---------- adding ----------

def add_items(s: Session, user: User, parsed: list[ParsedItem], source: str) -> AddResult:
    now = clock.now()
    res = AddResult()
    for p in parsed:
        key = p.key or catalogue.match(p.name) or _unknown_key(p.name)
        ing = catalogue.get(key)
        category = ing.category if ing else (p.category or "perishable")   # unknown food can go off
        unit = ing.unit if ing else (p.unit or "count")
        qty_known = bool(p.qty)
        qty = p.qty if p.qty else (ing.default_qty if ing else 1)
        piece_g = None
        if ing and unit in ("g", "ml") and p.qty and p.unit in (None, "count", "pack"):
            # "4 chicken fillets" = 4 pieces, not 4 grams
            piece_g = catalogue.piece_weight(key, ing)
            qty = p.qty * piece_g
        elif ing and p.unit and p.unit != ing.unit:
            qty = _convert(qty, p.unit, ing.unit, ing)
        if unit == "count" and qty >= 1:
            qty = round(qty)
        storage = p.storage or (ing.storage if ing else "cupboard")
        name = ing.name if ing else p.name.strip().capitalize()

        existing = [it for it in active_items(s, user) if it.key == key]
        if category == "staple":
            if existing:
                for it in existing:
                    it.confidence = 1.0
                res.skipped_staples += 1
                continue
        else:
            _reconcile_repurchase(s, user, key, existing, now, ing)

        added_at = now
        if source == "setup" and category == "perishable":
            days = catalogue.shelf_days(key, storage) or p.shelf_days or 7
            added_at = now - timedelta(days=days * SETUP_AGE_FRACTION)
        unit_cents = None
        if p.price_cents and qty:
            unit_cents = p.price_cents / qty
        elif ing and ing.cents_per_unit:
            unit_cents = ing.cents_per_unit
        item = PantryItem(
            user_id=user.id, key=key, name=name, qty=float(qty), unit=unit, category=category,
            storage=storage, added_at=added_at, confidence=1.0 if source != "setup" else 0.85,
            source=source, unit_cents=unit_cents, active=True,
            qty_known=qty_known, piece_g=piece_g,
        )
        item.expires_at = _expiry(s, user, key, storage, added_at, p.shelf_days)
        s.add(item)
        s.flush()
        res.added.append(item)
        if ing and ing.ask_storage and not p.storage:
            res.ask_storage.append(item)
        if source in ("slip", "voice"):
            h = habit(s, user, key)
            h.last_bought_at = now
    return res


def _reconcile_repurchase(s, user, key, existing, now, ing) -> None:
    """Buying something again tells us about the old stock."""
    h = habit(s, user, key)
    if h.last_bought_at and ing and ing.daily_use:
        interval = (now - h.last_bought_at).total_seconds() / 86400
        if 0.5 < interval < 60:
            h.repurchase_days = interval if not h.repurchase_days else 0.6 * h.repurchase_days + 0.4 * interval
    for it in existing:
        age = (now - it.added_at).total_seconds() / 86400
        if it.category == "perishable" and age >= 2:
            if ing and ing.daily_use:
                _remove(it, "replaced", now)
            else:
                it.confidence = min(it.confidence, 0.5)


def _unknown_key(name: str) -> str:
    return "x_" + "_".join(name.lower().split())[:50]


def _convert(qty: float, frm: str, to: str, ing) -> float:
    if frm == to:
        return qty
    table = {("kg", "g"): 1000, ("l", "ml"): 1000, ("g", "kg"): 0.001, ("ml", "l"): 0.001}
    if (frm, to) in table:
        return qty * table[(frm, to)]
    if frm in ("pack", "count") and to in ("g", "ml"):
        return qty * ing.default_qty
    if frm in ("kg",) and to == "count":
        return qty * 8          # ~8 tomatoes/onions per kg
    if frm == "g" and to == "count":
        return max(1, round(qty / 125))
    return qty


def set_storage(s: Session, user: User, item: PantryItem, storage: str) -> None:
    item.storage = storage
    item.expires_at = _expiry(s, user, item.key, storage, item.added_at, None)


# ---------- using / removing ----------

def deduct(s: Session, user: User, needs: list[tuple[str, float]]) -> int:
    """Take recipe amounts out of stock. Returns cents 'rescued' (use-soon stock used)."""
    now = clock.now()
    rescued = 0.0
    for key, qty in needs:
        ing = catalogue.get(key)
        if ing and ing.category == "staple":
            continue
        items = [it for it in active_items(s, user) if it.key == key and status(it, now) != "gone"]
        items.sort(key=lambda it: (0 if status(it, now) == "use_soon" else 1, it.expires_at or datetime.max))
        left = qty
        for it in items:
            if left <= 0:
                break
            take = min(it.qty, left)
            if status(it, now) == "use_soon" and it.unit_cents:
                rescued += take * it.unit_cents
            it.qty -= take
            left -= take
            if it.qty <= 0.0001 or (it.unit in ("g", "ml") and it.qty < 0.08 * (ing.default_qty if ing else 100)):
                _remove(it, "used", now)
    cents = int(round(rescued))
    if cents > 0:
        s.add(SavingsEvent(user_id=user.id, kind="rescued", key="meal", cents=cents, at=now))
    return cents


def remove_key(s: Session, user: User, key: str, reason: str, qty: float | None = None) -> int:
    """User says 'finished the milk' (finished) or 'threw out the lettuce' (binned)."""
    now = clock.now()
    items = [it for it in active_items(s, user) if it.key == key]
    if not items and catalogue.get(key) and catalogue.get(key).category == "staple" and reason == "finished":
        # record that a staple ran out
        ing = catalogue.get(key)
        s.add(PantryItem(user_id=user.id, key=key, name=ing.name, qty=0, unit=ing.unit, category="staple",
                         storage=ing.storage, source="correction", active=False, removed_reason="finished",
                         removed_at=now, confidence=0))
        return 1
    n = 0
    for it in sorted(items, key=lambda it: it.added_at):
        if qty is not None and it.qty > qty:
            it.qty -= qty
            n += 1
            break
        if reason == "binned":
            cents = int((it.unit_cents or 0) * it.qty)
            if cents:
                s.add(SavingsEvent(user_id=user.id, kind="wasted", key=key, cents=cents, at=now))
            if it.expires_at and now < it.expires_at:
                h = habit(s, user, key)
                h.shelf_factor = max(0.4, h.shelf_factor * 0.85)
        _remove(it, reason, now)
        n += 1
        if qty is not None:
            qty -= it.qty
            if qty <= 0:
                break
    return n


def set_qty(s: Session, user: User, key: str, qty: float) -> bool:
    items = [it for it in active_items(s, user) if it.key == key]
    if not items:
        return False
    items.sort(key=lambda it: it.added_at)
    for it in items[:-1]:
        _remove(it, "replaced", clock.now())
    items[-1].qty = qty
    items[-1].confidence = 1.0
    return True


def confirm_present(s: Session, user: User, key: str, present: bool) -> None:
    for it in active_items(s, user):
        if it.key == key:
            if present:
                it.confidence = 1.0
            else:
                _remove(it, "finished", clock.now())


def clear_place(s: Session, user: User, place: str, reason: str) -> int:
    """'Threw out everything in the fridge' -> remove every item stored there (staples stay assumed)."""
    now = clock.now()
    n = 0
    for it in active_items(s, user):
        if it.category == "staple":
            continue
        where = it.storage if it.storage in ("fridge", "freezer", "cupboard", "counter") else "cupboard"
        if place == "all" or where == place:
            _remove(it, reason, now)
            n += 1
    return n


def _remove(it: PantryItem, reason: str, now: datetime) -> None:
    it.active = False
    it.removed_reason = reason
    it.removed_at = now
    if reason in ("used", "finished", "binned", "replaced"):
        it.qty = max(it.qty, 0)


# ---------- display ----------

def fmt_qty(qty: float, unit: str) -> str:
    if unit == "g":
        return f"{qty/1000:.1f} kg".replace(".0 ", " ") if qty >= 1000 else f"{int(round(qty))} g"
    if unit == "ml":
        return f"{qty/1000:.1f} L".replace(".0 ", " ") if qty >= 1000 else f"{int(round(qty))} ml"
    frac = {0.25: "¼", 0.5: "½", 0.75: "¾"}
    whole, part = int(qty), round(qty - int(qty), 2)
    if part in frac:
        return "×" + (str(whole) if whole else "") + frac[part]
    q = int(qty) if float(qty).is_integer() else round(qty, 1)
    return f"×{q}"


def amount_phrase(name: str, qty: float, unit: str) -> str:
    """'500 g chicken fillets', '½ lettuce', '6 wraps'."""
    name = name.lower()
    if unit in ("g", "ml"):
        return f"{fmt_qty(qty, unit)} {name}"
    frac = {0.25: "¼", 0.5: "½", 0.75: "¾"}
    whole, part = int(qty), round(qty - int(qty), 2)
    if part in frac:
        q = (f"{whole}" if whole else "") + frac[part]
    else:
        q = str(int(round(qty))) if qty >= 1 else "a little"
    return f"{q} {name}"


def shown_qty(items: list, qty: float, unit: str) -> str:
    """What the user sees next to an item: only amounts they actually told us.
    Counted pieces show as ×N; no amount given -> nothing."""
    if not items or not all(getattr(i, "qty_known", True) is not False for i in items):
        return ""
    pg = [i.piece_g for i in items if getattr(i, "piece_g", None)]
    if pg:
        if len(pg) != len(items):
            return ""
        n = max(1, round(qty / (sum(pg) / len(pg)))) if qty > 0 else 0
        return f"×{n}"
    return fmt_qty(qty, unit)


def item_line(it: PantryItem) -> str:
    q = shown_qty([it], it.qty, it.unit)
    return f"{it.name} {q}".strip()


PLACE_TITLE = {"fridge": "🧊 Fridge", "freezer": "❄️ Freezer", "cupboard": "🥫 Cupboard", "counter": "🍞 Counter"}
PLACE_NAME = {"fridge": "fridge", "freezer": "freezer", "cupboard": "cupboard", "counter": "counter"}


def list_text(s: Session, user: User, place: str | None = None) -> str:
    """Everything in the house grouped by where it is, or just one place. ⚠️ = use soon."""
    groups: dict[str, list[str]] = {}
    for it in active_items(s, user):
        if it.category == "staple" or status(it) == "gone":
            continue
        where = it.storage if it.storage in PLACE_TITLE else "cupboard"
        if place and where != place:
            continue
        line = item_line(it)
        if status(it) == "use_soon":
            line = "⚠️ " + line + " (use soon)"
        groups.setdefault(where, []).append(line)
    if not groups:
        if place:
            return f"Nothing in your {PLACE_NAME[place]} on my list. Send a voice note if I've missed something."
        return "Your kitchen list is empty. Send a voice note or a slip photo to add items."
    parts = []
    for where in ("fridge", "freezer", "cupboard", "counter"):
        if where in groups:
            lines = sorted(set(groups[where]), key=lambda l: (not l.startswith("⚠️"), l))
            parts.append(f"*{PLACE_TITLE[where]}*\n" + "\n".join(f"• {l}" for l in lines))
    if not place:
        parts.append("(Salt, oil, spices and other basics are assumed.)")
    return "\n\n".join(parts)
