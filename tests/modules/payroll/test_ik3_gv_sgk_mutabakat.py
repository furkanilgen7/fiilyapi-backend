"""IK3-GV T6 — 🔴🔴 İKİ KATMAN MUTABAKATI: `payroll_lines` ↔ `sgk-summary`.

## Niçin bu dosya VAR (ölçülmüş kusur)

`sgk.py` gelir vergisini **`income_tax_pct × brüt`** ile YENİDEN TÜRETİYORDU.
Dilimli motor gelip satıra doğru vergiyi yazsa bile SGK ekranı düz yüzdeyi
basmaya devam ederdi → bordro ekranı ile SGK ekranı **aynı kişi için iki farklı
vergi** gösterirdi. (`income_tax_pct` `NULL`a çekildiği için bugün 500'e de
düşerdi; ama asıl kusur SESSİZ AYRIŞMAdır.)

## 🔴 Ve eski test bunu YAKALAYAMIYORDU

`test_payroll_sgk.test_isci_paylari_SGK_69_73` yalnız SGK ekranının **kendi
içinde** toplanabilirliğini iddia ediyordu: dört kalem toplamlarına eşit mi?
Düz oranla türetilen bir tablo bu iddiayı HER ZAMAN sağlar — kendi kendisiyle
tutarlıdır. *"Aynı yeşil iki anlam taşır"* ve *"iki katman birbirini maskeler"*
kanonlarının canlı, ölçülmüş örneğidir.

🔴 **Alt katmanın KENDİ bekçisi olur:** bu dosya SGK ekranını kendi içinde
değil, **satırlara karşı** ölçer. Aşağıdaki mutasyon testi de bunun ÖLÇÜLMÜŞ
kanıtıdır — bir satırın `income_tax_amount`ı bozulduğunda SGK özeti KIRMIZIYA
döner; IK3-GV öncesinde dönmezdi.
"""

from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.modules.payroll import service
from app.modules.payroll.models import PayrollLine, PayrollLineStatus

pytestmark = pytest.mark.asyncio


async def _hesapla_ve_ozetle(db_session, donem):
    await service.compute_period(db_session, donem.id)
    return await service.sgk_summary(db_session, donem.id)


async def _satirlar(db_session, donem) -> list[PayrollLine]:
    return list(
        (
            await db_session.execute(
                select(PayrollLine).where(PayrollLine.payroll_period_id == donem.id)
            )
        )
        .scalars()
        .all()
    )


# --------------------------------------------------------------------------- #
# 🔴 K6 — asıl bekçi
# --------------------------------------------------------------------------- #


async def test_K6_SGK_gelir_vergisi_SATIRLARIN_TOPLAMIDIR(db_session, donem, dort_tip):
    """🔴🔴 `SUM(payroll_lines.income_tax_amount) == sgk_summary.income_tax_total`.

    Bu dilimin EN DEĞERLİ bekçisidir: iki katmanın tek bir gerçek kaynağı
    olduğunu DOĞRUDAN iddia eder. SQL toplamı kasten servis üzerinden değil
    veritabanından alınır — ikisi aynı Python koduyla üretilseydi iddia
    kendi kendini doğrulardı.
    """
    ozet = await _hesapla_ve_ozetle(db_session, donem)
    satir_toplami = (
        await db_session.execute(
            select(func.coalesce(func.sum(PayrollLine.income_tax_amount), 0)).where(
                PayrollLine.payroll_period_id == donem.id
            )
        )
    ).scalar_one()

    assert ozet.income_tax_total == satir_toplami
    # Ekranın gerçekten bir sayı bastığından emin ol: 0 == 0 sahte yeşili YOK.
    assert satir_toplami > 0


async def test_K6_SGK_kesinti_toplami_SATIRIN_kesintisine_ESITTIR(db_session, donem, dort_tip):
    """SGK ekranının işçi kesintisi, satırların `deduction_amount` TOPLAMIDIR.

    IK3-GV öncesinde ikisi bir kuruş ayrışabiliyordu (satır tek seferde
    yuvarlanmış toplam yüzdeyi, SGK ekranı ayrı ayrı yuvarlanmış kalemleri
    kullanıyordu). Artık kesinti SATIRDA da dört kalemin toplamıdır
    (`compute.Deductions.total`) → iki ekran kuruşuna kadar mutabıktır.
    """
    ozet = await _hesapla_ve_ozetle(db_session, donem)
    beklenen = sum(
        (
            satir.deduction_amount
            for satir in await _satirlar(db_session, donem)
            if satir.gross_amount is not None
        ),
        Decimal("0.00"),
    )

    assert ozet.employee_deduction_total == beklenen


async def test_K6_MUTASYON_satirin_vergisi_bozulunca_SGK_ozeti_KIRILIR(db_session, donem, dort_tip):
    """🔴🔴 MUTASYON KANITI — bekçinin gerçekten bağlı olduğunun ölçümü.

    Bir satırın `income_tax_amount`ı elle 1,00 TL oynatılır. Doğru bağlanmış
    bir SGK özeti bunu GÖRÜR ve toplamı da 1,00 TL kayar.

    🔴 **IK3-GV ÖNCESİNDE BU MUTASYON GÖRÜNMEZDİ:** `sgk.py` vergiyi
    `income_tax_pct × brüt`ten türettiği için satırdaki değere hiç bakmıyordu;
    satır bozulsa bile SGK ekranı eski, "kendi içinde tutarlı" sayısını
    basmaya devam ederdi.
    """
    once = await _hesapla_ve_ozetle(db_session, donem)

    bozulan = next(
        satir
        for satir in await _satirlar(db_session, donem)
        if satir.income_tax_amount is not None and satir.status is not PayrollLineStatus.uncomputed
    )
    bozulan.income_tax_amount = bozulan.income_tax_amount + Decimal("1.00")
    await db_session.flush()

    sonra = await service.sgk_summary(db_session, donem.id)
    assert sonra.income_tax_total == once.income_tax_total + Decimal("1.00"), (
        "SGK özeti satırdaki vergiyi GÖRMÜYOR — orandan yeniden türetiyor olabilir"
    )


async def test_K6_DAMGA_da_ISTISNAYI_gorur(db_session, donem, dort_tip):
    """🔴 Damga `stamp_tax_pct × brüt` DEĞİLDİR: asgari ücret istisnası düşülür.

    `dort_tip` senaryosunda tüm brütler 2026 asgari ücretinin (33.030,00)
    altındadır → damga **0,00**dır. Orandan türetilseydi 2 × 9.000 × %0,759 =
    136,62 çıkardı ve asgari ücretliden mevzuata aykırı biçimde kesilmiş
    olurdu (DVK (II) IV/34).
    """
    ozet = await _hesapla_ve_ozetle(db_session, donem)

    assert ozet.stamp_tax_total == Decimal("0.00")
    assert ozet.stamp_tax_total != Decimal("136.62")


async def test_K6_kalemler_KENDI_TOPLAMINA_esit_KALIR(db_session, donem, dort_tip):
    """Eski iddia HÂLÂ YEŞİL: dört kalem kendi toplamına eşittir.

    🔴 Bu testin varlığı bilinçlidir: yeni bekçi eskisinin YERİNE GEÇMEZ,
    ÜSTÜNE gelir. Kullanıcı bu ekranda dört kalemi gözüyle toplar ve tablonun
    kendi içinde toplanabilir olması ayrı bir sözleşmedir.
    """
    ozet = await _hesapla_ve_ozetle(db_session, donem)

    assert (
        ozet.sgk_employee_total
        + ozet.unemployment_employee_total
        + ozet.income_tax_total
        + ozet.stamp_tax_total
        == ozet.employee_deduction_total
    )


# --------------------------------------------------------------------------- #
# 🔴 Vergisi BİLİNMEYEN satır — korkuluk, koruduğundan büyük hasar ÜRETMEZ
# --------------------------------------------------------------------------- #


async def test_IK3GV_ONCESI_satir_MATRAHTA_KALIR_ama_SAYACTA_gorunur(db_session, donem, dort_tip):
    """🔴 `income_tax_amount IS NULL` (IK3-GV öncesi satır) → fail-closed, ama DAR.

    Satırı SGK tabanından TAMAMEN düşürmek cazip ama YANLIŞTIR: SGK ekranının
    birincil işi PRİM bildirimidir ve prim brütten türer, gelir vergisinden
    BAĞIMSIZDIR. Düşürmek, ilgisiz bir eksik yüzünden ekranın asıl sayısını
    yok ederdi — *"bir korkuluk, koruduğu şeyden büyük hasar üretemez"*
    (IK3-RATE-FIX kanonu).

    Doğru davranış: satır matrahta ve PRİM kalemlerinde KALIR, yalnız
    vergi/damga toplamlarına GİRMEZ ve `unknown_tax_count`ta GÖRÜNÜR.
    """
    once = await _hesapla_ve_ozetle(db_session, donem)
    assert once.unknown_tax_count == 0

    bozulan = next(
        satir
        for satir in await _satirlar(db_session, donem)
        if satir.income_tax_amount == Decimal("2500.00")  # serbest meslekli
    )
    eski_vergi = bozulan.income_tax_amount
    bozulan.income_tax_amount = None
    await db_session.flush()

    sonra = await service.sgk_summary(db_session, donem.id)

    # Matrah ve prim kalemleri DEĞİŞMEDİ: bildirim ayakta.
    assert sonra.sgk_base_total == once.sgk_base_total
    assert sonra.declared_personnel_count == once.declared_personnel_count
    assert sonra.sgk_payable_total == once.sgk_payable_total
    # Vergi toplamı o satır kadar düştü ve eksiklik GÖRÜNÜR.
    assert sonra.income_tax_total == once.income_tax_total - eski_vergi
    assert sonra.unknown_tax_count == 1


async def test_bos_donemde_unknown_tax_count_SIFIRDIR(db_session, donem):
    """Satırsız dönemde sayaç uydurma bir sayı basmaz."""
    ozet = await service.sgk_summary(db_session, donem.id)
    assert ozet.unknown_tax_count == 0
