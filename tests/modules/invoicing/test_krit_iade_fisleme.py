"""🔴 KRIT-IADE — **İADE FATURASI AYNI YÖNÜN TERSİNİ YAZAR** (fatura fişi + KDV).

## Kapatılan kusur (ölçüldü, varsayılmadı)

`invoicing/posting.py::lines_for` YALNIZ `invoice.direction`a dallanıyordu;
`command grep -n "refund\\|document_type" app/modules/invoicing/posting.py`
**EXIT=1** (sıfır isabet) veriyordu. Yani bir İADE faturası, aynı yöndeki
normal faturayla **BİREBİR AYNI** fişi üretiyordu: hasılatı/gideri ve cariyi
AZALTMASI gerekirken ARTIRIYORDU. Aynı körlük `accounting/vat_return.py`de de
vardı (yine EXIT=1) ve beyan, iadeyi DÜŞECEĞİ yerde EKLİYORDU.

## 🔴 BEKÇİ **YÖNÜ** ÖLÇER, DENGEYİ DEĞİL

Kusurlu fiş DENGELİYDİ (`Σ borç = Σ alacak`) — mizanı ölçen hiçbir kapı onu
göremezdi (§4.6 damga vergisi kusurunun kardeşi). Bu yüzden bu dosyanın
iddiaları hesap başına **NET İŞARETİ** üzerindedir: `600`ün alacak neti, `120`
nin borç neti, `391`in alacak neti. Bir aynalamayı geri alan mutant dengeyi
BOZMAZ ama bu netlerin İŞARETİNİ çevirir.

## 🔴 KÜME BEKÇİSİ (sahte-yeşilin 8. hâli)

`post_document` idempotandır: "kaç fiş yazıldı" diyen bir test, kümeye sahte
bir üye eklendiğinde KIRMIZIYA DÖNMEZ. Bu yüzden `test_BACAK_TARAFI_KUMESI...`
evreni BAĞIMSIZ BİR KAYNAKTAN — `InvoiceDirection` × `InvoiceDocumentType`
enum'larının KARTEZYEN ÇARPIMINDAN — türetir ve **KÜMEYİ** karşılaştırır.
`InvoiceDocumentType`a yeni bir üye eklendiğinde bu test, o üyenin fişleme
yönüne bir karar verilene kadar KIRMIZI kalır.
"""

import itertools
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounting.models import JournalEntry
from app.modules.accounting.vat_return import build_vat_return
from app.modules.invoicing import posting
from app.modules.invoicing.models import (
    Invoice,
    InvoiceDirection,
    InvoiceDocumentType,
)
from app.modules.invoicing.transitions import InvoiceAction
from tests.modules.invoicing.test_mu3b_invoice_posting import (
    KOD_ALICILAR,
    KOD_GIDER,
    KOD_HES_KDV,
    KOD_IND_KDV,
    KOD_SATICILAR,
    KOD_SATIS,
    TARIH,
    _bacaklar,
    _fis,
    _gecis,
    _hesap_neti,
    fatura_kur,
)

#: Yöne göre BAĞLAYICI geçiş — `POSTING_ACTIONS` üründen okunmaz, iddianın
#: kendisidir (MU-3B deseni).
_GECIS = {
    InvoiceDirection.outgoing: InvoiceAction.send,
    InvoiceDirection.incoming: InvoiceAction.approve,
}

#: 🔴 BEKLENEN BACAK TARAFLARI — `(yön, iade mi) → {hesap kodu: taraf}`.
#: `"B"` borç, `"A"` alacak. ELLE yazılır ve öyle KALMALIDIR: üründen
#: türetilseydi test, ölçtüğü kararı ölçtüğü koddan okur ve karar ters
#: çevrildiğinde SESSİZCE onunla birlikte dönerdi.
BEKLENEN_TARAF: dict[tuple[InvoiceDirection, bool], dict[str, str]] = {
    (InvoiceDirection.outgoing, False): {KOD_ALICILAR: "B", KOD_SATIS: "A", KOD_HES_KDV: "A"},
    (InvoiceDirection.outgoing, True): {KOD_SATIS: "B", KOD_HES_KDV: "B", KOD_ALICILAR: "A"},
    (InvoiceDirection.incoming, False): {KOD_GIDER: "B", KOD_IND_KDV: "B", KOD_SATICILAR: "A"},
    (InvoiceDirection.incoming, True): {KOD_SATICILAR: "B", KOD_GIDER: "A", KOD_IND_KDV: "A"},
}


def _taraflar(satirlar: list[tuple[str, str, str]]) -> dict[str, str]:
    """`(kod, borç, alacak)` üçlülerini `{kod: "B"|"A"}`ya indirger.

    🔴 Tutar KASTEN atılır: bu bekçinin ölçtüğü şey YÖNDÜR ve tutarları da
    karşılaştıran bir iddia, yönü çeviren mutantı tutarların gürültüsünde
    kaybettirirdi. Tutarlar aşağıdaki iki uçtan uca testte ayrıca ölçülür.
    """
    return {kod: ("B" if Decimal(borc) > 0 else "A") for kod, borc, alacak in satirlar}


# --------------------------------------------------------------------------- #
# UÇTAN UCA — İADE FİŞİNİN BACAKLARI
# --------------------------------------------------------------------------- #


async def test_GIDEN_IADE_faturasi_satisin_TERSINI_yazar(
    seeded_db: AsyncSession, kullanici_id, fatura_eslemesi
):
    """🔴 Satış iadesi: `600` BORÇLANIR, `391` BORÇLANIR, `120` ALACAKLANIR.

    Kusurlu hâlde bu fiş normal satışla birebir aynıydı; müşteriye geri verilen
    mal hasılatı ARTIRIYORDU.
    """
    invoice = await fatura_kur(
        seeded_db,
        kullanici_id,
        direction=InvoiceDirection.outgoing,
        kalemler=[("1", "1000.00", "20")],
        document_type=InvoiceDocumentType.refund,
    )

    await _gecis(seeded_db, kullanici_id, invoice, InvoiceAction.send)

    entry = await _fis(seeded_db, invoice)
    assert entry is not None, "iade faturası `send` sonrası FİŞSİZ kaldı"
    assert await _bacaklar(seeded_db, entry) == [
        (KOD_SATIS, "1000.00", "0.00"),
        (KOD_HES_KDV, "200.00", "0.00"),
        (KOD_ALICILAR, "0.00", "1200.00"),
    ]
    assert entry.description.startswith("Satış iade faturası "), entry.description


async def test_GELEN_IADE_faturasi_alisin_TERSINI_yazar(
    seeded_db: AsyncSession, kullanici_id, fatura_eslemesi
):
    """🔴 Alış iadesi: `320` BORÇLANIR (borcumuz azalır), `740`/`191` ALACAKLANIR."""
    invoice = await fatura_kur(
        seeded_db,
        kullanici_id,
        direction=InvoiceDirection.incoming,
        kalemler=[("1", "1000.00", "20")],
        document_type=InvoiceDocumentType.refund,
    )

    await _gecis(seeded_db, kullanici_id, invoice, InvoiceAction.approve)

    entry = await _fis(seeded_db, invoice)
    assert entry is not None
    assert await _bacaklar(seeded_db, entry) == [
        (KOD_SATICILAR, "1200.00", "0.00"),
        (KOD_GIDER, "0.00", "1000.00"),
        (KOD_IND_KDV, "0.00", "200.00"),
    ]
    assert entry.description.startswith("Alış iade faturası "), entry.description


async def test_TEVKIFATLI_iade_de_AYNALANIR_ve_bacak_SAYISI_korunur(
    seeded_db: AsyncSession, kullanici_id, fatura_eslemesi
):
    """Tevkifat bacağı (`360`/`136`) de tarafını değiştirir — atlanmaz.

    Aynalama bacak KÜMESİNİ değil yalnız TARAFLARINI değiştirir: dört bacaklı
    bir fatura iadesinde de dört bacak doğar.
    """
    invoice = await fatura_kur(
        seeded_db,
        kullanici_id,
        direction=InvoiceDirection.incoming,
        kalemler=[("1", "1000.00", "20")],
        withholding_rate=Decimal("50"),
        document_type=InvoiceDocumentType.refund,
    )

    await _gecis(seeded_db, kullanici_id, invoice, InvoiceAction.approve)

    entry = await _fis(seeded_db, invoice)
    assert await _bacaklar(seeded_db, entry) == [
        (KOD_SATICILAR, "1100.00", "0.00"),
        ("360", "100.00", "0.00"),
        (KOD_GIDER, "0.00", "1000.00"),
        (KOD_IND_KDV, "0.00", "200.00"),
    ]


# --------------------------------------------------------------------------- #
# 🔴 YÖN BEKÇİSİ — DENGE DEĞİL
# --------------------------------------------------------------------------- #


async def test_IADE_hasilati_AZALTIR_mizan_neti_OLCULDU(
    seeded_db: AsyncSession, kullanici_id, fatura_eslemesi
):
    """🔴 BU DİLİMİN KABUL KAPISI — 1.000 satış + 400 iade = **600** hasılat.

    Kusurlu hâlde net 1.400'dü ve İKİ FİŞ DE DENGELİYDİ; dengeyi ölçen hiçbir
    kapı bunu göremezdi. Bekçi bu yüzden NETİN KENDİSİNİ okur.
    """
    satis = await fatura_kur(
        seeded_db,
        kullanici_id,
        direction=InvoiceDirection.outgoing,
        kalemler=[("1", "1000.00", "20")],
    )
    iade = await fatura_kur(
        seeded_db,
        kullanici_id,
        direction=InvoiceDirection.outgoing,
        kalemler=[("1", "400.00", "20")],
        document_type=InvoiceDocumentType.refund,
    )

    await _gecis(seeded_db, kullanici_id, satis, InvoiceAction.send)
    await _gecis(seeded_db, kullanici_id, iade, InvoiceAction.send)

    assert await _hesap_neti(seeded_db, KOD_SATIS, borc_yonlu=False) == Decimal("600.00")
    assert await _hesap_neti(seeded_db, KOD_HES_KDV, borc_yonlu=False) == Decimal("120.00")
    assert await _hesap_neti(seeded_db, KOD_ALICILAR, borc_yonlu=True) == Decimal("720.00")
    # İki AYRI fiş: iade orijinali STORNO ETMEZ, kendi belgesini yazar.
    assert await seeded_db.scalar(select(func.count()).select_from(JournalEntry)) == 2


async def test_IADE_gideri_AZALTIR_mizan_neti_OLCULDU(
    seeded_db: AsyncSession, kullanici_id, fatura_eslemesi
):
    """Gelen taraf ayağı: 1.000 alış + 400 iade = **600** gider."""
    alis = await fatura_kur(
        seeded_db,
        kullanici_id,
        direction=InvoiceDirection.incoming,
        kalemler=[("1", "1000.00", "20")],
    )
    iade = await fatura_kur(
        seeded_db,
        kullanici_id,
        direction=InvoiceDirection.incoming,
        kalemler=[("1", "400.00", "20")],
        document_type=InvoiceDocumentType.refund,
    )

    await _gecis(seeded_db, kullanici_id, alis, InvoiceAction.approve)
    await _gecis(seeded_db, kullanici_id, iade, InvoiceAction.approve)

    assert await _hesap_neti(seeded_db, KOD_GIDER, borc_yonlu=True) == Decimal("600.00")
    assert await _hesap_neti(seeded_db, KOD_IND_KDV, borc_yonlu=True) == Decimal("120.00")
    assert await _hesap_neti(seeded_db, KOD_SATICILAR, borc_yonlu=False) == Decimal("720.00")


# --------------------------------------------------------------------------- #
# 🔴 KÜME BEKÇİSİ — EVREN ENUM'LARDAN TÜRER
# --------------------------------------------------------------------------- #


def _sahte_fatura(direction: InvoiceDirection, document_type: InvoiceDocumentType) -> Invoice:
    """`lines_for` için gereken DÖRT donmuş kolonu taşıyan geçici nesne.

    DB'ye YAZILMAZ ve yazılmamalıdır: bu bekçi `lines_for`un SAF kararını
    (hangi bacak hangi tarafta) ölçer, veritabanının değil. Tutarlar dört
    bacağın DÖRDÜNÜN de doğması için sıfırdan farklı seçilir — sıfır bir bacak
    `_doludur` süzgecine takılır ve küme SESSİZCE eksik kalırdı.
    """
    return Invoice(
        direction=direction,
        document_type=document_type,
        invoice_no="KUME",
        issue_date=TARIH,
        party_name="Küme A.Ş.",
        total=Decimal("1100.00"),
        tax_base=Decimal("1000.00"),
        vat_amount=Decimal("200.00"),
        withholding_amount=Decimal("100.00"),
    )


def test_BACAK_TARAFI_KUMESI_iki_enumun_KARTEZYEN_carpimindan_TURETILIR():
    """🔴 Evren üründeki bir listeden DEĞİL, iki ENUM'dan türer.

    `InvoiceDocumentType`a yeni bir üye eklendiğinde (`withholding` gibi bir
    gün `credit_note` da eklenebilir) bu test, o üyenin fişleme yönü
    `BEKLENEN_TARAF`ta kararlaştırılana kadar KIRMIZI kalır — elle yazılmış bir
    liste kullanılsaydı yeni üye SESSİZCE normal fatura gibi fişlenirdi ve
    kusur ancak canlıda, ilk o belgede açılırdı.

    🔴 İDDİA TARAF ÜZERİNDEDİR, TUTAR ÜZERİNDE DEĞİL: dengeyi ölçen bir kapı bu
    kusuru göremiyordu.
    """
    evren = list(itertools.product(InvoiceDirection, InvoiceDocumentType))
    assert len(evren) == len(InvoiceDirection) * len(InvoiceDocumentType)

    olculen = {
        (direction, document_type): _taraflar(
            [
                (satir.role_key, str(satir.debit), str(satir.credit))
                for satir in posting.lines_for(_sahte_fatura(direction, document_type))
            ]
        )
        for direction, document_type in evren
    }

    # `BEKLENEN_TARAF` TDHP KODUYLA yazılmıştır (okuyucu için), ölçüm ROL
    # anahtarıyla döner; ikisi `INVOICE_POSTING_RULES` üzerinden buluşur.
    rol_of_kod = {kod: rol for rol, kod in posting.INVOICE_POSTING_RULES}

    # `BEKLENEN_TARAF` üç ANA bacağı listeler; tevkifatın tarafı aşağıda ayrıca
    # çakılır (o bacak `_sahte_fatura`da daima doludur).
    for direction, document_type in evren:
        tablo = {
            rol_of_kod[kod]: taraf
            for kod, taraf in BEKLENEN_TARAF[
                (direction, document_type is InvoiceDocumentType.refund)
            ].items()
        }
        assert {rol: olculen[(direction, document_type)][rol] for rol in tablo} == tablo, (
            f"{direction.value}/{document_type.value} fişinin bacak TARAFLARI beklenenden farklı: "
            f"ölçülen={olculen[(direction, document_type)]}"
        )

    # 🔴 Tevkifat bacağı cari bacağıyla TERS taraftadır — her dört hâlde de.
    for (direction, _document_type), tablo in olculen.items():
        cari_rol = (
            posting.ROLE_RECEIVABLE
            if direction is InvoiceDirection.outgoing
            else posting.ROLE_PAYABLE
        )
        tevkifat_rol = (
            posting.ROLE_WITHHOLDING_RECEIVABLE
            if direction is InvoiceDirection.outgoing
            else posting.ROLE_WITHHOLDING_PAYABLE
        )
        assert tablo[cari_rol] == tablo[tevkifat_rol], (
            "tevkifat bacağı cari bacağıyla AYNI tarafta olmalı (giden: ikisi de borç)"
        )


def test_IADE_bacak_KUMESI_normalle_AYNI_yalniz_TARAFLARI_ters():
    """Aynalama bacak KÜMESİNİ değiştirmez — `610 Satıştan İadeler` AÇILMAZ.

    Ayrı bir hesap seçilseydi `posting_rules`a yeni satırlar ve bir migration
    gerekirdi; üstelik `vat_return`/mizan mutabakatı `600`ün netine baktığı için
    iki taban SESSİZCE ayrışırdı. Bu iddia o kararı KİLİTLER.
    """
    for direction in InvoiceDirection:
        normal = posting.lines_for(_sahte_fatura(direction, InvoiceDocumentType.einvoice))
        iade = posting.lines_for(_sahte_fatura(direction, InvoiceDocumentType.refund))
        assert {satir.role_key for satir in normal} == {satir.role_key for satir in iade}
        normal_taraf = {satir.role_key: satir.debit > 0 for satir in normal}
        iade_taraf = {satir.role_key: satir.debit > 0 for satir in iade}
        assert all(normal_taraf[rol] is not iade_taraf[rol] for rol in normal_taraf), (
            f"{direction.value} iadesi bacakları TERSLEMEDİ"
        )
        # Borç bacakları ÖNCE — aynalama `sort_order` değişmezini bozmamalı.
        assert [satir.debit > 0 for satir in iade] == sorted(
            (satir.debit > 0 for satir in iade), reverse=True
        )


# --------------------------------------------------------------------------- #
# 🔴 KDV BEYANNAMESİ — İADE DÜŞÜLÜR
# --------------------------------------------------------------------------- #


async def test_BEYANNAME_iadeyi_DUSER_EKLEMEZ(
    seeded_db: AsyncSession, kullanici_id, fatura_eslemesi
):
    """🔴 1.000 satış + 400 iade → matrah 600, hesaplanan KDV 120.

    Kusurlu hâlde beyan 1.400 matrah / 280 KDV diyordu: devlete OLMAYAN bir
    borç yazılıyordu.
    """
    satis = await fatura_kur(
        seeded_db,
        kullanici_id,
        direction=InvoiceDirection.outgoing,
        kalemler=[("1", "1000.00", "20")],
    )
    iade = await fatura_kur(
        seeded_db,
        kullanici_id,
        direction=InvoiceDirection.outgoing,
        kalemler=[("1", "400.00", "20")],
        document_type=InvoiceDocumentType.refund,
    )
    await _gecis(seeded_db, kullanici_id, satis, InvoiceAction.send)
    await _gecis(seeded_db, kullanici_id, iade, InvoiceAction.send)

    beyan = await build_vat_return(seeded_db, year=TARIH.year, month=TARIH.month)

    assert [(satir.rate, satir.base, satir.vat) for satir in beyan.taxable_rows] == [
        (Decimal("20.00"), Decimal("600.00"), Decimal("120.00"))
    ]
    assert beyan.payable == Decimal("120.00")


async def test_BEYANNAME_GELEN_iadeyi_INDIRIMDEN_DUSER(
    seeded_db: AsyncSession, kullanici_id, fatura_eslemesi
):
    """Gelen iade indirilecek KDV'yi AZALTIR; artırsaydı devletten fazla
    indirim talep edilirdi."""
    alis = await fatura_kur(
        seeded_db,
        kullanici_id,
        direction=InvoiceDirection.incoming,
        kalemler=[("1", "1000.00", "20")],
    )
    iade = await fatura_kur(
        seeded_db,
        kullanici_id,
        direction=InvoiceDirection.incoming,
        kalemler=[("1", "400.00", "20")],
        document_type=InvoiceDocumentType.refund,
    )
    await _gecis(seeded_db, kullanici_id, alis, InvoiceAction.approve)
    await _gecis(seeded_db, kullanici_id, iade, InvoiceAction.approve)

    beyan = await build_vat_return(seeded_db, year=TARIH.year, month=TARIH.month)

    assert beyan.deductible_vat == Decimal("120.00")
    assert beyan.deductions[0].base == Decimal("600.00")
    assert beyan.carried_forward == Decimal("120.00")


async def test_KDV_MUTABAKATI_IADE_ICEREN_kumede_de_tutar(
    seeded_db: AsyncSession, kullanici_id, fatura_eslemesi
):
    """🔴 İŞ 3 MUTABAKATININ İADE AYAĞI — İKİ TABAN BİRLİKTE ölçülür.

    Bu, bu dosyanın en güçlü iddiasıdır: iki düzeltmeden **YALNIZ BİRİ**
    yapılsaydı (fiş aynalanır ama beyan aynalanmazsa, ya da tersi) beyanname ile
    yevmiye AYRIŞIR ve bu test KIRMIZI olurdu. Tek yönlü bir yamayı yakalayan
    başka hiçbir kapı yok.
    """
    kume = (
        (InvoiceDirection.outgoing, InvoiceDocumentType.einvoice, [("1", "1000.00", "20")]),
        (InvoiceDirection.outgoing, InvoiceDocumentType.refund, [("1", "400.00", "20")]),
        (InvoiceDirection.outgoing, InvoiceDocumentType.refund, [("3", "33.33", "10")]),
        (InvoiceDirection.incoming, InvoiceDocumentType.einvoice, [("2", "555.55", "20")]),
        (InvoiceDirection.incoming, InvoiceDocumentType.refund, [("1", "111.11", "20")]),
    )
    for direction, document_type, kalemler in kume:
        invoice = await fatura_kur(
            seeded_db,
            kullanici_id,
            direction=direction,
            kalemler=kalemler,
            document_type=document_type,
        )
        await _gecis(seeded_db, kullanici_id, invoice, _GECIS[direction])

    beyan = await build_vat_return(seeded_db, year=TARIH.year, month=TARIH.month)

    assert beyan.calculated_vat == await _hesap_neti(seeded_db, KOD_HES_KDV, borc_yonlu=False), (
        "HESAPLANAN KDV ayrıştı — iade beyanname ile yevmiyede AYNI yöne yazılmıyor"
    )
    assert beyan.deductible_vat == await _hesap_neti(seeded_db, KOD_IND_KDV, borc_yonlu=True), (
        "İNDİRİLECEK KDV ayrıştı — iade beyanname ile yevmiyede AYNI yöne yazılmıyor"
    )
    beyan_matrahi = sum((satir.base for satir in beyan.taxable_rows), Decimal("0"))
    beyan_matrahi += beyan.exempt_base
    assert beyan_matrahi == await _hesap_neti(seeded_db, KOD_SATIS, borc_yonlu=False)
    assert beyan.deductions[0].base == await _hesap_neti(seeded_db, KOD_GIDER, borc_yonlu=True)
    # Küme gerçekten para taşıyor: sıfır ↔ sıfır de "tutar"dı.
    assert beyan.calculated_vat > 0
    assert beyan.deductible_vat > 0
