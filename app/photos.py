"""One photo per recipe, generated once and reused for every household."""
import base64
import logging

import httpx

from .config import settings

log = logging.getLogger(__name__)

PHOTO_DIR = settings.data_dir / "photos"
IMAGE_USD = 0.04  # rough cost per generated image, for the admin cost view

STYLE = ("Realistic overhead food photo of a simple home-cooked South African family dinner: {name}. "
         "Served on an everyday white plate on a wooden kitchen table, natural daylight, "
         "generous portion, looks achievable at home, not restaurant styled. No text, no people.")


def path_for(recipe_id: str):
    return PHOTO_DIR / f"{recipe_id}.png"


def url_for(recipe_id: str) -> str | None:
    """Public URL of the recipe photo, generating it the first time if possible."""
    p = path_for(recipe_id)
    if not p.exists():
        if not generate(recipe_id):
            return None
    return f"{settings.public_base_url.rstrip('/')}/media/photos/{recipe_id}.png"


def generate(recipe_id: str) -> bool:
    from .recipes import RECIPES
    from .db import session_scope
    from .models import Usage
    if not settings.openai_api_key:
        return False
    recipe = RECIPES[recipe_id]
    try:
        r = httpx.post(
            "https://api.openai.com/v1/images/generations",
            headers={"Authorization": f"Bearer {settings.openai_api_key}"},
            json={"model": settings.image_model, "prompt": STYLE.format(name=recipe["name"]), "size": "1024x1024", "n": 1},
            timeout=120,
        )
        r.raise_for_status()
        data = r.json()["data"][0]
        if "b64_json" in data:
            img = base64.b64decode(data["b64_json"])
        else:
            img = httpx.get(data["url"], timeout=60).content
        path_for(recipe_id).write_bytes(img)
        with session_scope() as s:
            s.add(Usage(kind="ai_image", usd=IMAGE_USD, detail=recipe_id))
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("Photo generation failed for %s: %s", recipe_id, e)
        return False


def generate_all() -> int:
    from .recipes import RECIPES
    n = 0
    for rid in RECIPES:
        if not path_for(rid).exists() and generate(rid):
            n += 1
    return n
