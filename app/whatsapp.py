"""Sending and receiving WhatsApp messages (Meta WhatsApp Cloud API).

Outgoing messages are plain dicts so the same flow code can drive:
- the real WhatsApp Cloud API (CloudOutbox)
- the browser simulator and tests (MemoryOutbox)

Message shapes:
  {"type": "text", "body": str}
  {"type": "buttons", "body": str, "buttons": [(id, title), ...], "image": url|None, "footer": str|None}
  {"type": "template", "name": str, "params": [str], "image": url|None, "buttons": [id, ...], "fallback": <msg>}
"""
import hashlib
import hmac
import logging
import os
from collections import defaultdict
from dataclasses import dataclass

import httpx

from .config import settings

log = logging.getLogger(__name__)

# Meta per-message prices for South Africa (USD, excl. VAT). Update if Meta changes them.
PRICE_TEMPLATE_UTILITY = float(os.environ.get("WA_UTILITY_USD", "0.0076"))
PRICE_SERVICE = float(os.environ.get("WA_SERVICE_USD", "0.0076"))  # replies inside 24h window (charged from Oct 2026)


@dataclass
class Inbound:
    phone: str
    kind: str                 # text | image | audio | button | other
    text: str = ""
    media_id: str = ""
    mime: str = ""
    button_id: str = ""
    name: str = ""
    message_id: str = ""


def text(body: str) -> dict:
    return {"type": "text", "body": body}


def buttons(body: str, btns: list[tuple[str, str]], image: str | None = None, footer: str | None = None) -> dict:
    assert 1 <= len(btns) <= 3, "WhatsApp allows 1-3 reply buttons"
    return {"type": "buttons", "body": body, "buttons": [(i, t[:20]) for i, t in btns], "image": image, "footer": footer}


def template(name: str, params: list[str], fallback: dict, image: str | None = None, button_ids: list[str] | None = None) -> dict:
    return {"type": "template", "name": name, "params": params, "image": image, "buttons": button_ids or [], "fallback": fallback}


# ---------------------------------------------------------------- outboxes

class MemoryOutbox:
    """Keeps messages in memory - used by tests and the simulator."""

    def __init__(self):
        self.sent: dict[str, list[dict]] = defaultdict(list)

    def send(self, phone: str, msg: dict) -> None:
        if msg["type"] == "template":
            shown = dict(msg["fallback"])
            shown["via_template"] = msg["name"]
            self.sent[phone].append(shown)
        else:
            self.sent[phone].append(msg)

    def take(self, phone: str) -> list[dict]:
        msgs = self.sent.pop(phone, [])
        return msgs


class CloudOutbox:
    """Real WhatsApp Cloud API."""

    def __init__(self):
        self.base = f"https://graph.facebook.com/{settings.wa_api_version}"
        self.headers = {"Authorization": f"Bearer {settings.wa_token}"}

    def _post(self, payload: dict) -> None:
        url = f"{self.base}/{settings.wa_phone_number_id}/messages"
        r = httpx.post(url, json={"messaging_product": "whatsapp", **payload}, headers=self.headers, timeout=30)
        if r.status_code >= 300:
            log.error("WhatsApp send failed %s: %s", r.status_code, r.text[:500])
            r.raise_for_status()

    def send(self, phone: str, msg: dict) -> None:
        t = msg["type"]
        if t == "text":
            self._post({"to": phone, "type": "text", "text": {"body": msg["body"][:4096]}})
        elif t == "buttons":
            inter = {
                "type": "button",
                "body": {"text": msg["body"][:1024]},
                "action": {"buttons": [{"type": "reply", "reply": {"id": i, "title": title}} for i, title in msg["buttons"]]},
            }
            if msg.get("image"):
                inter["header"] = {"type": "image", "image": {"link": msg["image"]}}
            if msg.get("footer"):
                inter["footer"] = {"text": msg["footer"][:60]}
            self._post({"to": phone, "type": "interactive", "interactive": inter})
        elif t == "template":
            comps = []
            if msg.get("image"):
                comps.append({"type": "header", "parameters": [{"type": "image", "image": {"link": msg["image"]}}]})
            if msg.get("params"):
                comps.append({"type": "body", "parameters": [{"type": "text", "text": p} for p in msg["params"]]})
            for idx, bid in enumerate(msg.get("buttons", [])):
                comps.append({"type": "button", "sub_type": "quick_reply", "index": str(idx), "parameters": [{"type": "payload", "payload": bid}]})
            self._post({"to": phone, "type": "template", "template": {"name": msg["name"], "language": {"code": "en"}, "components": comps}})


outbox = CloudOutbox() if settings.whatsapp_enabled else MemoryOutbox()
sim_outbox = MemoryOutbox()   # simulator households ("sim-..." numbers) never touch real WhatsApp


def use_outbox(o) -> None:
    global outbox
    outbox = o


def send(phone: str, msg: dict) -> None:
    if phone.startswith("sim"):
        sim_outbox.send(phone, msg)
    else:
        outbox.send(phone, msg)


# ---------------------------------------------------------------- inbound

def verify_signature(body: bytes, signature_header: str | None) -> bool:
    if not settings.wa_app_secret:
        return True  # not configured yet (development)
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(settings.wa_app_secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header[7:])


def parse_webhook(payload: dict) -> list[Inbound]:
    out = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            names = {c.get("wa_id"): c.get("profile", {}).get("name", "") for c in value.get("contacts", [])}
            for m in value.get("messages", []):
                phone = m.get("from", "")
                base = dict(phone=phone, name=names.get(phone, ""), message_id=m.get("id", ""))
                t = m.get("type")
                if t == "text":
                    out.append(Inbound(kind="text", text=m["text"]["body"], **base))
                elif t == "image":
                    out.append(Inbound(kind="image", media_id=m["image"]["id"], mime=m["image"].get("mime_type", "image/jpeg"),
                                       text=m["image"].get("caption", ""), **base))
                elif t == "document" and m["document"].get("mime_type", "").startswith("image/"):
                    out.append(Inbound(kind="image", media_id=m["document"]["id"], mime=m["document"]["mime_type"], **base))
                elif t == "audio":
                    out.append(Inbound(kind="audio", media_id=m["audio"]["id"], mime=m["audio"].get("mime_type", "audio/ogg"), **base))
                elif t == "interactive":
                    i = m["interactive"]
                    rep = i.get("button_reply") or i.get("list_reply") or {}
                    out.append(Inbound(kind="button", button_id=rep.get("id", ""), text=rep.get("title", ""), **base))
                elif t == "button":  # quick reply on a template
                    out.append(Inbound(kind="button", button_id=m["button"].get("payload", ""), text=m["button"].get("text", ""), **base))
                else:
                    out.append(Inbound(kind="other", **base))
    return out


def download_media(media_id: str) -> tuple[bytes, str]:
    base = f"https://graph.facebook.com/{settings.wa_api_version}"
    headers = {"Authorization": f"Bearer {settings.wa_token}"}
    meta = httpx.get(f"{base}/{media_id}", headers=headers, timeout=30)
    meta.raise_for_status()
    info = meta.json()
    data = httpx.get(info["url"], headers=headers, timeout=60)
    data.raise_for_status()
    return data.content, info.get("mime_type", "application/octet-stream")
