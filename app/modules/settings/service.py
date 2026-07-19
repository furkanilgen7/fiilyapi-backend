from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.settings import repository
from app.modules.settings.models import UICurrency, UIDensity, UILocale, UITheme, UserPreferences
from app.modules.settings.schemas import PreferencesRead, PreferencesUpdate
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
