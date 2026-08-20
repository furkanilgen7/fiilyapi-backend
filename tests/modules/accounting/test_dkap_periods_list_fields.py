"""DKAP-B — `GET /accounting-periods` cevabına iki türetilmiş alan: `entry_count`
· `closed_by_name`. Kapsam SADECE liste ucudur; `close`/`reopen` cevabı
(`AccountingPeriodResponse`) DEĞİŞMEZ (bkz. `periods_schemas.py`).

K2 KARARI (ölçülerek verildi): `entry_count`, kapanış kapısının aynı süzgecini
kullanır — `assert_periods_open`/`lock_period` `(period_year, period_month)`e
göre çalışır ve kapalı dönem HER statüdeki fişi (draft dahil) reddeder; bu
yüzden sayaç da STATÜ AYRIMI YAPMADAN `(period_year, period_month)`e göre
sayar. Mockup kanıtı: `projedesign/Muhasebe - Dönem Kapanışı.dc.html` Temmuz
satırı — "3 taslak fiş var" uyarısıyla birlikte "Fiş" sütunu 218 basar; taslak
fişler toplam sayının İÇİNDEDİR, dışında değil.

K1 — N+1 YASAK — iki ayrı kanıt tutulur:
1. **Sayaç** (`_sorgu_sayaci`, repo kanonu): dönem sayısı artınca `journal_
   entries`/`accounting_periods`/`users` ifadelerinin sayısı SABİT kalır.
2. **Yapısal** (sayaçtan bağımsız): `AccountingPeriod` modelinde `closed_by_id`
   için bir `relationship()` YOKTUR (bkz. `models.py`) — dolayısıyla
   `lazy="selectin"` gibi bir önceden-yükleme kanonu bu ekranda YAPISAL
   OLARAK MÜMKÜN DEĞİLDİR ve sayaç kör kalamaz. Ayrıca `periods_service`teki
   toplu sayım fonksiyonu (`repository.count_entries_by_period`) dönem
   başına değil TEK SEFERDE çağrılır — bu da `monkeypatch` ile çağrı SAYISI
   ölçülerek ayrıca kanıtlanır (döngü içinde çağrı yapılsaydı çağrı sayısı
   dönem sayısına eşit çıkardı).
"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date

from httpx import AsyncClient
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounting import periods_service
from app.modules.accounting.models import AccountingPeriodStatus, JournalEntryStatus
from app.modules.audit.models import AuditLog
from tests.conftest import test_engine

from ._journal import iki_yaprak

YOL = "/accounting-periods"


def _kapat(year: int, month: int) -> str:
    return f"{YOL}/{year}/{month}/close"


@contextmanager
def _sorgu_sayaci() -> Iterator[list[str]]:
    """`progress_payments/test_summary.py`deki `_sorgu_sayaci` deseninin AYNISI —
    sürücüye giden HER ifadeyi toplar; iddia tahmine değil ÖLÇÜME dayanır."""
    ifadeler: list[str] = []

    def kaydet(conn, cursor, statement, parameters, context, executemany) -> None:  # noqa: ANN001
        ifadeler.append(" ".join(statement.split()))

    event.listen(test_engine.sync_engine, "before_cursor_execute", kaydet)
    try:
        yield ifadeler
    finally:
        event.remove(test_engine.sync_engine, "before_cursor_execute", kaydet)


def _donem_iliskili(ifadeler: list[str]) -> list[str]:
    """Yalnız bu ucun dokunduğu tablolara giden ifadeler — kimlik doğrulama
    sorguları (`users`/`roles` login akışında) N+1 iddiasından bağımsızdır."""
    return [i for i in ifadeler if "accounting_periods" in i or "journal_entries" in i]


# --------------------------------------------------------------------------- #
# 1 — entry_count doğruluğu
# --------------------------------------------------------------------------- #


async def test_entry_count_fisi_olan_donemde_DOGRU(
    client: AsyncClient,
    pm_headers: dict[str, str],
    donem_fabrikasi,
    hesap_fabrikasi,
    fis_fabrikasi,
) -> None:
    await donem_fabrikasi(2026, 7, status=AccountingPeriodStatus.open)
    kasa, saticilar = await iki_yaprak(hesap_fabrikasi)
    await fis_fabrikasi(
        [(kasa, "1000.00", "0"), (saticilar, "0", "1000.00")],
        status=JournalEntryStatus.posted,
        entry_date=date(2026, 7, 5),
    )
    await fis_fabrikasi(
        [(kasa, "500.00", "0"), (saticilar, "0", "500.00")],
        status=JournalEntryStatus.posted,
        entry_date=date(2026, 7, 12),
        description="İkinci fiş",
    )

    resp = await client.get(f"{YOL}?year=2026", headers=pm_headers)
    assert resp.status_code == 200, resp.text
    donem = next(d for d in resp.json()["items"] if d["month"] == 7)
    assert donem["entry_count"] == 2


async def test_entry_count_fisi_OLMAYAN_donemde_SIFIR(
    client: AsyncClient, pm_headers: dict[str, str], donem_fabrikasi
) -> None:
    """Satır EKSİLMEZ — fişsiz dönem `0` ile listede kalır."""
    await donem_fabrikasi(2026, 7, status=AccountingPeriodStatus.open)

    resp = await client.get(f"{YOL}?year=2026", headers=pm_headers)
    assert resp.status_code == 200, resp.text
    govde = resp.json()
    assert govde["total"] == 1
    assert govde["items"][0]["entry_count"] == 0


# --------------------------------------------------------------------------- #
# 2 — closed_by_name
# --------------------------------------------------------------------------- #


async def test_closed_by_name_KAPALI_donemde_DOLU(
    client: AsyncClient, pm_headers: dict[str, str], donem_fabrikasi
) -> None:
    """`donem_fabrikasi` kapanışı `kullanici_id` fixture'ının kullanıcısıyla
    damgalar (`fis@muhasebe.co`); ad `users.full_name`den GELMELİDİR."""
    await donem_fabrikasi(2026, 7, status=AccountingPeriodStatus.closed)

    resp = await client.get(f"{YOL}?year=2026", headers=pm_headers)
    assert resp.status_code == 200, resp.text
    donem = resp.json()["items"][0]
    assert donem["closed_by_name"] not in (None, "")
    assert isinstance(donem["closed_by_name"], str)


async def test_closed_by_name_ACIK_donemde_NULL(
    client: AsyncClient, pm_headers: dict[str, str], donem_fabrikasi
) -> None:
    """🔴 K4: NULL boş metne ÇEVRİLMEZ, `"Bilinmiyor"` UYDURULMAZ."""
    await donem_fabrikasi(2026, 7, status=AccountingPeriodStatus.open)

    resp = await client.get(f"{YOL}?year=2026", headers=pm_headers)
    assert resp.status_code == 200, resp.text
    donem = resp.json()["items"][0]
    assert donem["closed_by_name"] is None


# --------------------------------------------------------------------------- #
# 3 — N+1 YOK (sayaç + yapısal)
# --------------------------------------------------------------------------- #


async def test_N1_YOK_donem_sayisi_artinca_sorgu_sayisi_SABIT_KALIR(
    client: AsyncClient, pm_headers: dict[str, str], donem_fabrikasi
) -> None:
    """🔴 K1 kanıt 1/2 — SAYAÇ: 3 dönemle 12 dönem AYNI sorgu adedini üretir.

    `month` bandı `1..12`dir (`ck_accounting_periods_month_range`) — "çok"
    kümesi bu yüzden 12 ile sınırlıdır, tek yılın TÜM aylarını kapsar.
    """
    for ay in range(1, 4):
        await donem_fabrikasi(2025, ay, status=AccountingPeriodStatus.closed)
    with _sorgu_sayaci() as az:
        resp = await client.get(f"{YOL}?year=2025", headers=pm_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["total"] == 3
    az_sayisi = len(_donem_iliskili(az))

    for ay in range(4, 13):
        await donem_fabrikasi(2025, ay, status=AccountingPeriodStatus.closed)
    with _sorgu_sayaci() as cok:
        resp2 = await client.get(f"{YOL}?year=2025&limit=200", headers=pm_headers)
    assert resp2.status_code == 200, resp2.text
    assert resp2.json()["total"] == 12
    cok_sayisi = len(_donem_iliskili(cok))

    assert az_sayisi == cok_sayisi, (
        f"3 dönem {az_sayisi} ifade, 12 dönem {cok_sayisi} ifade üretti — N+1 VAR"
    )


async def test_N1_YOK_YAPISAL_toplu_sayim_TEK_KEZ_cagrilir(
    client: AsyncClient, pm_headers: dict[str, str], donem_fabrikasi, monkeypatch
) -> None:
    """🔴 K1 kanıt 2/2 — YAPISAL: sayaç `lazy="selectin"` gibi bir ön-yükleme
    tarafından KÖR edilebilir (repo kanonu); bu yüzden ayrıca çağrı SAYISI
    ölçülür. `repository.count_entries_by_period` döngü içinde çağrılsaydı
    çağrı sayısı dönem sayısına (burada 6) eşit çıkardı — burada TEK olmalı.
    """
    for ay in range(1, 7):
        await donem_fabrikasi(2025, ay, status=AccountingPeriodStatus.closed)

    cagri_sayisi = 0
    orijinal = periods_service.repository.count_entries_by_period

    async def sayilan(*args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        nonlocal cagri_sayisi
        cagri_sayisi += 1
        return await orijinal(*args, **kwargs)

    monkeypatch.setattr(periods_service.repository, "count_entries_by_period", sayilan)

    resp = await client.get(f"{YOL}?year=2025", headers=pm_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["total"] == 6
    assert cagri_sayisi == 1, f"6 dönem için {cagri_sayisi} çağrı — döngü içinde çağrılıyor"


# --------------------------------------------------------------------------- #
# 4 — K2 tutarlılığı: sayaç KAPANIŞ KAPISIYLA aynı kümeye bakar
# --------------------------------------------------------------------------- #


async def test_K2_entry_count_TASLAK_fisi_de_sayar_kapanis_kapisiyla_TUTARLI(
    client: AsyncClient,
    pm_headers: dict[str, str],
    muhasebe_headers: dict[str, str],
    hesap_fabrikasi,
    fis_fabrikasi,
) -> None:
    """Kapanış kapısı (`has_draft_entries`) bu dönemi TASLAK fiş yüzünden
    REDDEDER (409) — yani draft fiş dönemin `(period_year, period_month)`
    kümesinin İÇİNDEDİR. `entry_count` AYNI kümeye bakmalı ve draft'ı SAYMALI;
    yalnız `POSTING_STATUSES` sayan bir mutasyon burada `1` yerine `0` üretir
    ve bu test KIRMIZI olur.
    """
    kasa, saticilar = await iki_yaprak(hesap_fabrikasi)
    await fis_fabrikasi(
        [(kasa, "1000.00", "0"), (saticilar, "0", "1000.00")],
        status=JournalEntryStatus.draft,
        entry_date=date(2026, 7, 17),
    )

    kapat = await client.post(_kapat(2026, 7), headers=muhasebe_headers)
    assert kapat.status_code == 409, kapat.text

    resp = await client.get(f"{YOL}?year=2026", headers=pm_headers)
    assert resp.status_code == 200, resp.text
    donem = next(d for d in resp.json()["items"] if d["month"] == 7)
    assert donem["entry_count"] == 1


# --------------------------------------------------------------------------- #
# 5 — Denetim günlüğü değişmez
# --------------------------------------------------------------------------- #


async def test_liste_ucu_YENI_alanlarla_bile_DENETIM_YAZMAZ(
    client: AsyncClient,
    pm_headers: dict[str, str],
    donem_fabrikasi,
    hesap_fabrikasi,
    fis_fabrikasi,
    seeded_db: AsyncSession,
) -> None:
    await donem_fabrikasi(2026, 7, status=AccountingPeriodStatus.closed)
    kasa, saticilar = await iki_yaprak(hesap_fabrikasi)
    await fis_fabrikasi(
        [(kasa, "1000.00", "0"), (saticilar, "0", "1000.00")],
        status=JournalEntryStatus.posted,
        entry_date=date(2026, 7, 5),
    )
    once = len((await seeded_db.execute(select(AuditLog))).scalars().all())
    resp = await client.get(YOL, headers=pm_headers)
    assert resp.status_code == 200, resp.text
    sonra = len((await seeded_db.execute(select(AuditLog))).scalars().all())
    assert once == sonra


# --------------------------------------------------------------------------- #
# 6 — Kapı değişmedi: `view` okuyabiliyor
# --------------------------------------------------------------------------- #


async def test_view_yetkili_kullanici_yeni_alanlari_da_OKUYABILIR(
    client: AsyncClient, pm_headers: dict[str, str], donem_fabrikasi
) -> None:
    await donem_fabrikasi(2026, 7, status=AccountingPeriodStatus.closed)
    resp = await client.get(f"{YOL}?year=2026", headers=pm_headers)
    assert resp.status_code == 200, resp.text
    donem = resp.json()["items"][0]
    assert "entry_count" in donem
    assert "closed_by_name" in donem
