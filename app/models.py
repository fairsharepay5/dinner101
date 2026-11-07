from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from . import clock
from .db import Base


class User(Base):
    """One household = one WhatsApp number (others in the house can be linked later)."""
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    phone: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[Optional[str]] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=clock.now)
    # onboarding: new -> setup (waiting for kitchen voice note) -> active
    stage: Mapped[str] = mapped_column(String(20), default="new")
    dinner_time: Mapped[str] = mapped_column(String(5), default="16:30")
    last_inbound_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    # small state machine for "what are we waiting for" (e.g. storage questions queue)
    pending: Mapped[dict] = mapped_column(JSON, default=dict)
    # billing
    subscription_status: Mapped[str] = mapped_column(String(20), default="trial")  # trial|active|past_due|cancelled|paused
    trial_ends_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    paid_until: Mapped[Optional[datetime]] = mapped_column(DateTime)
    payfast_token: Mapped[Optional[str]] = mapped_column(String(64))
    trial_reminder_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    last_savings_report: Mapped[Optional[str]] = mapped_column(String(7))  # "2026-11"

    items: Mapped[list["PantryItem"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class PantryItem(Base):
    __tablename__ = "pantry_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    key: Mapped[str] = mapped_column(String(60), index=True)         # canonical ingredient key, e.g. "tomato"
    name: Mapped[str] = mapped_column(String(120))                   # what we show, e.g. "Tomatoes"
    qty: Mapped[float] = mapped_column(Float, default=1)
    unit: Mapped[str] = mapped_column(String(12), default="count")   # count|g|ml|pack|portion
    category: Mapped[str] = mapped_column(String(12))                # staple|long_life|perishable
    storage: Mapped[str] = mapped_column(String(12))                 # fridge|freezer|cupboard|counter
    added_at: Mapped[datetime] = mapped_column(DateTime, default=clock.now)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime)  # None = doesn't really expire
    confidence: Mapped[float] = mapped_column(Float, default=1.0)     # how sure we are it's still there
    source: Mapped[str] = mapped_column(String(12))                  # setup|slip|voice|correction
    unit_cents: Mapped[Optional[float]] = mapped_column(Float)        # price per unit (from slip, else catalogue)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    removed_reason: Mapped[Optional[str]] = mapped_column(String(20))  # used|binned|finished|replaced
    removed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    user: Mapped[User] = relationship(back_populates="items")


class Habit(Base):
    """What we learn per household per ingredient."""
    __tablename__ = "habits"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    key: Mapped[str] = mapped_column(String(60))
    shelf_factor: Mapped[float] = mapped_column(Float, default=1.0)   # <1 if they keep binning it early
    repurchase_days: Mapped[Optional[float]] = mapped_column(Float)   # how often they buy it (milk, bread)
    last_bought_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    likes: Mapped[int] = mapped_column(Integer, default=0)


class Suggestion(Base):
    __tablename__ = "suggestions"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    recipe_id: Mapped[str] = mapped_column(String(60))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=clock.now)
    # sent|accepted|rejected|cooked|not_cooked|other_meal|skipped
    status: Mapped[str] = mapped_column(String(20), default="sent")
    accepted_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    checkin_sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    leftovers: Mapped[Optional[bool]] = mapped_column(Boolean)


class SavingsEvent(Base):
    """Value of food rescued (used while 'use soon') or wasted (binned)."""
    __tablename__ = "savings_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    at: Mapped[datetime] = mapped_column(DateTime, default=clock.now)
    kind: Mapped[str] = mapped_column(String(10))  # rescued|wasted
    key: Mapped[str] = mapped_column(String(60))
    cents: Mapped[int] = mapped_column(Integer)


class Usage(Base):
    """Cost tracking: every AI call and WhatsApp message we pay for."""
    __tablename__ = "usage"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), index=True)
    at: Mapped[datetime] = mapped_column(DateTime, default=clock.now)
    kind: Mapped[str] = mapped_column(String(30))   # ai_parse|ai_transcribe|ai_image|wa_template|wa_service
    usd: Mapped[float] = mapped_column(Float, default=0)
    detail: Mapped[Optional[str]] = mapped_column(Text)


class ParseFailure(Base):
    """Slips/voice notes we couldn't read, for review in the admin page."""
    __tablename__ = "parse_failures"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    at: Mapped[datetime] = mapped_column(DateTime, default=clock.now)
    kind: Mapped[str] = mapped_column(String(10))   # slip|voice|text
    raw: Mapped[Optional[str]] = mapped_column(Text)
    error: Mapped[Optional[str]] = mapped_column(Text)


class ProductAlias(Base):
    """SA slip dictionary that grows over time: 'PNP TOM LOOSE' -> tomato."""
    __tablename__ = "product_aliases"
    id: Mapped[int] = mapped_column(primary_key=True)
    raw: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    key: Mapped[str] = mapped_column(String(60))
    hits: Mapped[int] = mapped_column(Integer, default=1)
