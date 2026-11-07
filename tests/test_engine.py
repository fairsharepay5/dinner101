"""Pantry engine, dinner picker, parsers, webhook and billing helpers."""
from datetime import timedelta

from app import billing, clock, pantry, parsing, recipes
from app import whatsapp as wa
from app.db import session_scope
from app.models import User
from app.pantry import ParsedItem


def _user(s):
    u = User(phone="sim-1", stage="active", dinner_time="16:30", pending={})
    s.add(u)
    s.flush()
    return u


def test_status_moves_fresh_use_soon_gone():
    with session_scope() as s:
        u = _user(s)
        res = pantry.add_items(s, u, [ParsedItem(name="tomatoes", qty=4)], "slip")
        it = res.added[0]
        assert pantry.status(it) == "fresh"
        assert pantry.status(it, clock.now() + timedelta(days=5)) == "use_soon"
        assert pantry.status(it, clock.now() + timedelta(days=9)) == "gone"


def test_setup_items_start_part_way_and_staples_assumed():
    with session_scope() as s:
        u = _user(s)
        it = pantry.add_items(s, u, [ParsedItem(name="lettuce")], "setup").added[0]
        assert (it.expires_at - clock.now()).days < 5
        st = pantry.stock(s, u)
        assert "salt" in st and "cooking_oil" in st


def test_meat_storage_question_and_freezer_extends_life():
    with session_scope() as s:
        u = _user(s)
        res = pantry.add_items(s, u, [ParsedItem(name="mince", qty=500, unit="g")], "voice")
        assert res.ask_storage
        it = res.ask_storage[0]
        short = it.expires_at
        pantry.set_storage(s, u, it, "freezer")
        assert it.expires_at - short > timedelta(days=60)


def test_said_frozen_means_no_question():
    with session_scope() as s:
        u = _user(s)
        items = parsing.understand_offline("500g mince in the freezer").actions
        res = pantry.add_items(s, u, [a.item for a in items], "voice")
        assert not res.ask_storage and res.added[0].storage == "freezer"


def test_picker_prefers_meal_that_rescues_food():
    with session_scope() as s:
        u = _user(s)
        pantry.add_items(s, u, [ParsedItem(name=n, qty=q, unit=un, storage=st) for n, q, un, st in [
            ("pasta", 1000, "g", None), ("mince", 500, "g", "freezer"), ("tinned tomatoes", 2, None, None),
            ("onions", 4, None, None), ("chicken fillets", 500, "g", "fridge"), ("tomatoes", 4, None, None),
            ("cream", 250, "ml", None)]], "slip")
        clock.advance(days=1, hours=12)   # chicken fillets now 'use soon'
        best, _ = recipes.pick(s, u)
        assert best.recipe["id"] == "tomato_chicken_pasta"
        assert "chicken_fillet" in best.use_soon


def test_deduct_counts_rescued_money():
    with session_scope() as s:
        u = _user(s)
        pantry.add_items(s, u, [ParsedItem(name="chicken fillets", qty=500, unit="g", storage="fridge", price_cents=8999)], "slip")
        clock.advance(days=1, hours=12)
        cents = pantry.deduct(s, u, [("chicken_fillet", 500)])
        assert cents == 8999
        assert "chicken_fillet" not in pantry.stock(s, u)


def test_binning_early_shortens_future_shelf_life():
    with session_scope() as s:
        u = _user(s)
        pantry.add_items(s, u, [ParsedItem(name="coriander")], "slip")
        pantry.remove_key(s, u, "coriander", "binned")
        assert pantry.habit(s, u, "coriander").shelf_factor < 1


def test_afrikaans_and_english_mixed():
    u = parsing.understand_offline("ses eiers, twee blikke tamaties, 'n bietjie kaas en 1kg boerewors")
    keys = [(a.item.key, a.item.qty) for a in u.actions]
    assert ("eggs", 6) in keys and ("canned_tomatoes", 2) in keys and ("boerewors", 1.0) in keys
    assert ("cheese", None) in keys


def test_ai_reply_is_mapped(monkeypatch):
    monkeypatch.setattr(parsing, "_ask_claude", lambda *a, **k: {
        "actions": [{"op": "add", "name": "tomatoes", "key": "tomato", "qty": 10, "unit": "count"},
                    {"op": "remove", "key": "milk", "reason": "finished"},
                    {"op": "add", "name": "Lemongrass", "key": None, "category": "perishable", "shelf_days": 10}],
        "other": None})
    u = parsing.ai_understand("anything")
    assert [a.op for a in u.actions] == ["add", "remove", "add"]
    assert u.actions[0].item.key == "tomato" and u.actions[2].item.key is None


def test_webhook_payload_parsing():
    payload = {"entry": [{"changes": [{"value": {
        "contacts": [{"wa_id": "27821234567", "profile": {"name": "Andre"}}],
        "messages": [
            {"from": "27821234567", "id": "m1", "type": "text", "text": {"body": "hi"}},
            {"from": "27821234567", "id": "m2", "type": "audio", "audio": {"id": "A1", "mime_type": "audio/ogg; codecs=opus"}},
            {"from": "27821234567", "id": "m3", "type": "image", "image": {"id": "I1", "mime_type": "image/jpeg"}},
            {"from": "27821234567", "id": "m4", "type": "interactive", "interactive": {"type": "button_reply", "button_reply": {"id": "cook:5", "title": "Let's cook it"}}},
            {"from": "27821234567", "id": "m5", "type": "button", "button": {"payload": "cooked:5", "text": "Cooked it"}},
        ]}}]}]}
    msgs = wa.parse_webhook(payload)
    assert [m.kind for m in msgs] == ["text", "audio", "image", "button", "button"]
    assert msgs[0].name == "Andre" and msgs[3].button_id == "cook:5" and msgs[4].button_id == "cooked:5"


def test_payfast_signature_stable(monkeypatch):
    monkeypatch.setattr(billing.settings, "payfast_passphrase", "secret")
    params = [("merchant_id", "10000100"), ("amount", "39.00"), ("item_name", "Dinner 101 monthly")]
    sig = billing._signature(params)
    assert len(sig) == 32 and sig == billing._signature(params)


def test_only_amounts_the_user_said_are_shown():
    with session_scope() as s:
        u = _user(s)
        items = [a.item for a in parsing.understand(
            "4 chicken fillets, cheddar cheese, onions, tomatoes, mushrooms, 500g pasta").actions if a.item]
        res = pantry.add_items(s, u, items, "setup")
        lines = {it.key: pantry.item_line(it) for it in res.added}
        assert lines["chicken_fillet"] == "Chicken fillets ×4"
        assert lines["cheese"] == "Cheddar cheese"
        assert lines["onion"] == "Onions"
        assert lines["tomato"] == "Tomatoes"
        assert lines["mushrooms"] == "Mushrooms"
        assert lines["pasta"] == "Pasta 500 g"
        # behind the scenes we still track an estimate (4 fillets ~ 600 g) for recipes
        chicken = next(it for it in res.added if it.key == "chicken_fillet")
        assert chicken.qty == 600
        text = pantry.list_text(s, u)
        assert "Chicken fillets ×4" in text and "400 g" not in text and "250 g" not in text
