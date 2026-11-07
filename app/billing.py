"""Free trial + monthly subscription through PayFast.

Flow: trial starts on first message -> payment link sent in WhatsApp 2 days before the
trial ends -> user pays on PayFast's page -> PayFast calls /payfast/itn -> active.
PayFast bills monthly and calls the ITN again each month.

NOTE: test this against the PayFast sandbox before going live.
"""
import hashlib
import logging
import urllib.parse
from datetime import datetime, timedelta

import httpx

from . import clock
from .config import settings
from .models import User

log = logging.getLogger(__name__)


def start_trial(user: User) -> None:
    user.subscription_status = "trial"
    user.trial_ends_at = clock.now() + timedelta(days=settings.trial_days)


def is_active(user: User, now: datetime | None = None) -> bool:
    now = now or clock.now()
    if user.subscription_status == "trial":
        return user.trial_ends_at is None or now < user.trial_ends_at
    if user.subscription_status == "active":
        return user.paid_until is None or now < user.paid_until + timedelta(days=3)
    return False


def _host() -> str:
    return "https://sandbox.payfast.co.za" if settings.payfast_sandbox else "https://www.payfast.co.za"


def _signature(params: list[tuple[str, str]]) -> str:
    pairs = [f"{k}={urllib.parse.quote_plus(str(v).strip())}" for k, v in params if str(v).strip() != ""]
    s = "&".join(pairs)
    if settings.payfast_passphrase:
        s += f"&passphrase={urllib.parse.quote_plus(settings.payfast_passphrase.strip())}"
    return hashlib.md5(s.encode()).hexdigest()


def payment_link(user: User) -> str:
    """PayFast subscription checkout link for this user (monthly, until cancelled)."""
    if not settings.payfast_merchant_id:
        return f"{settings.public_base_url.rstrip('/')}/subscribe?u={user.id}"
    base = settings.public_base_url.rstrip("/")
    amount = f"{settings.price_rands:.2f}"
    start = max(clock.now(), user.trial_ends_at or clock.now()).date().isoformat()
    params = [
        ("merchant_id", settings.payfast_merchant_id),
        ("merchant_key", settings.payfast_merchant_key),
        ("return_url", f"{base}/thanks"),
        ("cancel_url", f"{base}/"),
        ("notify_url", f"{base}/payfast/itn"),
        ("m_payment_id", f"u{user.id}-{int(clock.now().timestamp())}"),
        ("amount", amount),
        ("item_name", "Dinner 101 monthly"),
        ("custom_str1", user.phone),
        ("subscription_type", "1"),
        ("billing_date", start),
        ("recurring_amount", amount),
        ("frequency", "3"),
        ("cycles", "0"),
    ]
    params.append(("signature", _signature(params)))
    return f"{_host()}/eng/process?" + urllib.parse.urlencode(params)


def verify_itn(form: list[tuple[str, str]]) -> bool:
    """Check the ITN signature, then confirm with PayFast's server."""
    received = dict(form).get("signature", "")
    params = [(k, v) for k, v in form if k != "signature"]
    if _signature(params) != received:
        log.warning("PayFast ITN signature mismatch")
        return False
    try:
        body = urllib.parse.urlencode(params)
        r = httpx.post(f"{_host()}/eng/query/validate", content=body,
                       headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=20)
        return r.text.strip() == "VALID"
    except Exception as e:  # noqa: BLE001
        log.error("PayFast validate call failed: %s", e)
        return False


def apply_itn(user: User, form: dict) -> str:
    status = form.get("payment_status", "")
    if status == "COMPLETE":
        user.subscription_status = "active"
        user.paid_until = clock.now() + timedelta(days=31)
        if form.get("token"):
            user.payfast_token = form["token"]
    elif status == "CANCELLED":
        user.subscription_status = "cancelled"
    elif status == "FAILED":
        user.subscription_status = "past_due"
    return status
