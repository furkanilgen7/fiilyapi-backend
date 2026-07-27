"""Santiye kodu turetmesi (spec §8 acik soru 2).

Kod zorunludur ama kullanicidan istenmez: ad'dan turetilir ve kullanici PATCH
ile duzeltebilir. Ad'in sonundaki genel santiye soneki ("... Şantiyesi") koda
tasinmaz — spec ornegi "A-Blok Şantiyesi" icin A-BLOK verir.
"""

import pytest

from app.modules.sites import service
from app.modules.sites.models import Site
from app.modules.sites.schemas import SiteCreate
from app.modules.users.models import UserProjectAccess


async def _patron(session, user_factory, email: str):
    user = await user_factory(email=email, password="parola1234", role_key="patron")
    session.add(UserProjectAccess(user_id=user.id, project_id=None, all_projects=True))
    await session.flush()
    return user


# --- Saf turetme ---


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("A-Blok Şantiyesi", "A-BLOK"),
        ("B-Blok", "B-BLOK"),
        ("Merkez Şantiye", "MERKEZ"),
        # Sonek atilinca geriye bir sey kalmiyorsa ham ad slug'lanir.
        ("Şantiye", "SANTIYE"),
    ],
)
def test_spec_examples(name: str, expected: str):
    assert service.derive_code(name) == expected


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        # Sonek yazimi buyuk/kucuk ve Turkce karakter duyarsiz.
        ("A-Blok ŞANTİYESİ", "A-BLOK"),
        ("A-Blok santiyesi", "A-BLOK"),
        ("A-Blok Santiyesi", "A-BLOK"),
        ("A-Blok şantiye", "A-BLOK"),
    ],
)
def test_suffix_matching_is_case_and_diacritic_insensitive(name: str, expected: str):
    assert service.derive_code(name) == expected


def test_longer_suffix_wins():
    """ "Şantiyesi" once denenmezse geriye "SI" artigi kalir."""
    assert service.derive_code("Kuzey Şantiyesi") == "KUZEY"


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Şantiye Merkez", "SANTIYE-MERKEZ"),  # sonek DEGIL, basta
        ("Merkez Şantiye Ofisi", "MERKEZ-SANTIYE-OFISI"),  # sonda degil
    ],
)
def test_suffix_only_stripped_at_the_end(name: str, expected: str):
    assert service.derive_code(name) == expected


def test_suffix_must_be_a_whole_word():
    """Sadece ayni harflerle biten bir ad kirpilmamali."""
    assert service.derive_code("Büyükşantiye") == "BUYUKSANTIYE"


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Çığır Ğüneş", "CIGIR-GUNES"),
        ("İstanbul Şantiyesi", "ISTANBUL"),
        ("Öz Üst", "OZ-UST"),
    ],
)
def test_turkish_characters_fold_to_ascii(name: str, expected: str):
    assert service.derive_code(name) == expected


def test_punctuation_collapses_to_single_dash():
    assert service.derive_code("A  //  B") == "A-B"


def test_code_is_capped_at_column_length():
    code = service.derive_code("X" * 200)
    assert len(code) <= 50


def test_nameless_slug_falls_back():
    """Slug'lanacak hicbir alfanumerik yoksa sabit bir kod uretilir."""
    assert service.derive_code("!!!") == "SANTIYE"


# --- Ayni projede cakisma ---


async def test_collision_appends_incrementing_suffix(seeded_db, user_factory, project_factory):
    project = await project_factory("C-1")
    user = await _patron(seeded_db, user_factory, "c1@t.co")

    first = await service.create_site(
        seeded_db, user, project.id, SiteCreate(name="A-Blok Şantiyesi")
    )
    second = await service.create_site(
        seeded_db, user, project.id, SiteCreate(name="A-Blok Şantiyesi")
    )
    third = await service.create_site(
        seeded_db, user, project.id, SiteCreate(name="A-Blok Şantiyesi")
    )

    assert [first.code, second.code, third.code] == ["A-BLOK", "A-BLOK-2", "A-BLOK-3"]


async def test_collision_is_scoped_to_the_project(seeded_db, user_factory, project_factory):
    """Kod yalnizca proje ICINDE benzersizdir — baska proje sifirdan baslar."""
    project = await project_factory("C-2")
    other = await project_factory("C-3")
    user = await _patron(seeded_db, user_factory, "c2@t.co")

    await service.create_site(seeded_db, user, project.id, SiteCreate(name="A-Blok Şantiyesi"))
    elsewhere = await service.create_site(
        seeded_db, user, other.id, SiteCreate(name="A-Blok Şantiyesi")
    )

    assert elsewhere.code == "A-BLOK"


async def test_derived_code_avoids_existing_explicit_code(seeded_db, user_factory, project_factory):
    """Elle girilmis bir kod turetilenle cakisirsa turetilen kenara cekilir."""
    project = await project_factory("C-4")
    seeded_db.add(Site(project_id=project.id, code="A-BLOK", name="Elle girilmiş"))
    await seeded_db.flush()
    user = await _patron(seeded_db, user_factory, "c4@t.co")

    site = await service.create_site(
        seeded_db, user, project.id, SiteCreate(name="A-Blok Şantiyesi")
    )

    assert site.code == "A-BLOK-2"


async def test_explicit_duplicate_code_still_conflicts(seeded_db, user_factory, project_factory):
    """Cakisma cozumu YALNIZ turetilen koda uygulanir: kullanici acikca cakisan
    bir kod verdiyse sessizce degistirilmez, IntegrityError'a (409) birakilir."""
    from sqlalchemy.exc import IntegrityError

    project = await project_factory("C-5")
    seeded_db.add(Site(project_id=project.id, code="A-BLOK", name="Var olan"))
    await seeded_db.flush()
    user = await _patron(seeded_db, user_factory, "c5@t.co")

    with pytest.raises(IntegrityError):
        await service.create_site(
            seeded_db, user, project.id, SiteCreate(name="Kopya", code="A-BLOK")
        )
