"""MU-2 T3 — dönem kilidi UÇLARI: liste · kapat · aç.

🔴 **HEPSİ HTTP UCUNDAN geçer** (MU-1 dersi): modeli doğrudan kurup
`session.add()` yapan bir test yetki kapısını, `Path` aralık denetimini ve K7
zarfını **ASLA** sınamaz — o katmanlar yalnızca istek FastAPI'ye girdiğinde
koşar. Bu dosyada tek istisna KURULUM fabrikalarıdır (`donem_fabrikasi`,
`fis_fabrikasi`); iddia edilen her davranış uçtan ölçülür.

İzin seviyeleri (`accounting` modülü, seed matrisi `[_A,_F,_N,_N,_N,_F,_V,_N]`):

| Uç | Seviye | Geçen roller |
|---|---|---|
| `GET /accounting-periods` | `view` | PM · muhasebe · patron · sysadmin |
| `POST …/close` | `full` | muhasebe · patron · sysadmin (**PM 403**) |
| `POST …/reopen` | **`admin`** | YALNIZ sysadmin (**muhasebe 403**) |

`reopen`in `admin` olması `DELETE /journal-entries/{id}` ile aynı gerekçedir:
kapanmış bir dönemi yeniden açmak MALİ İZİ geri sarar; `full` (muhasebe) bunu
kendi başına yapamamalıdır.
"""

from datetime import date

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounting.models import (
    AccountingPeriod,
    AccountingPeriodStatus,
    JournalEntryStatus,
)
from app.modules.audit.models import AuditAction, AuditLog

from ._journal import iki_yaprak

YOL = "/accounting-periods"


def _kapat(year: int, month: int) -> str:
    return f"{YOL}/{year}/{month}/close"


def _ac(year: int, month: int) -> str:
    return f"{YOL}/{year}/{month}/reopen"


# --------------------------------------------------------------------------- #
# Uç 1 — GET /accounting-periods
# --------------------------------------------------------------------------- #


async def test_liste_K7_zarfini_dondurur(
    client: AsyncClient, pm_headers: dict[str, str], donem_fabrikasi
) -> None:
    """K7: `items` + `total` + `limit` + `offset` — dördü de zorunludur."""
    await donem_fabrikasi(2026, 7)
    resp = await client.get(YOL, headers=pm_headers)
    assert resp.status_code == 200, resp.text
    govde = resp.json()
    assert set(govde) == {"items", "total", "limit", "offset"}
    assert govde["total"] == 1
    assert govde["limit"] == 50 and govde["offset"] == 0
    assert govde["items"][0]["year"] == 2026
    assert govde["items"][0]["month"] == 7
    assert govde["items"][0]["status"] == "closed"


async def test_liste_YETKISIZ_role_403(
    client: AsyncClient, yetkisiz_headers: dict[str, str]
) -> None:
    """`site_chief` (`accounting=_N`) okumada bile geçemez."""
    resp = await client.get(YOL, headers=yetkisiz_headers)
    assert resp.status_code == 403, resp.text


async def test_liste_limit_TAVANI_ASILIRSA_422_KIRPILMAZ(
    client: AsyncClient, pm_headers: dict[str, str]
) -> None:
    """🔴 Tavan aşımı SESSİZCE KIRPILMAZ (K7): 201 → 422, 200 → 200."""
    assert (await client.get(f"{YOL}?limit=201", headers=pm_headers)).status_code == 422
    assert (await client.get(f"{YOL}?limit=200", headers=pm_headers)).status_code == 200
    assert (await client.get(f"{YOL}?limit=0", headers=pm_headers)).status_code == 422


async def test_liste_year_suzgeci(
    client: AsyncClient, pm_headers: dict[str, str], donem_fabrikasi
) -> None:
    await donem_fabrikasi(2025, 12)
    await donem_fabrikasi(2026, 1)
    resp = await client.get(f"{YOL}?year=2026", headers=pm_headers)
    assert resp.status_code == 200, resp.text
    govde = resp.json()
    assert govde["total"] == 1
    assert govde["items"][0]["year"] == 2026


async def test_liste_siralamasi_yil_ay_AZALAN(
    client: AsyncClient, pm_headers: dict[str, str], donem_fabrikasi
) -> None:
    """En yeni dönem başta — fiş listesinin `entry_date DESC` kanonuyla aynı."""
    for yil, ay in ((2025, 12), (2026, 3), (2026, 1)):
        await donem_fabrikasi(yil, ay)
    resp = await client.get(YOL, headers=pm_headers)
    assert resp.status_code == 200, resp.text
    assert [(d["year"], d["month"]) for d in resp.json()["items"]] == [
        (2026, 3),
        (2026, 1),
        (2025, 12),
    ]


# --------------------------------------------------------------------------- #
# Yol parametresi aralığı — 422, 500 DEĞİL
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("yil", "ay"),
    [(1999, 7), (2101, 7), (2026, 0), (2026, 13)],
)
async def test_yol_parametresi_ARALIK_DISI_422(
    client: AsyncClient, admin_headers: dict[str, str], yil: int, ay: int
) -> None:
    """🔴 Aralık `Path(...)`ta durur, modelin CHECK'ine DÜŞÜRÜLMEZ.

    Düşürülseydi `IntegrityError` handler'ı ayrımsız bir 409 (ya da 500) basar
    ve kullanıcı `month=13`ün neden reddedildiğini hiç öğrenemezdi.
    """
    assert (await client.post(_kapat(yil, ay), headers=admin_headers)).status_code == 422
    assert (await client.post(_ac(yil, ay), headers=admin_headers)).status_code == 422


# --------------------------------------------------------------------------- #
# Uç 2 — POST …/close
# --------------------------------------------------------------------------- #


async def test_kapatma_SATIR_YOKSA_upsert_ile_acilir(
    client: AsyncClient, muhasebe_headers: dict[str, str], seeded_db: AsyncSession
) -> None:
    """🔴 Dönem satırı PROAKTİF açılmaz; ilk `close` onu UPSERT ile doğurur."""
    resp = await client.post(_kapat(2026, 7), headers=muhasebe_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "closed"

    satirlar = (await seeded_db.execute(select(AccountingPeriod))).scalars().all()
    assert len(satirlar) == 1
    assert (satirlar[0].year, satirlar[0].month) == (2026, 7)


async def test_kapatma_DAMGAYI_yazar(
    client: AsyncClient, muhasebe_headers: dict[str, str], seeded_db: AsyncSession
) -> None:
    """`ck_accounting_periods_closed_stamp`: üçü BİRLİKTE yazılır."""
    resp = await client.post(_kapat(2026, 7), headers=muhasebe_headers)
    assert resp.status_code == 200, resp.text
    govde = resp.json()
    assert govde["closed_at"] is not None
    assert govde["closed_by_id"] is not None


async def test_kapatma_FULL_ister_PM_403(
    client: AsyncClient, pm_headers: dict[str, str], yetkisiz_headers: dict[str, str]
) -> None:
    """PM `view` taşır ve okur ama KAPATAMAZ."""
    assert (await client.post(_kapat(2026, 7), headers=pm_headers)).status_code == 403
    assert (await client.post(_kapat(2026, 7), headers=yetkisiz_headers)).status_code == 403


async def test_kapali_donemi_TEKRAR_kapatmak_409(
    client: AsyncClient, muhasebe_headers: dict[str, str], donem_fabrikasi
) -> None:
    await donem_fabrikasi(2026, 7)
    resp = await client.post(_kapat(2026, 7), headers=muhasebe_headers)
    assert resp.status_code == 409, resp.text


async def test_kapatma_TASLAK_fis_varsa_409(
    client: AsyncClient, muhasebe_headers: dict[str, str], hesap_fabrikasi, fis_fabrikasi
) -> None:
    """🔴 Dengesiz/eksik kayıt kapanışa GİRMEZ: `draft` fiş kapıyı kapatır."""
    kasa, saticilar = await iki_yaprak(hesap_fabrikasi)
    await fis_fabrikasi(
        [(kasa, "1000.00", "0"), (saticilar, "0", "1000.00")],
        status=JournalEntryStatus.draft,
        entry_date=date(2026, 7, 17),
    )
    resp = await client.post(_kapat(2026, 7), headers=muhasebe_headers)
    assert resp.status_code == 409, resp.text


async def test_kapatma_POSTED_ve_REVERSED_fis_ENGELLEMEZ(
    client: AsyncClient, muhasebe_headers: dict[str, str], hesap_fabrikasi, fis_fabrikasi
) -> None:
    """Kapanışın amacı MALİ İZİ DONDURMAKTIR; kayıtlı fiş engel değildir.

    `posted` fiş de engelleseydi hiçbir dönem asla kapanamazdı.
    """
    kasa, saticilar = await iki_yaprak(hesap_fabrikasi)
    await fis_fabrikasi(
        [(kasa, "1000.00", "0"), (saticilar, "0", "1000.00")],
        status=JournalEntryStatus.posted,
        entry_date=date(2026, 7, 17),
    )
    orijinal = await fis_fabrikasi(
        [(kasa, "500.00", "0"), (saticilar, "0", "500.00")],
        status=JournalEntryStatus.reversed,
        entry_date=date(2026, 7, 18),
    )
    assert orijinal is not None
    resp = await client.post(_kapat(2026, 7), headers=muhasebe_headers)
    assert resp.status_code == 200, resp.text


async def test_kapatma_baska_DONEMDEKI_taslagi_saymaz(
    client: AsyncClient, muhasebe_headers: dict[str, str], hesap_fabrikasi, fis_fabrikasi
) -> None:
    """Süzgeç `(period_year, period_month)`tir — komşu ayın taslağı engellemez."""
    kasa, saticilar = await iki_yaprak(hesap_fabrikasi)
    await fis_fabrikasi(
        [(kasa, "1000.00", "0"), (saticilar, "0", "1000.00")],
        status=JournalEntryStatus.draft,
        entry_date=date(2026, 8, 3),
    )
    resp = await client.post(_kapat(2026, 7), headers=muhasebe_headers)
    assert resp.status_code == 200, resp.text


# --------------------------------------------------------------------------- #
# Uç 3 — POST …/reopen
# --------------------------------------------------------------------------- #


async def test_acma_ADMIN_ister_muhasebe_403(
    client: AsyncClient, muhasebe_headers: dict[str, str], donem_fabrikasi
) -> None:
    """🔴 `full` YETMEZ: yeniden açmak mali izi geri sarar (DELETE emsali)."""
    await donem_fabrikasi(2026, 7)
    resp = await client.post(_ac(2026, 7), headers=muhasebe_headers)
    assert resp.status_code == 403, resp.text


async def test_acma_DAMGAYI_SOKER(
    client: AsyncClient, admin_headers: dict[str, str], donem_fabrikasi
) -> None:
    """`open` dönemde damga NULL'dır — CHECK'in ters yönü."""
    await donem_fabrikasi(2026, 7)
    resp = await client.post(_ac(2026, 7), headers=admin_headers)
    assert resp.status_code == 200, resp.text
    govde = resp.json()
    assert govde["status"] == "open"
    assert govde["closed_at"] is None
    assert govde["closed_by_id"] is None


async def test_acik_donemi_ACMAK_409(
    client: AsyncClient, admin_headers: dict[str, str], donem_fabrikasi
) -> None:
    await donem_fabrikasi(2026, 7, status=AccountingPeriodStatus.open)
    resp = await client.post(_ac(2026, 7), headers=admin_headers)
    assert resp.status_code == 409, resp.text


async def test_acma_SATIR_YOKSA_409(
    client: AsyncClient, admin_headers: dict[str, str], seeded_db: AsyncSession
) -> None:
    """Kayıt yoksa dönem AÇIKTIR (YAGNI) → onu açmak 409'dur.

    Satır yine de UPSERT ile doğar: kilitlenecek bir satır olmadan iki eşzamanlı
    istek serileşemezdi. 409 kararı KİLİTLİ satır üzerinde verilir.
    """
    resp = await client.post(_ac(2026, 7), headers=admin_headers)
    assert resp.status_code == 409, resp.text


# --------------------------------------------------------------------------- #
# Denetim — YENİ `AuditAction` üyesi AÇILMADI
# --------------------------------------------------------------------------- #


async def test_kapatma_APPROVE_acma_UPDATE_denetimi_yazar(
    client: AsyncClient, admin_headers: dict[str, str], seeded_db: AsyncSession
) -> None:
    """Ayrım `AuditAction`da DEĞİL METİNDEDİR (TB3/T3 kanonu)."""
    assert (await client.post(_kapat(2026, 7), headers=admin_headers)).status_code == 200
    kapanis = (
        (await seeded_db.execute(select(AuditLog).where(AuditLog.action == AuditAction.approve)))
        .scalars()
        .all()
    )
    assert len(kapanis) == 1
    assert "2026" in kapanis[0].detail and "kapat" in kapanis[0].detail.lower()

    assert (await client.post(_ac(2026, 7), headers=admin_headers)).status_code == 200
    acilis = (
        (await seeded_db.execute(select(AuditLog).where(AuditLog.action == AuditAction.update)))
        .scalars()
        .all()
    )
    assert len(acilis) == 1
    assert "aç" in acilis[0].detail.lower()


async def test_okuma_ucu_DENETIM_YAZMAZ(
    client: AsyncClient, pm_headers: dict[str, str], seeded_db: AsyncSession
) -> None:
    once = len((await seeded_db.execute(select(AuditLog))).scalars().all())
    assert (await client.get(YOL, headers=pm_headers)).status_code == 200
    sonra = len((await seeded_db.execute(select(AuditLog))).scalars().all())
    assert once == sonra
