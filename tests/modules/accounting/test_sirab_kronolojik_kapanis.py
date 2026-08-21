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

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date

from httpx import AsyncClient
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounting import guards, periods_service
from app.modules.accounting.models import (
    AccountingPeriod,
    AccountingPeriodStatus,
    JournalEntryStatus,
)
from tests.conftest import test_engine

from ._journal import iki_yaprak

YOL = "/accounting-periods"


@contextmanager
def _sorgu_sayaci() -> Iterator[list[str]]:
    """`test_dkap_periods_list_fields.py`deki sayacın AYNISI — sürücüye giden
    HER ifadeyi toplar; iddia tahmine değil ÖLÇÜME dayanır."""
    ifadeler: list[str] = []

    def kaydet(conn, cursor, statement, parameters, context, executemany) -> None:  # noqa: ANN001
        ifadeler.append(" ".join(statement.split()))

    event.listen(test_engine.sync_engine, "before_cursor_execute", kaydet)
    try:
        yield ifadeler
    finally:
        event.remove(test_engine.sync_engine, "before_cursor_execute", kaydet)


def _donem_iliskili(ifadeler: list[str]) -> list[str]:
    """Yalnız bu ucun dokunduğu tablolar; login sorguları iddiadan bağımsızdır."""
    return [i for i in ifadeler if "accounting_periods" in i or "journal_entries" in i]


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


# --------------------------------------------------------------------------- #
# 8 — SIRA-B/2: `previous_period_open` OLGUSU (liste ucu)
#
# Kural doğru olsa bile GÖRÜNMEZSE ekran "Dönemi Kapat"ı aktif basar, kullanıcı
# tıklar ve 409 sürprizi yer. Ekran bunu kendi listesinden TÜRETEMEZ: Ocak'ın
# öncesi bir önceki yılın Aralığıdır (K1) ve liste `year` süzgeciyle TEK yıl
# çeker — Aralık 2025 o sayfada YOKTUR.
#
# 🔴 K9 — taşınan şey OLGUDUR, karar DEĞİL. Alan adı `can_close` DEĞİLDİR ve
# olmayacaktır: kapatılabilirlik `status` + `draft_count` + bu olgunun
# birleşimidir ve o birleşimi kapı (`periods_service.close_period`) tanımlar.
# Kararın bir kopyası cevapta dursaydı, kapı bir gün değişince ekran SESSİZCE
# yanlış kalırdı (DKAP-B kanonu, `draft_count` ile birebir aynı gerekçe).
#
# 🔴 K10 — olgu ile kapı AYNI yardımcıdan beslenir (`previous_period`).
# İkisi ayrışsaydı ekran "kapatabilirsin" der, kapı 409 dönerdi — yani tam
# olarak düzeltmeye çalıştığımız sorunu yeniden üretirdik.
# --------------------------------------------------------------------------- #


def _satir(govde: dict, year: int, month: int) -> dict:
    (kalem,) = [i for i in govde["items"] if i["year"] == year and i["month"] == month]
    return kalem


async def test_8_OCAK_onceki_YILIN_ARALIGI_ACIKSA_true(
    client: AsyncClient, pm_headers: dict[str, str], donem_fabrikasi
) -> None:
    """🔴 K10/K1 — ekranın KENDİ BAŞINA cevaplayamadığı tek hâl.

    Liste `year=2027` süzgeciyle çekilir; 2026/12 o sayfada YOKTUR. Olgu yine
    de `true` gelmelidir — çözüm sayfadaki satırlardan değil, ANAHTARLA
    sorulan bir okumadan gelir.
    """
    await donem_fabrikasi(2026, 12, status=AccountingPeriodStatus.open)
    await donem_fabrikasi(2027, 1, status=AccountingPeriodStatus.open)
    resp = await client.get(f"{YOL}?year=2027", headers=pm_headers)
    assert resp.status_code == 200, resp.text
    assert _satir(resp.json(), 2027, 1)["previous_period_open"] is True


async def test_8b_OCAK_onceki_YILIN_ARALIGI_KAPALIYSA_false(
    client: AsyncClient, pm_headers: dict[str, str], donem_fabrikasi
) -> None:
    await donem_fabrikasi(2026, 12, status=AccountingPeriodStatus.closed)
    await donem_fabrikasi(2027, 1, status=AccountingPeriodStatus.open)
    resp = await client.get(f"{YOL}?year=2027", headers=pm_headers)
    assert resp.status_code == 200, resp.text
    assert _satir(resp.json(), 2027, 1)["previous_period_open"] is False


async def test_8c_ONCEKI_AYIN_KAYDI_YOKSA_false(
    client: AsyncClient, pm_headers: dict[str, str], donem_fabrikasi
) -> None:
    """K10/K2 — kaydı olmayan ay ENGEL DEĞİLDİR, olgu da `false` demelidir.

    `true` deseydi ekran kapatılabilir bir dönemi kilitli gösterir ve
    sistemin İLK kapanışı arayüzden hiç yapılamazdı.
    """
    await donem_fabrikasi(2026, 8, status=AccountingPeriodStatus.open)
    resp = await client.get(f"{YOL}?year=2026", headers=pm_headers)
    assert resp.status_code == 200, resp.text
    assert _satir(resp.json(), 2026, 8)["previous_period_open"] is False


async def test_8d_EN_ESKI_DONEM_false(
    client: AsyncClient, pm_headers: dict[str, str], donem_fabrikasi
) -> None:
    """K3 — öncesi YOKTUR. Üç açık dönemin EN ESKİSİ `false`, ötekiler `true`."""
    for ay in (5, 6, 7):
        await donem_fabrikasi(2026, ay, status=AccountingPeriodStatus.open)
    govde = (await client.get(f"{YOL}?year=2026", headers=pm_headers)).json()
    assert _satir(govde, 2026, 5)["previous_period_open"] is False
    assert _satir(govde, 2026, 6)["previous_period_open"] is True
    assert _satir(govde, 2026, 7)["previous_period_open"] is True


async def test_8e_SAYFA_SINIRINDAKI_donemin_oncekisi_SAYFADA_OLMASA_da_dogru(
    client: AsyncClient, pm_headers: dict[str, str], donem_fabrikasi
) -> None:
    """🔴 K11'in korunması gereken köşesi: çözüm SAYFADAN türetilemez.

    Liste `year DESC, month DESC` sıralıdır; `limit=1` yalnız 2026/7'yi basar.
    Onun öncesi (2026/6) sayfada YOKTUR ama AÇIKTIR — sayfadaki satırlardan
    türetilen bir uygulama burada `false` derdi ve ekran 409'a yürürdü.
    """
    await donem_fabrikasi(2026, 6, status=AccountingPeriodStatus.open)
    await donem_fabrikasi(2026, 7, status=AccountingPeriodStatus.open)
    resp = await client.get(f"{YOL}?year=2026&limit=1", headers=pm_headers)
    assert resp.status_code == 200, resp.text
    govde = resp.json()
    assert len(govde["items"]) == 1
    assert _satir(govde, 2026, 7)["previous_period_open"] is True


# --------------------------------------------------------------------------- #
# 9 — 🔴 OLGU ile KAPI TUTARLILIĞI (K10'un asıl bekçisi)
# --------------------------------------------------------------------------- #


async def test_9_previous_period_open_TRUE_olan_her_donem_GERCEKTEN_409_alir(
    client: AsyncClient,
    pm_headers: dict[str, str],
    muhasebe_headers: dict[str, str],
    donem_fabrikasi,
) -> None:
    """🔴 K10 — olgu ile kapı AYNI ŞEYİ söylemek ZORUNDADIR.

    Kurulum kasten karışıktır: yıl sınırı (2026/12 → 2027/1), kayıtsız önceki
    ay (2026/8), kapalı önceki ay ve zincirin en eskisi bir arada. Her satır
    için olgu okunur ve `close` GERÇEKTEN denenir; `true` diyen her dönem
    `PERIOD_PREVIOUS_OPEN` metniyle 409 almalıdır.

    İkisi ayrı `month - 1` hesabından beslenseydi (kapı `previous_period`,
    olgu elle) yıl sınırı satırı burada AYRIŞIRDI — testin bu kurulumu
    seçmesinin sebebi tam olarak budur.
    """
    await donem_fabrikasi(2026, 5, status=AccountingPeriodStatus.closed)
    await donem_fabrikasi(2026, 6, status=AccountingPeriodStatus.open)
    await donem_fabrikasi(2026, 7, status=AccountingPeriodStatus.open)
    await donem_fabrikasi(2026, 8, status=AccountingPeriodStatus.open)  # öncesi (7) açık
    await donem_fabrikasi(2026, 12, status=AccountingPeriodStatus.open)
    await donem_fabrikasi(2027, 1, status=AccountingPeriodStatus.open)

    olgular: dict[tuple[int, int], bool] = {}
    durumlar: dict[tuple[int, int], str] = {}
    for yil in (2026, 2027):
        govde = (await client.get(f"{YOL}?year={yil}&limit=200", headers=pm_headers)).json()
        for kalem in govde["items"]:
            olgular[(kalem["year"], kalem["month"])] = kalem["previous_period_open"]
            durumlar[(kalem["year"], kalem["month"])] = kalem["status"]

    assert olgular == {
        (2026, 5): False,  # öncesi (2026/4) KAYITSIZ
        (2026, 6): False,  # öncesi (2026/5) KAPALI
        (2026, 7): True,  # öncesi (2026/6) AÇIK
        (2026, 8): True,  # öncesi (2026/7) AÇIK
        (2026, 12): False,  # öncesi (2026/11) KAYITSIZ
        (2027, 1): True,  # 🔴 öncesi ÖNCEKİ YILIN Aralığı (2026/12) ve AÇIK
    }, olgular

    # 🔴 YENİDEN ESKİYE: bir dönemi kapatmak KENDİNDEN SONRAKİNİN olgusunu
    # değiştirir. Eskiden yeniye yürünseydi, 2026/6 kapatıldıktan sonra 2026/7
    # artık engelsiz olurdu ve test kendi kurulumunu bozup yalancı bir yeşil
    # üretirdi. `closed` dönemler atlanır: onlar `PERIOD_ALREADY_CLOSED`e düşer
    # ve bu testin iddiası olan sıra kapısına HİÇ ulaşmazlar.
    for yil, ay in sorted(olgular, reverse=True):
        if durumlar[(yil, ay)] != "open":
            continue
        engelli = olgular[(yil, ay)]
        resp = await client.post(_kapat(yil, ay), headers=muhasebe_headers)
        if engelli:
            assert resp.status_code == 409, f"{yil}/{ay}: olgu 'engelli' diyor ama {resp.text}"
            onceki_yil, onceki_ay = (yil - 1, 12) if ay == 1 else (yil, ay - 1)
            assert resp.json()["detail"] == guards.period_previous_open(onceki_yil, onceki_ay)
        else:
            assert resp.status_code == 200, (
                f"{yil}/{ay}: olgu 'engel yok' diyor ama kapı reddetti — {resp.text}"
            )


# --------------------------------------------------------------------------- #
# 10 — K11: N+1 YOK (iki AYRI kanıt, DKAP-B deseni)
# --------------------------------------------------------------------------- #


async def test_10_N1_YOK_SAYAC_donem_sayisi_artinca_sorgu_sayisi_SABIT(
    client: AsyncClient, pm_headers: dict[str, str], donem_fabrikasi
) -> None:
    """🔴 K11 kanıt 1/2 — SAYAÇ: 3 dönemle 12 dönem AYNI ifade adedi.

    `previous_period_open` dönem başına çözülseydi 12 dönem 9 ek
    `accounting_periods` ifadesi üretirdi.
    """
    for ay in range(1, 4):
        await donem_fabrikasi(2025, ay, status=AccountingPeriodStatus.closed)
    with _sorgu_sayaci() as az:
        resp = await client.get(f"{YOL}?year=2025", headers=pm_headers)
    assert resp.status_code == 200, resp.text
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


async def test_10b_N1_YOK_YAPISAL_toplu_cozucu_TEK_KEZ_cagrilir(
    client: AsyncClient, pm_headers: dict[str, str], donem_fabrikasi, monkeypatch
) -> None:
    """🔴 K11 kanıt 2/2 — YAPISAL: sayaç `lazy="selectin"` gibi bir ön-yükleme
    tarafından KÖR edilebilir (repo kanonu), bu yüzden ÇAĞRI SAYISI ayrıca
    ölçülür. Toplu çözücü döngü içinde çağrılsaydı 6 dönem için 6 çağrı
    çıkardı — TEK olmalı.
    """
    for ay in range(1, 7):
        await donem_fabrikasi(2025, ay, status=AccountingPeriodStatus.open)

    cagri_sayisi = 0
    orijinal = periods_service.repository.open_periods_among

    async def sayilan(*args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        nonlocal cagri_sayisi
        cagri_sayisi += 1
        return await orijinal(*args, **kwargs)

    monkeypatch.setattr(periods_service.repository, "open_periods_among", sayilan)

    resp = await client.get(f"{YOL}?year=2025", headers=pm_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["total"] == 6
    assert cagri_sayisi == 1, f"6 dönem için {cagri_sayisi} çağrı — döngü içinde çağrılıyor"


async def test_10c_N1_YOK_YAPISAL_AST_list_periods_DONGU_ICINDE_await_ICERMEZ(
    client: AsyncClient,
) -> None:
    """🔴 K11 kanıt 3/2 — AST: `list_periods` gövdesinde DÖNGÜ İÇİNDE `await` YOK.

    Sayaç ve çağrı sayacı ikisi de ÇALIŞMA ZAMANI kanıtıdır ve ikisi de
    kurulum küçükken (tek sayfa, tek yıl) yanılabilir. Bu kanıt kodun
    ŞEKLİNE bakar: `for`/`while`/comprehension gövdesinde bir `await`
    belirirse N+1 YAPISAL OLARAK mümkün hâle gelmiş demektir ve bu test
    kurulumdan BAĞIMSIZ olarak kırmızıya döner.
    """
    import ast
    import inspect
    import textwrap

    agac = ast.parse(textwrap.dedent(inspect.getsource(periods_service.list_periods)))
    ihlaller: list[str] = []
    for dugum in ast.walk(agac):
        govdeler: list[ast.AST] = []
        if isinstance(dugum, ast.For | ast.AsyncFor | ast.While):
            govdeler = [*dugum.body, *dugum.orelse]
        elif isinstance(dugum, ast.ListComp | ast.SetComp | ast.GeneratorExp):
            govdeler = [dugum.elt]
        elif isinstance(dugum, ast.DictComp):
            govdeler = [dugum.key, dugum.value]
        for govde in govdeler:
            ihlaller += [ast.unparse(alt) for alt in ast.walk(govde) if isinstance(alt, ast.Await)]
    assert ihlaller == [], f"`list_periods` döngü içinde `await` yapıyor — N+1 kapısı: {ihlaller}"
