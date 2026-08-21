"""SIRA-B — dönem kapanışının ÜÇÜNCÜ ön koşulu: KRONOLOJİK SIRA.

Kapanışın bugüne kadarki iki kapısı (zaten kapalı · taslak fiş) *dönemin
KENDİSİNE* bakıyordu; hiçbiri **defterin sırasına** bakmıyordu. Sonuç ölçüldü:
Temmuz açıkken Ağustos kapatılabiliyordu. O hâlde Ağustos donarken Temmuz'a
hâlâ fiş girilebilir ve mizan/bilanço "hangi aya kadar kesin" sorusuna cevap
veremez hâle gelirdi.

## Kurallar ve nereden geldikleri

* **K1 — önceki dönem TAKVİM ayıdır.** Ocak'ın öncesi *bir önceki yılın
  Aralık*ıdır. Yıl sınırında kopsaydı sıra kuralı her 1 Ocak'ta SESSİZCE
  sıfırlanır ve Aralık sonsuza dek açık kalabilirdi.
* **K2 — kaydı OLMAYAN önceki ay ENGEL DEĞİLDİR.** `accounting_periods`
  satırı PROAKTİF doğmaz; tek doğduğu yer `periods_service.lock_period`tir
  (UPSERT-SONRA-KİLİTLE) ve o da yalnız bir yazma/kapatma isteğiyle koşar.
  Yani "satırı yok" = *o ayda hiç iş olmamış*, "açık" DEĞİL. Engel sayılsaydı
  sistemin İLK kapanışı hiçbir zaman yapılamazdı: her ayın öncesinde sonsuza
  kadar kayıtsız aylar var.
* **K5 — `reopen` DEĞİŞMEZ.** Sıra kuralı yalnız KAPATMAYA bakar; geri açma
  zaten `admin` yetkisindedir ve "Ağustos kapalıyken Temmuz'u geri aç" meşru
  bir düzeltme yoludur. Oraya kural konsaydı yönetici düzeltemeyeceği bir
  defterle baş başa kalırdı.

## Neden HTTP ucundan

`test_mu2_periods_api.py` ile aynı gerekçe (MU-1 dersi): servisi doğrudan
çağıran bir test yetki kapısını ve `Path` aralık denetimini ASLA sınamaz.
Tek istisna KURULUM fabrikalarıdır.
"""

from datetime import date

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounting import guards
from app.modules.accounting.models import (
    AccountingPeriod,
    AccountingPeriodStatus,
    JournalEntryStatus,
)

from ._journal import iki_yaprak

YOL = "/accounting-periods"


def _kapat(year: int, month: int) -> str:
    return f"{YOL}/{year}/{month}/close"


def _ac(year: int, month: int) -> str:
    return f"{YOL}/{year}/{month}/reopen"


# --------------------------------------------------------------------------- #
# 1 — önceki dönem AÇIK ve KAYITLI → 409, hangi dönem engelliyor SÖYLENİR
# --------------------------------------------------------------------------- #


async def test_1_ONCEKI_DONEM_ACIKSA_kapatma_409(
    client: AsyncClient, muhasebe_headers: dict[str, str], donem_fabrikasi
) -> None:
    """🔴 ASIL KUSUR: Temmuz açıkken Ağustos kapanamaz."""
    await donem_fabrikasi(2026, 7, status=AccountingPeriodStatus.open)
    resp = await client.post(_kapat(2026, 8), headers=muhasebe_headers)
    assert resp.status_code == 409, resp.text


async def test_1b_hata_metni_ENGELLEYEN_DONEMI_soyler(
    client: AsyncClient, muhasebe_headers: dict[str, str], donem_fabrikasi
) -> None:
    """Kullanıcı "neden kapanmıyor" diye ARAMASIN: metin ayı ADIYLA verir.

    Genel bir "sıra hatası" cümlesi, on iki açık dönem arasından hangisinin
    engellediğini bulma işini kullanıcıya yıkardı.
    """
    await donem_fabrikasi(2026, 7, status=AccountingPeriodStatus.open)
    resp = await client.post(_kapat(2026, 8), headers=muhasebe_headers)
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"] == guards.period_previous_open(2026, 7)
    assert "2026/07" in resp.json()["detail"]


async def test_1c_kapatma_ENGELLENDIGINDE_DONEM_ACIK_kalir(
    client: AsyncClient,
    muhasebe_headers: dict[str, str],
    donem_fabrikasi,
    seeded_db: AsyncSession,
) -> None:
    """409 sonrası Ağustos DAMGASIZ ve `open` kalmalı.

    🔴 `lock_period` denetimden ÖNCE UPSERT ettiği için satır 409'a rağmen
    DOĞMUŞ OLABİLİR (ölçüldü: test koşumunda doğuyor; canlıda istek
    transaction'ı geri sarıldığı için doğmaz). İddia bu ikiliğe DAYANMAZ ve
    dayanmamalıdır: `open` satır ile satırsızlık bu modülde AYNI ŞEYDİR
    (`PERIOD_ALREADY_OPEN` gerekçesi). Bekçilik ettiği şey, kapanışın
    reddedildiği hâlde damganın SESSİZCE yazılmamasıdır.
    """
    await donem_fabrikasi(2026, 7, status=AccountingPeriodStatus.open)
    assert (await client.post(_kapat(2026, 8), headers=muhasebe_headers)).status_code == 409

    agustos = (
        await seeded_db.execute(
            select(AccountingPeriod).where(
                AccountingPeriod.year == 2026, AccountingPeriod.month == 8
            )
        )
    ).scalar_one_or_none()
    assert agustos is None or agustos.status is AccountingPeriodStatus.open
    if agustos is not None:
        assert agustos.closed_at is None
        assert agustos.closed_by_id is None


# --------------------------------------------------------------------------- #
# 2 — önceki dönem KAPALI → kapanış geçer
# --------------------------------------------------------------------------- #


async def test_2_ONCEKI_DONEM_KAPALIYSA_kapatma_gecer(
    client: AsyncClient, muhasebe_headers: dict[str, str], donem_fabrikasi
) -> None:
    await donem_fabrikasi(2026, 7, status=AccountingPeriodStatus.closed)
    resp = await client.post(_kapat(2026, 8), headers=muhasebe_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "closed"


# --------------------------------------------------------------------------- #
# 3 — 🔴 K2: önceki ayın KAYDI YOK → kapanış geçer
# --------------------------------------------------------------------------- #


async def test_3_ONCEKI_AYIN_KAYDI_YOKSA_kapatma_gecer(
    client: AsyncClient, muhasebe_headers: dict[str, str], seeded_db: AsyncSession
) -> None:
    """K2 — satırı olmayan ay "açık" değildir, HİÇ VAR OLMAMIŞTIR.

    Bu testin kırmızıya dönmesi, sıra denetiminin `lock_period`/`get_or_create`
    gibi bir yolla önceki ayı DOĞURDUĞU anlamına gelir; o hâlde sistemin ilk
    kapanışı asla yapılamazdı.
    """
    resp = await client.post(_kapat(2026, 8), headers=muhasebe_headers)
    assert resp.status_code == 200, resp.text

    satirlar = (await seeded_db.execute(select(AccountingPeriod))).scalars().all()
    assert [(s.year, s.month) for s in satirlar] == [(2026, 8)], (
        "sıra denetimi önceki dönem satırını DOĞURMAMALIDIR — okuma yeterlidir"
    )


async def test_3b_ONCEKI_AYIN_FISI_VARSA_ama_satiri_YOKSA_gecer(
    client: AsyncClient, muhasebe_headers: dict[str, str], hesap_fabrikasi, fis_fabrikasi
) -> None:
    """🔴 Kural DÖNEM SATIRINA bakar, fişe DEĞİL — sınır burada çizilidir.

    Fiş fabrikası (kurulum yolu) dönem satırı doğurmaz. Gerçek yazma yolu
    (`create_entry`) doğurur; ayrım tam olarak K2'nin ölçtüğü şeydir.
    """
    kasa, saticilar = await iki_yaprak(hesap_fabrikasi)
    await fis_fabrikasi(
        [(kasa, "500.00", "0"), (saticilar, "0", "500.00")],
        status=JournalEntryStatus.posted,
        entry_date=date(2026, 7, 9),
    )
    resp = await client.post(_kapat(2026, 8), headers=muhasebe_headers)
    assert resp.status_code == 200, resp.text


# --------------------------------------------------------------------------- #
# 4 — 🔴 K1: YIL SINIRI
# --------------------------------------------------------------------------- #


async def test_4_OCAK_kapatilirken_ONCEKI_YILIN_ARALIGINA_bakilir(
    client: AsyncClient, muhasebe_headers: dict[str, str], donem_fabrikasi
) -> None:
    """K1 — 2027 Ocak'ın öncesi **2026 Aralık**tır; açıksa 409.

    `month - 1` diye yazılmış bir denetim burada 2027/0'a bakar, hiçbir satır
    bulamaz ve Ocak'ı SESSİZCE kapatırdı: sıra kuralı her 1 Ocak'ta sıfırlanır,
    Aralık sonsuza dek açık kalabilirdi.
    """
    await donem_fabrikasi(2026, 12, status=AccountingPeriodStatus.open)
    resp = await client.post(_kapat(2027, 1), headers=muhasebe_headers)
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"] == guards.period_previous_open(2026, 12)


async def test_4b_YIL_SINIRI_onceki_ARALIK_kapaliysa_OCAK_gecer(
    client: AsyncClient, muhasebe_headers: dict[str, str], donem_fabrikasi
) -> None:
    await donem_fabrikasi(2026, 12, status=AccountingPeriodStatus.closed)
    resp = await client.post(_kapat(2027, 1), headers=muhasebe_headers)
    assert resp.status_code == 200, resp.text


async def test_4c_AYNI_YILIN_ARALIGI_ONCEKI_SAYILMAZ(
    client: AsyncClient, muhasebe_headers: dict[str, str], donem_fabrikasi
) -> None:
    """Ters yön: 2027/12 açıkken 2027/1 kapanabilmelidir.

    "Yıl içinde açık dönem var mı" diye yazılmış kaba bir denetim burada
    yanlışlıkla 409 verirdi — kural TEK BİR önceki aya bakar, yıla değil.
    """
    await donem_fabrikasi(2027, 12, status=AccountingPeriodStatus.open)
    resp = await client.post(_kapat(2027, 1), headers=muhasebe_headers)
    assert resp.status_code == 200, resp.text


# --------------------------------------------------------------------------- #
# 5 — K3: sistemdeki EN ESKİ dönem her zaman kapatılabilir
# --------------------------------------------------------------------------- #


async def test_5_EN_ESKI_DONEM_kapatilabilir(
    client: AsyncClient, muhasebe_headers: dict[str, str], donem_fabrikasi
) -> None:
    """K3 — öncesi YOKTUR. Üç açık dönem varken en eskisi kapanır."""
    for ay in (5, 6, 7):
        await donem_fabrikasi(2026, ay, status=AccountingPeriodStatus.open)
    resp = await client.post(_kapat(2026, 5), headers=muhasebe_headers)
    assert resp.status_code == 200, resp.text


async def test_5b_SIRAYLA_kapanis_ucunu_de_kapatir(
    client: AsyncClient, muhasebe_headers: dict[str, str], donem_fabrikasi
) -> None:
    """Kural bir KİLİT değil bir SIRADIR: eskiden yeniye üçü de kapanabilmeli.

    Aksi hâlde kural defteri tamamen dondururdu.
    """
    for ay in (5, 6, 7):
        await donem_fabrikasi(2026, ay, status=AccountingPeriodStatus.open)
    for ay in (5, 6, 7):
        resp = await client.post(_kapat(2026, ay), headers=muhasebe_headers)
        assert resp.status_code == 200, f"{ay}. ay: {resp.text}"


# --------------------------------------------------------------------------- #
# 6 — K5: `reopen` DEĞİŞMEDİ
# --------------------------------------------------------------------------- #


async def test_6_AGUSTOS_KAPALIYKEN_TEMMUZ_geri_acilabilir(
    client: AsyncClient, admin_headers: dict[str, str], donem_fabrikasi
) -> None:
    """🔴 K5 — sıra kuralı geri açmaya SIZMAZ.

    Sızsaydı yönetici "önce Ağustos'u aç" zincirine mahkûm olurdu; oysa tek
    hatalı fişi Temmuz'da düzeltmek meşru ve dar bir düzeltmedir.
    """
    await donem_fabrikasi(2026, 7, status=AccountingPeriodStatus.closed)
    await donem_fabrikasi(2026, 8, status=AccountingPeriodStatus.closed)
    resp = await client.post(_ac(2026, 7), headers=admin_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "open"


async def test_6b_geri_ACILAN_donem_sonraki_kapanisi_YENIDEN_engeller(
    client: AsyncClient,
    admin_headers: dict[str, str],
    muhasebe_headers: dict[str, str],
    donem_fabrikasi,
) -> None:
    """Zincir kapanıyor: Temmuz geri açıldıktan sonra Ağustos'un YENİDEN
    kapatılması engellenir. Denetim "bir kez geçildi" diye önbelleğe alınamaz."""
    await donem_fabrikasi(2026, 7, status=AccountingPeriodStatus.closed)
    await donem_fabrikasi(2026, 8, status=AccountingPeriodStatus.closed)
    assert (await client.post(_ac(2026, 7), headers=admin_headers)).status_code == 200
    assert (await client.post(_ac(2026, 8), headers=admin_headers)).status_code == 200
    resp = await client.post(_kapat(2026, 8), headers=muhasebe_headers)
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"] == guards.period_previous_open(2026, 7)


# --------------------------------------------------------------------------- #
# 7 — mevcut iki ön koşul BOZULMADI (sıra kapısı onları GÖLGELEMEZ)
# --------------------------------------------------------------------------- #


async def test_7_ZATEN_KAPALI_kapisi_SIRA_kapisindan_ONCE_konusur(
    client: AsyncClient, muhasebe_headers: dict[str, str], donem_fabrikasi
) -> None:
    """Ağustos kapalı VE Temmuz açık: kullanıcı "zaten kapalı" duymalı.

    Sıra hatası dönseydi kullanıcı Temmuz'u kapatır, sonra "Ağustos zaten
    kapalıymış" diye ikinci bir tur atardı.
    """
    await donem_fabrikasi(2026, 7, status=AccountingPeriodStatus.open)
    await donem_fabrikasi(2026, 8, status=AccountingPeriodStatus.closed)
    resp = await client.post(_kapat(2026, 8), headers=muhasebe_headers)
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"] == guards.PERIOD_ALREADY_CLOSED


async def test_7b_TASLAK_FIS_kapisi_SIRA_kapisindan_ONCE_konusur(
    client: AsyncClient,
    muhasebe_headers: dict[str, str],
    donem_fabrikasi,
    hesap_fabrikasi,
    fis_fabrikasi,
) -> None:
    """İki engel birden varsa taslak fiş önce söylenir: kullanıcının kendi
    dönemindeki eksik, komşu dönemin durumundan daha yakın bir iştir."""
    await donem_fabrikasi(2026, 7, status=AccountingPeriodStatus.open)
    kasa, saticilar = await iki_yaprak(hesap_fabrikasi)
    await fis_fabrikasi(
        [(kasa, "10.00", "0"), (saticilar, "0", "10.00")],
        status=JournalEntryStatus.draft,
        entry_date=date(2026, 8, 3),
    )
    resp = await client.post(_kapat(2026, 8), headers=muhasebe_headers)
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"] == guards.PERIOD_HAS_DRAFT_ENTRIES
