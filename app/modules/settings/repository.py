import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.settings.models import NotificationPref, UserPreferences


async def get_preferences(session: AsyncSession, user_id: uuid.UUID) -> UserPreferences | None:
    return await session.get(UserPreferences, user_id)


async def upsert_preferences(
    session: AsyncSession, user_id: uuid.UUID, values: dict
) -> UserPreferences:
    prefs = await session.get(UserPreferences, user_id)
    if prefs is None:
        prefs = UserPreferences(user_id=user_id, **values)
        session.add(prefs)
    else:
        for field, value in values.items():
            setattr(prefs, field, value)
    await session.flush()
    return prefs


async def list_notification_prefs(
    session: AsyncSession, user_id: uuid.UUID
) -> list[NotificationPref]:
    result = await session.execute(
        select(NotificationPref).where(NotificationPref.user_id == user_id)
    )
    return list(result.scalars().all())


async def upsert_notification_pref(
    session: AsyncSession,
    user_id: uuid.UUID,
    event_key: str,
    email: bool,
    in_app: bool,
    sms: bool,
) -> NotificationPref:
    existing = await session.scalar(
        select(NotificationPref).where(
            NotificationPref.user_id == user_id, NotificationPref.event_key == event_key
        )
    )
    if existing is None:
        existing = NotificationPref(
            user_id=user_id, event_key=event_key, email=email, in_app=in_app, sms=sms
        )
        session.add(existing)
    else:
        existing.email = email
        existing.in_app = in_app
        existing.sms = sms
    await session.flush()
    return existing
