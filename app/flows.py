"""Everything the user experiences, as WhatsApp conversations.

The user sees only four things: send a slip/voice note, tonight's dinner,
one-tap replies, and a monthly savings message. Everything else is background.
"""
import logging
import re
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import billing, catalogue, clock, pantry, parsing, photos, recipes
from . import whatsapp as wa
from .config import settings
from .models import ParseFailure, PantryItem, SavingsEvent, Suggestion, Usage, User
from .whatsapp import Inbound

log = logging.getLogger(__name__)


# ======================================================================
# Helpers
# ======================================================================

def get_user(s: Session, phone: str, name: str = "") -> tuple[User, bool]:
    u = s.scalar(select(User).where(User.phone == phone))
    if u:
        return u, False
    u = User(phone=phone, name=name or None, stage="new", dinner_time=settings.default_dinner_time, pending={})
    billing.start_trial(u)
    s.add(u)
    s.flush()
    return u, True


def in_window(user: User, now: datetime | None = None) -> bool:
    now = now or clock.now()
    return bool(user.last_inbound_at and now - user.last_inbound_at < timedelta(hours=23, minutes=50))


def send(s: Session, user: User, msg: dict) -> None:
    """Send, choosing free-form vs template based on the 24-hour window, and log the cost."""
    if msg["type"] == "template":
        if in_window(user):
            msg = msg["fallback"]
            kind, usd = "wa_service", wa.PRICE_SERVICE
        else:
            kind, usd = "wa_template", wa.PRICE_TEMPLATE_UTILITY
    else:
        if not in_window(user):
            log.warning("Tried to send free-form message to %s outside the 24h window; skipped", user.phone)
            return
        kind, usd = "wa_service", wa.PRICE_SERVICE
    wa.send(user.phone, msg)
    s.add(Usage(user_id=user.id, kind=kind, usd=usd, detail=msg.get("name") or msg["type"]))


def say(s, user, body):
    send(s, user, wa.text(body))


def _set_pending(user: User, **kv) -> None:
    p = dict(user.pending or {})
    p.update(kv)
    user.pending = p


def _pop_pending(user: User, key: str, default=None):
    p = dict(user.pending or {})
    v = p.pop(key, default)
    user.pending = p
    return v


def _names(keys: list[str]) -> str:
    names = [(catalogue.get(k).name if catalogue.get(k) else k).lower() for k in keys]
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def _summary(items: list[PantryItem], limit: int = 8) -> str:
    lines = [pantry.item_line(it) for it in items[:limit]]
    more = len(items) - limit
    text = ", ".join(lines)
    if more > 0:
        text += f" and {more} more"
    return text


# ======================================================================
# Entry point
# ======================================================================

def handle(s: Session, inb: Inbound) -> None:
    user, created = get_user(s, inb.phone, inb.name)
    user.last_inbound_at = clock.now()
    if inb.name and not user.name:
        user.name = inb.name

    if user.stage == "new":
        welcome(s, user)
        # A plain "Hi" just gets the welcome. If their first message already lists items
        # (or is a voice note / slip), carry on and process it.
        if inb.kind in ("button", "other") or (inb.kind == "text" and command_for(inb.text)):
            return

    if not billing.is_active(user) and inb.button_id != "pay":
        send_payment_prompt(s, user, expired=True)
        return

    try:
        if inb.kind == "button":
            on_button(s, user, inb.button_id)
        elif inb.kind == "audio":
            on_voice(s, user, inb)
        elif inb.kind == "image":
            on_slip_photo(s, user, inb)
        elif inb.kind == "text":
            on_text(s, user, inb.text, source="voice")
        else:
            say(s, user, "I can read slip photos, voice notes and text messages. Send one of those and I'll update your kitchen.")
    except Exception as e:  # noqa: BLE001
        log.exception("Error handling message from %s", user.phone)
        s.add(ParseFailure(user_id=user.id, kind=inb.kind, raw=inb.text or inb.media_id, error=str(e)[:1000]))
        say(s, user, "Sorry, something went wrong on my side reading that. Please try again in a minute.")


def _is_greeting(t: str) -> bool:
    return bool(re.fullmatch(r"\s*(hi|hello|hey|hallo|howzit|start|hi dinner 101|hello dinner 101|good (morning|afternoon|evening))[\s!.]*", (t or "").lower()))


# ======================================================================
# Onboarding
# ======================================================================

def welcome(s: Session, user: User) -> None:
    user.stage = "setup"
    name = f" {user.name.split()[0]}" if user.name else ""
    say(s, user,
        f"👋 Welcome to Dinner 101{name}!\n\n"
        "Every afternoon I'll send you one dinner idea using what's already in your kitchen.\n\n"
        "To start, walk through your kitchen and send me a voice note of everything you've got. "
        "Fridge, freezer, cupboards: any order, long or short, one note or a few.\n\n"
        f"Your first {settings.trial_days} days are free.")


def finish_setup(s: Session, user: User) -> None:
    user.stage = "active"
    n = len([it for it in pantry.active_items(s, user) if it.category != "staple"])
    send(s, user, wa.buttons(
        f"All set: {n} items in your kitchen. I'll send tonight's dinner idea at {user.dinner_time}.\n\n"
        "When you shop, just send a photo of the slip (or a voice note of what you bought).",
        [("see_list", "See my list"), ("dinner_now", "Dinner idea now")]))


# ======================================================================
# Adding stock: voice notes, text, slips
# ======================================================================

def on_voice(s: Session, user: User, inb: Inbound) -> None:
    audio, mime = wa.download_media(inb.media_id)
    text = parsing.transcribe(audio, mime or inb.mime)
    s.add(Usage(user_id=user.id, kind="ai_transcribe", usd=0.006, detail=text[:200]))
    if not text.strip():
        say(s, user, "I couldn't hear anything in that voice note. Please try again a bit closer to the phone.")
        return
    on_text(s, user, text, source="voice")


def on_text(s: Session, user: User, text: str, source: str = "voice") -> None:
    plan = (user.pending or {}).get("plan")
    if plan and plan.get("asked"):
        t = text.strip().lower().strip("!. ")
        if re.fullmatch(r"(yes|yep|ja|jip|yes we did|ja ons het|we did)", t):
            plan_answer(s, user, True)
            return
        if re.fullmatch(r"(no|nope|nee|it didn'?t|we didn'?t)", t):
            plan_answer(s, user, False)
            return
        _pop_pending(user, "plan")    # a voice note of what was used: handled as normal changes below
    cmd = command_for(text)
    if cmd and not (settings.ai_enabled and cmd in ("dinner", "time") and len(text.split()) > 6):
        run_command(s, user, cmd, text)
        return
    u = parsing.understand(text)
    if cmd and not u.intent and not u.actions:
        run_command(s, user, cmd, text)
        return
    if settings.ai_enabled:
        s.add(Usage(user_id=user.id, kind="ai_parse", usd=0.004, detail="text"))
    if u.intent:
        if u.actions:
            apply_actions(s, user, u.actions, source="setup" if user.stage == "setup" else source)
            if user.stage == "setup" or (user.pending or {}).get("storage_q"):
                return
        if u.intent == "dinner":
            send_dinner(s, user, force=True)
        elif u.intent == "set_time":
            set_dinner_time(s, user, u.time or parse_time(text))
        elif u.intent == "list":
            say(s, user, pantry.list_text(s, user, u.place))
        elif u.intent == "plan":
            plan_occasion(s, user, text)
        else:
            say(s, user, help_text())
        return
    if not u.actions:
        if user.stage == "setup":
            say(s, user, "I didn't catch any kitchen items there. Try a voice note like: \"six eggs, mince, a bag of potatoes, pasta, cheese…\"")
        else:
            say(s, user, help_text())
        return
    apply_actions(s, user, u.actions, source="setup" if user.stage == "setup" else source)


def apply_actions(s: Session, user: User, actions: list, source: str) -> None:
    to_add = [a.item for a in actions if a.op == "add" and a.item]
    removed, changed = [], []
    for a in actions:
        if a.op == "remove" and a.key:
            if pantry.remove_key(s, user, a.key, a.reason or "finished", a.qty):
                removed.append(a.key)
        elif a.op == "set" and a.key and a.qty is not None:
            if pantry.set_qty(s, user, a.key, a.qty):
                changed.append(a.key)
            else:
                to_add.append(pantry.ParsedItem(name=a.key, key=a.key, qty=a.qty))
    res = pantry.add_items(s, user, to_add, source) if to_add else pantry.AddResult()

    parts = []
    if res.added:
        verb = "Got" if source == "setup" else "Added"
        parts.append(f"✅ {verb} {len(res.added)} item{'s' if len(res.added) != 1 else ''}: {_summary(res.added)}")
    if removed:
        parts.append(f"🗑️ Took off: {_names(removed)}")
    if changed:
        parts.append(f"✏️ Updated: {_names(changed)}")
    if not parts:
        parts.append("👍 Noted.")

    queue = [it.id for it in res.ask_storage]
    if queue:
        _set_pending(user, storage_q=queue)
        say(s, user, "\n".join(parts) + "\n\nQuick question:")
        ask_next_storage(s, user)
        return
    if user.stage == "setup":
        say(s, user, "\n".join(parts))
        finish_setup(s, user)
    elif res.added and source == "slip":
        send(s, user, wa.buttons("\n".join(parts), [("slip_ok", "Looks right"), ("slip_fix", "Fix something")]))
    else:
        say(s, user, "\n".join(parts))


def ask_next_storage(s: Session, user: User) -> None:
    queue = list((user.pending or {}).get("storage_q", []))
    while queue:
        item = s.get(PantryItem, queue[0])
        if item and item.active:
            ing = catalogue.get(item.key)
            opts = ing.ask_storage if ing and ing.ask_storage else ("fridge", "freezer")
            btns = [(f"store:{item.id}:{o}", catalogue.STORAGE_LABEL[o]) for o in opts]
            send(s, user, wa.buttons(f"*{pantry.item_line(item)}*", btns))
            return
        queue.pop(0)
        _set_pending(user, storage_q=queue)
    _pop_pending(user, "storage_q")
    if user.stage == "setup":
        finish_setup(s, user)
    else:
        say(s, user, "👍 All sorted.")


def on_slip_photo(s: Session, user: User, inb: Inbound) -> None:
    image, mime = wa.download_media(inb.media_id)
    try:
        items = parsing.read_slip(image=image, mime=mime or inb.mime)
        s.add(Usage(user_id=user.id, kind="ai_parse", usd=0.02, detail="slip"))
    except Exception as e:  # noqa: BLE001
        s.add(ParseFailure(user_id=user.id, kind="slip", raw=inb.media_id, error=str(e)[:1000]))
        say(s, user, "I couldn't read that slip. Try a flat, well-lit photo of the whole slip, or send a voice note of what you bought.")
        return
    on_slip_items(s, user, items)


def on_slip_items(s: Session, user: User, items: list) -> None:
    if not items:
        s.add(ParseFailure(user_id=user.id, kind="slip", raw="no food items found"))
        say(s, user, "I couldn't find any food items on that slip. If it's a bit blurry, try another photo, or send a voice note of what you bought.")
        return
    _learn_aliases(s, items)
    apply_actions(s, user, [parsing.Action(op="add", item=i) for i in items], source="setup" if user.stage == "setup" else "slip")


def _learn_aliases(s: Session, items: list) -> None:
    from .models import ProductAlias
    for i in items:
        if i.raw and i.key and len(i.raw) <= 120:
            raw = i.raw.strip().upper()
            row = s.scalar(select(ProductAlias).where(ProductAlias.raw == raw))
            if row:
                row.hits += 1
            else:
                s.add(ProductAlias(raw=raw, key=i.key))


# ======================================================================
# Commands typed as text
# ======================================================================

def command_for(text: str) -> str | None:
    t = text.strip().lower()
    if re.fullmatch(r"(see )?(my )?(list|lys|kitchen|pantry|inventory)\??|what do i have\??|wat het ek\??", t) or place_asked(t):
        return "list"
    if parse_time(t) and re.search(r"\b(send|stuur|change|move|verander|dinner|supper|aandete|time|tyd|message|boodskap|remind)\b", t):
        return "time"
    if re.fullmatch(r"(dinner|supper|aandete|idea|idee|suggest.*)\W*", t) or re.search(
            r"what('?s| is| can| should| do)\b.*\b(make|cook|eat|dinner|supper|tonight)\b|"
            r"\b(dinner|supper|meal) (idea|ideas|suggestion)\b|\b(i'?m|we'?re) hungry\b|"
            r"\bwat\b.*\b(maak|kook|eet)\b|\baandete\b.*\?|\bhonger\b", t):
        return "dinner"
    if re.fullmatch(r"(help|hulp|\?|menu)", t):
        return "help"
    if re.fullmatch(r"(cancel|stop|unsubscribe|kanselleer)( (my )?(subscription|sub))?", t):
        return "cancel"
    if re.fullmatch(r"(pay|subscribe|betaal)", t):
        return "pay"
    if re.fullmatch(r"delete (my )?(data|account)|verwyder my data", t):
        return "delete"
    if _is_greeting(t):
        return "help"
    return None


_PLACE_WORDS = [("freezer", r"freezer|vrieskas|vriesier|deep ?freeze"), ("fridge", r"fridge|yskas|refrigerator"),
                ("cupboard", r"pantry|cupboard|kas|spens|grocery cupboard"), ("counter", r"counter|toonbank")]


def place_asked(t: str) -> str | None:
    """'what's in my freezer?' -> 'freezer'; 'what food do we have' -> 'all'."""
    t = t.lower()
    if not re.search(r"\b(what|wat|show|wys|list)\b", t):
        return None
    for place, pat in _PLACE_WORDS:
        if re.search(rf"\b(in|inside|uit)\b.*\b({pat})\b", t):
            return place
    if re.search(r"what (food )?(do|have) (i|we) (have|got)|wat (kos )?het (ek|ons)", t):
        return "all"
    return None


_NUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
        "ten": 10, "een": 1, "twee": 2, "drie": 3, "vier": 4, "vyf": 5, "ses": 6, "sewe": 7, "agt": 8, "nege": 9, "tien": 10}


def parse_time(t: str) -> str | None:
    """'6 o'clock', 'half past five', 'half six', '17:30', '6pm', 'sesuur', 'half ses' -> 'HH:MM' (evening assumed)."""
    t = t.lower()
    words = "|".join(_NUM)
    h = mi = None
    m = re.search(r"\b(\d{1,2})[:h.](\d{2})\b", t)
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
    if h is None:
        m = re.search(rf"\bhalf (?:past )?(\d{{1,2}}|{words})\b", t)
        if m:
            n = int(m.group(1)) if m.group(1).isdigit() else _NUM[m.group(1)]
            # English "half past six" = 6:30; English "half six" = 6:30; Afrikaans "half ses" = 5:30
            afr = m.group(1) in ("een", "twee", "drie", "vier", "vyf", "ses", "sewe", "agt", "nege", "tien")
            h, mi = (n - 1, 30) if afr and "past" not in m.group(0) else (n, 30)
    if h is None:
        m = re.search(rf"\bquarter (past|to) (\d{{1,2}}|{words})\b", t)
        if m:
            n = int(m.group(2)) if m.group(2).isdigit() else _NUM[m.group(2)]
            h, mi = (n, 15) if m.group(1) == "past" else (n - 1, 45)
    if h is None:
        m = re.search(rf"\b(\d{{1,2}}|{words})\s*(?:o'?clock|uur|pm|p\.m\.)|\b(\d{{1,2}}|{words})uur\b|\b(?:at|om|to|na)\s+(\d{{1,2}}|{words})\b", t)
        if m:
            g = m.group(1) or m.group(2) or m.group(3)
            h, mi = (int(g) if g.isdigit() else _NUM[g]), 0
    if h is None or not (0 <= h <= 23 and 0 <= mi <= 59):
        return None
    if h < 12 and h <= 10:
        h += 12          # dinner time: "6" means 18:00
    return f"{h:02d}:{mi:02d}"


def set_dinner_time(s: Session, user: User, hhmm: str | None) -> None:
    if not hhmm:
        say(s, user, "What time should I send your dinner idea? E.g. \"send it at 17:30\".")
        return
    user.dinner_time = hhmm
    say(s, user, f"👍 Done. I'll send your dinner idea at {hhmm} from now on.")


def run_command(s: Session, user: User, cmd: str, text: str) -> None:
    if cmd == "list":
        pl = place_asked(text)
        say(s, user, pantry.list_text(s, user, None if pl in (None, "all") else pl))
    elif cmd == "dinner":
        send_dinner(s, user, force=True)
    elif cmd == "time":
        set_dinner_time(s, user, parse_time(text.lower()))
    elif cmd == "help":
        say(s, user, help_text())
    elif cmd == "cancel":
        user.subscription_status = "cancelled"
        _set_pending(user, cancel_requested=clock.now().isoformat())
        say(s, user, "Done, your subscription is cancelled and you won't be billed again. Your kitchen list stays here if you ever come back. 👋")
    elif cmd == "pay":
        send_payment_prompt(s, user)
    elif cmd == "delete":
        say(s, user, "Done. I've deleted your kitchen list and history. If you subscribed, your subscription is cancelled too. Send \"Hi\" any time to start fresh. 👋")
        delete_user(s, user)


def delete_user(s: Session, user: User) -> None:
    from sqlalchemy import delete
    from .models import Habit
    for model in (PantryItem, Habit, Suggestion, SavingsEvent, Usage, ParseFailure):
        if model is Usage:
            s.execute(model.__table__.update().where(model.user_id == user.id).values(user_id=None))
        else:
            s.execute(delete(model).where(model.user_id == user.id))
    s.delete(user)


# ======================================================================
# Occasions: "braai for 6 tonight, what do I need?"
# ======================================================================

def _kitchen_lines(s: Session, user: User) -> list[str]:
    out = []
    for it in pantry.active_items(s, user):
        if pantry.status(it) == "gone":
            continue
        amt = pantry.shown_qty([it], it.qty, it.unit) or "amount unknown"
        out.append(f"{it.key} | {it.name} | {amt} (tracked as {round(it.qty)} {it.unit}) | {it.storage}")
    return out


def plan_occasion(s: Session, user: User, text: str) -> None:
    if not settings.ai_enabled:
        say(s, user, "Planning for a braai or a crowd isn't switched on yet. Try again a bit later.")
        return
    try:
        plan = parsing.ai_plan(text, _kitchen_lines(s, user), clock.now().strftime("%A %Y-%m-%d"))
    except Exception:  # noqa: BLE001
        log.exception("plan failed")
        say(s, user, "Sorry, I couldn't work that out right now. Please try again in a minute.")
        return
    s.add(Usage(user_id=user.id, kind="ai_plan", usd=0.01, detail=(plan.get("title") or "")[:200]))

    have = [h for h in plan.get("have", []) if h.get("key")]
    buy = [b for b in plan.get("buy", []) if b.get("name")]
    title = plan.get("title") or "Your plan"
    lines = [f"🔥 *{title}*"]
    if have:
        lines.append("\n✅ *Already at home:*\n" + "\n".join(f"• {h.get('name') or h['key']}" for h in have))
    if buy:
        lines.append("\n🛒 *To buy:*\n" + "\n".join(f"• {b['name']}" + (f" ({b['amount']})" if b.get("amount") else "") for b in buy))
    else:
        lines.append("\n🛒 You've got everything. Nothing to buy!")
    if plan.get("tip"):
        lines.append(f"\n💡 {plan['tip']}")
    say(s, user, "\n".join(lines))
    if buy:
        # a clean list on its own, easy to copy or forward
        say(s, user, f"Shopping list: {title}\n" + "\n".join(f"- {b['name']}" + (f", {b['amount']}" if b.get("amount") else "") for b in buy))

    # check in the morning after the event
    try:
        day = datetime.strptime(plan.get("event_date") or "", "%Y-%m-%d")
    except ValueError:
        day = clock.now()
    due = (day + timedelta(days=1)).replace(hour=9, minute=30, second=0, microsecond=0)
    _set_pending(user, plan={
        "title": title,
        "question": (plan.get("checkin_question") or f"Did the {title.lower()} happen?")[:200],
        "yes": (plan.get("yes_label") or "Yes")[:20],
        "use": [[h["key"], h.get("use_qty")] for h in have],
        "due": due.isoformat(),
    })


def send_plan_checkin(s: Session, user: User) -> None:
    plan = (user.pending or {}).get("plan")
    if not plan:
        return
    plan = dict(plan, asked=True)
    _set_pending(user, plan=plan)
    body = f"{plan['question']}\n\nTap yes and I'll take off what you used from home, or send a voice note of what was used."
    btns = [("plan:yes", plan["yes"]), ("plan:no", "No, it didn't")]
    send(s, user, wa.template(settings.tpl_notice, [plan["question"] + " Reply yes, or send a voice note of what you used."],
                              wa.buttons(body, btns)))


def plan_answer(s: Session, user: User, yes: bool) -> None:
    plan = _pop_pending(user, "plan")
    if not plan:
        say(s, user, "👍")
        return
    if not yes:
        say(s, user, "No problem, I haven't changed anything. 👍")
        return
    needs = []
    for key, q in plan.get("use", []):
        st = pantry.stock(s, user).get(key)
        if not st:
            continue
        needs.append((key, float(q) if q else st["qty"]))
    if needs:
        pantry.deduct(s, user, needs)
    say(s, user, "✅ Done, I've taken off what you used from home. "
                 "If anything's different (e.g. \"there's still half the steak left\"), just send a voice note.")


def help_text() -> str:
    return ("Here's what you can send me:\n"
            "📸 A photo of your till slip\n"
            "🎙️ A voice note: \"bought milk and bread\", \"we finished the eggs\", \"threw out the lettuce\"\n"
            "💬 \"list\" to see your kitchen, \"dinner\" for an idea now, \"send dinner at 17:30\" to change the time")


# ======================================================================
# Dinner
# ======================================================================

def today_suggestions(s: Session, user: User) -> list[Suggestion]:
    start = clock.now().replace(hour=0, minute=0, second=0, microsecond=0)
    return list(s.scalars(select(Suggestion).where(Suggestion.user_id == user.id, Suggestion.created_at >= start)
                          .order_by(Suggestion.id)))


def unresolved_checkin(s: Session, user: User) -> Suggestion | None:
    """An accepted dinner from a previous day we never heard back about."""
    start = clock.now().replace(hour=0, minute=0, second=0, microsecond=0)
    return s.scalar(select(Suggestion).where(
        Suggestion.user_id == user.id, Suggestion.status == "accepted", Suggestion.created_at < start,
        Suggestion.created_at >= start - timedelta(days=2)).order_by(Suggestion.id.desc()))


def send_dinner(s: Session, user: User, force: bool = False, exclude: set | None = None) -> Suggestion | None:
    if not force:
        pending = unresolved_checkin(s, user)
        if pending:
            pending.checkin_sent_at = clock.now()
            _set_pending(user, dinner_after_checkin=True)
            r = recipes.RECIPES[pending.recipe_id]
            body = f"Before tonight's idea: did you cook the {r['name'].lower()} last time?"
            btns = [(f"cooked:{pending.id}", "Cooked it"), (f"notcooked:{pending.id}", "Didn't cook")]
            send(s, user, wa.template(settings.tpl_checkin, [r["name"].lower()], wa.buttons(body, btns), button_ids=[b[0] for b in btns]))
            return None
    rejected = {sg.recipe_id for sg in today_suggestions(s, user) if sg.status == "rejected"}
    best, near = recipes.pick(s, user, exclude=(exclude or set()) | rejected)
    if not best:
        if near:
            item = near.missing[0]
            msg = (f"Your kitchen is running a bit low tonight. Grab {_names([item])}{recipes.price_hint(item)} "
                   f"and you can make *{near.recipe['name']}*.")
        else:
            msg = "I can't find a full dinner in your kitchen right now. Send me your next slip (or a voice note of what you've got) and I'll sort out ideas."
        send(s, user, wa.template(settings.tpl_notice, [msg], wa.text(msg)))
        return None

    sg = Suggestion(user_id=user.id, recipe_id=best.recipe["id"], status="sent")
    s.add(sg)
    s.flush()
    r = best.recipe
    if best.use_soon:
        uses = f"Uses up your {_names(best.use_soon)} before they go off. Everything's at home."
    else:
        uses = "Everything's at home."
    body = f"*Tonight: {r['name']}*\n{r['minutes']} min · serves {r['serves']}\n\n{uses}"
    if near:
        body += f"\n\n💡 One item short of *{near.recipe['name']}*: {_names(near.missing)}{recipes.price_hint(near.missing[0])}."
    btns = [(f"cook:{sg.id}", "Let's cook it"), (f"other:{sg.id}", "Something else"), (f"recipe:{sg.id}", "Show recipe")]
    image = photos.url_for(r["id"])
    fallback = wa.buttons(body, btns, image=image)
    send(s, user, wa.template(settings.tpl_dinner, [r["name"], str(r["minutes"]), uses], fallback, image=image,
                              button_ids=[b[0] for b in btns]))
    return sg


def recipe_text(s: Session, user: User, sg: Suggestion) -> str:
    r = recipes.RECIPES[sg.recipe_id]
    ev = recipes.eval_for(s, user, sg.recipe_id)
    uses = ", ".join(
        pantry.amount_phrase(catalogue.get(k).name if catalogue.get(k) else k, q, catalogue.get(k).unit if catalogue.get(k) else "count")
        for k, q in ev.used)
    steps = "\n".join(f"{i}. {st}" for i, st in enumerate(r["steps"], 1))
    return f"*{r['name']}* ({r['minutes']} min)\n\nFrom your kitchen: {uses}\n\n{steps}"


def accept(s: Session, user: User, sg: Suggestion) -> None:
    sg.status = "accepted"
    sg.accepted_at = clock.now()
    _learn_dinner_time(user)
    say(s, user, recipe_text(s, user, sg) + "\n\nEnjoy! I'll check in after dinner to update your kitchen.")


def _learn_dinner_time(user: User) -> None:
    now = clock.now()
    h, m = map(int, user.dinner_time.split(":"))
    current = h * 60 + m
    observed = now.hour * 60 + now.minute - 10
    if not (14 * 60 <= observed <= 20 * 60):
        return
    new = round((0.8 * current + 0.2 * observed) / 5) * 5
    new = max(15 * 60, min(19 * 60 + 30, new))
    user.dinner_time = f"{new // 60:02d}:{new % 60:02d}"


def send_checkin(s: Session, user: User, sg: Suggestion) -> None:
    sg.checkin_sent_at = clock.now()
    r = recipes.RECIPES[sg.recipe_id]
    btns = [(f"cooked:{sg.id}", "Cooked it"), (f"notcooked:{sg.id}", "Didn't cook")]
    send(s, user, wa.template(settings.tpl_checkin, [r["name"].lower()],
                              wa.buttons(f"How did the {r['name'].lower()} go?", btns), button_ids=[b[0] for b in btns]))


def _like(s: Session, user: User, recipe_id: str, delta: int) -> None:
    h = pantry.habit(s, user, f"recipe:{recipe_id}")
    h.likes = max(-5, min(5, h.likes + delta))


def _after_checkin(s: Session, user: User) -> None:
    if _pop_pending(user, "dinner_after_checkin"):
        send_dinner(s, user, force=True)


# ======================================================================
# Buttons
# ======================================================================

def on_button(s: Session, user: User, bid: str) -> None:
    parts = bid.split(":")
    action = parts[0]
    sg = None
    if len(parts) > 1 and action not in ("store", "plan"):
        try:
            sg = s.get(Suggestion, int(parts[1]))
        except ValueError:
            sg = None
        if sg and sg.user_id != user.id:
            sg = None

    if action == "see_list":
        say(s, user, pantry.list_text(s, user))
    elif action == "dinner_now":
        send_dinner(s, user, force=True)
    elif action == "slip_ok":
        say(s, user, "👍 Great.")
    elif action == "slip_fix":
        say(s, user, "No problem. Send a voice note or type what's wrong, e.g. \"only 4 eggs\", \"no chicken\" or \"it was 2 kg potatoes\".")
    elif action == "store" and len(parts) == 3:
        item = s.get(PantryItem, int(parts[1]))
        if item and item.user_id == user.id and parts[2] in ("fridge", "freezer", "counter", "cupboard"):
            pantry.set_storage(s, user, item, parts[2])
        queue = [i for i in (user.pending or {}).get("storage_q", []) if i != int(parts[1])]
        _set_pending(user, storage_q=queue)
        ask_next_storage(s, user)
    elif action == "plan" and len(parts) == 2:
        plan_answer(s, user, parts[1] == "yes")
    elif action == "pay":
        send_payment_prompt(s, user)
    elif sg is None:
        say(s, user, "That button has expired. Send \"dinner\" for a fresh idea.")
    elif action == "cook":
        ev = recipes.eval_for(s, user, sg.recipe_id)
        if ev.unsure_mains:
            key = ev.unsure_mains[0]
            send(s, user, wa.buttons(f"Quick check: still got the {_names([key])}?",
                                     [(f"have:{sg.id}:{key}:y", "Yes"), (f"have:{sg.id}:{key}:n", "No")]))
        else:
            accept(s, user, sg)
    elif action == "have" and len(parts) == 4:
        key, yes = parts[2], parts[3] == "y"
        pantry.confirm_present(s, user, key, yes)
        if yes:
            ev = recipes.eval_for(s, user, sg.recipe_id)
            if ev.unsure_mains:
                k = ev.unsure_mains[0]
                send(s, user, wa.buttons(f"And the {_names([k])}?", [(f"have:{sg.id}:{k}:y", "Yes"), (f"have:{sg.id}:{k}:n", "No")]))
            else:
                accept(s, user, sg)
        else:
            sg.status = "rejected"
            say(s, user, "Thanks, I've taken it off your list. Here's another idea:")
            send_dinner(s, user, force=True)
    elif action == "other":
        sg.status = "rejected"
        _like(s, user, sg.recipe_id, -1)
        nxt = send_dinner(s, user, force=True, exclude={sg.recipe_id})
        if nxt is None:
            pass
    elif action == "recipe":
        send(s, user, wa.buttons(recipe_text(s, user, sg), [(f"cook:{sg.id}", "Let's cook it"), (f"other:{sg.id}", "Something else")]))
    elif action == "cooked":
        if sg.status in ("cooked",):
            say(s, user, "Already updated 👍")
            return
        ev = recipes.eval_for(s, user, sg.recipe_id)
        rescued = pantry.deduct(s, user, recipes.needs(ev))
        sg.status, sg.resolved_at = "cooked", clock.now()
        _like(s, user, sg.recipe_id, +1)
        msg = "🍽️ Nice! I've updated your kitchen."
        if rescued >= 500:
            msg += f" You used about R{rescued / 100:.0f} of food that was close to going off."
        send(s, user, wa.buttons(msg + "\n\nAny leftovers?", [(f"left:{sg.id}:y", "Leftovers"), (f"left:{sg.id}:n", "All eaten")]))
    elif action == "notcooked":
        sg.status, sg.resolved_at = "not_cooked", clock.now()
        send(s, user, wa.buttons("No problem. What happened?", [(f"othermeal:{sg.id}", "Made something else"), (f"skipped:{sg.id}", "Ate out / skipped")]))
    elif action == "othermeal":
        sg.status = "other_meal"
        say(s, user, "Got it. If you used anything up, just send a voice note like \"we used the mince and the potatoes\".")
        _after_checkin(s, user)
    elif action == "skipped":
        sg.status = "skipped"
        say(s, user, "No problem, everything stays on your list for next time.")
        _after_checkin(s, user)
    elif action == "left" and len(parts) == 3:
        sg.leftovers = parts[2] == "y"
        if sg.leftovers:
            r = recipes.RECIPES[sg.recipe_id]
            s.add(PantryItem(user_id=user.id, key=f"x_leftovers_{sg.id}", name=f"Leftover {r['name'].lower()}", qty=1,
                             unit="portion", category="perishable", storage="fridge", source="leftovers",
                             added_at=clock.now(), expires_at=clock.now() + timedelta(days=3), confidence=1.0, active=True))
            say(s, user, "👍 Noted. Leftovers keep about 3 days in the fridge, handy for lunch tomorrow.")
        else:
            say(s, user, "👍 Great. See you tomorrow.")
        _after_checkin(s, user)
    else:
        say(s, user, help_text())


# ======================================================================
# Billing messages
# ======================================================================

def send_payment_prompt(s: Session, user: User, expired: bool = False) -> None:
    link = billing.payment_link(user)
    saved = month_savings(s, user, clock.now().replace(day=1) - timedelta(days=31), clock.now())
    lead = "Your free trial has ended." if expired else "Your free trial ends soon."
    extra = f" So far Dinner 101 helped you use about R{saved / 100:.0f} of food before it went off." if saved >= 1000 else ""
    msg = (f"{lead}{extra}\n\nKeep getting dinner sorted for R{settings.price_rands:.0f}/month. Cancel any time by sending \"cancel\".\n\n"
           f"Subscribe here: {link}")
    send(s, user, wa.template(settings.tpl_notice, [msg], wa.text(msg)))


def month_savings(s: Session, user: User, start: datetime, end: datetime) -> int:
    v = s.scalar(select(func.coalesce(func.sum(SavingsEvent.cents), 0)).where(
        SavingsEvent.user_id == user.id, SavingsEvent.kind == "rescued", SavingsEvent.at >= start, SavingsEvent.at < end))
    return int(v or 0)


def month_waste(s: Session, user: User, start: datetime, end: datetime) -> int:
    v = s.scalar(select(func.coalesce(func.sum(SavingsEvent.cents), 0)).where(
        SavingsEvent.user_id == user.id, SavingsEvent.kind == "wasted", SavingsEvent.at >= start, SavingsEvent.at < end))
    return int(v or 0)


def send_monthly_report(s: Session, user: User, month_start: datetime, month_end: datetime) -> None:
    saved = month_savings(s, user, month_start, month_end)
    wasted = month_waste(s, user, month_start, month_end)
    cooked = s.scalar(select(func.count()).select_from(Suggestion).where(
        Suggestion.user_id == user.id, Suggestion.status == "cooked",
        Suggestion.created_at >= month_start, Suggestion.created_at < month_end)) or 0
    label = month_start.strftime("%B")
    msg = f"📊 Your Dinner 101 {label}:\n🍽️ {cooked} dinners cooked from what you had"
    if saved:
        msg += f"\n💰 About R{saved / 100:.0f} of food used before it went off"
    if wasted:
        msg += f"\n🗑️ About R{wasted / 100:.0f} binned"
    if saved > settings.price_rands * 100:
        msg += f"\n\nThat's more than the R{settings.price_rands:.0f} Dinner 101 costs. 🙌"
    send(s, user, wa.template(settings.tpl_notice, [msg], wa.text(msg)))
