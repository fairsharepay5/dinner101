"""Turning slips, voice notes and typed messages into pantry actions.

With ANTHROPIC_API_KEY set, Claude reads slip photos and understands messages
(English/Afrikaans mixed). Without it, a rule-based parser is used - good enough
for the simulator and tests, and as a fallback if the AI call fails.
"""
import base64
import json
import logging
import re
from dataclasses import dataclass, field

from . import catalogue
from .pantry import ParsedItem

log = logging.getLogger(__name__)


@dataclass
class Action:
    op: str                     # add | remove | set
    item: ParsedItem | None = None
    key: str | None = None
    reason: str | None = None   # finished | binned
    qty: float | None = None


@dataclass
class Understood:
    actions: list[Action] = field(default_factory=list)
    other: str | None = None    # message isn't about the pantry (a question, a command)
    intent: str | None = None   # dinner | set_time | list | help (what they want besides pantry changes)
    time: str | None = None     # "HH:MM" for set_time
    place: str | None = None    # fridge | freezer | cupboard | counter, for a "what's in my ..." question


# ======================================================================
# Offline (rule-based) parser
# ======================================================================

NUM_WORDS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "dozen": 12, "half": 0.5,
    "'n": 1, "n": 1, "een": 1, "twee": 2, "drie": 3, "vier": 4, "vyf": 5, "ses": 6, "sewe": 7,
    "agt": 8, "nege": 9, "tien": 10, "couple": 2, "few": 3, "halwe": 0.5,
}
UNIT_WORDS = {
    "g": "g", "gram": "g", "grams": "g", "kg": "kg", "kilo": "kg", "kilos": "kg", "ml": "ml",
    "l": "l", "litre": "l", "litres": "l", "liter": "l", "liters": "l",
    "tin": "count", "tins": "count", "can": "count", "cans": "count", "blik": "count", "blikke": "count",
    "pack": "pack", "packs": "pack", "packet": "pack", "packets": "pack", "pak": "pack", "pakkie": "pack",
    "bag": "pack", "bags": "pack", "sak": "pack", "pocket": "pack", "box": "pack", "bottle": "count",
    "bottles": "count", "bottel": "count", "loaf": "count", "loaves": "count", "block": "count", "bunch": "count",
    "tray": "pack", "punnet": "pack",
}
FILLER = r"\b(some|bietjie|a bit of|lots of|of|van|the|die|my|we|have|got|i|there'?s|is|are|also|ook|plus|and|en|leftover|left over|oorskiet)\b"
REMOVE_FINISHED = r"\b(finished|ran out of|run out of|used up|used the|no more|out of|klaar|op is|is op|opgebruik|done with)\b"
REMOVE_BINNED = r"\b(threw out|thrown out|threw away|binned|chucked|went off|gone off|rotten|rotted|mouldy|moldy|weggegooi|gooi weg|vrot|expired)\b"
SET_QTY = r"\b(only|just|net|still)\s+(\d+(?:\.\d+)?|[a-z']+)\s+(.+?)\s*(left|over|oor)?$"

ABBREV = {
    "chkn": "chicken", "chk": "", "pnp": "", "ww": "", "spar": "", "rite": "", "no name": "", "ritebrand": "",
    "fllt": "fillet", "fllts": "fillets", "flt": "fillet", "brd": "bread", "mlk": "milk", "frsh": "fresh",
    "pot": "potatoes", "pots": "potatoes", "onio": "onions", "onn": "onions", "chs": "cheese", "ched": "cheddar",
    "mnce": "mince", "mnc": "mince", "bf": "beef", "wrs": "wors", "bwors": "boerewors", "tom": "tomatoes",
    "toms": "tomatoes", "tmt": "tomatoes", "crrt": "carrots", "carr": "carrots", "lttc": "lettuce",
    "cuc": "cucumber", "cucmbr": "cucumber", "yog": "yoghurt", "yogh": "yoghurt", "crm": "cream",
    "mush": "mushrooms", "mshrm": "mushrooms", "ppr": "pepper", "ban": "bananas", "app": "apples",
    "spag": "spaghetti", "mac": "macaroni", "lg": "", "xl": "", "ff": "", "lf": "", "ea": "", "loose": "",
    "pkt": "pack", "eggs": "eggs", "ptd": "", "pre": "", "pk": "pack",
}


def _num(tok: str) -> float | None:
    tok = tok.strip().lower()
    if re.fullmatch(r"\d+(\.\d+)?", tok):
        return float(tok)
    if re.fullmatch(r"\d+/\d+", tok):
        a, b = tok.split("/")
        return float(a) / float(b)
    return NUM_WORDS.get(tok)


def _storage_in(text: str) -> str | None:
    t = text.lower()
    for place, words in catalogue.STORAGE_WORDS.items():
        if any(re.search(rf"\b{w}\b", t) for w in words):
            return place
    return None


def _split_chunks(text: str) -> list[str]:
    text = re.sub(r"\s+(and|en|plus|also|ook)\s+", ",", text, flags=re.I)
    parts = re.split(r"[,;\n]|\.\s", text)
    return [p.strip(" .") for p in parts if p.strip(" .")]


def parse_item_phrase(phrase: str) -> ParsedItem | None:
    """'two tins of tomatoes', '500g mince in the freezer', "'n bietjie kaas" -> ParsedItem."""
    raw = phrase
    storage = _storage_in(phrase)
    p = phrase.lower()
    for words in catalogue.STORAGE_WORDS.values():
        for w in words:
            p = re.sub(rf"\b(in the|in die|in)?\s*{w}\b", " ", p)
    qty, unit = None, None
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(kg|g|ml|l)\b", p)
    if m:
        qty, unit = float(m.group(1).replace(",", ".")), m.group(2)
        p = p.replace(m.group(0), " ")
    vague = bool(re.search(r"\b(some|bietjie|a bit|a little|paar|leftover|left over)\b", p))
    tinned = bool(re.search(r"\b(tin|tins|can|cans|blik|blikke|tinned|canned)\b", p))
    tokens = p.split()
    rest = []
    for i, tok in enumerate(tokens):
        n = _num(tok)
        if n is not None and qty is None and tok not in ("a", "an") or (tok in ("a", "an", "'n", "n") and qty is None and i == 0):
            if n is None:
                n = 1
            qty = n if qty is None else qty
            continue
        if tok in UNIT_WORDS and unit is None:
            unit = UNIT_WORDS[tok]
            continue
        rest.append(tok)
    name = re.sub(FILLER, " ", " ".join(rest))
    name = re.sub(r"\s+", " ", name).strip(" -'")
    if not name:
        return None
    key = catalogue.match(name)
    if key is None and len(name) < 3:
        return None
    if tinned and key == "tomato":
        key = "canned_tomatoes"
    if vague and (unit is None or unit == "count") and qty is not None and qty <= 1:
        qty, unit = None, None
    if unit == "pack" and key and catalogue.get(key).unit == "count":
        unit = "count"
    return ParsedItem(name=name, key=key, qty=qty, unit=unit, storage=storage, raw=raw)


def understand_offline(text: str) -> Understood:
    t = text.strip()
    low = t.lower()
    u = Understood()
    if not t:
        return u
    # "only 3 eggs left"
    m = re.search(SET_QTY, low)
    if m:
        n = _num(m.group(2))
        key = catalogue.match(m.group(3))
        if n is not None and key:
            u.actions.append(Action(op="set", key=key, qty=n))
            return u
    binned = re.search(REMOVE_BINNED, low)
    finished = re.search(REMOVE_FINISHED, low)
    if binned or finished:
        reason = "binned" if binned else "finished"
        cleaned = re.sub(REMOVE_BINNED + "|" + REMOVE_FINISHED, " ", low)
        for chunk in _split_chunks(cleaned):
            item = parse_item_phrase(chunk)
            if item and item.key:
                u.actions.append(Action(op="remove", key=item.key, reason=reason))
        if u.actions:
            return u
    bought = re.sub(r"^(i |we )?(just )?(bought|got|picked up|added|have|het|gekoop)\b", "", low).strip(" :")
    for chunk in _split_chunks(bought):
        item = parse_item_phrase(chunk)
        if item:
            u.actions.append(Action(op="add", item=item))
    known = [a for a in u.actions if a.item and a.item.key]
    if not known:
        return Understood(other=t)
    return u


_PRICE = re.compile(r"(?:R\s*)?(\d+[.,]\d{2})\s*[A-Z]?\s*$")
_SKIP_LINE = re.compile(r"(total|subtotal|change|cash|card|vat|tax|balance|tender|smart shopper|xtra savings|"
                        r"discount|points|thank|tel|till|cashier|receipt|slip|bag|plastic|deposit|rounding|"
                        r"savings|due|approved|ref|auth|\bqty\b|items?\b)", re.I)


def parse_slip_text(text: str) -> list[ParsedItem]:
    """Offline reading of slip text lines like 'PNP TOM LOOSE 1.2KG   24.99'."""
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line or _SKIP_LINE.search(line):
            continue
        price = None
        m = _PRICE.search(line)
        if m:
            price = int(round(float(m.group(1).replace(",", ".")) * 100))
            line = line[: m.start()].strip()
        mult = 1
        m = re.search(r"\b(\d+)\s*[x@]\s*", line, re.I)
        if m:
            mult = int(m.group(1))
            line = line.replace(m.group(0), " ")
        words = []
        for w in re.split(r"\s+", line.lower()):
            w2 = ABBREV.get(w, w)
            if w2:
                words.append(w2)
        expanded = " ".join(words)
        item = parse_item_phrase(expanded)
        if not item or not item.key:
            continue
        item.raw = line
        item.price_cents = price
        if item.qty is None:
            item.qty = None
        if mult > 1:
            ing = catalogue.get(item.key)
            if item.qty and item.unit in ("g", "ml", "kg", "l"):
                item.qty *= mult
            else:
                item.qty = mult if not ing or ing.unit == "count" else (ing.default_qty * mult)
                item.unit = None if not ing or ing.unit == "count" else ing.unit
        out.append(item)
    return out


# ======================================================================
# AI parser (Claude)
# ======================================================================

def _catalogue_hint() -> str:
    rows = [f"{i.key}:{i.unit}" for i in catalogue.CATALOGUE.values()]
    return ", ".join(rows)


SYSTEM = """You turn South African grocery slips and kitchen voice notes into structured pantry data.
People mix English and Afrikaans. Slips use abbreviations (PNP, CHK, WW = store names; TOM = tomatoes; etc.).
Known ingredient keys with their counting unit (key:unit): {catalogue}
Rules:
- Use a known key whenever the item matches one.
- Only give a qty the person actually said or the slip shows. Never invent or assume an amount: no amount mentioned -> qty null, unit null.
- If they counted pieces ("4 chicken fillets", "6 chops", "2 blocks of cheese", "half a block"), return that count with unit "count" - do not convert pieces to grams.
- If they gave a weight or volume, convert it into the key's unit (1.2 kg tomatoes -> about 10 count; 2 L milk -> 2000 ml; 1 kg chicken -> 1000 g; 1 dozen eggs -> 12).
- If an item has no key, set key to null, give a short plain English name, and guess category (staple|long_life|perishable) and shelf_days.
- Vague amounts ("some", "a bit", "a few") -> qty null.
- storage only if the person said it (fridge|freezer|cupboard|counter), else null.
- Ignore non-food (toiletries, cleaning, plastic bags, airtime) and slip totals.
- price_cents = line total in cents if visible, else null.
- intent: what the person wants besides changing their kitchen list, in any wording or language:
  "dinner" = they want a meal idea now (what can I make/cook/eat tonight, what's for supper, wat kan ek vanaand maak, I'm hungry, give me an idea);
  "set_time" = they want the daily dinner message at another time (send it at six, change dinner time to half past five, stuur dit om sesuur) -> also fill time as 24h HH:MM; evening hours given without am/pm are pm (six -> 18:00, half five -> 17:30);
  "list" = they ask what food they have (what's in my fridge/freezer/pantry, wat is in die yskas) -> also set place if they name one (pantry/cupboard/kas = cupboard);
  "plan" = they are planning a meal or occasion and ask what they need (braai for 6, birthday lunch for 10, what do I need for lasagne for 4) - do NOT add those foods to the kitchen list;
  "help" = they ask how this works; else null.
  A message can both add items and have an intent ("bought chicken, what can I make tonight?").
Reply with JSON only."""

SLIP_SCHEMA = '{"items":[{"raw":"slip line","name":"..","key":"..|null","qty":n|null,"unit":"..|null","price_cents":n|null,"category":"..|null","shelf_days":n|null}]}'
MSG_SCHEMA = ('{"actions":[{"op":"add","name":"..","key":"..|null","qty":n|null,"unit":"..|null","storage":"..|null","category":"..|null","shelf_days":n|null},'
              '{"op":"remove","key":"..","reason":"finished|binned","qty":n|null},{"op":"set","key":"..","qty":n}],'
              '"intent":"dinner|set_time|list|plan|help|null","time":"HH:MM|null","place":"fridge|freezer|cupboard|counter|null",'
              '"other":"the message text if it is NOT about adding/removing kitchen items, else null"}')


def _client():
    import anthropic
    from .config import settings
    return anthropic.Anthropic(api_key=settings.anthropic_api_key)


def _ask_claude(content: list, schema: str, max_tokens: int = 2000) -> dict:
    from .config import settings
    resp = _client().messages.create(
        model=settings.parse_model,
        max_tokens=max_tokens,
        system=SYSTEM.format(catalogue=_catalogue_hint()),
        messages=[{"role": "user", "content": content + [{"type": "text", "text": f"Return JSON exactly in this shape: {schema}"}]}],
    )
    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError(f"No JSON in reply: {text[:200]}")
    return json.loads(m.group(0))


def _item_from(d: dict) -> ParsedItem:
    key = d.get("key")
    if key and key not in catalogue.CATALOGUE:
        key = catalogue.match(d.get("name") or key)
    return ParsedItem(
        name=d.get("name") or key or "item", key=key, qty=d.get("qty"), unit=d.get("unit"),
        storage=d.get("storage"), price_cents=d.get("price_cents"), raw=d.get("raw") or "",
        category=d.get("category"), shelf_days=d.get("shelf_days"),
    )


def ai_read_slip(image: bytes, mime: str) -> list[ParsedItem]:
    data = _ask_claude([
        {"type": "image", "source": {"type": "base64", "media_type": mime, "data": base64.b64encode(image).decode()}},
        {"type": "text", "text": "Read every food/grocery line on this till slip."},
    ], SLIP_SCHEMA, max_tokens=3000)
    return [_item_from(d) for d in data.get("items", [])]


def ai_understand(text: str) -> Understood:
    data = _ask_claude([{"type": "text", "text": f"Message from the household (may be a voice-note transcript):\n\"\"\"{text}\"\"\""}], MSG_SCHEMA)
    u = Understood(other=data.get("other"))
    if data.get("intent") in ("dinner", "set_time", "list", "plan", "help"):
        u.intent = data["intent"]
    if data.get("place") in ("fridge", "freezer", "cupboard", "counter"):
        u.place = data["place"]
    if u.intent == "plan":
        u.actions = []          # planned food is not in the kitchen yet
    if isinstance(data.get("time"), str) and re.fullmatch(r"\d{1,2}:\d{2}", data["time"]):
        h, m = data["time"].split(":")
        u.time = f"{int(h):02d}:{m}"
    for a in data.get("actions", []):
        op = a.get("op")
        if op == "add":
            u.actions.append(Action(op="add", item=_item_from(a)))
        elif op in ("remove", "set") and a.get("key"):
            key = a["key"] if a["key"] in catalogue.CATALOGUE else catalogue.match(a["key"]) or a["key"]
            u.actions.append(Action(op=op, key=key, reason=a.get("reason") or "finished", qty=a.get("qty")))
    return u


# ======================================================================
# Transcription (voice notes)
# ======================================================================

def transcribe(audio: bytes, mime: str) -> str:
    """Voice note -> text. Uses OpenAI's transcription endpoint (handles English + Afrikaans)."""
    import httpx
    from .config import settings
    if not settings.openai_api_key:
        raise RuntimeError("No OPENAI_API_KEY set - can't transcribe voice notes yet.")
    ext = "ogg" if "ogg" in mime else mime.split("/")[-1]
    r = httpx.post(
        "https://api.openai.com/v1/audio/transcriptions",
        headers={"Authorization": f"Bearer {settings.openai_api_key}"},
        files={"file": (f"voice.{ext}", audio, mime)},
        data={"model": settings.transcribe_model, "prompt": "South African kitchen items, English and Afrikaans: tamaties, maalvleis, boerewors, kaas, melk, eiers."},
        timeout=60,
    )
    r.raise_for_status()
    return r.json().get("text", "")


# ======================================================================
# Public entry points (AI first, offline fallback)
# ======================================================================

def understand(text: str) -> Understood:
    from .config import settings
    if settings.ai_enabled:
        try:
            return ai_understand(text)
        except Exception as e:  # noqa: BLE001
            log.warning("AI understand failed, using offline parser: %s", e)
    return understand_offline(text)


def read_slip(image: bytes | None = None, mime: str = "image/jpeg", text: str | None = None) -> list[ParsedItem]:
    from .config import settings
    if image is not None and settings.ai_enabled:
        return ai_read_slip(image, mime)
    if text is not None:
        return parse_slip_text(text)
    raise RuntimeError("Slip photos need ANTHROPIC_API_KEY to be read.")


# ======================================================================
# Occasion planning ("braai for 6 tonight, what do I need?")
# ======================================================================

PLAN_SYSTEM = """You help a South African household plan food for a meal or occasion using what they already have.
You get their request and their current kitchen list (key, name, amount if known, where it is).
Work out a sensible menu from their request (keep to what they asked for; fill obvious gaps like bread, salads, sauces only if typical),
scaled to the number of people. Then split it into what they already have and what they need to buy.
Amounts to buy: practical shop amounts (e.g. "1.5 kg rump steak", "2 loaves white bread", "1 pack braai spice").
For things at home, estimate how much of it this will use in the key's unit, so we can take it off their list afterwards.
If an at-home amount is unknown, assume they have enough unless clearly not (e.g. 1 onion for 6 people).
Write in plain friendly English (mirror Afrikaans words they use, like braaibroodjies, boerewors).
Reply with JSON only."""

PLAN_SCHEMA = ('{"title":"short e.g. Braai for 6","people":n|null,"event_date":"YYYY-MM-DD|null",'
               '"checkin_question":"short personal question for the next morning, e.g. Did you braai last night? 🔥",'
               '"yes_label":"button text <= 20 chars, e.g. Yes, we braaied",'
               '"have":[{"key":"kitchen key","name":"..","use_qty":n|null}],'
               '"buy":[{"name":"..","amount":".."}],"tip":"one short optional idea using what they have, or null"}')


def ai_plan(request: str, kitchen_lines: list[str], today: str) -> dict:
    from .config import settings
    content = (f"Today is {today}.\nRequest:\n\"\"\"{request}\"\"\"\n\nKitchen list:\n" + "\n".join(kitchen_lines)
               + f"\n\nReturn JSON exactly in this shape: {PLAN_SCHEMA}")
    resp = _client().messages.create(model=settings.parse_model, max_tokens=2000, system=PLAN_SYSTEM,
                                     messages=[{"role": "user", "content": content}])
    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError(f"No JSON in plan reply: {text[:200]}")
    return json.loads(m.group(0))
