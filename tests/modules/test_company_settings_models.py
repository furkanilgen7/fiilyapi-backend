import pytest
from sqlalchemy.exc import IntegrityError

from app.core.config import settings as app_settings
from app.modules.company.models import Company
from app.modules.settings.models import NotificationPref, UserPreferences


def test_logo_and_brand_config_defaults():
    assert app_settings.logo_max_bytes == 1_048_576
    assert "image/png" in app_settings.allowed_logo_content_type_set
    assert "image/svg+xml" in app_settings.allowed_logo_content_type_set
    assert app_settings.default_brand_color == "#2563eb"
    assert str(app_settings.default_vat_rate) == "20.00"


async def test_company_defaults(db_session):
    company = Company()
    db_session.add(company)
    await db_session.flush()
    assert company.only_row is True
    assert company.brand_color == "#2563eb"
    assert str(company.default_vat_rate) == "20.00"
    assert company.auto_einvoice is False
    assert company.logo_data is None


async def test_company_is_singleton(db_session):
    db_session.add(Company())
    await db_session.flush()
    db_session.add(Company())
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_preferences_defaults(db_session, user_factory):
    user = await user_factory(email="pref@t.co", password="parola1234", role_key="patron")
    prefs = UserPreferences(user_id=user.id)
    db_session.add(prefs)
    await db_session.flush()
    assert prefs.locale.value == "tr"
    assert prefs.currency.value == "TRY"
    assert prefs.density.value == "normal"
    assert prefs.theme.value == "light"
    assert prefs.accent_color == "#2563eb"


async def test_notification_pref_unique(db_session, user_factory):
    user = await user_factory(email="notif@t.co", password="parola1234", role_key="patron")
    db_session.add(
        NotificationPref(
            user_id=user.id, event_key="vat_due_soon", email=True, in_app=True, sms=False
        )
    )
    await db_session.flush()
    db_session.add(
        NotificationPref(
            user_id=user.id, event_key="vat_due_soon", email=False, in_app=False, sms=False
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()
