"""End-to-end conversation tests using the in-memory WhatsApp outbox."""
from datetime import datetime, timedelta

from sqlalchemy import select

from app import clock, pantry, scheduler
from app import whatsapp as wa
from app.db import session_scope
from app.flows import handle, on_slip_items
from app.models import PantryItem, Suggestion, User
from app.parsing import parse_slip_text
from app.whatsapp import Inbound

PHONE = "sim-27820000001"


def send_text(t):
    with session_scope() as s:
        handle(s, Inbound(phone=PHONE, kind="text", text=t))
    return wa.sim_outbox.take(PHONE)


def tap(bid):
    with session_scope() as s:
        handle(s, Inbound(phone=PHONE, kind="button", button_id=bid))
    return wa.sim_outbox.take(PHONE)


def slip(text):
    with session_scope() as s:
        user = s.scalar(select(User).where(User.phone == PHONE))
        user.last_inbound_at = clock.now()
        on_slip_items(s, user, parse_slip_text(text))
    return wa.sim_outbox.take(PHONE)


def buttons_of(msgs):
    return [b for m in msgs if m["type"] == "buttons" for b in m["buttons"]]


def at(h, m=0, days=0):
    base = datetime.now().replace(hour=h, minute=m, second=0, microsecond=0) + timedelta(days=days)
    clock.set_to(base)


def onboard():
    at(10)
    out = send_text("Hi Dinner 101")
    assert "Welcome to Dinner 101" in out[0]["body"]
    out = send_text("Six eggs, half a block of cheddar, milk, some tomatoes, a cucumber, mayo, 500g mince, "
                    "a bag of pasta, two tins of tomatoes, chicken fillets, onions, rice, a pocket of potatoes")
    return out


def test_onboarding_asks_only_meat_storage_then_finishes():
    out = onboard()
    assert "Got" in out[0]["body"]
    btns = buttons_of(out)
    # first storage question is about a meat with Fridge/Frozen buttons
    assert [t for _, t in btns] == ["Fridge", "Frozen"]
    out = tap(btns[1][0])          # mince -> frozen
    btns = buttons_of(out)
    assert [t for _, t in btns] == ["Fridge", "Frozen"]
    out = tap(btns[0][0])          # chicken -> fridge
    assert "All set" in out[0]["body"]
    with session_scope() as s:
        user = s.scalar(select(User).where(User.phone == PHONE))
        assert user.stage == "active"
        mince = s.scalar(select(PantryItem).where(PantryItem.key == "mince"))
        assert mince.storage == "freezer" and mince.expires_at - mince.added_at > timedelta(days=30)
        keys = {it.key for it in pantry.active_items(s, user)}
        assert {"eggs", "cheese", "tomato", "canned_tomatoes", "pasta", "potato", "chicken_fillet"} <= keys


def test_full_day_dinner_cook_checkin_and_deduction():
    out = onboard()
    for _ in range(3):
        btns = buttons_of(out)
        if not btns or btns[0][1] != "Fridge":
            break
        out = tap(btns[0][0])
    at(16, 31)
    stats = scheduler.tick()
    assert stats["dinners"] == 1
    out = wa.sim_outbox.take(PHONE)
    dinner = out[-1]
    assert dinner["body"].startswith("*Tonight:")
    assert [t for _, t in dinner["buttons"]] == ["Let's cook it", "Something else", "Show recipe"]

    # Something else -> a different meal
    first_name = dinner["body"].split("\n")[0]
    out = tap(dinner["buttons"][1][0])
    second = out[-1]
    assert second["body"].split("\n")[0] != first_name

    out = tap(second["buttons"][0][0])
    if out and out[-1]["type"] == "buttons" and out[-1]["buttons"][0][1] == "Yes":
        out = tap(out[-1]["buttons"][0][0])
    assert "Enjoy" in out[-1]["body"]

    with session_scope() as s:
        before = {it.key: it.qty for it in pantry.active_items(s, s.scalar(select(User)))}

    at(19, 30)
    stats = scheduler.tick()
    assert stats["checkins"] == 1
    out = wa.sim_outbox.take(PHONE)
    assert [t for _, t in out[-1]["buttons"]] == ["Cooked it", "Didn't cook"]
    out = tap(out[-1]["buttons"][0][0])
    assert "updated your kitchen" in out[-1]["body"]
    with session_scope() as s:
        user = s.scalar(select(User))
        after = {it.key: it.qty for it in pantry.active_items(s, user)}
        sg = s.scalar(select(Suggestion).where(Suggestion.status == "cooked"))
        assert sg is not None
    assert after != before  # something was deducted

    # no second dinner the same evening
    assert scheduler.tick()["dinners"] == 0


def test_unanswered_checkin_is_asked_before_next_dinner():
    out = onboard()
    while buttons_of(out) and buttons_of(out)[0][1] == "Fridge":
        out = tap(buttons_of(out)[0][0])
    at(16, 31)
    scheduler.tick()
    dinner = wa.sim_outbox.take(PHONE)[-1]
    out = tap(dinner["buttons"][0][0])
    if out[-1]["type"] == "buttons" and out[-1]["buttons"][0][1] == "Yes":
        tap(out[-1]["buttons"][0][0])
    # user ignores check-in; next day at dinner time we ask about last night first
    at(16, 31, days=1)
    scheduler.tick()
    out = wa.sim_outbox.take(PHONE)
    assert "did you cook" in out[-1]["body"].lower()
    out = tap(out[-1]["buttons"][1][0])        # Didn't cook
    out = tap(out[-1]["buttons"][1][0])        # Ate out / skipped -> dinner follows
    assert any(m["body"].startswith("*Tonight:") for m in out)


def test_slip_adds_items_and_buy_again_lowers_old_confidence():
    out = onboard()
    while buttons_of(out) and buttons_of(out)[0][1] == "Fridge":
        out = tap(buttons_of(out)[0][0])
    at(12, days=1)
    out = slip("PNP TOM LOOSE 1.2KG 24.99\nPNP CHKN FLLT 1KG 89.99\nCLOVER FRSH MLK 2L 36.99\nCOLGATE 29.99\nTOTAL 151.97")
    assert "Added 3 items" in out[0]["body"], out
    assert "×10" in out[0]["body"]
    with session_scope() as s:
        toms = list(s.scalars(select(PantryItem).where(PantryItem.key == "tomato", PantryItem.active.is_(True))))
        assert len(toms) == 2
        assert min(t.confidence for t in toms) <= 0.5


def test_voice_corrections():
    onboard()
    out = send_text("we finished the milk")
    assert "Took off" in out[0]["body"]
    out = send_text("threw out the cucumber")
    assert "Took off" in out[0]["body"]
    out = send_text("only 2 eggs left")
    assert "Updated" in out[0]["body"]
    with session_scope() as s:
        eggs = s.scalar(select(PantryItem).where(PantryItem.key == "eggs", PantryItem.active.is_(True)))
        assert eggs.qty == 2


def test_trial_expiry_pauses_and_prompts_payment():
    out = onboard()
    while buttons_of(out) and buttons_of(out)[0][1] == "Fridge":
        out = tap(buttons_of(out)[0][0])
    at(10, days=12)
    send_text("list")  # keeps window open
    stats = scheduler.tick()
    assert stats["reminders"] == 1
    at(10, days=15)
    scheduler.tick()
    out = send_text("dinner")
    assert "trial has ended" in out[-1]["body"]


def test_delete_my_data():
    onboard()
    out = send_text("delete my data")
    assert "deleted" in out[-1]["body"]
    with session_scope() as s:
        assert s.scalar(select(User).where(User.phone == PHONE)) is None
        assert s.scalar(select(PantryItem)) is None


def test_plain_language_dinner_and_time():
    out = onboard()
    for _ in range(4):
        b = buttons_of(out)
        if not b:
            break
        out = tap(b[0][0])
    out = send_text("Okay, what can I make tonight?")
    assert any(m.get("buttons") or "tonight" in m.get("body", "").lower() for m in out)
    assert "Here's what you can send me" not in out[0].get("body", "")
    out = send_text("change the dinner time to 6 o'clock")
    assert "18:00" in out[0]["body"]
    with session_scope() as s:
        assert s.scalar(select(User).where(User.phone == PHONE)).dinner_time == "18:00"


def test_whats_in_my_freezer_and_braai_plan(monkeypatch):
    from app import parsing
    from app.config import settings
    out = onboard()
    out = tap(buttons_of(out)[1][0])      # mince -> frozen
    out = tap(buttons_of(out)[0][0])      # chicken -> fridge
    out = send_text("what's in my freezer?")
    body = out[0]["body"]
    assert "Freezer" in body and "mince" in body.lower() and "Chicken" not in body
    out = send_text("what food do we have")
    assert "Fridge" in out[0]["body"] and "Freezer" in out[0]["body"]

    # occasion planning (AI faked)
    monkeypatch.setattr(type(settings), "ai_enabled", property(lambda self: True))
    monkeypatch.setattr(parsing, "ai_understand", lambda t: parsing.Understood(intent="plan"))
    monkeypatch.setattr(parsing, "ai_plan", lambda req, lines, today: {
        "title": "Braai for 6", "people": 6, "event_date": None,
        "checkin_question": "Did you braai last night? 🔥", "yes_label": "Yes, we braaied",
        "have": [{"key": "cheese", "name": "Cheddar cheese", "use_qty": 100}],
        "buy": [{"name": "Rump steak", "amount": "1.5 kg"}, {"name": "White bread", "amount": "2 loaves"}],
        "tip": None})
    out = send_text("We're having a braai tonight with 6 friends, braaibroodjies and steak. What do I need?")
    assert "Braai for 6" in out[0]["body"] and "Rump steak" in out[0]["body"]
    assert out[1]["body"].startswith("Shopping list")
    with session_scope() as s:
        user = s.scalar(select(User).where(User.phone == PHONE))
        assert "steak" not in {it.key for it in pantry.active_items(s, user)}   # planned food isn't added
        before = pantry.stock(s, user)["cheese"]["qty"]

    clock.set_to((clock.now() + timedelta(days=1)).replace(hour=9, minute=35))   # next morning
    scheduler.tick()
    out = wa.sim_outbox.take(PHONE)
    assert any("Did you braai last night" in (m.get("body") or "") for m in out)
    out = tap("plan:yes")
    assert "taken off" in out[0]["body"]
    with session_scope() as s:
        user = s.scalar(select(User).where(User.phone == PHONE))
        assert pantry.stock(s, user)["cheese"]["qty"] == before - 100


def test_checkin_only_when_they_engaged():
    out = onboard()
    out = tap(buttons_of(out)[0][0])
    out = tap(buttons_of(out)[0][0])
    # day 1: dinner arrives at 16:30, they ignore it -> no check-in that night or next day
    at(16, 31)
    scheduler.tick()
    first = wa.sim_outbox.take(PHONE)
    assert first, "dinner should be sent"
    at(20, 0)
    scheduler.tick()
    assert not any("cook" in (m.get("body") or "").lower() and "did you" in (m.get("body") or "").lower()
                   for m in wa.sim_outbox.take(PHONE))
    at(16, 31, days=1)
    scheduler.tick()
    out = wa.sim_outbox.take(PHONE)
    assert not any("last time" in (m.get("body") or "") for m in out)
    # day 2: they open the recipe -> check-in comes later that evening
    sg_btn = next(b for b, t in buttons_of(out) if t == "Show recipe")
    tap(sg_btn)
    clock.advance(hours=3)
    scheduler.tick()
    out = wa.sim_outbox.take(PHONE)
    assert any("Cooked it" in [t for _, t in buttons_of([m])] for m in out)


def test_low_kitchen_tip_is_sent_only_once_a_day():
    at(10)
    send_text("Hi Dinner 101")
    send_text("2 onions and some rice")
    for b, _ in buttons_of(wa.sim_outbox.take(PHONE)):
        tap(b)
    wa.sim_outbox.take(PHONE)
    sent = []
    for minute in range(31, 40):
        at(16, minute)
        scheduler.tick()
        sent += wa.sim_outbox.take(PHONE)
    assert len(sent) == 1, [m.get("body") for m in sent]
    assert "R0" not in sent[0]["body"]


def test_threw_out_everything_in_fridge_and_cupboard():
    out = onboard()
    for _ in range(3):
        b = buttons_of(out)
        if not b:
            break
        out = tap(b[0][0])
    out = send_text("I threw everything in the fridge and in the cupboard away")
    body = out[0]["body"]
    assert "Cleared your fridge" in body and "Cleared your cupboard" in body
    with session_scope() as s:
        user = s.scalar(select(User).where(User.phone == PHONE))
        left = {it.storage for it in pantry.active_items(s, user) if it.category != "staple"}
        assert "fridge" not in left and "cupboard" not in left
    out = send_text("okay, 2 onions")
    assert "Okay" not in out[0]["body"]


def test_assistant_removes_items_and_answers_cooking_questions(monkeypatch):
    from app import parsing
    from app.config import settings
    out = onboard()
    for _ in range(3):
        b = buttons_of(out)
        if not b:
            break
        out = tap(b[0][0])
    monkeypatch.setattr(type(settings), "ai_enabled", property(lambda self: True))
    seen = {}

    def fake(text, lines, history, today):
        seen["lines"] = lines
        if "bin" in text:
            return {"reply": "🗑️ Done, took the tomatoes and eggs off your list.",
                    "actions": [{"op": "remove", "key": "tomato", "reason": "binned"},
                                {"op": "remove", "key": "eggs", "reason": "binned"}]}
        if "onion" in text:
            return {"reply": "1. Cut off the top\n2. Halve it\n3. Peel the skin back", "actions": []}
        return {"reply": "Sorry, I can only help with food and the kitchen.", "actions": []}

    monkeypatch.setattr(parsing, "ai_assistant", fake)
    out = send_text("The tomatoes I threw in the bin, and the eggs too")
    assert "took the tomatoes" in out[0]["body"]
    assert any(l.startswith("tomato |") for l in seen["lines"])
    with session_scope() as s:
        user = s.scalar(select(User).where(User.phone == PHONE))
        keys = {it.key for it in pantry.active_items(s, user)}
        assert "tomato" not in keys and "eggs" not in keys
    out = send_text("How do I peel an onion?")
    assert "Halve it" in out[0]["body"]
    out = send_text("How do I change my car's oil?")
    assert "only help with food" in out[0]["body"]
