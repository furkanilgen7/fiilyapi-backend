"""MU-2 T5 — `GET /vat-return` (KDV Beyannamesi).

Mockup: `projedesign/Muhasebe - KDV Beyanı.dc.html` (150 satır).

🔴 **HEPSİ HTTP UCUNDAN geçer** (MU-1 dersi, T4 emsali): tek istisna KURULUM
fabrikasıdır (`fatura_fabrikasi`); iddia edilen her davranış uçtan ölçülür.
Sorgu SAYISI ölçümü çekirdek fonksiyona doğrudan gider (HTTP katmanı oturum/izin
sorgularını ekler ve N+1 sinyalini boğardı).

## Ölçülen kusur sınıfları

1. 🔴 **İKİNCİ PARA FORMÜLÜ** (`test_matrah_avans_ve_teminat_DUSULMUS_*`).
   Matrahı SQL'de `SUM(line_total)` diye yeniden yazan bir uygulama, avans ve
   teminatı OLMAYAN her faturada doğru sonuç verir ve bu dosyanın öteki
   testlerinin hepsini geçer. Ayrışma ancak başlık düzeyindeki kesintiler
   doluyken görünür: `tax_base = subtotal − avans − teminat`.
2. 🔴 **ÇOK ORANLI KARIŞIM** (`test_cok_oranli_fatura_*`). Tek oranlı bir kurulum
   `vat_rate`i başlıktan okuyan bir kusuru göstermez; %20/%10/%1/%0 satırları
   AYNI faturada olunca gruplama ayrışır.
3. 🔴 **YUVARLAMA** (`test_yarim_kurus_ROUND_HALF_UP_*`). `round_money`
   `ROUND_HALF_UP`tır; Python `Decimal`in VARSAYILANI `ROUND_HALF_EVEN`dir.
   `100,50 × %1 = 1,005` iki kuralda FARKLI sonuç verir (1,01 ↔ 1,00) — kendi
   yuvarlamasını yazan bir uygulama tam burada ayrışır.
4. 🔴 **YAPISAL YASAK** (`test_vat_return_kaynaginda_IKINCI_yuvarlama_YOK`).
   Değer testi tek başına yetmez: bugün doğru sonuç veren bir kopya formül yarın
   `amounts.py` değiştiğinde sessizce sapardı. Kaynak metni denetlenir.
5. **Durum ve yön süzgeçleri** — her biri AYRI test (`draft`/`pending`/`disputed`
   girmez; `sent`/`collected`/`approved` girer; yön karışmaz).
6. **Ay penceresi** — TEK AY, iki sınırı da KAPALI; Şubat + artık yıl ayrı.
7. **Devreden KDV** — `payable` ve `carried_forward` aynı anda >0 OLAMAZ.
8. **N+1** — fatura sayısından bağımsız sabit sorgu (`before_cursor_execute`).
"""

import inspect
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounting import vat_return
from app.modules.invoicing import amounts
from app.modules.invoicing.models import (
    Invoice,
    InvoiceDirection,
    InvoiceDocumentType,
    InvoiceLine,
    InvoiceStatus,
)
from app.modules.users.models import User
from tests.conftest import test_engine

YOL = "/vat-return"

#: Mockup satır 45 — dönem `Haziran 2026`; satır 68 vade `28.07.2026`.
DONEM = {"year": 2026, "month": 6}


@contextmanager
def _sorgu_sayaci() -> Iterator[list[str]]:
    """Sürücüye giden HER ifadeyi toplar (`test_mu2_trial_balance.py` deseni)."""
    ifadeler: list[str] = []

    def kaydet(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001, ANN202
        ifadeler.append(statement)

    event.listen(test_engine.sync_engine, "before_cursor_execute", kaydet)
    try:
        yield ifadeler
    finally:
        event.remove(test_engine.sync_engine, "before_cursor_execute", kaydet)


@pytest.fixture
def fatura_fabrikasi(seeded_db: AsyncSession, user_factory):
    """Faturayı İSTENEN DURUMDA doğrudan kurar.

    🔴 Başlık para kolonları `amounts.compute` ile doldurulur — elle yazılsaydı
    fabrika kendi (ikinci) para formülünü doğurur ve testler uygulamayı değil
    fabrikayı ölçerdi. `vat_rate` SATIR BAZINDA parametredir: çok oranlı ayrışma
    noktası ancak böyle kurulabilir.

    `lines` = `(miktar, birim_fiyat, kdv_orani)` üçlüleri, hepsi metin.
    """
    sayac = {"n": 0}

    async def _create(
        *,
        direction: InvoiceDirection = InvoiceDirection.outgoing,
        status: InvoiceStatus = InvoiceStatus.sent,
        issue_date: date = date(2026, 6, 15),
        lines: list[tuple[str, str, str]] | None = None,
        advance_rate: str | None = None,
        retention_rate: str | None = None,
        withholding_rate: str | None = None,
    ) -> Invoice:
        sayac["n"] += 1
        creator = (
            await seeded_db.execute(select(User).where(User.email == "kdv@muhasebe.co"))
        ).scalar_one_or_none() or await user_factory(
            email="kdv@muhasebe.co", password="parola1234", role_key="system_admin"
        )
        satirlar = lines if lines is not None else [("1", "1000.00", "20.00")]
        girdiler = [
            amounts.LineInput(
                quantity=Decimal(miktar), unit_price=Decimal(fiyat), vat_rate=Decimal(oran)
            )
            for miktar, fiyat, oran in satirlar
        ]
        hesap = amounts.compute(
            girdiler,
            advance_rate=None if advance_rate is None else Decimal(advance_rate),
            retention_rate=None if retention_rate is None else Decimal(retention_rate),
            withholding_rate=None if withholding_rate is None else Decimal(withholding_rate),
        )
        invoice = Invoice(
            direction=direction,
            invoice_no=f"KDV{sayac['n']:09d}",
            document_type=InvoiceDocumentType.einvoice,
            status=status,
            issue_date=issue_date,
            party_name="Güneşkent Gayrimenkul A.Ş.",
            party_tax_number="1234567890",
            subtotal=hesap.subtotal,
            advance_rate=None if advance_rate is None else Decimal(advance_rate),
            advance_amount=hesap.advance_amount,
            retention_rate=None if retention_rate is None else Decimal(retention_rate),
            retention_amount=hesap.retention_amount,
            tax_base=hesap.tax_base,
            vat_amount=hesap.vat_amount,
            withholding_rate=None if withholding_rate is None else Decimal(withholding_rate),
            withholding_amount=hesap.withholding_amount,
            total=hesap.total,
            created_by_id=creator.id,
        )
        seeded_db.add(invoice)
        await seeded_db.flush()
        eslesen = zip(girdiler, hesap.line_totals, strict=True)
        for sira, (girdi, satir_toplami) in enumerate(eslesen):
            seeded_db.add(
                InvoiceLine(
                    invoice_id=invoice.id,
                    sort_order=sira,
                    description=f"Kalem {sira + 1}",
                    unit="m³",
                    quantity=girdi.quantity,
                    unit_price=girdi.unit_price,
                    vat_rate=girdi.vat_rate,
                    line_total=satir_toplami,
                )
            )
        await seeded_db.flush()
        return invoice

    return _create


async def _beyan(client: AsyncClient, headers: dict[str, str], **params) -> dict:
    resp = await client.get(YOL, params={**DONEM, **params}, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _oran_satiri(govde: dict, rate: str) -> dict:
    eslesen = [s for s in govde["taxable_rows"] if Decimal(s["rate"]) == Decimal(rate)]
    assert eslesen, f"%{rate} satırı yok: {govde['taxable_rows']}"
    return eslesen[0]


# --------------------------------------------------------------------------- #
# 1. Kapılar — izin ve aralık denetimi (T4 emsali)
# --------------------------------------------------------------------------- #


async def test_yetkisiz_rol_403(client: AsyncClient, yetkisiz_headers: dict[str, str]) -> None:
    """`site_chief` (`accounting=_N`) okumada bile 403 alır."""
    resp = await client.get(YOL, params=DONEM, headers=yetkisiz_headers)
    assert resp.status_code == 403, resp.text


async def test_view_seviyesi_YETER(client: AsyncClient, pm_headers: dict[str, str]) -> None:
    """`project_manager` (`accounting=_V`) beyanı OKUYABİLİR — beyan bir rapordur."""
    resp = await client.get(YOL, params=DONEM, headers=pm_headers)
    assert resp.status_code == 200, resp.text


async def test_kimliksiz_401(client: AsyncClient) -> None:
    resp = await client.get(YOL, params=DONEM)
    assert resp.status_code == 401, resp.text


@pytest.mark.parametrize(
    "params",
    [
        pytest.param({"month": 6}, id="year-yok"),
        pytest.param({"year": 2026}, id="month-yok"),
        pytest.param({"year": 1999, "month": 6}, id="year-alt-sinir"),
        pytest.param({"year": 2101, "month": 6}, id="year-ust-sinir"),
        pytest.param({"year": 2026, "month": 0}, id="month-alt-sinir"),
        pytest.param({"year": 2026, "month": 13}, id="month-ust-sinir"),
    ],
)
async def test_aralik_disi_ve_eksik_parametre_422(
    client: AsyncClient, pm_headers: dict[str, str], params: dict
) -> None:
    """🔴 `year`/`month` ZORUNLUDUR — sunucunun "bugün"üne HİÇ ihtiyaç yoktur ve
    TB5'in yerel-takvim kusuru bu uçta YAPISAL OLARAK imkânsızdır."""
    resp = await client.get(YOL, params=params, headers=pm_headers)
    assert resp.status_code == 422, resp.text


# --------------------------------------------------------------------------- #
# 2. 🔴 TEK PARA FORMÜLÜ — ayrışma noktaları
# --------------------------------------------------------------------------- #


async def test_matrah_avans_ve_teminat_DUSULMUS_tax_base_uzerindendir(
    client: AsyncClient, pm_headers: dict[str, str], fatura_fabrikasi
) -> None:
    """🔴 EN KRİTİK AYRIŞMA NOKTASI — ikinci para formülünün bekçisi.

    `subtotal` 1.000,00 · avans %10 (100,00) · teminat %5 (50,00) →
    `tax_base` **850,00** ve KDV `round(850 × %20)` = **170,00**.

    Matrahı `SUM(line_total)` diye yeniden yazan bir uygulama 1.000,00 / 200,00
    basar ve fatura özetiyle (`amounts.py`) ÇELİŞİR. Kesintisiz her kurulumda
    iki formül aynı sonucu verdiği için bu kusuru YALNIZ bu test görür.
    """
    await fatura_fabrikasi(
        lines=[("1", "1000.00", "20.00")], advance_rate="10.00", retention_rate="5.00"
    )

    govde = await _beyan(client, pm_headers)

    satir = _oran_satiri(govde, "20.00")
    assert Decimal(satir["base"]) == Decimal("850.00")
    assert Decimal(satir["vat"]) == Decimal("170.00")
    assert Decimal(govde["calculated_vat"]) == Decimal("170.00")


async def test_cok_oranli_fatura_gruplari_AYRISIR_ve_toplam_gruplara_esittir(
    client: AsyncClient, pm_headers: dict[str, str], fatura_fabrikasi
) -> None:
    """🔴 %20 · %10 · %1 · %0 AYNI faturada. Tek oranlı bir kurulum, oranı
    başlıktan okuyan bir kusuru göstermez."""
    await fatura_fabrikasi(
        lines=[
            ("1", "1000.00", "20.00"),
            ("1", "500.00", "10.00"),
            ("1", "200.00", "1.00"),
            ("1", "300.00", "0.00"),
        ]
    )

    govde = await _beyan(client, pm_headers)

    assert Decimal(_oran_satiri(govde, "20.00")["base"]) == Decimal("1000.00")
    assert Decimal(_oran_satiri(govde, "20.00")["vat"]) == Decimal("200.00")
    assert Decimal(_oran_satiri(govde, "10.00")["base"]) == Decimal("500.00")
    assert Decimal(_oran_satiri(govde, "10.00")["vat"]) == Decimal("50.00")
    assert Decimal(_oran_satiri(govde, "1.00")["base"]) == Decimal("200.00")
    assert Decimal(_oran_satiri(govde, "1.00")["vat"]) == Decimal("2.00")

    toplam = sum(Decimal(s["vat"]) for s in govde["taxable_rows"])
    assert Decimal(govde["calculated_vat"]) == toplam == Decimal("252.00")


async def test_taxable_rows_oran_AZALAN_siralidir(
    client: AsyncClient, pm_headers: dict[str, str], fatura_fabrikasi
) -> None:
    """Mockup satır 85-88 en yüksek oranı (`%20`) üstte çizer."""
    await fatura_fabrikasi(
        lines=[("1", "200.00", "1.00"), ("1", "1000.00", "20.00"), ("1", "500.00", "10.00")]
    )

    govde = await _beyan(client, pm_headers)

    oranlar = [Decimal(s["rate"]) for s in govde["taxable_rows"]]
    assert oranlar == sorted(oranlar, reverse=True), oranlar


async def test_yarim_kurus_ROUND_HALF_UP_bankaci_yuvarlamasindan_AYRISIR(
    client: AsyncClient, pm_headers: dict[str, str], fatura_fabrikasi
) -> None:
    """🔴 `100,50 × %1 = 1,005` · `300,50 × %1 = 3,005`.

    `ROUND_HALF_UP` (repo kanonu, `amounts.round_money`) **1,01** ve **3,01**;
    Python `Decimal`in VARSAYILANI `ROUND_HALF_EVEN` **1,00** ve **3,00** verir.
    Kendi yuvarlamasını yazan bir uygulama tam burada ayrışır — testin iddiası
    aynı zamanda iki kuralın gerçekten FARKLI olduğunu da doğrular.
    """
    for taban in ("100.50", "300.50"):
        yarim_kurus = Decimal(taban) * Decimal("1.00") / Decimal("100")
        bankaci = yarim_kurus.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
        assert bankaci != amounts.round_money(yarim_kurus), (
            f"{taban} ayrışma noktası DEĞİL — test değerini değiştir"
        )

    await fatura_fabrikasi(lines=[("1", "100.50", "1.00")])
    await fatura_fabrikasi(lines=[("1", "300.50", "1.00")])

    govde = await _beyan(client, pm_headers)

    # İki fatura AYRI yuvarlanır (fatura başına bir grup): 1,01 + 3,01.
    assert Decimal(_oran_satiri(govde, "1.00")["base"]) == Decimal("401.00")
    assert Decimal(_oran_satiri(govde, "1.00")["vat"]) == Decimal("4.02")
    assert Decimal(govde["calculated_vat"]) == Decimal("4.02")


async def test_buyuk_tutar_tasmadan_toplanir(
    client: AsyncClient, pm_headers: dict[str, str], fatura_fabrikasi
) -> None:
    """`Numeric(18, 2)` sınırına yakın tutar — `19.999.999,998` → **20.000.000,00**."""
    await fatura_fabrikasi(lines=[("1", "99999999.99", "20.00")])

    govde = await _beyan(client, pm_headers)

    assert Decimal(_oran_satiri(govde, "20.00")["base"]) == Decimal("99999999.99")
    assert Decimal(_oran_satiri(govde, "20.00")["vat"]) == Decimal("20000000.00")


async def test_vat_return_kaynaginda_IKINCI_yuvarlama_YOK(pm_headers: dict[str, str]) -> None:
    """🔴 YAPISAL YASAK — değer testinin kardeşi, onun yerine geçmez.

    Bugün doğru sonuç veren bir KOPYA formül, `amounts.py` yarın değiştiğinde
    sessizce sapardı ve hiçbir değer testi bunu göstermezdi. Kaynak metni
    denetlenir: modül kendi `quantize`/`ROUND_*` kuralını YAZAMAZ, tek para
    yuvarlaması `amounts.round_money`tan İTHAL EDİLİR.
    """
    kaynak = inspect.getsource(vat_return)
    # Docstring'deki anlatım yasağı tetiklemesin diye YALNIZ kod satırları taranır.
    anlatim = ("#", '"', "*", "|")
    kod = "\n".join(s for s in kaynak.splitlines() if not s.lstrip().startswith(anlatim))

    assert "quantize(" not in kod, "vat_return.py kendi yuvarlamasını yazıyor"
    assert "ROUND_" not in kod, "vat_return.py kendi yuvarlama kuralını seçiyor"
    assert "round_money" in kaynak, "round_money İTHAL EDİLMEMİŞ"
    assert "amounts" in kaynak, "amounts.py yeniden kullanılmıyor"
    assert "compute" in kaynak, "amounts.compute çağrılmıyor"


# --------------------------------------------------------------------------- #
# 3. Durum süzgeci — her durum AYRI test
# --------------------------------------------------------------------------- #


async def test_giden_draft_HESAPLANANA_girmez(
    client: AsyncClient, pm_headers: dict[str, str], fatura_fabrikasi
) -> None:
    """`draft` henüz KESİLMEMİŞTİR; `journal_entries`in `POSTING_STATUSES`
    kanonuyla paralel — yalnız kesinleşmiş kayıt mali beyana girer."""
    await fatura_fabrikasi(status=InvoiceStatus.draft)

    govde = await _beyan(client, pm_headers)

    assert Decimal(govde["calculated_vat"]) == Decimal("0.00")
    assert govde["taxable_rows"] == []


@pytest.mark.parametrize("status", [InvoiceStatus.sent, InvoiceStatus.collected])
async def test_giden_sent_ve_collected_HESAPLANANA_girer(
    client: AsyncClient, pm_headers: dict[str, str], fatura_fabrikasi, status: InvoiceStatus
) -> None:
    await fatura_fabrikasi(status=status)

    govde = await _beyan(client, pm_headers)

    assert Decimal(govde["calculated_vat"]) == Decimal("200.00")


@pytest.mark.parametrize("status", [InvoiceStatus.pending, InvoiceStatus.disputed])
async def test_gelen_pending_ve_disputed_INDIRIME_girmez(
    client: AsyncClient, pm_headers: dict[str, str], fatura_fabrikasi, status: InvoiceStatus
) -> None:
    """`pending` henüz onaylanmamıştır; `disputed` itiraz altındadır ve indirim
    hakkı belirsizdir."""
    await fatura_fabrikasi(direction=InvoiceDirection.incoming, status=status)

    govde = await _beyan(client, pm_headers)

    assert Decimal(govde["deductible_vat"]) == Decimal("0.00")
    assert govde["deductions"] == []


async def test_gelen_approved_INDIRIME_girer(
    client: AsyncClient, pm_headers: dict[str, str], fatura_fabrikasi
) -> None:
    await fatura_fabrikasi(direction=InvoiceDirection.incoming, status=InvoiceStatus.approved)

    govde = await _beyan(client, pm_headers)

    assert Decimal(govde["deductible_vat"]) == Decimal("200.00")
    assert len(govde["deductions"]) == 1
    assert govde["deductions"][0]["source"] == "Alışlar"
    assert Decimal(govde["deductions"][0]["base"]) == Decimal("1000.00")
    assert Decimal(govde["deductions"][0]["vat"]) == Decimal("200.00")


# --------------------------------------------------------------------------- #
# 4. Yön süzgeci — iki taraf KARIŞMAZ
# --------------------------------------------------------------------------- #


async def test_gelen_fatura_HESAPLANANA_karismaz_giden_INDIRIME_karismaz(
    client: AsyncClient, pm_headers: dict[str, str], fatura_fabrikasi
) -> None:
    await fatura_fabrikasi(
        direction=InvoiceDirection.outgoing,
        status=InvoiceStatus.sent,
        lines=[("1", "1000.00", "20.00")],
    )
    await fatura_fabrikasi(
        direction=InvoiceDirection.incoming,
        status=InvoiceStatus.approved,
        lines=[("1", "400.00", "20.00")],
    )

    govde = await _beyan(client, pm_headers)

    assert Decimal(govde["calculated_vat"]) == Decimal("200.00")
    assert Decimal(govde["deductible_vat"]) == Decimal("80.00")
    # Hesaplanan tablosu YALNIZ gidenden kurulur.
    assert Decimal(_oran_satiri(govde, "20.00")["base"]) == Decimal("1000.00")
    assert Decimal(govde["deductions"][0]["base"]) == Decimal("400.00")


# --------------------------------------------------------------------------- #
# 5. Ay penceresi — TEK AY, iki sınır da KAPALI
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("issue_date", "iceride"),
    [
        pytest.param(date(2026, 5, 31), False, id="onceki-ayin-son-gunu-DISARIDA"),
        pytest.param(date(2026, 6, 1), True, id="ayin-ilk-gunu-ICERIDE"),
        pytest.param(date(2026, 6, 30), True, id="ayin-son-gunu-ICERIDE"),
        pytest.param(date(2026, 7, 1), False, id="ertesi-ayin-ilk-gunu-DISARIDA"),
    ],
)
async def test_ay_penceresi_sinirlari(
    client: AsyncClient,
    pm_headers: dict[str, str],
    fatura_fabrikasi,
    issue_date: date,
    iceride: bool,
) -> None:
    """🔴 Pencere TEK AYDIR — mizanın BİRİKİMLİ aralığından farklı."""
    await fatura_fabrikasi(issue_date=issue_date)

    govde = await _beyan(client, pm_headers)

    beklenen = Decimal("200.00") if iceride else Decimal("0.00")
    assert Decimal(govde["calculated_vat"]) == beklenen


async def test_subat_artik_yil_29u_ICERIDE(
    client: AsyncClient, pm_headers: dict[str, str], fatura_fabrikasi
) -> None:
    """`calendar.monthrange` ile saf aritmetik — 2028 artık yıldır."""
    await fatura_fabrikasi(issue_date=date(2028, 2, 29))

    govde = await _beyan(client, pm_headers, year=2028, month=2)

    assert Decimal(govde["calculated_vat"]) == Decimal("200.00")


async def test_subat_artik_OLMAYAN_yilda_28i_son_gundur(
    client: AsyncClient, pm_headers: dict[str, str], fatura_fabrikasi
) -> None:
    await fatura_fabrikasi(issue_date=date(2026, 2, 28))
    await fatura_fabrikasi(issue_date=date(2026, 3, 1))

    govde = await _beyan(client, pm_headers, year=2026, month=2)

    assert Decimal(govde["calculated_vat"]) == Decimal("200.00")


# --------------------------------------------------------------------------- #
# 6. İstisna işlemler (`vat_rate = 0`)
# --------------------------------------------------------------------------- #


async def test_istisna_kalemler_MATRAHTA_gorunur_vergisi_SIFIRDIR(
    client: AsyncClient, pm_headers: dict[str, str], fatura_fabrikasi
) -> None:
    """Mockup satır 90-95 (italik/gri `İstisna İşlemler`) = `vat_rate = 0`.

    Matrah toplanır, vergi 0'dır ve VERGİLİ gruplara KARIŞMAZ."""
    await fatura_fabrikasi(lines=[("1", "700.00", "0.00"), ("1", "1000.00", "20.00")])

    govde = await _beyan(client, pm_headers)

    assert Decimal(govde["exempt_base"]) == Decimal("700.00")
    assert [Decimal(s["rate"]) for s in govde["taxable_rows"]] == [Decimal("20.00")]
    assert Decimal(_oran_satiri(govde, "20.00")["base"]) == Decimal("1000.00")
    assert Decimal(govde["calculated_vat"]) == Decimal("200.00")


async def test_yalniz_istisna_faturasi_vergili_satir_URETMEZ(
    client: AsyncClient, pm_headers: dict[str, str], fatura_fabrikasi
) -> None:
    await fatura_fabrikasi(lines=[("1", "700.00", "0.00")])

    govde = await _beyan(client, pm_headers)

    assert govde["taxable_rows"] == []
    assert Decimal(govde["exempt_base"]) == Decimal("700.00")
    assert Decimal(govde["calculated_vat"]) == Decimal("0.00")


# --------------------------------------------------------------------------- #
# 7. Sonuç — ödenecek ↔ DEVREDEN
# --------------------------------------------------------------------------- #


async def test_hesaplanan_buyukse_ODENECEK_dogar(
    client: AsyncClient, pm_headers: dict[str, str], fatura_fabrikasi
) -> None:
    """Mockup satır 138: `824.000 – 412.000`."""
    await fatura_fabrikasi(status=InvoiceStatus.sent, lines=[("1", "1000.00", "20.00")])
    await fatura_fabrikasi(
        direction=InvoiceDirection.incoming,
        status=InvoiceStatus.approved,
        lines=[("1", "400.00", "20.00")],
    )

    govde = await _beyan(client, pm_headers)

    assert Decimal(govde["payable"]) == Decimal("120.00")
    assert Decimal(govde["carried_forward"]) == Decimal("0.00")


async def test_indirilecek_buyukse_DEVREDEN_dogar_odenecek_SIFIRDIR(
    client: AsyncClient, pm_headers: dict[str, str], fatura_fabrikasi
) -> None:
    """🔴 Negatif fark "ödenecek" DEĞİL, DEVREDEN KDV'dir. `payable` NEGATİF
    OLAMAZ — negatif basan bir uygulama devlete borç yerine alacak yazardı."""
    await fatura_fabrikasi(status=InvoiceStatus.sent, lines=[("1", "400.00", "20.00")])
    await fatura_fabrikasi(
        direction=InvoiceDirection.incoming,
        status=InvoiceStatus.approved,
        lines=[("1", "1000.00", "20.00")],
    )

    govde = await _beyan(client, pm_headers)

    assert Decimal(govde["payable"]) == Decimal("0.00")
    assert Decimal(govde["carried_forward"]) == Decimal("120.00")


@pytest.mark.parametrize(
    ("giden", "gelen"),
    [
        pytest.param("1000.00", "400.00", id="odenecek"),
        pytest.param("400.00", "1000.00", id="devreden"),
        pytest.param("1000.00", "1000.00", id="esit"),
    ],
)
async def test_INVARIANT_odenecek_ve_devreden_AYNI_ANDA_sifirdan_buyuk_OLAMAZ(
    client: AsyncClient, pm_headers: dict[str, str], fatura_fabrikasi, giden: str, gelen: str
) -> None:
    """İkisi de `max(±fark, 0)`tır; biri doluysa öteki TANIMI GEREĞİ sıfırdır."""
    await fatura_fabrikasi(status=InvoiceStatus.sent, lines=[("1", giden, "20.00")])
    await fatura_fabrikasi(
        direction=InvoiceDirection.incoming,
        status=InvoiceStatus.approved,
        lines=[("1", gelen, "20.00")],
    )

    govde = await _beyan(client, pm_headers)

    odenecek = Decimal(govde["payable"])
    devreden = Decimal(govde["carried_forward"])
    assert odenecek >= 0 and devreden >= 0
    assert not (odenecek > 0 and devreden > 0), (odenecek, devreden)
    assert odenecek - devreden == Decimal(govde["calculated_vat"]) - Decimal(
        govde["deductible_vat"]
    )


# --------------------------------------------------------------------------- #
# 8. Vade — izleyen ayın 28'i
# --------------------------------------------------------------------------- #


async def test_vade_izleyen_ayin_28i(client: AsyncClient, pm_headers: dict[str, str]) -> None:
    """Mockup satır 68 BİREBİR: dönem `Haziran 2026` → `Vade: 28.07.2026`."""
    govde = await _beyan(client, pm_headers)

    assert govde["due_date"] == "2026-07-28"
    assert govde["year"] == 2026
    assert govde["month"] == 6


async def test_vade_aralik_doneminde_YIL_TASAR(
    client: AsyncClient, pm_headers: dict[str, str]
) -> None:
    """🔴 Aralık → izleyen YILIN Ocak 28'i. `month + 1` diye yazan bir uygulama
    `2026-13-28` üretip 500 verirdi."""
    govde = await _beyan(client, pm_headers, year=2026, month=12)

    assert govde["due_date"] == "2027-01-28"


# --------------------------------------------------------------------------- #
# 9. Boş ay + N+1
# --------------------------------------------------------------------------- #


async def test_bos_ay_SIFIR_basar_500_DEGIL(
    client: AsyncClient, pm_headers: dict[str, str]
) -> None:
    """Hiç fatura yoksa altı para alanı da `0`, listeler boş, vade YİNE dolu."""
    govde = await _beyan(client, pm_headers)

    assert govde["taxable_rows"] == []
    assert govde["deductions"] == []
    for alan in ("calculated_vat", "deductible_vat", "payable", "carried_forward", "exempt_base"):
        assert Decimal(govde[alan]) == Decimal("0.00"), alan
    assert govde["due_date"] == "2026-07-28"


async def test_sorgu_sayisi_fatura_sayisindan_BAGIMSIZ(
    seeded_db: AsyncSession, fatura_fabrikasi
) -> None:
    """🔴 N+1 bekçisi — fatura başına satır sorgusu koşan bir uygulama patlardı.

    Ölçüm çekirdek fonksiyona doğrudan gider (HTTP katmanı kendi oturum/izin
    sorgularını ekler ve sinyali boğardı)."""
    await fatura_fabrikasi()
    with _sorgu_sayaci() as tek:
        await vat_return.build_vat_return(seeded_db, year=2026, month=6)

    for _ in range(5):
        await fatura_fabrikasi()
    with _sorgu_sayaci() as coklu:
        await vat_return.build_vat_return(seeded_db, year=2026, month=6)

    assert len(coklu) == len(tek), f"N+1: 1 fatura {len(tek)}, 6 fatura {len(coklu)} sorgu"
    assert len(tek) <= 2, f"beklenen en fazla 2 sorgu, ölçülen {len(tek)}: {tek}"


async def test_donen_alanlarin_HICBIRI_None_degil(
    client: AsyncClient, pm_headers: dict[str, str], fatura_fabrikasi
) -> None:
    """Boş taraf `0` basar — `null` dönseydi ekranın her aritmetiği `null` yayardı."""
    await fatura_fabrikasi()

    govde = await _beyan(client, pm_headers)

    assert all(deger is not None for deger in govde.values()), govde
    assert all(deger is not None for satir in govde["taxable_rows"] for deger in satir.values()), (
        govde["taxable_rows"]
    )


async def test_yalniz_secilen_ayin_faturalari_TOPLANIR_id_sizmasi_yok(
    client: AsyncClient, pm_headers: dict[str, str], fatura_fabrikasi
) -> None:
    """Aynı faturanın satırları KENDİ faturasının kesintileriyle hesaplanır:
    ay dışındaki bir faturanın satırı ay içindeki bir faturaya SIZAMAZ."""
    ay_ici = await fatura_fabrikasi(issue_date=date(2026, 6, 10), lines=[("1", "1000.00", "20.00")])
    await fatura_fabrikasi(issue_date=date(2026, 7, 10), lines=[("1", "5000.00", "20.00")])

    govde = await _beyan(client, pm_headers)

    assert isinstance(ay_ici.id, uuid.UUID)
    assert Decimal(_oran_satiri(govde, "20.00")["base"]) == Decimal("1000.00")
    assert Decimal(govde["calculated_vat"]) == Decimal("200.00")
