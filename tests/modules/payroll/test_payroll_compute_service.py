"""İK-3 T2 — `compute` AKIŞI (`service.compute_period`).

Hesabın kendisi `test_payroll_compute.py`de sınanır; burada akış sınanır:
kimlerin satırı açılır · gün nereden gelir · hangi satırlar KORUNUR · dönem
durumu kapıyı ne zaman kapatır.

Router YOKTUR (T3): servis doğrudan çağrılır, `DomainError` sınıfları HTTP'ye
T3'te çevrilir.
"""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.errors import ConflictError, NotFoundError
from app.modules.payroll import service
from app.modules.payroll.models import (
    PayrollLine,
    PayrollLineStatus,
    PayrollPeriod,
    PayrollPeriodStatus,
)
from app.modules.personnel.models import PaymentMethod, WageType
from app.modules.site_diary.models import WorkerSource
from app.modules.timesheet.models import TimesheetCode
from tests.modules.payroll.conftest import satir_of

pytestmark = pytest.mark.asyncio

AY_ICI = [1, 2, 3, 4, 5]


async def _satirlar(session, period) -> list[PayrollLine]:
    return list(
        (
            await session.execute(
                select(PayrollLine).where(PayrollLine.payroll_period_id == period.id)
            )
        )
        .scalars()
        .all()
    )


# --- Satır üretimi ----------------------------------------------------------


async def test_dort_tip_icin_satir_uretilir(
    db_session, donem, oranlar, personel_fabrikasi, puantaj_fabrikasi
):
    """BY dört bölüm çiziyor (127 · 175 · 243 · 271) — dördü de satır üretir.

    Taşeron satırı da ÜRETİLİR: görünür ve maliyete girer (K2), yalnız ödeme
    onayına girmez.
    """
    kisiler = {
        WorkerSource.company: await personel_fabrikasi("Ayşe Demir"),
        WorkerSource.subcontractor: await personel_fabrikasi(
            "Mehmet Yılmaz", source=WorkerSource.subcontractor
        ),
        WorkerSource.freelance: await personel_fabrikasi(
            "Kemal Tunç",
            source=WorkerSource.freelance,
            wage_type=WageType.monthly,
            wage_amount=Decimal("12500.00"),
        ),
        WorkerSource.intern: await personel_fabrikasi(
            "Burak Aydın",
            source=WorkerSource.intern,
            wage_type=WageType.monthly,
            wage_amount=Decimal("7500.00"),
        ),
    }
    for kisi in kisiler.values():
        await puantaj_fabrikasi(kisi, AY_ICI)

    sonuc = await service.compute_period(db_session, donem.id)
    satirlar = await _satirlar(db_session, donem)

    assert sonuc.created == 4
    assert {s.personnel_source for s in satirlar} == set(kisiler)
    # BY 254-257: serbest meslekli gün YOK, 12.500 → %20 stopaj → 10.000.
    serbest = satir_of(satirlar, kisiler[WorkerSource.freelance].id)
    assert serbest.days is None
    assert serbest.net_amount == Decimal("10000.00")
    # BY 283-285: stajyerde kesinti "—" → 0, net = brüt.
    stajyer = satir_of(satirlar, kisiler[WorkerSource.intern].id)
    assert stajyer.deduction_amount == Decimal("0.00")
    assert stajyer.net_amount == Decimal("7500.00")


async def test_taseron_satiri_excluded_ve_gerekcesi_yazili(
    db_session, donem, oranlar, personel_fabrikasi, puantaj_fabrikasi
):
    """K2 — çift ödeme YAPISAL olarak imkânsız: satır hiçbir yoldan `pending` olmaz."""
    kisi = await personel_fabrikasi("Ali Kaya", source=WorkerSource.subcontractor)
    await puantaj_fabrikasi(kisi, AY_ICI)

    await service.compute_period(db_session, donem.id)
    (satir,) = await _satirlar(db_session, donem)

    assert satir.status is PayrollLineStatus.excluded
    assert satir.excluded_reason
    # Maliyete GİRER: tutarlar hesaplanmış durumda (BY 186-189).
    assert satir.gross_amount == Decimal("9000.00")


async def test_ucretsiz_personel_uncomputed_ve_SIFIR_BASILMAZ(
    db_session, donem, oranlar, personel_fabrikasi, puantaj_fabrikasi
):
    """S4 fail-closed — satır AÇILIR ama para alanları `null` durur."""
    kisi = await personel_fabrikasi("Ücretsiz Kişi", wage_type=None, wage_amount=None)
    await puantaj_fabrikasi(kisi, AY_ICI)

    await service.compute_period(db_session, donem.id)
    (satir,) = await _satirlar(db_session, donem)

    assert satir.status is PayrollLineStatus.uncomputed
    assert satir.gross_amount is None
    assert satir.net_amount is None
    assert satir.bank_amount is None
    assert satir.cash_amount is None


async def test_oran_seti_olmayan_tip_uncomputed(
    db_session, donem, oranlar, personel_fabrikasi, puantaj_fabrikasi
):
    """🔴 ŞEF KARARI 2 — `general` bordro tipi değildir, oran satırı yoktur.

    Ücreti tanımlı olsa bile kesintisi bilinmediği için hesap YAPILMAZ.
    """
    kisi = await personel_fabrikasi("Genel İşçi", source=WorkerSource.general)
    await puantaj_fabrikasi(kisi, AY_ICI)

    await service.compute_period(db_session, donem.id)
    (satir,) = await _satirlar(db_session, donem)

    assert satir.status is PayrollLineStatus.uncomputed
    assert satir.gross_amount is None


async def test_donemin_YILI_kullanilir_bugunun_degil(
    db_session, oranlar, personel_fabrikasi, puantaj_fabrikasi
):
    """S2 — oran seti `(dönemin yılı, tip)` ile seçilir.

    2027 dönemi açıldı ama seti henüz girilmedi → fail-closed (ŞEF KARARI 2).
    Bugünün yılıyla seçilseydi 2027 bordrosu sessizce 2026 oranıyla hesaplanır
    ve mevzuat değişikliği görünmezleşirdi.
    """
    gelecek = PayrollPeriod(year=2027, month=1)
    db_session.add(gelecek)
    await db_session.flush()
    kisi = await personel_fabrikasi("Ayşe Demir")
    await puantaj_fabrikasi(kisi, AY_ICI, year=2027, month=1)

    await service.compute_period(db_session, gelecek.id)
    (satir,) = await _satirlar(db_session, gelecek)

    assert satir.status is PayrollLineStatus.uncomputed


# --- Gün: `MAN_DAY_CODES` kanonu -------------------------------------------


async def test_gun_sayisi_yalniz_MAN_DAY_kodlarindan(
    db_session, donem, oranlar, personel_fabrikasi, puantaj_fabrikasi
):
    """`matrix.MAN_DAY_CODES` = `{worked, overtime}` — TEK kaynak (S7).

    İzin/tatil/geçici görev günü adam-güne SAYILMAZ; sayılsaydı bordro ile
    puantaj ekranının adam-günü ayrışırdı (ŞP 235-236 · ŞP 245).
    """
    kisi = await personel_fabrikasi("Karışık Ay")
    await puantaj_fabrikasi(kisi, [1, 2, 3])
    await puantaj_fabrikasi(kisi, [6, 7], code=TimesheetCode.overtime)
    await puantaj_fabrikasi(kisi, [8], code=TimesheetCode.leave)
    await puantaj_fabrikasi(kisi, [9], code=TimesheetCode.holiday)
    await puantaj_fabrikasi(kisi, [10], code=TimesheetCode.temporary_duty)

    await service.compute_period(db_session, donem.id)
    (satir,) = await _satirlar(db_session, donem)

    assert satir.days == 5
    assert satir.gross_amount == Decimal("9000.00")


async def test_baska_ayin_gunleri_SAYILMAZ(
    db_session, donem, oranlar, personel_fabrikasi, puantaj_fabrikasi
):
    """Dönem bir AYDIR: komşu ayın hücresi bu ayın brütünü şişiremez."""
    kisi = await personel_fabrikasi("Ayşe Demir")
    await puantaj_fabrikasi(kisi, [1, 2])
    await puantaj_fabrikasi(kisi, [1, 2, 3], month=6)
    await puantaj_fabrikasi(kisi, [1, 2, 3], month=8)

    await service.compute_period(db_session, donem.id)
    (satir,) = await _satirlar(db_session, donem)

    assert satir.days == 2


async def test_mesai_SAATI_brute_eklenmez(
    db_session, donem, oranlar, personel_fabrikasi, puantaj_fabrikasi
):
    """🔴 ŞEF KARARI 4 — mesai saati otomatik paraya çevrilmez.

    BY 110-118 tablo başlığında mesai sütunu YOKTUR ve K3 mesaiyi açıkça
    override yoluna bağlar. `overtime` kodlu gün zaten GÜN olarak sayılır;
    saatini ayrıca ödemek aynı mesaiyi iki kez ödemek olurdu.
    """
    sade = await personel_fabrikasi("Mesaisiz")
    mesaili = await personel_fabrikasi("Mesaili")
    await puantaj_fabrikasi(sade, [1, 2, 3])
    await puantaj_fabrikasi(
        mesaili, [1, 2, 3], code=TimesheetCode.overtime, overtime_hours=Decimal("4.0")
    )

    await service.compute_period(db_session, donem.id)
    satirlar = await _satirlar(db_session, donem)

    assert satir_of(satirlar, sade.id).gross_amount == satir_of(satirlar, mesaili.id).gross_amount


@pytest.mark.parametrize(
    ("wage_type", "wage_amount"),
    [
        (WageType.daily, Decimal("1800.00")),
        (WageType.hourly, Decimal("225.00")),
        (WageType.monthly, Decimal("50600.00")),
    ],
)
async def test_puantaj_KAYDI_OLMAYAN_personel_UC_UCRET_TIPINDE_de_FAIL_CLOSED(
    db_session, donem, oranlar, personel_fabrikasi, wage_type, wage_amount
):
    """🔴 YÖNETİM KARARI (T4b) — dönemde HİÇ kaydı olmayan kişi `uncomputed`.

    Satır yine AÇILIR (kişi ekranda görünmelidir, "unutuldu mu?" sorusu ancak
    böyle sorulabilir) ama para alanları `null`dur: "hiç çalışmadı" ile
    "puantajı girilmedi" DB'de ayırt edilemez ve ikisine de 0 basmak, eksik
    veriyi "ödenecek bir şey yok" gibi gösterirdi (S4 · NULL-EŞİK kanonu).

    `monthly` DE dâhildir (yönetim kararı): gün sayısının brütü etkilememesi,
    işe hiç başlamamış personele tam maaş hesaplamayı meşrulaştırmaz.
    """
    await personel_fabrikasi("Kayıtsız Kişi", wage_type=wage_type, wage_amount=wage_amount)

    await service.compute_period(db_session, donem.id)
    (satir,) = await _satirlar(db_session, donem)

    assert satir.status is PayrollLineStatus.uncomputed
    assert satir.days is None
    assert satir.gross_amount is None
    assert satir.deduction_amount is None
    assert satir.net_amount is None
    assert satir.bank_amount is None
    assert satir.cash_amount is None


@pytest.mark.parametrize(
    ("wage_type", "wage_amount", "beklenen_brut"),
    [
        (WageType.daily, Decimal("1800.00"), Decimal("0.00")),
        (WageType.monthly, Decimal("50600.00"), Decimal("50600.00")),
    ],
)
async def test_kaydi_VAR_ama_hepsi_IZIN_kodlu_ise_gun_0_GERCEKTIR(
    db_session,
    donem,
    oranlar,
    personel_fabrikasi,
    puantaj_fabrikasi,
    wage_type,
    wage_amount,
    beklenen_brut,
):
    """🔴 AYRIM — "hiç kayıt yok" ≠ "kayıt var ama `MAN_DAY_CODES` dışı".

    İzin/tatil kodlu bir ay VERİ GİRİLMİŞ bir aydır: adam-gün 0'dır ve bu 0
    gerçektir, bilinmeyen değil. Satır hesaplanır ve onaya girebilir. İki durum
    tek koşula (`man_days == 0`) indirgenirse bu test kırmızıya döner — o
    indirgeme, izinli geçen gerçek bir ayı "veri eksik" diye kilitlerdi.
    """
    kisi = await personel_fabrikasi("İzinli Kişi", wage_type=wage_type, wage_amount=wage_amount)
    await puantaj_fabrikasi(kisi, [1, 2, 3], code=TimesheetCode.leave)

    await service.compute_period(db_session, donem.id)
    (satir,) = await _satirlar(db_session, donem)

    assert satir.status is PayrollLineStatus.pending
    assert satir.days == 0
    assert satir.gross_amount == beklenen_brut


async def test_BASKA_AYIN_kaydi_bu_ayin_kapisini_ACMAZ(
    db_session, donem, oranlar, personel_fabrikasi, puantaj_fabrikasi
):
    """Kayıt varlığı da DÖNEMİN AYINA bakar (gün sayımıyla aynı pencere).

    Haziran puantajı Temmuz'un eksik verisini kapatsaydı, işten Haziran'da
    ayrılmış birine Temmuz'da maaş hesaplanırdı.
    """
    kisi = await personel_fabrikasi("Geçen Ay Çalıştı", wage_type=WageType.monthly)
    await puantaj_fabrikasi(kisi, [1, 2, 3], month=6)

    await service.compute_period(db_session, donem.id)
    (satir,) = await _satirlar(db_session, donem)

    assert satir.status is PayrollLineStatus.uncomputed
    assert satir.gross_amount is None


# --- Kimler bordroya girer (ŞEF KARARI 5) ----------------------------------


@pytest.mark.parametrize(("is_active", "is_draft"), [(False, False), (True, True), (False, True)])
async def test_pasif_ve_taslak_personel_bordroya_GIRMEZ(
    db_session, donem, oranlar, personel_fabrikasi, puantaj_fabrikasi, is_active, is_draft
):
    """🔴 ŞEF KARARI 5 — yalnız `is_active=True` ve `is_draft=False` (İK-1 yayın kuralı).

    Taslak kartın ücreti henüz doğrulanmamıştır; pasif kişi ise işten ayrılmıştır.
    İkisine de satır açmak ödeme listesine gerçek olmayan kişi eklerdi.
    """
    kisi = await personel_fabrikasi("Dışarıda", is_active=is_active, is_draft=is_draft)
    await puantaj_fabrikasi(kisi, AY_ICI)

    sonuc = await service.compute_period(db_session, donem.id)

    assert sonuc.created == 0
    assert await _satirlar(db_session, donem) == []


# --- Yeniden hesap (S6 · S5) ------------------------------------------------


async def test_ikinci_kosu_INSERT_degil_UPDATE_ve_sonuc_AYNI(
    db_session, donem, oranlar, personel_fabrikasi, puantaj_fabrikasi
):
    """S6 + UQ `(dönem, personel)`: `compute` idempotenttir.

    İkinci koşu satır ÇOĞALTMAZ ve tutarları değiştirmez — değiştirseydi aynı
    veriyle iki farklı bordro üretilebilirdi.
    """
    kisi = await personel_fabrikasi("Ayşe Demir")
    await puantaj_fabrikasi(kisi, AY_ICI)

    ilk = await service.compute_period(db_session, donem.id)
    (once,) = await _satirlar(db_session, donem)
    onceki = (once.id, once.days, once.gross_amount, once.net_amount, once.status)

    ikinci = await service.compute_period(db_session, donem.id)
    (sonra,) = await _satirlar(db_session, donem)

    assert (ilk.created, ilk.updated) == (1, 0)
    assert (ikinci.created, ikinci.updated) == (0, 1)
    assert (sonra.id, sonra.days, sonra.gross_amount, sonra.net_amount, sonra.status) == onceki


async def test_puantaj_degisince_satir_TAZELENIR(
    db_session, donem, oranlar, personel_fabrikasi, puantaj_fabrikasi
):
    """S6'nın diğer yüzü: düzeltilmemiş satır yeniden hesapla GÜNCELLENİR."""
    kisi = await personel_fabrikasi("Ayşe Demir")
    await puantaj_fabrikasi(kisi, [1, 2])
    await service.compute_period(db_session, donem.id)

    await puantaj_fabrikasi(kisi, [3, 4, 5])
    await service.compute_period(db_session, donem.id)
    (satir,) = await _satirlar(db_session, donem)

    assert satir.days == 5
    assert satir.gross_amount == Decimal("9000.00")


async def test_ELLE_DUZELTILMIS_satir_yeniden_hesapta_DEGISMEZ(
    db_session, donem, oranlar, personel_fabrikasi, puantaj_fabrikasi
):
    """🔴 S6 — `is_overridden` satır KORUNUR (K3'ün gereği).

    Yeniden hesap kullanıcının düzeltmesini (mesai/ikramiye/avans) sessizce
    ezemez. Puantaj DEĞİŞTİRİLİR ki tazeleme yolu gerçekten tetiklensin: satır
    yalnız `is_overridden` bayrağı yüzünden korunmalıdır.
    """
    kisi = await personel_fabrikasi("Ayşe Demir")
    await puantaj_fabrikasi(kisi, [1, 2])
    await service.compute_period(db_session, donem.id)
    (satir,) = await _satirlar(db_session, donem)

    satir.is_overridden = True
    satir.gross_amount = Decimal("99999.00")
    satir.deduction_amount = Decimal("0.00")
    satir.net_amount = Decimal("99999.00")
    satir.bank_amount = Decimal("99999.00")
    satir.cash_amount = Decimal("0.00")
    satir.previous_gross_amount = Decimal("3600.00")
    await db_session.flush()
    await puantaj_fabrikasi(kisi, [3, 4, 5])

    sonuc = await service.compute_period(db_session, donem.id)
    (sonra,) = await _satirlar(db_session, donem)

    assert sonuc.skipped_overridden == 1
    assert sonuc.updated == 0
    assert sonra.gross_amount == Decimal("99999.00")
    assert sonra.net_amount == Decimal("99999.00")
    assert sonra.days == 2
    assert sonra.status is PayrollLineStatus.pending


async def test_ONAYLI_satir_yeniden_hesapta_DEGISMEZ(
    db_session, donem, oranlar, personel_fabrikasi, puantaj_fabrikasi
):
    """S5 — onaylanan satır DEĞİŞTİRİLEMEZ; `compute` da bir değiştirmedir.

    Dönem `pending_approval` iken tek tek onaylanmış satırlar olabilir; yeniden
    hesap onların tutarını sessizce değiştirseydi ÖDEME İZİ bozulurdu (S5'in
    gerekçesi budur). Atlama SESSİZ DEĞİLDİR: sonuçta sayılır.
    """
    kisi = await personel_fabrikasi("Ayşe Demir")
    await puantaj_fabrikasi(kisi, [1, 2])
    await service.compute_period(db_session, donem.id)
    (satir,) = await _satirlar(db_session, donem)
    satir.status = PayrollLineStatus.approved
    await db_session.flush()
    await puantaj_fabrikasi(kisi, [3, 4, 5])

    sonuc = await service.compute_period(db_session, donem.id)
    (sonra,) = await _satirlar(db_session, donem)

    assert sonuc.skipped_approved == 1
    assert sonra.days == 2
    assert sonra.gross_amount == Decimal("3600.00")


# --- Dönem durumu kapısı ----------------------------------------------------


@pytest.mark.parametrize("durum", [PayrollPeriodStatus.approved, PayrollPeriodStatus.paid])
async def test_onayli_veya_odenmis_donemde_compute_CAKISIR(
    db_session, donem, oranlar, personel_fabrikasi, durum
):
    """Spec §5 — dönem `approved`/`paid` ise `compute` **409**.

    Ödenmiş bir ayın tutarlarını yeniden hesaplamak, banka çıkışıyla kayıt
    arasındaki bağı koparırdı.
    """
    await personel_fabrikasi("Ayşe Demir")
    donem.status = durum
    await db_session.flush()

    with pytest.raises(ConflictError):
        await service.compute_period(db_session, donem.id)


@pytest.mark.parametrize("durum", [PayrollPeriodStatus.draft, PayrollPeriodStatus.pending_approval])
async def test_taslak_ve_onay_bekleyen_donemde_compute_ACIK(
    db_session, donem, oranlar, personel_fabrikasi, durum
):
    donem.status = durum
    await db_session.flush()
    await personel_fabrikasi("Ayşe Demir")

    sonuc = await service.compute_period(db_session, donem.id)

    assert sonuc.created == 1


async def test_olmayan_donem_404(db_session, oranlar):
    """Görünmeyen/var olmayan kayıt AYIRT EDİLEMEZ (spec §6.8)."""
    with pytest.raises(NotFoundError):
        await service.compute_period(db_session, uuid.uuid4())


# --- S3: yarım dolu satır DB'ye de yazılmaz --------------------------------


async def test_yazilan_satirlarda_banka_arti_elden_NETE_ESIT(
    db_session, donem, oranlar, personel_fabrikasi, puantaj_fabrikasi
):
    """Yönetim eki #3 — `net` doluysa bölüşüm de dolu ve toplamı nete eşit.

    Yarım dolu satır T3'teki S3 kapısını sessizce atlatırdı (kapı yalnız
    GÖNDERİLEN bölüşümü denetler, hiç gönderilmemişi göremez). Nakit ödemeli
    kişi de taranır: bölüşüm elden tarafına düşer, invariant yine tutar.
    """
    bankali = await personel_fabrikasi("Bankalı", payment_method=PaymentMethod.bank)
    nakitci = await personel_fabrikasi("Nakitçi", payment_method=PaymentMethod.cash)
    karma = await personel_fabrikasi("Karma", payment_method=PaymentMethod.mixed)
    yontemsiz = await personel_fabrikasi("Yöntemsiz", payment_method=None)
    kurusluk = await personel_fabrikasi(
        "Kuruşlu", wage_type=WageType.monthly, wage_amount=Decimal("12345.67")
    )
    for kisi in (bankali, nakitci, karma, yontemsiz, kurusluk):
        await puantaj_fabrikasi(kisi, AY_ICI)

    await service.compute_period(db_session, donem.id)
    satirlar = await _satirlar(db_session, donem)

    assert len(satirlar) == 5
    for satir in satirlar:
        assert satir.net_amount is not None
        assert satir.bank_amount + satir.cash_amount == satir.net_amount
        assert satir.gross_amount - satir.deduction_amount == satir.net_amount

    # Nakit ödemeli kişide bölüşüm ELDEN tarafına düşer (ŞEF KARARI 3'ün sınırı:
    # varsayılan banka YALNIZCA yöntem `cash` DEĞİLKEN geçerlidir).
    assert satir_of(satirlar, nakitci.id).bank_amount == Decimal("0.00")
    assert satir_of(satirlar, nakitci.id).cash_amount == satir_of(satirlar, nakitci.id).net_amount
    # `mixed` ve yöntemsiz kişide varsayılan HEPSİ BANKA (BY 143/163/259/287).
    for kisi in (karma, yontemsiz):
        assert satir_of(satirlar, kisi.id).cash_amount == Decimal("0.00")


# --- T6: `compute` dönemi ONAY BEKLİYOR yapar ------------------------------
#
# 🔴 YÖNETİM KARARI (2026-08-13, mockup gerekçeli). BY 63 banner'ı "Temmuz 2026
# bordrosu onay bekliyor" diyor: hesap biter bitmez dönem ZATEN onay bekler.
# Kullanıcının TEK tıkı BY 56 "Ödemeyi Onayla"dır (`pending_approval →
# approved`); ayrıca bir "onaya gönder" tıkı YOKTUR. Geçiş KÜMESİ değişmedi
# (S8 aynı), yalnız `draft → pending_approval` geçişinin TETİKLEYİCİSİ artık
# `compute`tur ve geçiş yine `transitions.assert_period_transition`ten geçer.


async def test_T6_compute_donemi_ONAY_BEKLIYOR_yapar(
    db_session, donem, oranlar, personel_fabrikasi, puantaj_fabrikasi
):
    """BY 63 — hesaplanan dönem onay bekler; kullanıcı ayrıca "gönder" demez."""
    kisi = await personel_fabrikasi("Ayşe Demir")
    await puantaj_fabrikasi(kisi, AY_ICI)
    assert donem.status is PayrollPeriodStatus.draft

    await service.compute_period(db_session, donem.id)

    assert donem.status is PayrollPeriodStatus.pending_approval


async def test_T6_hesaplanabilir_satir_YOKSA_donem_TASLAK_kalir(
    db_session, donem, oranlar, personel_fabrikasi
):
    """🔴 BOŞ dönem onaya DÜŞMEZ.

    Ücreti tanımsız (S4) ve puantajsız (S4.1) personelin satırı `uncomputed`,
    taşeronunki `excluded`tır — ödenecek hiçbir şey yoktur. Dönem yine de
    "onay bekliyor" olsaydı kullanıcı BY 56'ya basmaya davet edilir, onaylanacak
    satır bulamaz ve dönem boşuna `approved` olurdu (geri dönüşü YOK: `compute`
    kapısı da kapanırdı).
    """
    await personel_fabrikasi("Ücretsiz", wage_type=None, wage_amount=None)
    await personel_fabrikasi("Taşeron", source=WorkerSource.subcontractor)

    sonuc = await service.compute_period(db_session, donem.id)

    assert sonuc.created == 2
    assert donem.status is PayrollPeriodStatus.draft


async def test_T6_ikinci_compute_durumu_GERI_ALMAZ(
    db_session, donem, oranlar, personel_fabrikasi, puantaj_fabrikasi
):
    """Yeniden hesap dönemi `draft`a DÜŞÜRMEZ — ilerleme tek yönlüdür (S8)."""
    kisi = await personel_fabrikasi("Ayşe Demir")
    await puantaj_fabrikasi(kisi, AY_ICI)
    await service.compute_period(db_session, donem.id)

    await service.compute_period(db_session, donem.id)

    assert donem.status is PayrollPeriodStatus.pending_approval


async def test_T6_bos_donemden_sonra_hesaplanan_satir_donemi_ILERLETIR(
    db_session, donem, oranlar, personel_fabrikasi, puantaj_fabrikasi
):
    """Boş kalan dönem TIKANMAZ: puantaj girilince ikinci `compute` ilerletir."""
    kisi = await personel_fabrikasi("Ayşe Demir")
    await service.compute_period(db_session, donem.id)
    assert donem.status is PayrollPeriodStatus.draft

    await puantaj_fabrikasi(kisi, AY_ICI)
    await service.compute_period(db_session, donem.id)

    assert donem.status is PayrollPeriodStatus.pending_approval
