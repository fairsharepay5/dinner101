"""Dinner 101 web server: WhatsApp webhook, PayFast ITN, website, admin, simulator.

Run:  uvicorn app.main:app --host 0.0.0.0 --port 8000
"""
from pathlib import Path
import asyncio
import logging
import urllib.parse
from collections import OrderedDict
from contextlib import asynccontextmanager
from datetime import timedelta

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, Response
from sqlalchemy import delete, func, select

from . import billing, clock, flows, pages, pantry, parsing, photos, recipes, scheduler
from . import whatsapp as wa
from .config import settings
from .db import init_db, session_scope
from .models import Habit, PantryItem, ParseFailure, SavingsEvent, Suggestion, Usage, User

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("dinner101")
USD_TO_ZAR = 18.5


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    task = asyncio.create_task(scheduler.run_forever()) if settings.run_scheduler else None
    yield
    if task:
        task.cancel()


app = FastAPI(title="Dinner 101", lifespan=lifespan)
_seen: OrderedDict[str, None] = OrderedDict()


def _first_time(message_id: str) -> bool:
    """Meta sometimes delivers the same webhook twice."""
    if not message_id:
        return True
    if message_id in _seen:
        return False
    _seen[message_id] = None
    while len(_seen) > 5000:
        _seen.popitem(last=False)
    return True


# ---------------------------------------------------------------- WhatsApp webhook

@app.get("/webhook")
def verify(request: Request):
    q = request.query_params
    if q.get("hub.mode") == "subscribe" and q.get("hub.verify_token") == settings.wa_verify_token:
        return PlainTextResponse(q.get("hub.challenge", ""))
    raise HTTPException(403, "Verification failed")


def _process(inbound: list[wa.Inbound]) -> None:
    for inb in inbound:
        try:
            with session_scope() as s:
                flows.handle(s, inb)
        except Exception:  # noqa: BLE001
            log.exception("Failed processing message from %s", inb.phone)


@app.post("/webhook")
async def webhook(request: Request, background: BackgroundTasks):
    body = await request.body()
    if not wa.verify_signature(body, request.headers.get("X-Hub-Signature-256")):
        raise HTTPException(401, "Bad signature")
    payload = await request.json()
    inbound = [m for m in wa.parse_webhook(payload) if _first_time(m.message_id)]
    if inbound:
        background.add_task(_process, inbound)   # answer Meta fast; slips take a few seconds
    return {"ok": True}


# ---------------------------------------------------------------- media

@app.get("/media/photos/{name}")
def photo(name: str):
    p = photos.PHOTO_DIR / name
    if "/" in name or not p.exists():
        raise HTTPException(404)
    return FileResponse(p, media_type="image/png")


@app.get("/media/placeholder")
def placeholder(name: str = "Dinner"):
    return Response(pages.plate_svg(name), media_type="image/svg+xml")


# ---------------------------------------------------------------- website

@app.get("/", response_class=HTMLResponse)
def home():
    return pages.landing()


@app.get("/privacy", response_class=HTMLResponse)
def privacy():
    return pages.privacy()


@app.get("/terms", response_class=HTMLResponse)
def terms():
    return pages.terms()


@app.get("/thanks", response_class=HTMLResponse)
def thanks():
    return pages.thanks()


@app.get("/subscribe", response_class=HTMLResponse)
def subscribe():
    return pages.subscribe_placeholder()


@app.get("/health")
def health():
    return {"ok": True, "whatsapp": settings.whatsapp_enabled, "ai": settings.ai_enabled, "now": clock.now().isoformat()}


# ---------------------------------------------------------------- PayFast

@app.post("/payfast/itn")
async def payfast_itn(request: Request):
    raw = (await request.body()).decode()
    form = urllib.parse.parse_qsl(raw, keep_blank_values=True)
    if not billing.verify_itn(form):
        raise HTTPException(400, "Invalid ITN")
    data = dict(form)
    phone = data.get("custom_str1", "")
    with session_scope() as s:
        user = s.scalar(select(User).where(User.phone == phone))
        if not user:
            raise HTTPException(404, "Unknown user")
        status = billing.apply_itn(user, data)
        if status == "COMPLETE" and flows.in_window(user):
            flows.say(s, user, "🎉 You're subscribed. Thanks! Dinner ideas keep coming as usual.")
    return PlainTextResponse("OK")


# ---------------------------------------------------------------- admin

def _check_admin(key: str) -> None:
    if not key or key != settings.admin_key or settings.admin_key == "change-me" and not settings.simulator_enabled:
        raise HTTPException(403, "Wrong admin key")


@app.get("/admin", response_class=HTMLResponse)
def admin(key: str = ""):
    _check_admin(key)
    since = clock.now() - timedelta(days=30)
    with session_scope() as s:
        users = list(s.scalars(select(User).order_by(User.id.desc()).limit(500)))
        rows = []
        for u in users:
            items = s.scalar(select(func.count()).select_from(PantryItem).where(PantryItem.user_id == u.id, PantryItem.active.is_(True))) or 0
            dinners = s.scalar(select(func.count()).select_from(Suggestion).where(Suggestion.user_id == u.id)) or 0
            cooked = s.scalar(select(func.count()).select_from(Suggestion).where(Suggestion.user_id == u.id, Suggestion.status == "cooked")) or 0
            saved = s.scalar(select(func.coalesce(func.sum(SavingsEvent.cents), 0)).where(SavingsEvent.user_id == u.id, SavingsEvent.kind == "rescued")) or 0
            cost = s.scalar(select(func.coalesce(func.sum(Usage.usd), 0)).where(Usage.user_id == u.id, Usage.at >= since)) or 0
            rows.append({"phone": u.phone, "name": u.name, "stage": u.stage, "status": u.subscription_status,
                         "items": items, "dinners": dinners, "cooked": cooked, "saved": saved / 100, "cost": cost})
        costs = {}
        for kind, n, usd in s.execute(select(Usage.kind, func.count(), func.coalesce(func.sum(Usage.usd), 0)).where(Usage.at >= since).group_by(Usage.kind)):
            costs[kind] = {"n": n, "usd": usd}
        fails = [{"at": f.at.strftime("%Y-%m-%d %H:%M"), "kind": f.kind, "raw": f.raw, "error": f.error}
                 for f in s.scalars(select(ParseFailure).order_by(ParseFailure.id.desc()).limit(30))]
        n_active = sum(1 for u in users if u.subscription_status == "active")
        n_trial = sum(1 for u in users if u.subscription_status == "trial")
        total_usd = sum(v["usd"] for v in costs.values())
        engaged = max(1, sum(1 for u in users if u.stage == "active"))
    data = {"users": rows, "costs": costs, "failures": fails, "n_users": len(users), "n_active": n_active, "n_trial": n_trial,
            "cost_per_user_zar": total_usd * USD_TO_ZAR / engaged, "revenue": n_active * settings.price_rands,
            "photos": sum(1 for r in recipes.RECIPES if photos.path_for(r).exists()), "recipes": len(recipes.RECIPES)}
    return pages.admin(data, key)


@app.get("/admin/whatsapp-setup", response_class=HTMLResponse)
def whatsapp_setup_form(key: str = ""):
    _check_admin(key)
    return pages._page("WhatsApp setup", f"""<h1>Connect the WhatsApp number</h1>
<p>Run this once after the server is online. It registers the number for the Cloud API
(status Pending → Connected) and subscribes the WhatsApp account to this app's webhook.</p>
<form method="post" action="/admin/whatsapp-setup?key={key}">
<p>Choose a 6-digit PIN (two-step verification for the number; write it down):<br>
<input name="pin" pattern="[0-9]{{6}}" required style="font-size:18px;padding:6px"></p>
<p>WhatsApp Business Account ID:<br><input name="waba_id" value="1674792774359283" style="font-size:16px;padding:6px;width:260px"></p>
<button class="btn" style="border:0">Register and subscribe</button></form>""")


@app.post("/admin/whatsapp-setup", response_class=HTMLResponse)
async def whatsapp_setup(request: Request, key: str = ""):
    _check_admin(key)
    import httpx
    form = dict(urllib.parse.parse_qsl((await request.body()).decode()))
    pin, waba = form.get("pin", ""), form.get("waba_id", "")
    base = f"https://graph.facebook.com/{settings.wa_api_version}"
    headers = {"Authorization": f"Bearer {settings.wa_token}"}
    out = []
    r = httpx.post(f"{base}/{settings.wa_phone_number_id}/register", headers=headers,
                   json={"messaging_product": "whatsapp", "pin": pin}, timeout=30)
    out.append(f"Register number: {r.status_code} {r.text[:300]}")
    r = httpx.post(f"{base}/{waba}/subscribed_apps", headers=headers, timeout=30)
    out.append(f"Subscribe account to app: {r.status_code} {r.text[:300]}")
    body = "".join(f"<pre style='white-space:pre-wrap'>{html_escape(o)}</pre>" for o in out)
    return pages._page("WhatsApp setup", f"<h1>Result</h1>{body}<p><a href='/admin?key={key}'>Back to admin</a></p>")


PROFILE_ABOUT = "Dinner ideas from what's already in your kitchen 🍽️ Smart meals. Less waste."
PROFILE_DESCRIPTION = (
    "Dinner 101 tells you what to cook tonight from what's already in your fridge and cupboard. "
    "Send a voice note of your kitchen or a photo of your till slip, and every afternoon you get one dinner idea "
    "made from what you have, using up what's about to go off first. Tap \"Cooked it\" and your kitchen list "
    "updates itself. Planning a braai or dinner for friends? Ask what you need and get a ready shopping list. "
    "Free for 7 days. Just say Hi to start.")
PROFILE_WEBSITE = "https://www.instagram.com/getdinner101"


@app.get("/admin/whatsapp-profile", response_class=HTMLResponse)
def whatsapp_profile_form(key: str = ""):
    _check_admin(key)
    esc = html_escape
    return pages._page("WhatsApp profile", f"""<h1>WhatsApp business profile</h1>
<p>Sets the profile picture (the Dinner 101 logo) and the business info people see when they tap the chat name.</p>
<img src="/brand/whatsapp_profile.jpg" alt="Dinner 101 logo" style="width:180px;height:180px;border-radius:90px;display:block;margin:12px 0">
<form method="post" action="/admin/whatsapp-profile?key={esc(key)}">
<p><label>About (max 139 characters)<br><input name="about" maxlength="139" value="{esc(PROFILE_ABOUT)}" style="width:100%;font-size:15px;padding:6px"></label></p>
<p><label>Description (max 512 characters)<br><textarea name="description" maxlength="512" rows="7" style="width:100%;font-size:15px;padding:6px">{esc(PROFILE_DESCRIPTION)}</textarea></label></p>
<p><label>Website<br><input name="website" value="{esc(PROFILE_WEBSITE)}" style="width:100%;font-size:15px;padding:6px"></label></p>
<button class="btn" style="border:0">Update WhatsApp profile</button></form>""")


@app.get("/brand/{name}")
def brand_file(name: str):
    from fastapi.responses import FileResponse
    allowed = {"whatsapp_profile.jpg", "logo.png", "launch-poster.png"}
    if name not in allowed:
        raise HTTPException(404)
    return FileResponse(Path(__file__).parent / "data" / "brand" / name)


@app.post("/admin/whatsapp-profile", response_class=HTMLResponse)
async def whatsapp_profile(request: Request, key: str = ""):
    _check_admin(key)
    import httpx
    form = dict(urllib.parse.parse_qsl((await request.body()).decode()))
    base = f"https://graph.facebook.com/{settings.wa_api_version}"
    token = settings.wa_token
    img = (Path(__file__).parent / "data" / "brand" / "whatsapp_profile.jpg").read_bytes()
    out = []
    # 1) upload the picture with Meta's resumable upload API -> a handle
    r = httpx.post(f"{base}/{settings.wa_app_id}/uploads",
                   params={"file_length": len(img), "file_type": "image/jpeg", "access_token": token}, timeout=30)
    out.append(f"Start upload: {r.status_code} {r.text[:200]}")
    handle = None
    if r.status_code == 200 and r.json().get("id"):
        r2 = httpx.post(f"{base}/{r.json()['id']}", content=img,
                        headers={"Authorization": f"OAuth {token}", "file_offset": "0"}, timeout=60)
        out.append(f"Upload picture: {r2.status_code} {r2.text[:200]}")
        if r2.status_code == 200:
            handle = r2.json().get("h")
    # 2) set the profile
    body = {"messaging_product": "whatsapp", "about": form.get("about", "")[:139],
            "description": form.get("description", "")[:512], "vertical": "OTHER"}
    if form.get("website"):
        body["websites"] = [form["website"]]
    if handle:
        body["profile_picture_handle"] = handle
    r3 = httpx.post(f"{base}/{settings.wa_phone_number_id}/whatsapp_business_profile",
                    headers={"Authorization": f"Bearer {token}"}, json=body, timeout=30)
    out.append(f"Update profile: {r3.status_code} {r3.text[:300]}")
    res = "".join(f"<pre style='white-space:pre-wrap'>{html_escape(o)}</pre>" for o in out)
    return pages._page("WhatsApp profile", f"<h1>Result</h1>{res}<p><a href='/admin?key={html_escape(key)}'>Back to admin</a></p>")


def html_escape(s: str) -> str:
    import html
    return html.escape(s)


@app.post("/admin/generate-photos", response_class=HTMLResponse)
def gen_photos(background: BackgroundTasks, key: str = ""):
    _check_admin(key)
    background.add_task(photos.generate_all)
    return f'<p>Generating photos in the background. <a href="/admin?key={key}">Back to admin</a></p>'


# ---------------------------------------------------------------- simulator

def _sim_guard(phone: str) -> None:
    if not settings.simulator_enabled:
        raise HTTPException(404)
    if not phone.startswith("sim"):
        raise HTTPException(400, "Simulator numbers must start with 'sim'")


def _sim_messages(phone: str) -> list[dict]:
    out = []
    for m in wa.sim_outbox.take(phone):
        m = dict(m)
        if m.get("type") == "buttons" and not m.get("image") and (m.get("body") or "").startswith("*Tonight:"):
            name = m["body"].split("\n")[0].replace("*Tonight:", "").strip(" *")
            m["placeholder"] = "/media/placeholder?name=" + urllib.parse.quote(name)
        out.append(m)
    return out


@app.get("/simulator", response_class=HTMLResponse)
def simulator():
    if not settings.simulator_enabled:
        raise HTTPException(404)
    return pages.SIMULATOR


@app.post("/sim/send")
async def sim_send(request: Request):
    body = await request.json()
    phone = body.get("phone", "sim-1")
    _sim_guard(phone)
    kind = body.get("kind")
    with session_scope() as s:
        if kind == "slip":
            user, _ = flows.get_user(s, phone)
            user.last_inbound_at = clock.now()
            if user.stage == "new":
                flows.welcome(s, user)
            items = parsing.parse_slip_text(body.get("text", ""))
            flows.on_slip_items(s, user, items)
        elif kind == "button":
            flows.handle(s, wa.Inbound(phone=phone, kind="button", button_id=body.get("button_id", "")))
        else:
            flows.handle(s, wa.Inbound(phone=phone, kind="text", text=body.get("text", ""), name="Simulator"))
    return {"messages": _sim_messages(phone)}


@app.post("/sim/clock")
async def sim_clock(request: Request):
    body = await request.json()
    phone = body.get("phone", "sim-1")
    _sim_guard(phone)
    to = body.get("to")
    now = clock.now()
    with session_scope() as s:
        user = s.scalar(select(User).where(User.phone == phone))
        dt = (user.dinner_time if user else settings.default_dinner_time)
    if to == "dinner":
        h, m = map(int, dt.split(":"))
        target = now.replace(hour=h, minute=m, second=0, microsecond=0) + timedelta(minutes=1)
        if target <= now:
            target += timedelta(days=1)
        clock.set_to(target)
    elif to == "checkin":
        clock.advance(hours=3)
    elif to == "nextday":
        clock.set_to((now + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0))
    elif to == "trial":
        clock.advance(days=13)
    scheduler.tick()
    return {"now": clock.now().strftime("%a %d %b %H:%M"), "messages": _sim_messages(phone)}


@app.post("/sim/reset")
async def sim_reset(request: Request):
    body = await request.json()
    phone = body.get("phone", "sim-1")
    _sim_guard(phone)
    with session_scope() as s:
        user = s.scalar(select(User).where(User.phone == phone))
        if user:
            for model in (PantryItem, Habit, Suggestion, SavingsEvent, Usage, ParseFailure):
                s.execute(delete(model).where(model.user_id == user.id))
            s.delete(user)
    wa.sim_outbox.take(phone)
    clock.reset()
    return {"ok": True}


@app.get("/sim/state")
def sim_state(phone: str = "sim-1"):
    _sim_guard(phone)
    with session_scope() as s:
        user = s.scalar(select(User).where(User.phone == phone))
        if not user:
            return {"now": clock.now().strftime("%a %d %b %H:%M"), "pantry": "(new household)", "dinner_time": None}
        lines = []
        for it in sorted(pantry.active_items(s, user), key=lambda i: (i.storage, i.name)):
            st = pantry.status(it)
            exp = it.expires_at.strftime("%d %b %y") if it.expires_at else "never"
            lines.append(f"{st:8} {it.storage:8} {pantry.item_line(it)[:24]:24} {exp:9} {pantry.confidence(it):.2f}")
        return {"now": clock.now().strftime("%a %d %b %H:%M"), "dinner_time": user.dinner_time,
                "status": user.subscription_status, "pantry": ("status   place    item                     expires   sure\n" + "\n".join(lines)) if lines else "(empty)"}
