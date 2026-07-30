"""T5 — taslak-farkindalikli santiye dogrulamasi (spec §5.1, §7.2).

KURAL: **tutarlilik kurallari HER ZAMAN, zorunluluk kurallari YALNIZ
taslak-disinda.** Yarim kalmis bir taslak asla gecersiz veri saklamaz, yalniz
EKSIK veri saklar.

Ikinci taraf da bagliyicidir: bu dogrulama PATCH'te tam olarak KOSMAZ (§0.3/3),
yoksa canlidaki sefsiz/alan bilgisi olmayan santiyeler duzenlenemez hâle gelir.
Burasi yalniz kural katmanini kilitler; cagrilma noktalari T6/T7'nin isidir.
"""

from datetime import date

import pytest
from fastapi import status

from app.core.errors import SiteValidationError
from app.main import app
from app.modules.sites import guards
from app.modules.sites.schemas import SiteCreate, SiteSectionInput


def _full() -> dict:
    """Taslak-disi POST'un GECTIGI tam govde (§5.1'in 7-10 kurallarini karsilar)."""
    return {
        "name": "A-Blok Şantiyesi",
        "site_manager_user_id": None,
        "site_manager_name": "Sercan Öztürk",
        "city": "Ankara",
        "construction_area_m2": "12500.00",
        "start_date": date(2026, 3, 1),
        "end_date": date(2026, 12, 31),
    }


def _validate(is_draft: bool, **overrides) -> None:
    guards.validate_site(SiteCreate(**{**_full(), **overrides}), is_draft=is_draft)


def _message(is_draft: bool, **overrides) -> str:
    with pytest.raises(SiteValidationError) as excinfo:
        _validate(is_draft, **overrides)
    return str(excinfo.value)


# --- 1: ad bos olamaz (Pydantic min_length=1, her iki durumda da) ---


@pytest.mark.parametrize("is_draft", [True, False])
def test_name_required_in_both_modes(is_draft: bool):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        SiteCreate(name="", is_draft=is_draft)


# --- 2: santiye bitis >= baslangic (TUTARLILIK — taslakta da) ---


def test_end_before_start_rejected_in_draft():
    assert (
        _message(True, start_date=date(2026, 12, 31), end_date=date(2026, 3, 1))
        == guards.END_BEFORE_START
    )


def test_end_before_start_rejected_in_published():
    assert (
        _message(False, start_date=date(2026, 12, 31), end_date=date(2026, 3, 1))
        == guards.END_BEFORE_START
    )


# --- 3 / 11: bolum satiri kurallari (TUTARLILIK — taslakta da) ---


def test_section_end_before_start_rejected_in_draft():
    sections = [
        SiteSectionInput(name="Kat 1-5"),
        SiteSectionInput(name="Kat 6-10", start_date=date(2026, 9, 1), end_date=date(2026, 1, 1)),
    ]
    # {n} 1-TABANLIDIR: kullanici 2. satiri goruyor, 1 indeksini degil.
    assert _message(True, sections=sections) == "2. bölüm: bitiş tarihi başlangıçtan önce olamaz."


def test_section_name_blank_rejected_in_draft():
    """Pydantic bos adi zaten reddeder; korkuluk BOSLUKTAN ibaret adi da yakalar."""
    sections = [SiteSectionInput(name="Kat 1-5"), SiteSectionInput(name="   ")]
    assert _message(True, sections=sections) == "2. bölüm: bölüm adı zorunludur."


def test_validation_stops_at_first_section_error():
    """Cok satirli hata listesi URETILMEZ (§8.2): form 2-5 satirlik, tek mesaj yeter."""
    sections = [
        SiteSectionInput(name="   "),
        SiteSectionInput(name="   "),
    ]
    error = _message(True, sections=sections)
    assert error == "1. bölüm: bölüm adı zorunludur."
    assert "2. bölüm" not in error


# --- 4: tutarlar >= 0 (Pydantic ge=0, her iki durumda da) ---


@pytest.mark.parametrize("is_draft", [True, False])
def test_negative_amounts_rejected_in_both(is_draft: bool):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        SiteCreate(name="A", budget=-1, is_draft=is_draft)


# --- 5: GPS — KURAL YOK (§3.5) ---


@pytest.mark.parametrize("is_draft", [True, False])
def test_gps_never_validated(is_draft: bool):
    _validate(is_draft, gps_coordinates="abc")


# --- 6 / 6b: ISG uzmani ---


def test_safety_officer_mutual_exclusion_in_draft():
    import uuid

    assert (
        _message(True, safety_officer_user_id=uuid.uuid4(), safety_officer_is_outsourced=True)
        == guards.SAFETY_OFFICER_CONFLICT
    )


def test_safety_officer_never_required():
    """§13/6 kilidi: ISG HICBIR kosulda zorunlu degil — tam govde ISG'siz gecer."""
    _validate(False)


# --- 7-10: zorunluluk kurallari YALNIZ taslak-disinda ---


@pytest.mark.parametrize(
    ("overrides", "message_attr"),
    [
        ({"site_manager_name": None}, "SITE_MANAGER_REQUIRED"),
        ({"city": None}, "CITY_REQUIRED"),
        ({"construction_area_m2": None}, "CONSTRUCTION_AREA_REQUIRED"),
        ({"start_date": None}, "DATES_REQUIRED"),
        ({"end_date": None}, "DATES_REQUIRED"),
    ],
)
def test_requirements_apply_only_when_published(overrides: dict, message_attr: str):
    _validate(True, **overrides)  # taslakta GECER
    assert _message(False, **overrides) == getattr(guards, message_attr)


def test_site_manager_user_id_satisfies_the_manager_requirement():
    """Sef ya FK ile ya ad ile verilir; ikisinden biri yeter."""
    import uuid

    _validate(False, site_manager_name=None, site_manager_user_id=uuid.uuid4())


# --- 15: HTTP eslemesi ---


async def test_site_validation_error_maps_to_422():
    handler = app.exception_handlers[SiteValidationError]
    response = await handler(None, SiteValidationError(guards.CITY_REQUIRED))

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert guards.CITY_REQUIRED.encode("utf-8") in response.body


def test_site_validation_error_is_a_domain_error():
    from app.core.errors import DomainError

    assert issubclass(SiteValidationError, DomainError)
