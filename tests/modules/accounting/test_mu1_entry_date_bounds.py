"""MU-1 T3b — `entry_date` GELECEK SINIRI (`POST` + `PATCH`).

Kusur: `entry_date` için üst sınır hiçbir katmanda yoktu — ne şemada
(`schemas.py:293` çıplak `entry_date: date`), ne serviste, ne DB kısıtında
(`ck_journal_entries_period_matches_date` yalnız dönem kolonlarını tarihe
bağlar), ne de dönem kapısında: `periods_service.lock_period` istenen dönemi
YOKSA `open` olarak DOĞURUR, dolayısıyla 2027/03 dönemi isteğin kendisiyle
açılır ve fiş `posted` olabilir.

🔴 Zarar iki katlıdır ve ikisi de sessizdir:

1. İleri tarihli fiş, bugünün ayına ait mizanda/bilançoda/KDV beyanında
   GÖRÜNMEZ — kullanıcı "kayıtlaştırıldı" bildirimini almıştır;
2. `state_service` stornonun tarihini `timezone.today()`e sabitler (K6), yani
   ters kayıt orijinalinden ÖNCEKİ döneme düşer: bir ay −tutar, öteki ay
   +tutar basar ve "şu ana kadar" bakiyesi İKİ TARİH ARASINDA HİÇ tutmaz.

## Sınır günü BİLEREK testlidir

`today()` TAM SINIRDA GEÇER. `<` ile `<=` karıştırmak bu kapının tek kör
noktasıdır (T6/K6 dersi: sınır günü ayrı iddiadır) — bugünün fişi kesilemeseydi
kapı kuralı değil, kullanımı engellerdi.

## Dönem SATIRI da doğmamalıdır

Kapı `assert_periods_open`tan ÖNCE koşmazsa istek 422 dönse bile
`accounting_periods`ta gelecek bir dönem satırı DOĞAR (`lock_period` UPSERT'tir).
Canlıda `get_db` istisna yolunda rollback yapar, ama test hattı session'ı
override ettiği için rollback YOKTUR — bu yüzden bu iddia SIRAYI ölçer.
"""

from datetime import timedelta

from sqlalchemy import select

from app.core.timezone import today
from app.modules.accounting import guards
from app.modules.accounting.models import AccountingPeriod
from tests.modules.accounting._journal import YOL as _YOL
from tests.modules.accounting._journal import fis_olustur as _fis_olustur
from tests.modules.accounting._journal import govde as _govde
from tests.modules.accounting._journal import iki_yaprak as _iki_yaprak

#: Gelecek AYA düşen bir gün. `today() + 1 gün` ÇOĞU ZAMAN aynı dönemdedir;
#: dönem satırı iddiası için ayrı bir aya çıkmak ZORUNLUDUR.
_GELECEK_AY = timedelta(days=400)


async def test_GELECEK_tarihli_fis_yaratilamaz(client, muhasebe_headers, hesap_fabrikasi) -> None:
    kasa, saticilar = await _iki_yaprak(hesap_fabrikasi)
    yarin = today() + timedelta(days=1)

    resp = await client.post(
        _YOL, json=_govde(kasa, saticilar, entry_date=yarin.isoformat()), headers=muhasebe_headers
    )

    assert resp.status_code == 422, resp.text
    assert guards.ENTRY_DATE_IN_FUTURE in resp.json()["detail"]


async def test_BUGUN_sinir_gunu_KABUL_edilir(client, muhasebe_headers, hesap_fabrikasi) -> None:
    """🔴 Sınır günü: `<` yerine `<=` yazılsaydı bugünün fişi de reddedilir ve
    kapı kuralı değil KULLANIMI engellerdi."""
    kasa, saticilar = await _iki_yaprak(hesap_fabrikasi)
    bugun = today()

    resp = await client.post(
        _YOL, json=_govde(kasa, saticilar, entry_date=bugun.isoformat()), headers=muhasebe_headers
    )

    assert resp.status_code == 201, resp.text
    assert resp.json()["entry_date"] == bugun.isoformat()


async def test_PATCH_ile_de_gelecege_tasinamaz(client, muhasebe_headers, hesap_fabrikasi) -> None:
    """Kural yalnız POST'ta olsaydı aynı delik bir tarih düzeltmesiyle açılırdı
    (`code` kilidinin K-Ş3 dersinin aynısı)."""
    fis = await _fis_olustur(client, muhasebe_headers, hesap_fabrikasi)
    yarin = today() + timedelta(days=1)

    resp = await client.patch(
        f"{_YOL}/{fis['id']}", json={"entry_date": yarin.isoformat()}, headers=muhasebe_headers
    )

    assert resp.status_code == 422, resp.text
    assert guards.ENTRY_DATE_IN_FUTURE in resp.json()["detail"]


async def test_gelecek_donem_SATIRI_dogmaz(
    client, muhasebe_headers, hesap_fabrikasi, seeded_db
) -> None:
    """🔴 SIRA iddiası: kapı `assert_periods_open`tan ÖNCE koşmalıdır, yoksa
    reddedilen istek gelecek bir dönemi `open` olarak DOĞURUR."""
    kasa, saticilar = await _iki_yaprak(hesap_fabrikasi)
    uzak = today() + _GELECEK_AY

    resp = await client.post(
        _YOL, json=_govde(kasa, saticilar, entry_date=uzak.isoformat()), headers=muhasebe_headers
    )

    assert resp.status_code == 422, resp.text
    satir = (
        await seeded_db.execute(
            select(AccountingPeriod).where(
                AccountingPeriod.year == uzak.year, AccountingPeriod.month == uzak.month
            )
        )
    ).scalar_one_or_none()
    assert satir is None, "reddedilen istek gelecek dönem satırını DOĞURDU"
