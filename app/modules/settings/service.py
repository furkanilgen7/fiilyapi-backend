from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.settings import repository
from app.modules.settings.constants import NOTIFICATION_EVENTS, NOTIFICATION_LABELS
from app.modules.settings.models import UICurrency, UIDensity, UILocale, UITheme, UserPreferences
from app.modules.settings.schemas import (
    NotificationPrefItem,
    NotificationPrefsUpdate,
    PreferencesRead,
    PreferencesUpdate,
)
from app.modules.users.models import User


def _default_preferences() -> PreferencesRead:
    return PreferencesRead(
        locale=UILocale.tr,
        currency=UICurrency.TRY,
        date_format="DD.MM.YYYY",
        density=UIDensity.normal,
        theme=UITheme.light,
        accent_color="#2563eb",
    )


async def get_preferences(session: AsyncSession, user: User) -> PreferencesRead:
    prefs = await repository.get_preferences(session, user.id)
    if prefs is None:
        return _default_preferences()
    return PreferencesRead.model_validate(prefs)


async def update_preferences(
    session: AsyncSession, user: User, data: PreferencesUpdate
) -> PreferencesRead:
    values = data.model_dump(exclude_unset=True)
    prefs: UserPreferences = await repository.upsert_preferences(session, user.id, values)
    return PreferencesRead.model_validate(prefs)


async def get_notifications(session: AsyncSession, user: User) -> list[NotificationPrefItem]:
    """Katalogu saklanan satirlarla merge eder; eksik olaylar varsayilanla doner."""
    stored = {p.event_key: p for p in await repository.list_notification_prefs(session, user.id)}
    result: list[NotificationPrefItem] = []
    for event in NOTIFICATION_EVENTS:
        row = stored.get(event["event_key"])
        if row is None:
            result.append(
                NotificationPrefItem(
                    event_key=event["event_key"],
                    label=event["label"],
                    email=event["email"],
                    in_app=event["in_app"],
                    sms=event["sms"],
                )
            )
        else:
            result.append(
                NotificationPrefItem(
                    event_key=row.event_key,
                    label=NOTIFICATION_LABELS[row.event_key],
                    email=row.email,
                    in_app=row.in_app,
                    sms=row.sms,
                )
            )
    return result


async def update_notifications(
    session: AsyncSession, user: User, data: NotificationPrefsUpdate
) -> list[NotificationPrefItem]:
    for item in data.items:
        await repository.upsert_notification_pref(
            session, user.id, item.event_key, item.email, item.in_app, item.sms
        )
    return await get_notifications(session, user)
