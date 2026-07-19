from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.settings.constants import NOTIFICATION_EVENT_KEYS
from app.modules.settings.models import UICurrency, UIDensity, UILocale, UITheme

_HEX_COLOR = r"^#[0-9A-Fa-f]{6}$"


class PreferencesRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    locale: UILocale
    currency: UICurrency
    date_format: str
    density: UIDensity
    theme: UITheme
    accent_color: str


class PreferencesUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    locale: UILocale | None = None
    currency: UICurrency | None = None
    date_format: str | None = Field(default=None, max_length=20)
    density: UIDensity | None = None
    theme: UITheme | None = None
    accent_color: str | None = Field(default=None, pattern=_HEX_COLOR)

    @field_validator("theme")
    @classmethod
    def _only_light_theme(cls, value: UITheme | None) -> UITheme | None:
        # Spec §9: v1'de yalnizca acik tema aktif; koyu/sistem pasif.
        if value is not None and value is not UITheme.light:
            raise ValueError("Koyu tema henuz aktif degil")
        return value


class NotificationPrefItem(BaseModel):
    event_key: str
    label: str
    email: bool
    in_app: bool
    sms: bool


class NotificationPrefUpdateItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_key: str
    email: bool
    in_app: bool
    sms: bool


class NotificationPrefsUpdate(BaseModel):
    items: list[NotificationPrefUpdateItem]

    @field_validator("items")
    @classmethod
    def _known_event_keys(
        cls, items: list[NotificationPrefUpdateItem]
    ) -> list[NotificationPrefUpdateItem]:
        unknown = {i.event_key for i in items} - NOTIFICATION_EVENT_KEYS
        if unknown:
            raise ValueError(f"Bilinmeyen bildirim olayi: {', '.join(sorted(unknown))}")
        return items
