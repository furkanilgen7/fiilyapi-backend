"""İK-1 T2 — servis katmanı: TCKN checksum + taslak/yayın zorunluluğu + atama kapsamı.

Spec: `docs/superpowers/specs/2026-08-12-ik1-personel-belge-design.md` §1, §5 K1/K3/K4.

Servis fonksiyonları DOĞRUDAN çağrılır (router/HTTP değil): kural katmanı burada
sınanır. `PersonnelValidationError` -> 422, `NotFoundError` -> 404, `DuplicateError`
-> 409 (router bunları HTTP koduna çevirir; `test_personnel_ik_api.py` uçtan uca
statüyü doğrular).
"""

import uuid
from datetime import date

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    DuplicateError,
    NotFoundError,
    PersonnelValidationError,
)
from app.modules.personnel import service
from app.modules.personnel.guards import validate_tckn
from app.modules.personnel.schemas import PersonnelCreate, PersonnelUpdate
from app.modules.site_diary.models import WorkerSource
from app.modules.sites.models import Section, Site

# `10000000146` — checksum'ı geçerli, kamuya açık örnek TCKN (gerçek kişi değil).
GECERLI_TCKN = "10000000146"

# Yayın için TÜM ✱ alanları dolu bir gövde (PE 51-118). Atama alanları testte eklenir.
_TAM = {
    "full_name": "Ahmet Yılmaz",
    "source": WorkerSource.company,
    "tc_no": GECERLI_TCKN,
    "birth_date": date(1990, 1, 1),
    "phone": "5551112233",
    "address": "Mahalle Sokak No 1",
    "emergency_contact_name": "Ayşe Yılmaz",
    "emergency_contact_phone": "5559998877",
    "trade": "Kalıpçı",
    "hire_date": date(2026, 1, 1),
    "wage_type": "daily",
    "wage_amount": "1500.00",
}


# --- TCKN checksum (spec §5 K1) -----------------------------------------------


def test_gecerli_tckn_gecer():
    validate_tckn(GECERLI_TCKN)  # istisna ATMAMALI


@pytest.mark.parametrize(
    "tc_no",
    [
        "10000000140",  # son hane bozuk (checksum tutmaz)
        "1000000014",  # 10 hane
        "100000001466",  # 12 hane
        "1000000014A",  # harf içeriyor
        "01000000146",  # ilk hane 0 olamaz
        "00000000000",  # ilk hane 0
    ],
)
def test_gecersiz_tckn_422(tc_no):
    with pytest.raises(PersonnelValidationError):
        validate_tckn(tc_no)


# --- Taslak/yayın zorunluluğu — CREATE (spec §5 K3) --------------------------


@pytest.mark.asyncio
async def test_taslak_eksik_alanla_olusturulabilir(db_session: AsyncSession):
    """`is_draft=True` iken ✱ küme zorunlu DEĞİL — yarım kart saklanabilir."""
    kayit = await service.create_personnel(
        db_session,
        PersonnelCreate(full_name="Taslak İşçi", source=WorkerSource.company, is_draft=True),
    )
    assert kayit.is_draft is True


@pytest.mark.asyncio
async def test_yayin_eksik_alanla_422(db_session: AsyncSession):
    """`is_draft=False` iken eksik ✱ alan → 422, eksik alanlar mesajda anılır."""
    with pytest.raises(PersonnelValidationError) as exc:
        await service.create_personnel(
            db_session,
            PersonnelCreate(full_name="Yarım", source=WorkerSource.company, is_draft=False),
        )
    assert "TC Kimlik No" in str(exc.value)


@pytest.mark.asyncio
async def test_yayin_tam_alanla_olusturulur(db_session: AsyncSession, project_factory):
    proje = await project_factory(code="IK1-SRV-1")
    kayit = await service.create_personnel(
        db_session,
        PersonnelCreate(**_TAM, assigned_project_id=proje.id, is_draft=False),
    )
    assert kayit.is_draft is False
    assert kayit.tc_no == GECERLI_TCKN


@pytest.mark.asyncio
async def test_null_tc_no_dogrulama_atlanir(db_session: AsyncSession):
    """`tc_no` boş bir TASLAK'ta checksum ÇALIŞMAZ — serbest."""
    kayit = await service.create_personnel(
        db_session,
        PersonnelCreate(full_name="Taslak", source=WorkerSource.company, is_draft=True),
    )
    assert kayit.tc_no is None


@pytest.mark.asyncio
async def test_gecersiz_tckn_ile_taslak_bile_reddedilir(db_session: AsyncSession):
    """`tc_no` DOLU ise taslak da olsa checksum koşar (girilen değer geçerli olmalı)."""
    with pytest.raises(PersonnelValidationError):
        await service.create_personnel(
            db_session,
            PersonnelCreate(
                full_name="Taslak", source=WorkerSource.company, tc_no="10000000140", is_draft=True
            ),
        )


@pytest.mark.asyncio
async def test_ayni_tckn_ikinci_kayitta_409(db_session: AsyncSession):
    await service.create_personnel(
        db_session,
        PersonnelCreate(full_name="Birinci", source=WorkerSource.company, tc_no=GECERLI_TCKN),
    )
    with pytest.raises(DuplicateError):
        await service.create_personnel(
            db_session,
            PersonnelCreate(full_name="İkinci", source=WorkerSource.company, tc_no=GECERLI_TCKN),
        )


# --- PATCH birleşik zorunluluk (P6 _merged deseni) ---------------------------


@pytest.mark.asyncio
async def test_taslagi_yayina_cevirirken_birlesik_dolu_sart(
    db_session: AsyncSession, project_factory
):
    """Taslak eksik yaratılır; PATCH ile geri kalan ✱ alanlar VERİLİRSE yayına geçer."""
    proje = await project_factory(code="IK1-SRV-2")
    taslak = await service.create_personnel(
        db_session,
        PersonnelCreate(full_name="Ahmet", source=WorkerSource.company, is_draft=True),
    )
    # Eksik alanları TEK gövdede tamamla + is_draft=False → geçmeli.
    yayin = await service.update_personnel(
        db_session,
        taslak.id,
        PersonnelUpdate(
            tc_no=GECERLI_TCKN,
            birth_date=date(1990, 1, 1),
            phone="5551112233",
            address="Adres",
            emergency_contact_name="Yakın",
            emergency_contact_phone="5559998877",
            trade="Kalıpçı",
            hire_date=date(2026, 1, 1),
            assigned_project_id=proje.id,
            wage_type="daily",
            wage_amount="1500.00",
            is_draft=False,
        ),
    )
    assert yayin.is_draft is False


@pytest.mark.asyncio
async def test_taslagi_eksik_birlesikle_yayina_cevirmek_422(db_session: AsyncSession):
    """PATCH yalnız `is_draft=False` gönderir ama birleşik kayıt eksik → 422."""
    taslak = await service.create_personnel(
        db_session,
        PersonnelCreate(full_name="Ahmet", source=WorkerSource.company, is_draft=True),
    )
    with pytest.raises(PersonnelValidationError):
        await service.update_personnel(db_session, taslak.id, PersonnelUpdate(is_draft=False))


@pytest.mark.asyncio
async def test_yayin_kaydi_eksige_dusurulemez_422(db_session: AsyncSession, project_factory):
    """Yayında bir kaydı PATCH ile zorunlu alanı NULL'a çekmek yasak (birleşik kayıt)."""
    proje = await project_factory(code="IK1-SRV-3")
    yayin = await service.create_personnel(
        db_session,
        PersonnelCreate(**_TAM, assigned_project_id=proje.id, is_draft=False),
    )
    with pytest.raises(PersonnelValidationError):
        await service.update_personnel(db_session, yayin.id, PersonnelUpdate(phone=None))


# --- Atama alanları: proje/bölüm var mı + bölüm o projeye ait mi -------------


@pytest.mark.asyncio
async def test_var_olmayan_atanan_proje_404(db_session: AsyncSession):
    with pytest.raises(NotFoundError):
        await service.create_personnel(
            db_session,
            PersonnelCreate(
                full_name="Ahmet",
                source=WorkerSource.company,
                assigned_project_id=uuid.uuid4(),
                is_draft=True,
            ),
        )


@pytest.mark.asyncio
async def test_bolum_baska_projede_422(db_session: AsyncSession, project_factory):
    """`assigned_section_id` başka projenin şantiyesine ait → 422 (kural ihlali)."""
    proje_a = await project_factory(code="IK1-SRV-A")
    proje_b = await project_factory(code="IK1-SRV-B")
    santiye_b = Site(project_id=proje_b.id, code="SB", name="Şantiye B")
    db_session.add(santiye_b)
    await db_session.flush()
    bolum_b = Section(site_id=santiye_b.id, name="Bölüm B")
    db_session.add(bolum_b)
    await db_session.flush()

    with pytest.raises(PersonnelValidationError):
        await service.create_personnel(
            db_session,
            PersonnelCreate(
                full_name="Ahmet",
                source=WorkerSource.company,
                assigned_project_id=proje_a.id,
                assigned_section_id=bolum_b.id,
                is_draft=True,
            ),
        )


@pytest.mark.asyncio
async def test_bolum_projesiz_verilemez_422(db_session: AsyncSession):
    """Bölüm verilip proje verilmezse birleşik kayıtta proje yok → 422."""
    with pytest.raises(PersonnelValidationError):
        await service.create_personnel(
            db_session,
            PersonnelCreate(
                full_name="Ahmet",
                source=WorkerSource.company,
                assigned_section_id=uuid.uuid4(),
                is_draft=True,
            ),
        )


@pytest.mark.asyncio
async def test_bolum_dogru_projede_kabul(db_session: AsyncSession, project_factory):
    proje = await project_factory(code="IK1-SRV-OK")
    santiye = Site(project_id=proje.id, code="S1", name="Şantiye")
    db_session.add(santiye)
    await db_session.flush()
    bolum = Section(site_id=santiye.id, name="Bölüm")
    db_session.add(bolum)
    await db_session.flush()

    kayit = await service.create_personnel(
        db_session,
        PersonnelCreate(
            full_name="Ahmet",
            source=WorkerSource.company,
            assigned_project_id=proje.id,
            assigned_section_id=bolum.id,
            is_draft=True,
        ),
    )
    assert kayit.assigned_section_id == bolum.id
