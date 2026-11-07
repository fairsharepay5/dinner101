"""All settings come from environment variables (see .env.example)."""
import os
from dataclasses import dataclass, field
from pathlib import Path


def _load_dotenv() -> None:
    env = Path(__file__).resolve().parent.parent / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv()


def _get(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


@dataclass
class Settings:
    # General
    app_name: str = "Dinner 101"
    public_base_url: str = field(default_factory=lambda: _get("PUBLIC_BASE_URL", "http://localhost:8000"))
    database_url: str = field(default_factory=lambda: _get("DATABASE_URL", "sqlite:///./dinner101.db"))
    timezone: str = field(default_factory=lambda: _get("TIMEZONE", "Africa/Johannesburg"))
    admin_key: str = field(default_factory=lambda: _get("ADMIN_KEY", "change-me"))
    data_dir: Path = field(default_factory=lambda: Path(_get("DATA_DIR", "./data")))
    run_scheduler: bool = field(default_factory=lambda: _get("RUN_SCHEDULER", "1") == "1")
    simulator_enabled: bool = field(default_factory=lambda: _get("SIMULATOR_ENABLED", "1") == "1")

    # WhatsApp Cloud API (Meta)
    wa_token: str = field(default_factory=lambda: _get("WHATSAPP_TOKEN"))
    wa_phone_number_id: str = field(default_factory=lambda: _get("WHATSAPP_PHONE_NUMBER_ID"))
    wa_verify_token: str = field(default_factory=lambda: _get("WHATSAPP_VERIFY_TOKEN", "dinner101-verify"))
    wa_app_secret: str = field(default_factory=lambda: _get("WHATSAPP_APP_SECRET"))
    wa_display_number: str = field(default_factory=lambda: _get("WHATSAPP_DISPLAY_NUMBER", "27000000000"))
    wa_api_version: str = field(default_factory=lambda: _get("WHATSAPP_API_VERSION", "v21.0"))
    # Approved template names (create these in Meta Business Manager, see README)
    tpl_dinner: str = field(default_factory=lambda: _get("WA_TEMPLATE_DINNER", "dinner_tonight"))
    tpl_checkin: str = field(default_factory=lambda: _get("WA_TEMPLATE_CHECKIN", "dinner_checkin"))
    tpl_notice: str = field(default_factory=lambda: _get("WA_TEMPLATE_NOTICE", "account_notice"))

    # AI
    anthropic_api_key: str = field(default_factory=lambda: _get("ANTHROPIC_API_KEY"))
    parse_model: str = field(default_factory=lambda: _get("PARSE_MODEL", "claude-sonnet-5-5"))
    openai_api_key: str = field(default_factory=lambda: _get("OPENAI_API_KEY"))
    transcribe_model: str = field(default_factory=lambda: _get("TRANSCRIBE_MODEL", "whisper-1"))
    image_model: str = field(default_factory=lambda: _get("IMAGE_MODEL", "gpt-image-1"))

    # Billing (PayFast)
    price_rands: float = field(default_factory=lambda: float(_get("PRICE_RANDS", "39")))
    trial_days: int = field(default_factory=lambda: int(_get("TRIAL_DAYS", "14")))
    payfast_merchant_id: str = field(default_factory=lambda: _get("PAYFAST_MERCHANT_ID"))
    payfast_merchant_key: str = field(default_factory=lambda: _get("PAYFAST_MERCHANT_KEY"))
    payfast_passphrase: str = field(default_factory=lambda: _get("PAYFAST_PASSPHRASE"))
    payfast_sandbox: bool = field(default_factory=lambda: _get("PAYFAST_SANDBOX", "1") == "1")

    # Product behaviour
    default_dinner_time: str = field(default_factory=lambda: _get("DEFAULT_DINNER_TIME", "16:30"))
    checkin_after_hours: float = field(default_factory=lambda: float(_get("CHECKIN_AFTER_HOURS", "2.5")))

    @property
    def ai_enabled(self) -> bool:
        return bool(self.anthropic_api_key)

    @property
    def whatsapp_enabled(self) -> bool:
        return bool(self.wa_token and self.wa_phone_number_id)


settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
(settings.data_dir / "photos").mkdir(exist_ok=True)
