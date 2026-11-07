"""Background jobs, run every minute:
- send tonight's dinner at each household's dinner time
- check in ('Cooked it / Didn't cook') a few hours after they tapped 'Let's cook it'
- trial ending reminders, pausing expired accounts
- monthly savings report on the 1st
"""
import asyncio
import logging
from datetime import datetime, timedelta

from sqlalchemy import select

from . import billing, clock, flows
from .config import settings
from .db import session_scope
from .models import Suggestion, User

log = logging.getLogger(__name__)


def _dinner_dt(user: User, now: datetime) -> datetime:
    h, m = map(int, (user.dinner_time or settings.default_dinner_time).split(":"))
    return now.replace(hour=h, minute=m, second=0, microsecond=0)


def tick() -> dict:
    """One pass over all households. Safe to run repeatedly."""
    now = clock.now()
    stats = {"dinners": 0, "checkins": 0, "reminders": 0, "paused": 0, "reports": 0}
    with session_scope() as s:
        users = list(s.scalars(select(User).where(User.stage == "active")))
        for user in users:
            try:
                _tick_user(s, user, now, stats)
            except Exception:  # noqa: BLE001
                log.exception("tick failed for user %s", user.id)
    return stats


def _tick_user(s, user: User, now: datetime, stats: dict) -> None:
    # --- billing ---
    if user.subscription_status == "trial" and user.trial_ends_at:
        if not user.trial_reminder_sent and now >= user.trial_ends_at - timedelta(days=2) and now.hour >= 9:
            flows.send_payment_prompt(s, user)
            user.trial_reminder_sent = True
            stats["reminders"] += 1
        if now >= user.trial_ends_at:
            user.subscription_status = "paused"
            stats["paused"] += 1
            return
    if user.subscription_status == "active" and user.paid_until and now > user.paid_until + timedelta(days=3):
        user.subscription_status = "past_due"
    if not billing.is_active(user, now):
        return

    # --- check-in after dinner (inside the 24h window opened by their 'Let's cook it' tap) ---
    accepted = s.scalars(select(Suggestion).where(
        Suggestion.user_id == user.id, Suggestion.status == "accepted", Suggestion.checkin_sent_at.is_(None)))
    for sg in accepted:
        due = sg.accepted_at + timedelta(hours=settings.checkin_after_hours)
        if now >= due and now.date() == sg.accepted_at.date() and now.hour < 22:
            flows.send_checkin(s, user, sg)
            stats["checkins"] += 1

    # --- morning after a planned occasion: "Did you braai last night?" ---
    plan = (user.pending or {}).get("plan")
    if plan and not plan.get("asked"):
        try:
            due = datetime.fromisoformat(plan["due"])
        except (KeyError, ValueError):
            due = None
        if due and now >= due and 8 <= now.hour < 20:
            flows.send_plan_checkin(s, user)
            stats["checkins"] += 1

    # --- tonight's dinner ---
    if now >= _dinner_dt(user, now) and now.hour < 21 and not flows.today_suggestions(s, user):
        if (user.pending or {}).get("dinner_after_checkin"):
            # we asked about last night first; if no answer within 45 min, send dinner anyway
            asked = s.scalar(select(Suggestion.checkin_sent_at).where(Suggestion.user_id == user.id)
                             .order_by(Suggestion.checkin_sent_at.desc().nullslast()))
            if asked and now - asked < timedelta(minutes=45):
                return
            flows._pop_pending(user, "dinner_after_checkin")
            flows.send_dinner(s, user, force=True)
        else:
            flows.send_dinner(s, user)
        stats["dinners"] += 1

    # --- monthly report (1st of the month, mid-morning) ---
    if now.day == 1 and 10 <= now.hour < 18:
        this_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        prev_start = (this_month - timedelta(days=1)).replace(day=1)
        label = prev_start.strftime("%Y-%m")
        if user.last_savings_report != label and user.created_at < this_month:
            flows.send_monthly_report(s, user, prev_start, this_month)
            user.last_savings_report = label
            stats["reports"] += 1


async def run_forever() -> None:
    while True:
        try:
            await asyncio.to_thread(tick)
        except Exception:  # noqa: BLE001
            log.exception("scheduler tick failed")
        await asyncio.sleep(60)
