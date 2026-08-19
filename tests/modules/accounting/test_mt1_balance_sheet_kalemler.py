"""MT-1 T4 — Bilanço: `Dönem Net Kârı` · denge · para · kapsam dışı · N+1.

`test_mt1_balance_sheet.py`nin devamıdır; kurulum yardımcıları
`_balance_sheet.py`de PAYLAŞILIR (800 satır tavanı, `_journal.py` emsali).
Bu dosya bilançonun **türetilen** yüzeyini kilitler:

* 🔴 MT-K3 — `Dönem Net Kârı` `6xx`/`7xx`ten türer, `59` grubu ÇİFT SAYILMAZ ve
  önceki yılların sonucu `Geçmiş Yıllar Kârları`na gider (T7 final review'de
  bulunan CRITICAL kusurun bekçileri buradadır).
* 🔴 `is_balanced` ÖLÇÜLÜR, `True` VARSAYILMAZ.
* MT-K2 uç YUVARLAMAZ · MT-K5/K6/K8/K9 açılmayanlar · N+1 sayacı.
"""

from datetime import date
from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounting import balance_sheet
from app.modules.accounting.models import JournalEntryStatus
from tests.modules.accounting._balance_sheet import (
    _T,
    AS_OF,
    YOL,
    _bilanco,
    _bolum,
    _kalem,
    _sorgu_sayaci,
    _tutar,
)

# --------------------------------------------------------------------------- #
# 5. 🔴 MT-K3 — Dönem Net Kârı ve ÇİFT SAYIM YASAĞI
# --------------------------------------------------------------------------- #


async def test_donem_net_kari_6xx_eksi_7xx(
    client: AsyncClient, muhasebe_headers: dict[str, str], hesap_fabrikasi, fis_fabrikasi
) -> None:
    """🔑 MT-K3: `Dönem Net Kârı` bir GRUPTAN okunmaz, `6xx`/`7xx` penceresinden
    TÜRETİLİR ve formül `statement_map.period_profit()`te TEK KOPYADIR (Gelir
    Tablosu dilimi onu İTHAL EDER)."""
    kasa = await hesap_fabrikasi("100", name="Kasa", account_type=_T.asset)
    satis = await hesap_fabrikasi("600", name="Yurt İçi Satışlar", account_type=_T.revenue)
    gider = await hesap_fabrikasi("730", name="Genel Üretim Gid.", account_type=_T.expense)

    await fis_fabrikasi([(kasa, "5000.00", "0"), (satis, "0", "5000.00")])
    await fis_fabrikasi([(gider, "1800.00", "0"), (kasa, "0", "1800.00")])

    govde = await _bilanco(client, muhasebe_headers)
    assert _tutar(govde, "period_profit") == Decimal("3200.00")
    assert _tutar(govde, "cash") == Decimal("3200.00")
    assert govde["is_balanced"] is True


async def test_donem_kari_penceresi_YILBASINDA_baslar_sinir_gunu(
    client: AsyncClient, muhasebe_headers: dict[str, str], hesap_fabrikasi, fis_fabrikasi
) -> None:
    """🔴 MU-2 T6 DERSİNİN İKİNCİ ISIRIĞI — `year-01-01` sınırı.

    Önceki yılın kârı `Dönem Net Kârı`na GİRMEZ; bilanço gövdesindeki kasa ise
    kümülatiftir ve DURUR. Sınır `<` yazılsaydı 1 Ocak'ta kesilen fiş hiçbir
    yıla ait olmaz ve kâr sessizce eksik çıkardı; `<=` yerine önceki yılı da
    alan bir pencere ise geçmiş yılların kârını bu yıla taşırdı.

    Üç fiş: 2025-12-31 (önceki yıl) · 2026-01-01 (SINIR GÜNÜ) · 2026-06-15.
    """
    kasa = await hesap_fabrikasi("100", name="Kasa", account_type=_T.asset)
    satis = await hesap_fabrikasi("600", name="Yurt İçi Satışlar", account_type=_T.revenue)

    await fis_fabrikasi(
        [(kasa, "700.00", "0"), (satis, "0", "700.00")], entry_date=date(2025, 12, 31)
    )
    await fis_fabrikasi(
        [(kasa, "300.00", "0"), (satis, "0", "300.00")], entry_date=date(2026, 1, 1)
    )
    await fis_fabrikasi(
        [(kasa, "500.00", "0"), (satis, "0", "500.00")], entry_date=date(2026, 6, 15)
    )

    govde = await _bilanco(client, muhasebe_headers)
    # 🔴 Yalnız 2026: 300 + 500. 2025'in 700'ü DIŞARIDA.
    assert _tutar(govde, "period_profit") == Decimal("800.00")
    # Gövde KÜMÜLATİFTİR: kasa üç fişi de taşır.
    assert _tutar(govde, "cash") == Decimal("1500.00")
    # 🔴 T7 FINAL REVIEW'ÜN BULDUĞU KUSUR: 2025'in 700'ü `Dönem Net Kârı`ndan
    # ÇIKARILDI ama BİR YERE KONULMADI — ilk yazımda hiçbir kaleme girmiyordu ve
    # bu test onu GÖRMÜYORDU çünkü `is_balanced`i hiç okumuyordu.
    # Bkz. bir alttaki test: kural ÜÇ pencereye çıkar.
    assert _tutar(govde, "retained_earnings") == Decimal("700.00")
    assert govde["is_balanced"] is True


async def test_ONCEKI_YILLARIN_kar_zarari_GECMIS_YILLAR_KARLARINA_gider(
    client: AsyncClient, muhasebe_headers: dict[str, str], hesap_fabrikasi, fis_fabrikasi
) -> None:
    """🔴 T7 FINAL REVIEW BULGUSU — bilançonun ÜÇ penceresi vardır, iki değil.

    Ürünte **KAPANIŞ AKIŞI YOKTUR** (`models.py` "AÇILMAYANLAR"): `6xx`/`7xx`
    hesapları hiçbir zaman `570`e kapatılmaz, bakiyeleri yıllar boyunca DEFTERDE
    KALIR. Bilanço gövdesi onları dışlar (`Dönem Net Kârı` ile çift sayılmasınlar
    diye) ve `Dönem Net Kârı` **yalnız bu yılın** penceresinden türer. Aradaki
    üçüncü küme — `entry_date < {as_of.year}-01-01` tarihli gelir/gider
    hareketleri — ilk yazımda **HİÇBİR KALEME girmiyordu**.

    🔴 Bu bir uç durum DEĞİL, takvimin kendisidir: 2026'da defter tutan bir
    şirketin **2027'de çekilen HER bilançosu** geçen yılın kârı kadar
    dengesizdir. Kusur canlıda kod değişmeden, yalnız yıl dönerken doğardı.

    Doğru yer `Geçmiş Yıllar Kârları`dır (BL:82) — kapanış fişi atılmış olsaydı
    `59` üzerinden zaten oraya taşınacaktı. Aynı pencere ayrımı `59` grubunun
    dışlanmasıyla da tutarlıdır (MT-K1/2).

    Kurulum: 2024 kârı 400 · 2025 zararı −150 · 2026 kârı 900."""
    kasa = await hesap_fabrikasi("100", name="Kasa", account_type=_T.asset)
    satis = await hesap_fabrikasi("600", name="Yurt İçi Satışlar", account_type=_T.revenue)
    gider = await hesap_fabrikasi("730", name="Genel Üretim Gid.", account_type=_T.expense)

    await fis_fabrikasi(
        [(kasa, "400.00", "0"), (satis, "0", "400.00")], entry_date=date(2024, 6, 1)
    )
    await fis_fabrikasi(
        [(gider, "150.00", "0"), (kasa, "0", "150.00")], entry_date=date(2025, 9, 9)
    )
    await fis_fabrikasi(
        [(kasa, "900.00", "0"), (satis, "0", "900.00")], entry_date=date(2026, 4, 4)
    )

    govde = await _bilanco(client, muhasebe_headers)
    assert _tutar(govde, "cash") == Decimal("1150.00")  # 400 − 150 + 900
    assert _tutar(govde, "period_profit") == Decimal("900.00")  # yalnız 2026
    assert _tutar(govde, "retained_earnings") == Decimal("250.00")  # 400 − 150
    assert Decimal(govde["assets"]["total"]) == Decimal("1150.00")
    assert Decimal(govde["liabilities"]["total"]) == Decimal("1150.00")
    assert govde["is_balanced"] is True


async def test_GECMIS_YILLAR_KARLARI_57_HESABIYLA_TOPLANIR(
    client: AsyncClient, muhasebe_headers: dict[str, str], hesap_fabrikasi, fis_fabrikasi
) -> None:
    """Türetilen geçmiş dönem sonucu, `57` grubunun GERÇEK bakiyesinin YERİNE
    geçmez, ona EKLENİR.

    Kapanış fişi atmış bir şirkette `570` dolu olur ve `6xx`/`7xx` boşalır;
    atmamışta tersi. İkisi TOPLANIR ki her iki hâlde de aynı sayı çıksın —
    biri ötekini ezseydi kapanış yapan şirketin bilançosu geçmiş kârını
    kaybederdi."""
    kasa = await hesap_fabrikasi("100", name="Kasa", account_type=_T.asset)
    gecmis = await hesap_fabrikasi("570", name="Geçmiş Yıllar Kârları", account_type=_T.equity)
    satis = await hesap_fabrikasi("600", name="Yurt İçi Satışlar", account_type=_T.revenue)

    await fis_fabrikasi(
        [(kasa, "1000.00", "0"), (gecmis, "0", "1000.00")], entry_date=date(2025, 1, 5)
    )
    await fis_fabrikasi(
        [(kasa, "200.00", "0"), (satis, "0", "200.00")], entry_date=date(2025, 8, 8)
    )

    govde = await _bilanco(client, muhasebe_headers)
    assert _tutar(govde, "retained_earnings") == Decimal("1200.00")  # 1000 kayıtlı + 200 türetilen
    assert _tutar(govde, "period_profit") == Decimal("0")
    assert govde["is_balanced"] is True


async def test_59_grubu_CIFT_SAYILMAZ(
    client: AsyncClient, muhasebe_headers: dict[str, str], hesap_fabrikasi, fis_fabrikasi
) -> None:
    """🔴 MT-K1/2 ÇİFT SAYIM YASAĞI.

    `590 Dönem Net Kârı` bir KAPANIŞ hesabıdır ve üründe kapanış akışı YOKTUR.
    Bakiyesi olsa bile `III. ÖZKAYNAKLAR` bölümüne EKLENMEZ; `Dönem Net Kârı`
    kalemi DAİMA `6xx`/`7xx`ten türer. İkisi birden sayılsaydı kâr İKİ KEZ
    görünür ve özkaynaklar kâr kadar şişerdi.

    Bu kurulumda `590` 900 alacak bakiyeli, `6xx`/`7xx` ise 250 kâr üretiyor:
    özkaynak bölümü 250 + sermaye kadar olmalı, 1150 + sermaye DEĞİL."""
    kasa = await hesap_fabrikasi("100", name="Kasa", account_type=_T.asset)
    sermaye = await hesap_fabrikasi("500", name="Sermaye", account_type=_T.equity)
    donem = await hesap_fabrikasi("590", name="Dönem Net Kârı", account_type=_T.equity)
    satis = await hesap_fabrikasi("600", name="Yurt İçi Satışlar", account_type=_T.revenue)

    await fis_fabrikasi([(kasa, "1000.00", "0"), (sermaye, "0", "1000.00")])
    await fis_fabrikasi([(kasa, "250.00", "0"), (satis, "0", "250.00")])
    await fis_fabrikasi([(kasa, "900.00", "0"), (donem, "0", "900.00")])

    govde = await _bilanco(client, muhasebe_headers)
    ozkaynak = _bolum(govde, "liabilities", "equity")
    assert _tutar(govde, "period_profit") == Decimal("250.00")
    assert Decimal(ozkaynak["subtotal"]) == Decimal("1250.00")
    for satir in ozkaynak["lines"]:
        assert "590" not in satir["account_codes"], "59 grubu gövdeye sızdı"


async def test_gelir_tablosu_hesaplari_GOVDEYE_girmez(
    client: AsyncClient, muhasebe_headers: dict[str, str], hesap_fabrikasi, fis_fabrikasi
) -> None:
    """`600`/`730` hiçbir bilanço kaleminin `account_codes`unda görünmez —
    gövdeye de konsalardı aynı para hem kalem hem kâr olarak sayılırdı."""
    kasa = await hesap_fabrikasi("100", name="Kasa", account_type=_T.asset)
    satis = await hesap_fabrikasi("600", name="Satışlar", account_type=_T.revenue)
    gider = await hesap_fabrikasi("730", name="Üretim Gid.", account_type=_T.expense)
    await fis_fabrikasi([(kasa, "900.00", "0"), (satis, "0", "900.00")])
    await fis_fabrikasi([(gider, "200.00", "0"), (kasa, "0", "200.00")])

    govde = await _bilanco(client, muhasebe_headers)
    tum_kodlar = {
        kod
        for t in ("assets", "liabilities")
        for b in govde[t]["sections"]
        for s in b["lines"]
        for kod in s["account_codes"]
    }
    assert "600" not in tum_kodlar
    assert "730" not in tum_kodlar


# --------------------------------------------------------------------------- #
# 6. 🔴 `is_balanced` ÖLÇÜLÜR, VARSAYILMAZ
# --------------------------------------------------------------------------- #


async def test_DENGESIZ_reversed_fis_is_balanced_FALSE_yapar(
    client: AsyncClient, muhasebe_headers: dict[str, str], hesap_fabrikasi, fis_fabrikasi
) -> None:
    """🔴 Sabit `True` basan bir bilanço SESSİZCE YALAN SÖYLER.

    `POSTING_STATUSES` `reversed`ı deftere ALIR ve tek bacaklı bir defter
    dengesizdir. Bilançonun kontrol göstergesi bu yüzden ÖLÇÜLMEK zorundadır
    (mizanın `is_balanced`i emsal).

    🔴 **TB6 T2'DEN SONRA:** dengesizlik artık BAŞLIKTAN kurulamaz —
    `ck_journal_entries_posting_balanced` `posted`/`reversed` bir fişin
    `total_debit = total_credit` olmasını ZORLAR. Prob yine de kurulabilir ve
    iddiası DEĞİŞMEDİ, çünkü defter **SATIRLARI** toplar, başlığı DEĞİL:
    `header_totals` ile başlık dengeli yazılır, satırlar dengesiz bırakılır.
    (Uygulama böyle bir fiş üretemez — `apply_totals` yalnız `draft`ta koşar —
    ama ölçülecek şey `is_balanced`in SÜS OLMADIĞIDIR.)
    """
    kasa = await hesap_fabrikasi("100", name="Kasa", account_type=_T.asset)
    await fis_fabrikasi(
        [(kasa, "1200.00", "0")],
        status=JournalEntryStatus.reversed,
        header_totals=("1200.00", "1200.00"),
    )

    govde = await _bilanco(client, muhasebe_headers)
    assert _tutar(govde, "cash") == Decimal("1200.00")
    assert Decimal(govde["assets"]["total"]) == Decimal("1200.00")
    assert Decimal(govde["liabilities"]["total"]) == Decimal("0.00")
    assert govde["is_balanced"] is False


async def test_draft_GIRMEZ_reversed_GIRER(
    client: AsyncClient, muhasebe_headers: dict[str, str], hesap_fabrikasi, fis_fabrikasi
) -> None:
    """`POSTING_STATUSES` (`balance.py` TEK KOPYA): `draft` yarım bir fiştir ve
    mali tabloyu kirletemez; `reversed` GİRER — kayıtlaştırılmış fiş defterden
    ÇIKMAZ, yalnız ters kaydıyla nötrlenir (çift ters kayıt kanonu)."""
    kasa = await hesap_fabrikasi("100", name="Kasa", account_type=_T.asset)
    sermaye = await hesap_fabrikasi("500", name="Sermaye", account_type=_T.equity)

    await fis_fabrikasi(
        [(kasa, "999.00", "0"), (sermaye, "0", "999.00")], status=JournalEntryStatus.draft
    )
    await fis_fabrikasi(
        [(kasa, "400.00", "0"), (sermaye, "0", "400.00")], status=JournalEntryStatus.reversed
    )

    govde = await _bilanco(client, muhasebe_headers)
    assert _tutar(govde, "cash") == Decimal("400.00")


# --------------------------------------------------------------------------- #
# 7. Para — MT-K2 uç YUVARLAMAZ
# --------------------------------------------------------------------------- #


async def test_UC_YUVARLAMAZ_kurus_korunur(
    client: AsyncClient, muhasebe_headers: dict[str, str], hesap_fabrikasi, fis_fabrikasi
) -> None:
    """🔴 MT-K2: uç yuvarlarsa ara toplamlar bileşenlerinden sapar ve
    `is_balanced` sahte biçimde FALSE olur.

    Üç kuruşlu kalem: 0,33 + 0,33 + 0,34 = 1,00. Yuvarlayan bir uç üç kalemi de
    `0` basar ama toplamı `1,00` gösterirdi."""
    kasa = await hesap_fabrikasi("100", name="Kasa", account_type=_T.asset)
    alici = await hesap_fabrikasi("120", name="Alıcılar", account_type=_T.asset)
    stok = await hesap_fabrikasi("150", name="Stok", account_type=_T.asset)
    sermaye = await hesap_fabrikasi("500", name="Sermaye", account_type=_T.equity)
    await fis_fabrikasi(
        [
            (kasa, "0.33", "0"),
            (alici, "0.33", "0"),
            (stok, "0.34", "0"),
            (sermaye, "0", "1.00"),
        ]
    )

    govde = await _bilanco(client, muhasebe_headers)
    assert _kalem(govde, "cash")["amount"] == "0.33"
    assert _kalem(govde, "trade_receivables")["amount"] == "0.33"
    assert _kalem(govde, "inventory")["amount"] == "0.34"
    assert Decimal(govde["assets"]["total"]) == Decimal("1.00")
    assert govde["is_balanced"] is True


# --------------------------------------------------------------------------- #
# 8. MT-K5/K6/K8 — açılmayanlar
# --------------------------------------------------------------------------- #


async def test_UCUN_TEK_parametresi_as_of_SOZLESMEDEN_dogrulanir(
    client: AsyncClient, muhasebe_headers: dict[str, str]
) -> None:
    """MT-K5 (proje/şantiye süzgeci YOK — üç muhasebe tablosunda da kolon
    yoktur ve mockup süzgeç çizmiyor) · MT-K6 (karşılaştırma sütunu YOK) ·
    MT-K10 (sayfalama zarfı KULLANILMAZ).

    🔴 İddia **SÖZLEŞMEDEN** (OpenAPI) okunur, istek denemesinden DEĞİL: FastAPI
    tanımsız sorgu parametrelerini sessizce YOK SAYAR, yani `?project_id=1`
    göndermek 422 vermez ve "422 bekliyorum" diye yazılmış bir test aslında
    çerçevenin davranışını sınardı (ölçüldü). Sözleşmede parametre YOKSA istemci
    onu üretmez — kusur kaynağında kapanır.

    Bir gün süzgeç gerçekten gerekirse bu test kırmızı olur ve kararın yeniden
    alınmasını ZORLAR."""
    resp = await client.get("/openapi.json", headers=muhasebe_headers)
    assert resp.status_code == 200, resp.text
    parametreler = resp.json()["paths"][YOL]["get"].get("parameters", [])
    assert [p["name"] for p in parametreler] == ["as_of"]
    assert parametreler[0]["required"] is True


async def test_KAPALI_DONEM_bilancoyu_DEGISTIRMEZ(
    client: AsyncClient,
    muhasebe_headers: dict[str, str],
    hesap_fabrikasi,
    fis_fabrikasi,
    donem_fabrikasi,
) -> None:
    """MT-K8: bilanço SALT-OKUMADIR; `assert_periods_open` ÇAĞRILMAZ ve kilit
    rozeti DÖNMEZ. Kapalı bir dönemin bilançosu ile açığınki arasında fark
    yoktur ve mockup rozet ÇİZMEMİŞTİR."""
    kasa = await hesap_fabrikasi("100", name="Kasa", account_type=_T.asset)
    sermaye = await hesap_fabrikasi("500", name="Sermaye", account_type=_T.equity)
    await fis_fabrikasi([(kasa, "700.00", "0"), (sermaye, "0", "700.00")])
    await donem_fabrikasi(2026, 7)

    govde = await _bilanco(client, muhasebe_headers)
    assert _tutar(govde, "cash") == Decimal("700.00")
    assert "period_locked" not in govde
    assert "is_locked" not in govde


async def test_GET_ucu_denetim_gunlugune_YAZMAZ(
    client: AsyncClient, muhasebe_headers: dict[str, str]
) -> None:
    """MT-K9 (`reports_router.py:33` kanonu): okumalar denetlenmez.

    🔴 Denetim AST tabanlıdır, düz metin grep DEĞİL: modül docstring'i kuralı
    ANLATIRKEN `record_audit` adını anar ve metin taraması onu yanlış alarm
    sayardı (fiilen oldu). `test_local_calendar_guard.py`nin AST tercihiyle
    aynı gerekçe."""
    import ast
    from pathlib import Path

    from app.modules.accounting import reports_router

    agac = ast.parse(Path(reports_router.__file__).read_text(encoding="utf-8"))
    adlar = {
        dugum.id if isinstance(dugum, ast.Name) else dugum.attr
        for dugum in ast.walk(agac)
        if isinstance(dugum, ast.Name | ast.Attribute)
    }
    assert "record_audit" not in adlar

    resp = await client.get(YOL, params={"as_of": AS_OF}, headers=muhasebe_headers)
    assert resp.status_code == 200


# --------------------------------------------------------------------------- #
# 9. N+1 — hesap sayısından BAĞIMSIZ
# --------------------------------------------------------------------------- #


async def test_sorgu_sayisi_HESAP_SAYISINDAN_bagimsizdir(
    seeded_db: AsyncSession, hesap_fabrikasi, fis_fabrikasi
) -> None:
    """🔴 N+1 tahminle değil SAYAÇLA ölçülür (`test_mu1_balance.py` emsali) ve
    ölçüm ÇEKİRDEK fonksiyona doğrudan yapılır — HTTP ucundan ölçülseydi
    oturum/izin sorguları sinyali boğardı.

    İki hesapla ve on hesapla AYNI sayıda sorgu koşmalıdır; hesap başına sorgu
    koşan bir uygulama tekdüzen hesap planında (~200 satır) patlardı."""
    kasa = await hesap_fabrikasi("100", name="Kasa", account_type=_T.asset)
    sermaye = await hesap_fabrikasi("500", name="Sermaye", account_type=_T.equity)
    await fis_fabrikasi([(kasa, "100.00", "0"), (sermaye, "0", "100.00")])
    await seeded_db.flush()

    with _sorgu_sayaci() as az:
        await balance_sheet.build_balance_sheet(seeded_db, as_of=date(2026, 7, 31))

    for sira in range(1, 9):
        borc = await hesap_fabrikasi(f"1{sira}0", name=f"Aktif {sira}", account_type=_T.asset)
        await fis_fabrikasi([(borc, "10.00", "0"), (sermaye, "0", "10.00")])
    await seeded_db.flush()

    with _sorgu_sayaci() as cok:
        await balance_sheet.build_balance_sheet(seeded_db, as_of=date(2026, 7, 31))

    assert len(az) == len(cok), f"N+1: {len(az)} → {len(cok)}\n" + "\n".join(cok)
    assert len(cok) <= 2, "beklenenden fazla sorgu:\n" + "\n".join(cok)
