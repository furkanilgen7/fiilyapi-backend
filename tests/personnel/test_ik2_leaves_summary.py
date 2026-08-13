"""İK-2 T4 — `GET /hr/leaves/summary` (İZ mockup birebir).

Spec: `docs/superpowers/specs/2026-08-12-ik2-izin-yonetimi-design.md` §2, §3, §4.
Mockup: `projedesign/İK - İzin Yönetimi.dc.html` (İZ).

Ölçülen ÜÇ ayrı şey — karıştırılmaz:

1. **5 KPI** (İZ 46-50) — sabit `today` ile "bugün"/"bu ay" pencereleri
   deterministik: Bekleyen Talep · Bugün İzinli · Bu Ay Kullanılan · Toplam İzin
   Borcu · Devreden Risk.
2. **Bakiye tablosu** (İZ 122-170) — Personel/Kıdem/Yıllık Hak/Devreden/
   Kullanılan/Kalan/Kullanım sütunları ve **NULL gösterimi** (İZ 163-167 "Hak
   yok · 1 yıl dolunca hak kazanır"): hak hesaplanamayan personel 0 SAYILMAZ,
   `null` döner ve KPI toplamlarına GİRMEZ (🔴 fail-closed).
3. **N+1 önlemi** — sorgu sayısı 2 vs 10 personelde AYNI (aggrega + group-by;
   personel başına SELECT yok).

Türevlerin (hak/kalan/yüzde/kıdem) DOĞRULUĞU burada YENİDEN sınanmaz —
`test_ik2_leave_balance.py` `leave.py` tek kaynağını sınar. Buradaki iddia
"özet o tek kaynağı kullanıyor ve doğru topluyor" iddiasıdır.
"""

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.personnel import service
from app.modules.personnel.models import (
    LeaveBalance,
    LeaveRequest,
    LeaveStatus,
    LeaveType,
    Personnel,
)
from app.modules.site_diary.models import WorkerSource
from tests.conftest import test_engine

pytestmark = pytest.mark.asyncio

# Sabit "bugün": İZ'in "Bugün İzinli" ve "Bu Ay Kullanılan" pencereleri ancak
# enjekte edilmiş bir tarihle deterministik sınanabilir.
BUGUN = date(2026, 6, 15)
YIL = 2026


# --- yardımcılar -------------------------------------------------------------


async def _mk_personnel(
    db: AsyncSession,
    name: str,
    *,
    hire_date: date | None,
    active: bool = True,
    draft: bool = False,
) -> Personnel:
    p = Personnel(
        full_name=name,
        source=WorkerSource.company,
        hire_date=hire_date,
        is_active=active,
        is_draft=draft,
    )
    db.add(p)
    await db.flush()
    return p


async def _mk_type(db: AsyncSession, name: str, *, deducts: bool) -> LeaveType:
    t = LeaveType(name=name, deducts_from_annual=deducts, sort_order=1)
    db.add(t)
    await db.flush()
    return t


async def _mk_request(
    db: AsyncSession,
    personnel: Personnel,
    leave_type: LeaveType,
    start: date,
    end: date,
    status: LeaveStatus = LeaveStatus.approved,
) -> LeaveRequest:
    r = LeaveRequest(
        personnel_id=personnel.id,
        leave_type_id=leave_type.id,
        start_date=start,
        end_date=end,
        days=(end - start).days + 1,
        status=status,
    )
    db.add(r)
    await db.flush()
    return r


async def _mk_balance(db: AsyncSession, personnel: Personnel, carried: str) -> LeaveBalance:
    b = LeaveBalance(personnel_id=personnel.id, year=YIL, carried_over=Decimal(carried))
    db.add(b)
    await db.flush()
    return b


@pytest.fixture
async def yillik(seeded_db: AsyncSession) -> LeaveType:
    return await _mk_type(seeded_db, "Yıllık İzin", deducts=True)


@pytest.fixture
async def hastalik(seeded_db: AsyncSession) -> LeaveType:
    """İZ 87 "Rapor" — yıllık haktan DÜŞMEZ."""
    return await _mk_type(seeded_db, "Hastalık İzni", deducts=False)


@pytest.fixture
async def izmockup(
    seeded_db: AsyncSession, yillik: LeaveType, hastalik: LeaveType
) -> dict[str, Personnel]:
    """İZ 133-168'in DÖRT bakiye satırını birebir kuran altın kurulum.

    Ayşe 14+3−6=11 (İZ 134-140) · Mehmet 14+0−5=9 (143-149) · Hasan 14+6−12=8
    (152-158) · Sercan kıdem<1 → hak YOK (161-167).
    """
    ayse = await _mk_personnel(seeded_db, "Ayşe Demir", hire_date=date(2024, 5, 15))
    mehmet = await _mk_personnel(seeded_db, "Mehmet Yılmaz", hire_date=date(2025, 2, 15))
    hasan = await _mk_personnel(seeded_db, "Hasan Çelik", hire_date=date(2024, 12, 15))
    sercan = await _mk_personnel(seeded_db, "Sercan Öztürk", hire_date=date(2026, 1, 15))

    await _mk_balance(seeded_db, ayse, "3")
    await _mk_balance(seeded_db, hasan, "6")

    # Kullanılan günler (yalnız `deducts_from_annual` tipler sayılır).
    await _mk_request(seeded_db, ayse, yillik, date(2026, 3, 2), date(2026, 3, 7))  # 6
    await _mk_request(seeded_db, mehmet, yillik, date(2026, 6, 10), date(2026, 6, 14))  # 5
    await _mk_request(seeded_db, hasan, yillik, date(2026, 6, 4), date(2026, 6, 15))  # 12
    # Sercan'ın raporu haktan DÜŞMEZ ama "bugün izinli"dir (kişi işbaşında değil).
    await _mk_request(seeded_db, sercan, hastalik, date(2026, 6, 15), date(2026, 6, 16))
    # İki bekleyen talep — İZ 46/56 "Bekleyen Talep (6)" sayacının tabanı.
    await _mk_request(
        seeded_db, mehmet, yillik, date(2026, 8, 4), date(2026, 8, 8), LeaveStatus.pending
    )
    await _mk_request(
        seeded_db, ayse, hastalik, date(2026, 7, 31), date(2026, 7, 31), LeaveStatus.pending
    )
    return {"ayse": ayse, "mehmet": mehmet, "hasan": hasan, "sercan": sercan}


# --- 1. beş KPI altın senaryosu (İZ 46-50) ----------------------------------


async def test_bes_kpi_altin(seeded_db: AsyncSession, izmockup: dict[str, Personnel]) -> None:
    ozet = await service.build_hr_leaves_summary(seeded_db, year=YIL, today=BUGUN)

    # İZ 46 "Bekleyen Talep": yalnız `pending` talepler (tipten bağımsız).
    assert ozet.pending_requests == 2
    # İZ 47 "Bugün İzinli": bugünü KAPSAYAN onaylı izni olan TEKİL personel
    # (Hasan 04-15 Haz · Sercan 15-16 Haz raporlu). Mehmet 14'ünde bitti.
    assert ozet.on_leave_today == 2
    # İZ 48 "Bu Ay Kullanılan": bu ay BAŞLAYAN onaylı + haktan DÜŞEN günler
    # (Mehmet 5 + Hasan 12 = 17). Sercan'ın raporu "kullanılan" değildir (İZ 87).
    assert ozet.days_used_this_month == 17
    # İZ 49 "Toplam İzin Borcu": hesaplanabilir kalanların toplamı 11+9+8 = 28.
    assert ozet.total_leave_debt == Decimal("28")
    # İZ 50 "Devreden Risk": devredeni olan VE kalanı duran kişi (Ayşe + Hasan).
    assert ozet.carryover_risk_personnel == 2
    # 🔴 Hak hesaplanamayan personel SESSİZCE 0 sayılmaz — açıkça sayılır (Sercan).
    assert ozet.unknown_entitlement_personnel == 1
    assert ozet.year == YIL


# --- 2. bakiye tablosu: İZ satırları birebir + sıralama ---------------------


async def test_bakiye_tablosu_iz_satirlari(
    seeded_db: AsyncSession, izmockup: dict[str, Personnel]
) -> None:
    """İZ 133-168: dört satır, "Kalan" azalan sırada (11 · 9 · 8 · hak yok)."""
    ozet = await service.build_hr_leaves_summary(seeded_db, year=YIL, today=BUGUN)

    assert [r.personnel_name for r in ozet.balances] == [
        "Ayşe Demir",
        "Mehmet Yılmaz",
        "Hasan Çelik",
        "Sercan Öztürk",
    ]
    ayse, mehmet, hasan, sercan = ozet.balances

    # İZ 134-140: kıdem "2 yıl 1 ay" · hak 14 · devreden 3 · kullanılan 6 · kalan 11 · %35
    assert (ayse.seniority_years, ayse.seniority_months) == (2, 1)
    assert ayse.annual_entitlement == 14
    assert ayse.carried_over == Decimal("3")
    assert ayse.used == 6
    assert ayse.remaining == Decimal("11")
    assert ayse.usage_pct == 35

    # İZ 143-149: 1 yıl 4 ay · 14 · 0 · 5 · 9 · %36
    assert (mehmet.seniority_years, mehmet.seniority_months) == (1, 4)
    assert mehmet.carried_over == Decimal("0")
    assert mehmet.remaining == Decimal("9")
    assert mehmet.usage_pct == 36

    # İZ 152-158: 1 yıl 6 ay · 14 · 6 · 12 · 8 · %60
    assert (hasan.seniority_years, hasan.seniority_months) == (1, 6)
    assert hasan.carried_over == Decimal("6")
    assert hasan.used == 12
    assert hasan.remaining == Decimal("8")
    assert hasan.usage_pct == 60

    # İZ 161-167: kıdem 5 ay → hak "—", kalan "Hak yok", kullanım "1 yıl dolunca".
    assert (sercan.seniority_years, sercan.seniority_months) == (0, 5)
    assert sercan.annual_entitlement is None
    assert sercan.remaining is None
    assert sercan.usage_pct is None
    assert sercan.used == 0


# --- 3. 🔴 NULL/fail-closed: bilinmeyen hak toplamlara SIZMAZ ---------------


async def test_hire_date_yok_toplamlara_sizmaz(seeded_db: AsyncSession) -> None:
    """`hire_date` NULL → hak BİLİNMEZ: satır `null` basar, borç toplamına GİRMEZ."""
    await _mk_personnel(seeded_db, "Tarihsiz", hire_date=None)
    await _mk_personnel(seeded_db, "Kıdemli", hire_date=date(2024, 1, 10))

    ozet = await service.build_hr_leaves_summary(seeded_db, year=YIL, today=BUGUN)

    assert ozet.unknown_entitlement_personnel == 1
    assert ozet.total_leave_debt == Decimal("14")  # yalnız kıdemli personelin kalanı
    tarihsiz = next(r for r in ozet.balances if r.personnel_name == "Tarihsiz")
    assert tarihsiz.annual_entitlement is None
    assert tarihsiz.remaining is None
    assert tarihsiz.seniority_years is None  # 0 DEĞİL: kıdem bilinmiyor


async def test_negatif_kalan_borcu_azaltmaz(seeded_db: AsyncSession, yillik: LeaveType) -> None:
    """Fazla kullanılmış (negatif kalan) personel şirketin BORCUNU AZALTMAZ.

    Borç, personele HÂLÂ borçlu olunan gündür; negatif kalan ters yönlü bir
    alacaktır ve netleştirilirse ekrandaki toplam sessizce küçülürdü.
    """
    borclu = await _mk_personnel(seeded_db, "Fazla Kullanan", hire_date=date(2024, 1, 10))
    await _mk_personnel(seeded_db, "Normal", hire_date=date(2024, 1, 10))
    await _mk_request(seeded_db, borclu, yillik, date(2026, 2, 1), date(2026, 3, 12))  # 40 gün

    ozet = await service.build_hr_leaves_summary(seeded_db, year=YIL, today=BUGUN)

    satir = next(r for r in ozet.balances if r.personnel_name == "Fazla Kullanan")
    assert satir.remaining == Decimal("-26")  # satırda GÖRÜNÜR (kırpılmaz)
    assert ozet.total_leave_debt == Decimal("14")  # ama toplamı aşağı ÇEKMEZ


# --- 4. kapsam: yalnız aktif + yayında personel -----------------------------


async def test_pasif_ve_taslak_personel_sayilmaz(
    seeded_db: AsyncSession, yillik: LeaveType
) -> None:
    """İK-1 özet kanonu: taslak/pasif personel hiçbir sayaca ve tabloya girmez."""
    pasif = await _mk_personnel(seeded_db, "Ayrılmış", hire_date=date(2024, 1, 10), active=False)
    taslak = await _mk_personnel(seeded_db, "Taslak", hire_date=date(2024, 1, 10), draft=True)
    await _mk_request(
        seeded_db, pasif, yillik, date(2026, 6, 10), date(2026, 6, 20), LeaveStatus.pending
    )
    await _mk_request(seeded_db, taslak, yillik, date(2026, 6, 10), date(2026, 6, 20))

    ozet = await service.build_hr_leaves_summary(seeded_db, year=YIL, today=BUGUN)

    assert ozet.balances == []
    assert ozet.pending_requests == 0
    assert ozet.on_leave_today == 0
    assert ozet.days_used_this_month == 0
    assert ozet.total_leave_debt == Decimal("0")


# --- 5. pencere sınırları: bugün / bu ay / yıl ------------------------------


async def test_bugun_izinli_sinirlari(seeded_db: AsyncSession, yillik: LeaveType) -> None:
    """ "Bugün İzinli" ARALIK KAPSAMIDIR: bitişi bugün olan sayılır, dünkü sayılmaz."""
    biten = await _mk_personnel(seeded_db, "Dün Bitti", hire_date=date(2024, 1, 10))
    bugun_biten = await _mk_personnel(seeded_db, "Bugün Bitiyor", hire_date=date(2024, 1, 10))
    baslayan = await _mk_personnel(seeded_db, "Bugün Başladı", hire_date=date(2024, 1, 10))
    bekleyen = await _mk_personnel(seeded_db, "Onaysız", hire_date=date(2024, 1, 10))
    await _mk_request(seeded_db, biten, yillik, date(2026, 6, 10), date(2026, 6, 14))
    await _mk_request(seeded_db, bugun_biten, yillik, date(2026, 6, 10), BUGUN)
    await _mk_request(seeded_db, baslayan, yillik, BUGUN, date(2026, 6, 20))
    # Onaylanmamış talep kişiyi izinli YAPMAZ.
    await _mk_request(
        seeded_db, bekleyen, yillik, date(2026, 6, 1), date(2026, 6, 30), LeaveStatus.pending
    )

    ozet = await service.build_hr_leaves_summary(seeded_db, year=YIL, today=BUGUN)

    assert ozet.on_leave_today == 2


async def test_bu_ay_kullanilan_ay_penceresi(seeded_db: AsyncSession, yillik: LeaveType) -> None:
    """ "Bu Ay Kullanılan" izin BAŞLADIĞI aya yazılır (`leave_year` kararının ay hâli)."""
    p = await _mk_personnel(seeded_db, "Tek Kişi", hire_date=date(2024, 1, 10))
    await _mk_request(seeded_db, p, yillik, date(2026, 5, 28), date(2026, 6, 2))  # 6 gün, MAYIS
    await _mk_request(seeded_db, p, yillik, date(2026, 6, 1), date(2026, 6, 3))  # 3 gün, HAZİRAN

    ozet = await service.build_hr_leaves_summary(seeded_db, year=YIL, today=BUGUN)

    assert ozet.days_used_this_month == 3
    assert ozet.balances[0].used == 9  # yıl toplamı ikisini de sayar


async def test_year_suzgeci(seeded_db: AsyncSession, yillik: LeaveType) -> None:
    """İZ 120 yıl seçici: bakiye penceresi `?year=` ile kayar."""
    p = await _mk_personnel(seeded_db, "Yıl Sınırı", hire_date=date(2023, 1, 10))
    await _mk_request(seeded_db, p, yillik, date(2025, 4, 1), date(2025, 4, 5))  # 5 gün, 2025

    bu_yil = await service.build_hr_leaves_summary(seeded_db, year=YIL, today=BUGUN)
    gecen_yil = await service.build_hr_leaves_summary(seeded_db, year=2025, today=BUGUN)

    assert bu_yil.balances[0].used == 0
    assert gecen_yil.balances[0].used == 5
    assert gecen_yil.year == 2025
    # "Bugün İzinli"/"Bekleyen" pencereleri YILDAN bağımsızdır (bugüne bağlıdır).
    assert gecen_yil.on_leave_today == bu_yil.on_leave_today == 0


# --- 6. devreden risk tanımı ------------------------------------------------


async def test_devreden_risk_tanimi(seeded_db: AsyncSession, yillik: LeaveType) -> None:
    """Risk = devredeni VAR **ve** kalanı DURUYOR (yıl sonunda yanabilir).

    Devredeni olmayan kişi risk değildir; kalanı tükenmiş kişi de değildir
    (yanacak gün kalmamıştır).
    """
    riskli = await _mk_personnel(seeded_db, "Riskli", hire_date=date(2024, 1, 10))
    tuketen = await _mk_personnel(seeded_db, "Tüketen", hire_date=date(2024, 1, 10))
    await _mk_personnel(seeded_db, "Devredensiz", hire_date=date(2024, 1, 10))
    await _mk_balance(seeded_db, riskli, "5")
    await _mk_balance(seeded_db, tuketen, "5")
    await _mk_request(seeded_db, tuketen, yillik, date(2026, 2, 1), date(2026, 3, 11))  # 39 gün

    ozet = await service.build_hr_leaves_summary(seeded_db, year=YIL, today=BUGUN)

    assert ozet.carryover_risk_personnel == 1


# --- 7. N+1: sorgu sayısı sabit ---------------------------------------------


async def _ozet_sorgu_sayisi(db: AsyncSession, kisi_sayisi: int, etiket: str) -> int:
    tip = await _mk_type(db, f"Yıllık {etiket}", deducts=True)
    for i in range(kisi_sayisi):
        p = await _mk_personnel(db, f"K{etiket}{i:03d}", hire_date=date(2024, 1, 10))
        await _mk_balance(db, p, "1")
        await _mk_request(db, p, tip, date(2026, 3, 1), date(2026, 3, 3))

    sayac: list[str] = []

    def kaydet(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        alt = statement.lower()
        if "personnel" in alt or "leave_" in alt:
            sayac.append(alt)

    event.listen(test_engine.sync_engine, "before_cursor_execute", kaydet)
    try:
        await service.build_hr_leaves_summary(db, year=YIL, today=BUGUN)
    finally:
        event.remove(test_engine.sync_engine, "before_cursor_execute", kaydet)
    return len(sayac)


async def test_n_plus_1_sabit_sorgu(seeded_db: AsyncSession) -> None:
    """Aggrega + group-by kanıtı: 2 vs 10 personelde sorgu sayısı AYNI."""
    iki = await _ozet_sorgu_sayisi(seeded_db, 2, "A")
    on = await _ozet_sorgu_sayisi(seeded_db, 10, "B")

    assert iki == on, f"N+1: sorgu sayısı veriyle değişti ({iki} vs {on})"


# --- 8. liste tavanı --------------------------------------------------------


async def test_bakiye_tablosu_50_tavani(seeded_db: AsyncSession) -> None:
    """Tablo 50'de kırpılır ama KPI'lar TÜM personeli sayar (İK-1 emsali)."""
    for i in range(55):
        await _mk_personnel(seeded_db, f"P{i:03d}", hire_date=date(2024, 1, 10))

    ozet = await service.build_hr_leaves_summary(seeded_db, year=YIL, today=BUGUN)

    assert len(ozet.balances) == service.SUMMARY_LIST_LIMIT
    assert ozet.total_leave_debt == Decimal("770")  # 55 × 14 — KPI kırpılmaz


# --- 9. yetki + endpoint wiring ---------------------------------------------


async def test_endpoint_view_yeter_200(client, sef_headers: dict[str, str]) -> None:
    """`site_chief` = `personnel=view`: özet ucu OKUMAYA açıktır → 200."""
    yanit = await client.get("/hr/leaves/summary", headers=sef_headers)
    assert yanit.status_code == 200, yanit.text
    govde = yanit.json()
    for anahtar in (
        "pending_requests",
        "on_leave_today",
        "days_used_this_month",
        "total_leave_debt",
        "carryover_risk_personnel",
        "unknown_entitlement_personnel",
        "balances",
        "year",
    ):
        assert anahtar in govde
    assert govde["year"] == date.today().year  # süzgeç verilmezse İÇİNDE BULUNULAN yıl


async def test_endpoint_yetkisiz_403(client, yetkisiz_headers: dict[str, str]) -> None:
    """`procurement` = `personnel=none`: 403."""
    yanit = await client.get("/hr/leaves/summary", headers=yetkisiz_headers)
    assert yanit.status_code == 403, yanit.text


async def test_endpoint_proje_kapsami_daraltmaz(
    client, kisitli_ik_headers: dict[str, str], seeded_db: AsyncSession
) -> None:
    """`personnel` ŞİRKET-GENELİDİR: proje görünürlüğü daraltılmış İK yine görür.

    IDOR kanonu bu modülde kapsam SÜZGECİ değil, izin SEVİYESİDİR (403 testi):
    kapsam süzgeci uydurulsaydı İK kendi personelini kaybederdi.
    """
    await _mk_personnel(seeded_db, "Şirket Geneli", hire_date=date(2024, 1, 10))
    yanit = await client.get("/hr/leaves/summary", headers=kisitli_ik_headers)
    assert yanit.status_code == 200, yanit.text
    assert [r["personnel_name"] for r in yanit.json()["balances"]] == ["Şirket Geneli"]


async def test_endpoint_year_suzgeci_sinirli(client, ik_headers: dict[str, str]) -> None:
    """`?year=` bakiye uçlarıyla AYNI aralıkta (2000-2100) — anlamsız yıl 422."""
    assert (await client.get("/hr/leaves/summary?year=2025", headers=ik_headers)).json()[
        "year"
    ] == 2025
    yanit = await client.get("/hr/leaves/summary?year=1999", headers=ik_headers)
    assert yanit.status_code == 422, yanit.text


async def test_endpoint_gercek_veri(
    client, ik_headers: dict[str, str], seeded_db: AsyncSession
) -> None:
    """Endpoint yolu (today=date.today()) gerçek veriyle uçtan uca hesaplar."""
    bugun = date.today()
    tip = await _mk_type(seeded_db, "Yıllık İzin", deducts=True)
    p = await _mk_personnel(seeded_db, "Canlı", hire_date=date(bugun.year - 3, 1, 10))
    await _mk_request(seeded_db, p, tip, bugun, bugun, LeaveStatus.approved)

    yanit = await client.get("/hr/leaves/summary", headers=ik_headers)
    assert yanit.status_code == 200, yanit.text
    govde = yanit.json()
    assert govde["on_leave_today"] == 1
    assert govde["days_used_this_month"] == 1
    assert govde["balances"][0]["personnel_name"] == "Canlı"
    assert uuid.UUID(govde["balances"][0]["personnel_id"]) == p.id
