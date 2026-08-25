"""MU-2 T3 — 🔴 EŞİK = KİLİT: dönem kapanışı ve kapalı-döneme-yazma yasağı.

## Niçin `client`/`seeded_db` KULLANILMAZ

Kök `tests/conftest.py`'deki `db_session` her testi TEK bağlantı üzerinde
SAVEPOINT'e sarar; o session üzerindeki iki `asyncio` görevi AYNI bağlantıyı
paylaşır ve gerçek satır kilidi test EDİLEMEZ. Bu dosya
`tests/modules/invoicing/test_invoicing_lock.py` ve
`tests/modules/treasury/test_hz1_payment_lock.py` desenini birebir izler:
`test_engine` üzerinden İKİ BAĞIMSIZ bağlantı, gerçek commit, gerçek temizlik.

## 🔴 ÇAKIŞMA PENCERESİ DETERMİNİSTİKTİR — sabit `sleep` YOKTUR

Her görev **önce kendi bağlantısını ısıtır** (`session.get(User, …)` — bağlantıyı
havuzdan çeker, transaction'ı başlatır), **ANCAK ONDAN SONRA** `asyncio.Barrier`a
varır. Isınma barajdan SONRA yapılsaydı izole koşuda bağlantı kurulum gecikmesi
görevleri sıraya sokar ve kilitsiz kod da doğru sonucu verirdi (FAT-1 T4b dersi:
*"test var" ≠ "test bekçilik ediyor"*). Tavan yalnızca BOZUK bir kurulumun testi
sonsuza asmasını engeller, pencere AÇMAK için kullanılmaz.

## 🔴 UPSERT-SONRA-KİLİTLE — bu dosyanın ASIL iddiası

Dönem satırı PROAKTİF açılmaz (YAGNI): kayıt yoksa dönem AÇIK sayılır. Ama o
zaman kilitlenecek satır da yoktur ve iki eşzamanlı `close` ikisi de "satır yok"
görüp INSERT ederdi → `uq_accounting_periods_year_month` ihlali → biri **500**.
Bu yüzden `periods_service.lock_period` önce
`INSERT … ON CONFLICT (year, month) DO NOTHING`, **sonra**
`SELECT … FOR UPDATE` koşar. İki adım aynı transaction'da çakışmayı serileştirir:
ikinci istek ya UNIQUE indeks kilidinde ya satır kilidinde bekler.

`test_1_IKI_ESZAMANLI_close_YALNIZ_BIRI_gecer` bunu ölçer ve **500'ün OLMADIĞINI
AYRICA** iddia eder — sayım doğru çıkıp altta bir `IntegrityError` sızmış olsaydı
kusur görünmezdi.

## 🔴 İKİ KURULUM ŞART: satır YOK **ve** satır VAR — ölçülmüş bir ders

İlk hâlinde bu dosya yalnız "satır YOK" hâlini kuruyordu ve `with_for_update`
kaldırıldığında **6/6 YEŞİL** kalıyordu. Sebep ölçüldü: `INSERT … ON CONFLICT
DO NOTHING` **kendisi bloke eder** — çakışan tuple'ı yazan işlem COMMIT edene
kadar ikinci INSERT UNIQUE indeksinde bekler. Yani satır yokken serileştirmeyi
UPSERT tek başına yapar ve `FOR UPDATE` hiç sınanmaz.

`FOR UPDATE`in TEK BAŞINA taşıdığı yük, satır **ZATEN VARKEN** ortaya çıkar:
o hâlde `ON CONFLICT DO NOTHING` hiçbir şey yazmaz, hiç beklemez ve iki işlem
aynı `open` satırı okuyup ikisi de kapatır. Bu yüzden iki eşzamanlılık testi de
`donem_var` üzerinden PARAMETRELİDİR; mutasyonu yakalayan dal `True` dalıdır,
`False` dalı ise UPSERT'ün kendi serileştirmesini korur.

*"Test var" ≠ "test bekçilik ediyor"* — bu satırlar o dersin bedelidir.

## Mutasyon kanıtı

`lock_period`taki `with_for_update` kaldırılırsa (`donem_var=True` dalları):
* test 1 → iki `close` de 'closed' döndürür (`count == 1` KIRMIZI);
* test 2 → hem dönem kapanır hem içine taze bir `draft` fiş düşer
  (`count("conflict") == 1` KIRMIZI).
"""

import asyncio

import pytest
from sqlalchemy import select, tuple_

from app.modules.accounting.models import (
    AccountingPeriod,
    AccountingPeriodStatus,
    JournalEntry,
    JournalEntryCounter,
    JournalEntryStatus,
)
from tests.modules.accounting._mu2_periods_lock import (
    _DONEMLER,
    _TAVAN_SANIYE,
    AY,
    ONCEKI,
    YIL,
    _ac_donem,
    _fis_olustur,
    _guvenli_temizlik,
    _kapat,
    _kayitlastir,
    _kur,
    _SessionFactory,
    _temizle,
)

# --------------------------------------------------------------------------- #
# (i) İki eşzamanlı `close`
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("donem_var", [False, True])
async def test_1_IKI_ESZAMANLI_close_YALNIZ_BIRI_gecer(donem_var: bool) -> None:
    """🔴 EŞİK = KİLİT — iki istek AYNI dönemi aynı anda kapatmak ister.

    Doğru davranış: BİRİ `closed` yazar, ÖTEKİ **409** alır ve ortada TEK satır
    kalır.

    * `donem_var=False` → satır YOKTUR; UPSERT'ün kendi serileştirmesi
      (`ON CONFLICT` UNIQUE indeks kilidi) ve 500'süzlük ölçülür.
    * `donem_var=True` → satır ZATEN VARDIR; UPSERT hiç beklemez ve tek koruma
      `FOR UPDATE`tir. **Mutasyonu yakalayan dal budur:** kilit kaldırılırsa
      ikisi de `open` okur, ikisi de damgayı yazar ve `count("closed") == 1`
      KIRMIZI'ya döner.

    `error:` sonuçları ayrıca iddia edilir: `ON CONFLICT DO NOTHING` yerine düz
    bir INSERT yazılsaydı biri `IntegrityError` (canlıda 500) alırdı ve sayım
    yine 1 çıkardı — kusur GÖRÜNMEZ kalırdı.
    """
    kurulum = await _kur(donem_var=donem_var)
    baraj = asyncio.Barrier(2)
    gorevler: list[asyncio.Task] = []
    try:
        gorevler = [
            asyncio.create_task(_kapat(kurulum, 0, baraj)),
            asyncio.create_task(_kapat(kurulum, 1, baraj)),
        ]
        sonuclar = list(await asyncio.wait_for(asyncio.gather(*gorevler), timeout=_TAVAN_SANIYE))
        assert not [s for s in sonuclar if s.startswith("error:")], (
            f"eşzamanlı `close` bir istisna sızdırdı ({sonuclar}) — `lock_period` "
            "UPSERT-sonra-kilitle desenini uygulamıyor; canlıda bu bir 500'dür"
        )
        assert sonuclar.count("closed") == 1, (
            f"iki eşzamanlı `close` de geçti ({sonuclar}) — `lock_period` dönem satırını "
            "DENETİMDEN ÖNCE kilitlemiyor; dönem iki kez kapatılmış sayılır"
        )
        assert sonuclar.count("conflict") == 1, sonuclar

        async with _SessionFactory() as session:
            satirlar = (
                (
                    await session.execute(
                        select(AccountingPeriod).where(
                            AccountingPeriod.year == YIL, AccountingPeriod.month == AY
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(satirlar) == 1, "aynı (yıl, ay) için birden fazla satır doğdu"
            assert satirlar[0].status is AccountingPeriodStatus.closed
            assert satirlar[0].closed_at is not None
            assert satirlar[0].closed_by_id is not None
    finally:
        await _guvenli_temizlik(kurulum, *gorevler)


# --------------------------------------------------------------------------- #
# (ii) `close` + yazma
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("donem_var", [False, True])
async def test_2_ESZAMANLI_close_ve_FIS_OLUSTURMA_yalniz_biri_gecer(donem_var: bool) -> None:
    """🔴 Kapalı döneme yazma yasağının EŞZAMANLI hâli — ASIL mutasyon regresyonu.

    `close` dönem satırını kilitler; `create_entry` de AYNI satırı (UPSERT
    sonrası `FOR UPDATE`) kilitler. Bu yüzden ikisi SERİLEŞİR:
    * `close` önce geçerse → `create_entry` kapalı dönem görür ve **409** alır;
    * `create_entry` önce geçerse → `close` dönemde bir `draft` fiş bulur ve
      **409** alır.

    Kilitsiz hâlde ikisi de geçer: dönem kapanır VE içine taptaze bir taslak fiş
    düşer — kapanmış mizan geçmişe dönük değişir ve bunu hiçbir kolon farkı ele
    vermez. **Mutasyonu yakalayan dal `donem_var=True`dur** (gerekçe modül
    docstring'i: satır yokken serileştirmeyi UPSERT'ün kendisi yapar).
    """
    kurulum = await _kur(donem_var=donem_var)
    baraj = asyncio.Barrier(2)
    gorevler: list[asyncio.Task] = []
    try:
        gorevler = [
            asyncio.create_task(_kapat(kurulum, 0, baraj)),
            asyncio.create_task(_fis_olustur(kurulum, 1, baraj)),
        ]
        kapanis, yazma = await asyncio.wait_for(asyncio.gather(*gorevler), timeout=_TAVAN_SANIYE)
        assert not kapanis.startswith("error:") and not yazma.startswith("error:"), (
            kapanis,
            yazma,
        )
        assert [kapanis, yazma].count("conflict") == 1, (
            f"kapanış={kapanis} · yazma={yazma} — ikisi de geçtiyse KAPALI bir döneme "
            "fiş yazılmış demektir (dönem satırı denetimden önce kilitlenmiyor)"
        )

        async with _SessionFactory() as session:
            donem = (
                await session.execute(
                    select(AccountingPeriod).where(
                        AccountingPeriod.year == YIL, AccountingPeriod.month == AY
                    )
                )
            ).scalar_one()
            taslaklar = (
                (
                    await session.execute(
                        select(JournalEntry).where(
                            JournalEntry.period_year == YIL,
                            JournalEntry.period_month == AY,
                            JournalEntry.status == JournalEntryStatus.draft,
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert not (donem.status is AccountingPeriodStatus.closed and taslaklar), (
                "dönem KAPALI ama içinde taslak fiş var — son durum tutarsız"
            )
    finally:
        await _guvenli_temizlik(kurulum, *gorevler)


async def test_2b_ESZAMANLI_close_ve_post_SON_DURUM_TUTARLI() -> None:
    """`close` + `post` — dönemde kayıtlaştırılacak `draft` fiş VARDIR.

    Kurulum gereği `close` ancak o taslak `posted` olduktan SONRA geçebilir
    (adım 3 draft kapısı). Yani `post` HER ZAMAN kazanır; `close` ya sonra geçer
    ya 409 alır. İddia edilen şey SON DURUMUN TUTARLILIĞIDIR: kapalı bir dönemde
    `draft` fiş KALMAZ ve hiçbir istek 500 üretmez.

    (Yasağın mutasyon kanıtı yukarıdaki `close` + `create_entry` testindedir:
    bu senaryoda `post`un kaybedebileceği bir dal KURULUM GEREĞİ yoktur ve
    sayıma dayalı bir iddia kilidi sınamazdı — bu ayrım bilerek yazılıdır.)
    """
    kurulum = await _kur(taslak_fis=True)
    baraj = asyncio.Barrier(2)
    gorevler: list[asyncio.Task] = []
    try:
        gorevler = [
            asyncio.create_task(_kapat(kurulum, 0, baraj)),
            asyncio.create_task(_kayitlastir(kurulum, 1, baraj)),
        ]
        kapanis, gecis = await asyncio.wait_for(asyncio.gather(*gorevler), timeout=_TAVAN_SANIYE)
        assert not kapanis.startswith("error:") and not gecis.startswith("error:"), (
            kapanis,
            gecis,
        )
        assert gecis == "posted", gecis
        assert kapanis in {"closed", "conflict"}, kapanis

        async with _SessionFactory() as session:
            entry = await session.get(JournalEntry, kurulum.entry_id)
            assert entry.status is JournalEntryStatus.posted
            donem = (
                await session.execute(
                    select(AccountingPeriod).where(
                        AccountingPeriod.year == YIL, AccountingPeriod.month == AY
                    )
                )
            ).scalar_one_or_none()
            if donem is not None and donem.status is AccountingPeriodStatus.closed:
                taslak_sayisi = (
                    (
                        await session.execute(
                            select(JournalEntry).where(
                                JournalEntry.period_year == YIL,
                                JournalEntry.period_month == AY,
                                JournalEntry.status == JournalEntryStatus.draft,
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                assert not taslak_sayisi, "kapalı dönemde taslak fiş kaldı"
    finally:
        await _guvenli_temizlik(kurulum, *gorevler)


# --------------------------------------------------------------------------- #
# (iii) `close` + `reopen`
# --------------------------------------------------------------------------- #


async def test_3_ESZAMANLI_close_ve_reopen_TEK_SATIR_TUTARLI_DAMGA() -> None:
    """Kilit sırası her iki uçta AYNI olduğu için ikisi SERİLEŞİR.

    Satır YOKTUR: iki istek de onu UPSERT etmek ister. Beklenen sonuç kümesi
    ikisinden biridir — `close` önce geçerse `reopen` de geçer (kapalıyı açar),
    `reopen` önce geçerse zaten açık olan dönemde **409** alır ve `close` geçer.
    Her iki dalda da ortada **TEK** satır kalır ve damgası durumuyla TUTARLIDIR
    (`ck_accounting_periods_closed_stamp`); hiçbir dalda 500 yoktur.
    """
    kurulum = await _kur()
    baraj = asyncio.Barrier(2)
    gorevler: list[asyncio.Task] = []
    try:
        gorevler = [
            asyncio.create_task(_kapat(kurulum, 0, baraj)),
            asyncio.create_task(_ac_donem(kurulum, 1, baraj)),
        ]
        kapanis, acilis = await asyncio.wait_for(asyncio.gather(*gorevler), timeout=_TAVAN_SANIYE)
        assert not kapanis.startswith("error:") and not acilis.startswith("error:"), (
            kapanis,
            acilis,
        )
        assert kapanis == "closed", kapanis
        assert acilis in {"opened", "conflict"}, acilis

        async with _SessionFactory() as session:
            satirlar = (
                (
                    await session.execute(
                        select(AccountingPeriod).where(
                            AccountingPeriod.year == YIL, AccountingPeriod.month == AY
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(satirlar) == 1, "aynı (yıl, ay) için birden fazla satır doğdu"
            donem = satirlar[0]
            kapali = donem.status is AccountingPeriodStatus.closed
            assert (donem.closed_at is not None) is kapali
            assert (donem.closed_by_id is not None) is kapali
    finally:
        await _guvenli_temizlik(kurulum, *gorevler)


# --------------------------------------------------------------------------- #
# (iv) SIRA-B — iki KOMŞU dönemin eşzamanlı kapanışı
# --------------------------------------------------------------------------- #


async def test_4_ESZAMANLI_KOMSU_close_KRONOLOJIK_TUTARSIZLIK_URETMEZ() -> None:
    """🔴 SIRA-B / K6 — Temmuz ve Ağustos AYNI ANDA kapatılmak istenirse ne olur?

    Kronolojik sıra denetimi önceki dönemi **KİLİTLEMEZ** (`repository.get_period`,
    `FOR UPDATE` yok). Emir haklı olarak sordu: bu, ikisini birden geçirir mi?

    **Ölçüm (6 koşu, deterministik):** bu kurulumda (AY-1 KAYITLI ve `open`)
    sonuç DAİMA `['closed', 'conflict']`tır — `AY`ı kapatan görev, `AY-1`i
    henüz commit edilmemiş hâlde yani `open` okur ve **409** alır. READ
    COMMITTED altında öteki işlemin damgası görünmez; denetim yani kilitsiz
    olmasına rağmen MUHAFAZAKÂR yönde yanılır.

    `AY-1` KAYITSIZ olsaydı ikisi de geçerdi (K2) — o da SORUN DEĞİLDİR.
    Burada korunacak eşik/sayaç yoktur; korunacak şey bir SON DURUM
    invaryantıdır:

        🔴 "kapalı bir dönemin takvim öncesi, KAYITLI ve `open` olamaz"

    "İkisi de kapandı" bu invaryantı SAĞLAR. Bozan tek son durum
    *"AY kapalı, AY-1 açık"*tır ve hiçbir sıralama onu üretemez: `AY`ı geçiren
    okuma `AY-1`i ya `closed` ya KAYITSIZ görmüştür, ve `AY-1`i kayıtlı-`open`
    bırakabilecek tek yol olan BAŞARISIZ bir `close` denemesi kendi UPSERT'ünü
    de geri sarar (READ COMMITTED altında o satır zaten hiç görünmez).

    Bu yüzden kilit GENİŞLETİLMEDİ: önceki dönemi de kilitlemek modül
    docstring'indeki SABİT kilit sırasına yeni bir kenar eklerdi ve karşılığında
    hiçbir invaryant kazandırmazdı.

    Test bu invaryantı ölçer, "kaç tanesi geçti"yi DEĞİL — sayıya bağlanan bir
    iddia, yarışın nasıl düştüğüne göre kâh yeşil kâh kırmızı olurdu (görsel
    turdaki `flaky` dersi).
    """
    kurulum = await _kur(donem_var=True, sira_zinciri=True)
    baraj = asyncio.Barrier(2)
    gorevler: list[asyncio.Task] = []
    try:
        gorevler = [
            asyncio.create_task(_kapat(kurulum, 0, baraj, ONCEKI[0], ONCEKI[1])),
            asyncio.create_task(_kapat(kurulum, 1, baraj, YIL, AY)),
        ]
        sonuclar = list(await asyncio.wait_for(asyncio.gather(*gorevler), timeout=_TAVAN_SANIYE))
        assert not [s for s in sonuclar if s.startswith("error:")], (
            f"eşzamanlı komşu `close` bir istisna sızdırdı ({sonuclar}) — canlıda 500"
        )

        async with _SessionFactory() as session:
            durum = {
                (satir.year, satir.month): satir.status
                for satir in (
                    (
                        await session.execute(
                            select(AccountingPeriod).where(
                                tuple_(AccountingPeriod.year, AccountingPeriod.month).in_(_DONEMLER)
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
            }
        if durum.get((YIL, AY)) is AccountingPeriodStatus.closed:
            assert durum.get(ONCEKI) is not AccountingPeriodStatus.open, (
                f"🔴 KRONOLOJİK TUTARSIZLIK: {YIL}/{AY} kapalı ama {ONCEKI} kayıtlı ve AÇIK "
                f"(sonuçlar: {sonuclar}, durum: {durum}) — sıra denetimi eşzamanlı "
                "kapanışta sızıntı veriyor"
            )
    finally:
        await _guvenli_temizlik(kurulum, *gorevler)


async def test_5_ESZAMANLI_ONCEKI_reopen_ve_SONRAKI_close_SIZINTI_OLCUMU() -> None:
    """🔴 SIRA-B / K6 ikinci yön — `reopen(AY-1)` ile `close(AY)` aynı anda.

    Bu, sıra kuralını eşzamanlı olarak DELEBİLECEK tek gerçek desendir:
    `close(AY)` `AY-1`i `closed` okurken, `reopen(AY-1)` onu `open`a çevirebilir
    ve son durum *"AY kapalı, AY-1 açık"* olur.

    **Ama bu bir KUSUR DEĞİL, K5'in KENDİSİDİR.** Aynı son duruma sıralı olarak
    da ulaşılır ve bu MEŞRUDUR: "Ağustos kapalıyken Temmuz'u geri aç" tam olarak
    yöneticinin elinde bırakılan düzeltme yoludur (`reopen` `admin` yetkisinde,
    `close` `full`). Kilit koyarak engellenecek bir şey yoktur; engellenseydi
    yönetici düzeltemeyeceği bir defterle baş başa kalırdı.

    **Ölçüm (6 koşu, deterministik):** `['opened', 'closed']` — son durum
    *"AY kapalı, AY-1 açık"*. Yani sıra kuralı eşzamanlı `reopen` ile GERÇEKTEN
    delinebilir; delen şey `close`un kilitsiz okuması değil, `reopen`in K5
    gereği hiçbir sıra kuralına tabi OLMAMASIDIR — aynı sonuca iki ayrı
    istekle, sırayla da ulaşılır. Kilit genişletmek bunu değiştirmezdi.

    Test bu yüzden yasak KOYMAZ, iki şeyi ölçer: (a) 500 SIZMAZ, (b) `AY-1`
    satırı TEKTİR ve damgası kendi durumuyla TUTARLIDIR
    (`ck_accounting_periods_closed_stamp`).
    """
    kurulum = await _kur(donem_var=True, sira_zinciri=True)
    baraj = asyncio.Barrier(2)
    gorevler: list[asyncio.Task] = []
    try:
        # `AY-1`i önce KAPAT (sıralı, yarışsız) — `reopen` için kapalı olmalı.
        tek = asyncio.Barrier(1)
        assert await _kapat(kurulum, 0, tek, ONCEKI[0], ONCEKI[1]) == "closed"

        gorevler = [
            asyncio.create_task(_ac_donem(kurulum, 0, baraj, ONCEKI[0], ONCEKI[1])),
            asyncio.create_task(_kapat(kurulum, 1, baraj, YIL, AY)),
        ]
        sonuclar = list(await asyncio.wait_for(asyncio.gather(*gorevler), timeout=_TAVAN_SANIYE))
        assert not [s for s in sonuclar if s.startswith("error:")], (
            f"eşzamanlı `reopen`+`close` bir istisna sızdırdı ({sonuclar}) — canlıda 500"
        )

        async with _SessionFactory() as session:
            satirlar = (
                (
                    await session.execute(
                        select(AccountingPeriod).where(
                            AccountingPeriod.year == ONCEKI[0],
                            AccountingPeriod.month == ONCEKI[1],
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(satirlar) == 1, "aynı (yıl, ay) için birden fazla satır doğdu"
            onceki = satirlar[0]
            if onceki.status is AccountingPeriodStatus.open:
                assert onceki.closed_at is None and onceki.closed_by_id is None, (
                    "geri açılan dönem eski kapatma damgasını taşıyor — mali iz YALAN SÖYLER"
                )
            else:
                assert onceki.closed_at is not None and onceki.closed_by_id is not None
    finally:
        await _guvenli_temizlik(kurulum, *gorevler)


async def test_6_TEMIZLIK_HICBIR_SATIR_BIRAKMAZ_sayac_DAHIL() -> None:
    """🔴 SIZINTI KATMANININ KENDI BEKÇİSİ (TB-XDIST, 2026-08-25).

    Bu dosya `db_session` yalıtımını KULLANMAZ: kendi bağlantılarında GERÇEKTEN
    commit eder, yani bıraktığı her satır **paylaşılan test veritabanında kalıcıdır**
    ve sonraki testlere sızar. `_temizle` bu yüzden TEK korumadır.

    Fiilen sızdı: `_kur(taslak_fis=True)` `generate_entry_no(..., year=YIL)` çağırıp
    `journal_entry_counters`e `{2031: N}` satırı yazıyordu; `_temizle` o tabloyu
    hiç bilmiyordu. `test_fisno_numbering.py::test_YIL_sayaclari_BIRBIRINI_sifirlamaz`
    tabloyu GLOBAL okuduğu için kırmızıya döndü. Seri koşuda görünmüyordu — alfabetik
    sırada `test_fisno_*` bu dosyadan ÖNCE koşuyor; sıra değişince (xdist
    `--dist loadfile`) hemen patladı. İki dosya bu sırayla SERİ koşulunca da kırmızı
    olduğu ÖLÇÜLDÜ: kusur paralellikten DEĞİL, temizliğin eksikliğinden geliyordu.

    🔴 Bu bekçi neden AYRI: sızıntı kapatıldıktan sonra karşı taraftaki iddia da
    kendi yıllarına daraltıldı. İki katman birbirini MASKELER — daraltma yerinde
    dururken `_temizle`den sayaç silmeyi kaldırmak hiçbir testi kırmıyordu
    (ölçüldü). Bu test, sızıntı katmanına DOĞRUDAN bakar (WORKFLOW §4: "çok
    katmanlı korumada mutasyon kanıtı her katman için AYRI verilir").
    """
    kurulum = await _kur(taslak_fis=True, donem_var=True, sira_zinciri=True)
    await _temizle(kurulum)

    async with _SessionFactory() as session:
        artik_sayac = (
            (
                await session.execute(
                    select(JournalEntryCounter).where(JournalEntryCounter.year == YIL)
                )
            )
            .scalars()
            .all()
        )
        assert artik_sayac == [], (
            f"`_temizle` `journal_entry_counters` satırını BIRAKTI (yıl {YIL}) — "
            "bu dosya gerçekten commit ediyor, artık satır sonraki testlere SIZAR."
        )

        artik_donem = (
            (
                await session.execute(
                    select(AccountingPeriod).where(
                        tuple_(AccountingPeriod.year, AccountingPeriod.month).in_(_DONEMLER)
                    )
                )
            )
            .scalars()
            .all()
        )
        assert artik_donem == [], "`_temizle` dönem satırı bıraktı."

        artik_fis = (
            (
                await session.execute(
                    select(JournalEntry).where(
                        JournalEntry.period_year == YIL, JournalEntry.period_month == AY
                    )
                )
            )
            .scalars()
            .all()
        )
        assert artik_fis == [], "`_temizle` fiş satırı bıraktı."
