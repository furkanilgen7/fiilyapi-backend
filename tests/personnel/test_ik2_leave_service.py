"""İK-2 T2 — izin gün hesabı + çakışma yardımcısı (servis/repository katmanı).

Spec: `docs/superpowers/specs/2026-08-12-ik2-izin-yonetimi-design.md` §5 K2, K3.

İki saf/dar davranış BURADA sınanır (HTTP'siz), çünkü ikisi de T3'ün (approve/
reject) TEMELİDİR ve T2'de hiçbir uç onları 409'a çevirmez:

* **`calculate_leave_days`** — K2: TAKVİM günü, başlangıç ve bitiş DAHİL. İş günü
  DEĞİL (hafta sonu/tatil çıkarma İK-3). Mockup 04-08 Ağustos = 5 gün doğrular.
* **`find_overlapping_approved_leave`** — K3: aynı personelin ÇAKIŞAN **onaylı**
  izni. T2'de yalnız HAZIRLANIR; POST/PATCH bunu 409'a ÇEVİRMEZ (spec §3: kural
  `approve`ta işler, T3). Bu yüzden davranışı yalnız burada kanıtlanır.
"""

from datetime import date

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.personnel import leave, service
from app.modules.personnel.models import LeaveRequest, LeaveStatus, LeaveType, Personnel
from app.modules.site_diary.models import WorkerSource


@pytest.fixture
async def personel(db_session: AsyncSession) -> Personnel:
    kayit = Personnel(full_name="Çakışma Testi", source=WorkerSource.company)
    db_session.add(kayit)
    await db_session.flush()
    return kayit


@pytest.fixture
async def yillik(db_session: AsyncSession) -> LeaveType:
    tip = LeaveType(name="Yıllık İzin", deducts_from_annual=True, sort_order=1)
    db_session.add(tip)
    await db_session.flush()
    return tip


async def _izin(
    session: AsyncSession,
    personel: Personnel,
    tip: LeaveType,
    baslangic: date,
    bitis: date,
    durum: LeaveStatus,
) -> LeaveRequest:
    kayit = LeaveRequest(
        personnel_id=personel.id,
        leave_type_id=tip.id,
        start_date=baslangic,
        end_date=bitis,
        days=leave.calculate_leave_days(baslangic, bitis),
        status=durum,
    )
    session.add(kayit)
    await session.flush()
    return kayit


# --- K2: gün hesabı (takvim günü, iki uç dahil) ------------------------------


@pytest.mark.parametrize(
    ("baslangic", "bitis", "beklenen"),
    [
        (date(2026, 8, 4), date(2026, 8, 8), 5),  # mockup İZ satırı: 04-08 Ağu = 5
        (date(2026, 7, 31), date(2026, 7, 31), 1),  # tek gün = 1 (0 DEĞİL)
        (date(2026, 8, 10), date(2026, 8, 21), 12),  # mockup İZ satırı: 12 gün
        (date(2026, 8, 8), date(2026, 8, 9), 2),  # hafta sonu ÇIKARILMAZ (K2)
        (date(2026, 12, 30), date(2027, 1, 2), 4),  # yıl sınırı
    ],
)
def test_gun_hesabi_takvim_gunu_iki_uc_dahil(baslangic: date, bitis: date, beklenen: int) -> None:
    assert leave.calculate_leave_days(baslangic, bitis) == beklenen


# --- K3: çakışan ONAYLI izin yardımcısı --------------------------------------


@pytest.mark.asyncio
async def test_cakisan_onayli_izin_bulunur(db_session, personel, yillik):
    await _izin(
        db_session, personel, yillik, date(2026, 8, 4), date(2026, 8, 8), LeaveStatus.approved
    )
    bulunan = await service.find_overlapping_approved_leave(
        db_session, personel.id, date(2026, 8, 6), date(2026, 8, 10)
    )
    assert bulunan is not None


@pytest.mark.asyncio
async def test_ayni_gun_dokunan_izin_cakisir(db_session, personel, yillik):
    """Bitiş ile başlangıç AYNI güne düşerse çakışmadır (o gün iki izne birden ait
    olamaz) — `<=`/`>=` sınırı bilinçlidir."""
    await _izin(
        db_session, personel, yillik, date(2026, 8, 4), date(2026, 8, 8), LeaveStatus.approved
    )
    bulunan = await service.find_overlapping_approved_leave(
        db_session, personel.id, date(2026, 8, 8), date(2026, 8, 12)
    )
    assert bulunan is not None


@pytest.mark.asyncio
async def test_ayni_gun_dokunan_izin_ters_yonde_de_cakisir(db_session, personel, yillik):
    """SİMETRİ: mevcut iznin BAŞLANGICI yeni iznin BİTİŞİNE denk gelirse de çakışır.

    Bir önceki testin aynası — iki sınır (`start <= end` ve `end >= start`) AYRI
    koşullardır ve yalnız birini sınamak ötekinin `<` olarak yazılmasını yakalamaz.
    """
    await _izin(
        db_session, personel, yillik, date(2026, 8, 8), date(2026, 8, 12), LeaveStatus.approved
    )
    bulunan = await service.find_overlapping_approved_leave(
        db_session, personel.id, date(2026, 8, 4), date(2026, 8, 8)
    )
    assert bulunan is not None


@pytest.mark.asyncio
async def test_sonraki_bitisik_izin_cakismaz(db_session, personel, yillik):
    """`test_bitisik_gunler_cakismaz`ın aynası: mevcut izin YENİDEN SONRA başlıyorsa
    (bir gün boşlukla) çakışma yoktur."""
    await _izin(
        db_session, personel, yillik, date(2026, 8, 9), date(2026, 8, 12), LeaveStatus.approved
    )
    bulunan = await service.find_overlapping_approved_leave(
        db_session, personel.id, date(2026, 8, 4), date(2026, 8, 8)
    )
    assert bulunan is None


@pytest.mark.asyncio
async def test_bitisik_gunler_cakismaz(db_session, personel, yillik):
    """08'de biten iznin ardından 09'da başlayan izin ÇAKIŞMAZ."""
    await _izin(
        db_session, personel, yillik, date(2026, 8, 4), date(2026, 8, 8), LeaveStatus.approved
    )
    bulunan = await service.find_overlapping_approved_leave(
        db_session, personel.id, date(2026, 8, 9), date(2026, 8, 12)
    )
    assert bulunan is None


@pytest.mark.asyncio
async def test_bekleyen_izin_cakisma_saymaz(db_session, personel, yillik):
    """Kural YALNIZ `approved` izinlere bakar (spec §5 K3) — bekleyen talep engel değil."""
    await _izin(
        db_session, personel, yillik, date(2026, 8, 4), date(2026, 8, 8), LeaveStatus.pending
    )
    bulunan = await service.find_overlapping_approved_leave(
        db_session, personel.id, date(2026, 8, 6), date(2026, 8, 10)
    )
    assert bulunan is None


@pytest.mark.asyncio
async def test_reddedilen_izin_cakisma_saymaz(db_session, personel, yillik):
    await _izin(
        db_session, personel, yillik, date(2026, 8, 4), date(2026, 8, 8), LeaveStatus.rejected
    )
    bulunan = await service.find_overlapping_approved_leave(
        db_session, personel.id, date(2026, 8, 6), date(2026, 8, 10)
    )
    assert bulunan is None


@pytest.mark.asyncio
async def test_baska_personelin_izni_cakisma_saymaz(db_session, personel, yillik):
    digeri = Personnel(full_name="Başkası", source=WorkerSource.company)
    db_session.add(digeri)
    await db_session.flush()
    await _izin(
        db_session, digeri, yillik, date(2026, 8, 4), date(2026, 8, 8), LeaveStatus.approved
    )
    bulunan = await service.find_overlapping_approved_leave(
        db_session, personel.id, date(2026, 8, 6), date(2026, 8, 10)
    )
    assert bulunan is None


@pytest.mark.asyncio
async def test_exclude_id_kendini_saymaz(db_session, personel, yillik):
    """T3 `approve`ta kaydın KENDİSİ hariç tutulur — aksi hâlde her onaylı kayıt
    kendisiyle çakışırdı."""
    kayit = await _izin(
        db_session, personel, yillik, date(2026, 8, 4), date(2026, 8, 8), LeaveStatus.approved
    )
    bulunan = await service.find_overlapping_approved_leave(
        db_session, personel.id, date(2026, 8, 4), date(2026, 8, 8), exclude_id=kayit.id
    )
    assert bulunan is None
