# Dinner 101

Tells you what's for dinner tonight, on WhatsApp, using what you already have at home, and shows you how much money it saved you.

The user only ever sees WhatsApp:
1. **Setup:** one voice note walking through the kitchen (any order). The bot only asks fridge/frozen for meat (and counter/freezer for bread).
2. **Shopping:** a slip photo or a voice note ("bought milk and bread at the Spar").
3. **Every afternoon:** one dinner with a photo and buttons **Let's cook it / Something else / Show recipe**.
4. **After dinner:** **Cooked it / Didn't cook**. Cooked deducts the ingredients; didn't cook asks **Made something else / Ate out or skipped**.
5. **Monthly:** "Dinner 101 saved you R___ this month."

Everything else runs in the background.

---

## Try it now (no accounts needed)

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open **http://localhost:8000/simulator**. It's a fake WhatsApp chat wired to the real bot logic:
- Type a message as if it were a voice-note transcript, e.g. `ses eiers, 500g maalvleis, pasta, tamaties, chicken fillets, kaas`
- Paste slip text and press **Send slip**
- Use the clock buttons to jump to dinner time, 3 hours later (check-in) or the next day
- The right-hand panel shows the background kitchen list: status, storage, expiry and confidence

Other pages: `/` landing page · `/privacy` · `/terms` · `/admin?key=ADMIN_KEY`

Run the tests: `python -m pytest -q`

Without API keys the bot uses a built-in rule-based reader (English and Afrikaans). With keys, Claude reads real slip photos and messages, and voice notes are transcribed.

---

## How it's built

| File | What it does |
|---|---|
| `app/flows.py` | Every WhatsApp conversation: onboarding, slips, voice notes, dinner, buttons, check-ins, billing messages |
| `app/pantry.py` | Kitchen engine: shelf-life clocks, confidence, fresh / use soon / gone, deductions, learning habits |
| `app/catalogue.py` | ~90 SA ingredients: English and Afrikaans words, where they're kept, shelf life, rough prices |
| `app/parsing.py` | Slip and voice-note understanding: Claude when a key is set, offline parser otherwise |
| `app/recipes.py` + `data/recipes.json` | 30 SA family dinners and the picker that chooses one meal |
| `app/scheduler.py` | Runs every minute: dinner at each household's time, check-ins, trial reminders, monthly report |
| `app/whatsapp.py` | WhatsApp Cloud API: send buttons/images/templates, read webhooks, download media |
| `app/photos.py` | One AI photo per recipe, made once and reused for everyone |
| `app/billing.py` | 14-day free trial, PayFast monthly subscription link and payment notifications |
| `app/main.py` / `app/pages.py` | Web server: webhook, PayFast, landing/privacy/terms, admin, simulator |

**Background rules built in**
- Staples (salt, oil, spices…) are assumed present. Long-life items are counted. Perishables run on shelf-life clocks.
- Items from the first voice note start part-way through their clock, because we don't know when they were bought.
- Buying something again means the old stock is probably low (milk and bread: learns how often you buy them).
- Binning something early shortens that item's clock for that household.
- Before cooking, the bot asks "still got the chicken?" only if it's unsure about the main ingredient.
- The picker favours meals that use food about to go off, avoids repeats, learns likes from "Cooked it" and "Something else", and avoids long recipes on weekdays.
- Dinner time adjusts to when the household actually taps "Let's cook it".
- If last night's check-in went unanswered, today's first message asks about it, and the dinner follows.
- Text commands: `list`, `dinner`, `send dinner at 17:30`, `help`, `cancel`, `delete my data`.

---

## What I need from you (to go live)

### 1. WhatsApp Business Platform (Meta)
- A **Meta Business account**, verified with your company (Pips to Profit (Pty) Ltd).
- A **phone number for Dinner 101** that is **not** already on the WhatsApp app (a new SIM works).
- In Meta for Developers: create an app → add WhatsApp → note the **Phone number ID**, **App secret**, and create a **permanent System User token**.
- Webhook: URL `https://YOUR-DOMAIN/webhook`, verify token = `WHATSAPP_VERIFY_TOKEN`, subscribe to **messages**.
- **Create these message templates** (needed for anything the bot sends first, outside the 24-hour reply window):

| Name | Category | Header | Body | Quick-reply buttons |
|---|---|---|---|---|
| `dinner_tonight` | Utility | Image | `Tonight: {{1}} ({{2}} min). {{3}}` | Let's cook it · Something else · Show recipe |
| `dinner_checkin` | Utility | none | `Quick one: did you cook the {{1}}?` | Cooked it · Didn't cook |
| `account_notice` | Utility | none | `Dinner 101 update: {{1}}` | none |

⚠️ **Cost risk to watch:** Meta decides the category. If it classes the dinner message as **Marketing** instead of Utility, each one costs about 5× more. Submit it as Utility; if Meta re-classifies it, tell me and we'll reword it. `account_notice` might also be rejected for being too general. If so, we split it into separate templates (trial ending, monthly report, low stock).

### 2. AI keys
- **Anthropic API key** (reads slip photos and understands voice notes and messages): `ANTHROPIC_API_KEY`
- **OpenAI API key** (voice-note transcription and the one-off recipe photos): `OPENAI_API_KEY`
- After adding the OpenAI key, open `/admin` and press **Generate missing recipe photos** (30 images, a once-off cost).

### 3. PayFast
- A PayFast merchant account with **subscriptions/recurring billing** enabled, a **passphrase** set, and the merchant ID and key.
- Test first with `PAYFAST_SANDBOX=1`, then switch to `0`.

### 4. Hosting and domain
- Any host that runs Docker with HTTPS and a domain (e.g. dinner101.co.za). Meta and PayFast both need a public HTTPS address.
- Set `PUBLIC_BASE_URL`, `ADMIN_KEY` (long and random), and `SIMULATOR_ENABLED=0`.

### 5. Legal
- `/privacy` and `/terms` are drafts. Add your contact email and have them checked (POPIA).

---

## Known gaps / next steps
- **Cancelling at PayFast:** "cancel" stops dinner messages and marks the account cancelled, but the PayFast subscription must still be cancelled (manually in PayFast for now; the automatic API call comes next).
- **Several phones per household** (shared kitchen list): not built yet.
- **Real-slip tuning:** the AI reading is tested with mock replies. It needs 20–30 real slips from Checkers, Pick n Pay, Woolworths and Spar to tune.
- **Recipes:** 30 to start; grow the list in `app/data/recipes.json` (keys must match `catalogue.py`).
- **Database:** SQLite is fine for the pilot; move to Postgres before a few hundred households.
