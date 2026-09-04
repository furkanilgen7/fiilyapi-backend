"""🔴 MU-3D İŞ 4 — MUTABAKAT: hakediş tarafı ↔ yevmiye ↔ beyanname.

## Neden bu dosya bu dilimin KABUL KAPISIDIR

MU-3D'den önce `600`/`740`/`320`/`120`ye yazan TEK aile faturaydı. MU-3D üç
hakediş ailesini daha o hesaplara yazdırıyor, yani aynı büyüklüğün **İKİ
kaynağı** oldu.

🔴 **Kanon (MU-3B/MU-3C'de ölçüldü): aynı büyüklüğün iki kaynağı varsa,
ayrıştıklarını HİÇBİR KOLON FARKI ele vermez — çünkü bakiye SAKLANMAZ.** İki
taraf sessizce ayrışır ve fark ancak yıl sonunda, elle bir sayımda görünür.

## 🔴 ÖNCEKİ ŞEFİN BULDUĞU SAHTE-YEŞİL: FIXTURE-KAPSAMLI MUTABAKAT

MU-3B'nin KDV mutabakatı (`test_mu3b_invoice_posting.py`) kendi fatura kümesini
kurar ve **hakediş KURMAZ**. Yeni bir aile o hesaplara yazmaya başladığında o
test YEŞİL KALIR ve kimlik yalnızca ÜRETİMDE bozulur. Bu dosya tam olarak o
kör noktayı kapatır: kümede hakediş DE vardır.

## İki kimlik, İKİ AYRI kader — ölçüldü

* **KDV** (`391`/`191` ↔ beyanname) — 🟢 **TUTAR**, çünkü hakediş fişi
  KDV'SİZDİR.
* **MATRAH** (`600`/`740` ↔ beyanname) — 🔴 **TUTMAZ ve TUTMAMALI**, çünkü
  faturalanmayan hakedişin gideri deftere GİRER (kararın 1. vaadi).

🔴 İkincisi bir kusur DEĞİL, **SEÇENEK B'nin tanımıdır**. Ama bu, mutabakatın
bırakılabileceği anlamına gelmez — kimlik yeniden yazılır:

    yevmiye(740) == beyanname(alışlar matrahı) + Σ FATURALANMAMIŞ gider hakedişi
    yevmiye(600) == beyanname(satış matrahı)   + Σ FATURALANMAMIŞ hasılat hakedişi

Faturalanan hakediş SOL tarafta bir kez görünür (fişi stornolandığı için net 0,
faturasının fişi onun yerine geçer) ve SAĞ tarafta bir kez sayılır. Çift sayım
tam olarak burada yakalanır.

## 🔴 MUTABAKAT KIRILIMLIDIR

Yalnız toplam ölçülseydi, parayı YANLIŞ HESABA yazan bir eşleme hatası YEŞİL
kalırdı (`740` yerine `600`e yazan bir kural `740 + 600` toplamını
değiştirmezdi — MU-3C'de ölçüldü). Bu yüzden DÖRT hesap AYRI AYRI ölçülür ve
üstelik iki YÖN de (gider/hasılat · borç/alacak) ayrı ayrı çakılır.

## 🔴 PENCERE İKİ TARAFTA DA AYNIDIR

Aylık bir büyüklüğü kümülatif bir netle karşılaştıran mutabakat, veri tek aya
sığdığı sürece TUTAR ve fişi yanlış güne yazan kusuru GÖREMEZ (MU-3C'nin M4
mutantı bunu şefin KENDİ bekçisinde ortaya çıkardı).

🔴 Burada bu tehlike DAHA BÜYÜKTÜR ve ölçüldü: iki aile fişini **FARKLI TARİH
KAYNAKLARINDAN** yazar —

* hakediş fişi → **ONAY GÜNÜ** (`approved_at`, TR takvimiyle),
* fatura fişi  → **`issue_date`** (faturanın kendi günü).

Kurulum bu yüzden faturaları BUGÜNE keser; aksi hâlde iki taraf iki AYRI aya
düşer ve aylık mutabakat, kod doğruyken bile kırmızı verirdi. Kimlik hem AYLIK
hem KÜMÜLATİF pencerede ayrı ayrı ölçülür.
"""

from decimal import Decimal

from app.modules.accounting.vat_return import build_vat_return
from app.modules.equipment import rental_service
from app.modules.invoicing import service as invoicing_service
from app.modules.invoicing import state_service as invoicing_state
from app.modules.invoicing.models import InvoiceDirection, InvoiceDocumentType
from app.modules.invoicing.schemas import InvoiceCreate, InvoiceLineCreate
from app.modules.invoicing.transitions import InvoiceAction
from app.modules.progress_payments import transitions as isveren_transitions
from app.modules.progress_payments.transitions import PaymentAction
from app.modules.subcontractor_progress_payments import transitions as taseron_transitions
from tests.modules.posting._mu3d import (
    KOD_ALICILAR,
    KOD_GIDER,
    KOD_HES_KDV,
    KOD_IND_KDV,
    KOD_SATICILAR,
    KOD_SATIS,
    aktor,
    bugun,
    esleme_kur,
    hesap_neti,
    isveren_hakedisi,
    kira_hakedisi,
    taseron_hakedisi,
)

# --------------------------------------------------------------------------- #
# BEKLENEN ARİTMETİK — TESTİN KENDİ İDDİASI, üründen OKUNMAZ
#
# 🔴 Bu sabitler ürün fonksiyonlarından türetilmez. Türetilseydi `posting_base`
#    bozulduğunda iki taraf BİRLİKTE kayar ve mutabakat yine tutardı.
# --------------------------------------------------------------------------- #

#: Taşeron: brüt 10×1.000 = 10.000 · avans %10 = 1.000 · teminat %5 = 500
TASERON_TABAN = Decimal("8500.00")
TASERON_BRUT = Decimal("10000.00")
#: İşveren: brüt 600×100 = 60.000 · avans %20 = 12.000 · teminat %5 = 3.000
ISVEREN_TABAN = Decimal("45000.00")
ISVEREN_BRUT = Decimal("60000.00")
#: Kira: `invoice_amount` DOĞRUDAN (avans/teminat YOK)
KIRA_TABAN = Decimal("100000.00")

KDV_ORANI = Decimal("20")
TASERON_KDV = Decimal("1700.00")  # 8.500 × %20
ISVEREN_KDV = Decimal("9000.00")  # 45.000 × %20


async def _fatura_kes(
    session,
    kullanici,
    *,
    yon,
    kaynak_alani,
    kaynak_id,
    matrah,
    no=None,
    advance_rate=None,
    retention_rate=None,
):
    """Kaynağa BAĞLI fatura — ÜRÜN yolundan, **BUGÜNE** kesilir (pencere gereği).

    🔴 FAT-HAK (2026-09-03): hakedişe bağlı faturada `matrah` artık BRÜTTÜR ve
    kesinti oranları hakedişin KENDİ oranlarıdır. `tax_base` yine
    `brüt − avans − teminat`a iner, yani aşağıdaki BEKLENEN ARİTMETİK sabitleri
    (`TASERON_TABAN` · `ISVEREN_TABAN`) DEĞİŞMEDİ — mutabakat aynı sayılarla
    tutar. Kira kaynağı kuralın DIŞINDADIR ve oransız kalır.
    """
    data = InvoiceCreate(
        direction=yon,
        invoice_no=no,
        document_type=InvoiceDocumentType.einvoice,
        issue_date=bugun(),
        party_name="Mutabakat Karşı Tarafı",
        advance_rate=advance_rate,
        retention_rate=retention_rate,
        lines=[
            InvoiceLineCreate(
                description="Hakediş bedeli",
                quantity=Decimal("1"),
                unit="Ad",
                unit_price=matrah,
                vat_rate=KDV_ORANI,
            )
        ],
        **{kaynak_alani: kaynak_id},
    )
    invoice, _m = await invoicing_service.create_invoice(session, kullanici, data)
    return invoice


async def _kumeyi_kur(seeded_db, user_factory):
    """🔴 Kümenin GENİŞLİĞİ iddianın parçasıdır.

    Üç aile · İKİ YÖN · faturalanmış VE faturalanmamış hakediş · kaynağa bağlı
    OLMAYAN bir fatura birlikte kurulur. Tek bir hakedişle ölçülseydi ne takas
    ne de "faturalanmayan deftere girer" dalı koşardı.
    """
    await esleme_kur(seeded_db)
    kullanici = await aktor(seeded_db, user_factory)

    # A — TAŞERON, FATURALANMAMIŞ: gideri defterde KALIR.
    a, _c = await taseron_hakedisi(seeded_db, kullanici, kod="MTB-TA")
    await taseron_transitions.perform(seeded_db, kullanici, a.id, PaymentAction.approve)

    # B — TAŞERON, FATURALANMIŞ: hakediş fişi STORNO, faturanınki geçer.
    b, _c = await taseron_hakedisi(seeded_db, kullanici, kod="MTB-TB")
    await taseron_transitions.perform(seeded_db, kullanici, b.id, PaymentAction.approve)
    b_fatura = await _fatura_kes(
        seeded_db,
        kullanici,
        yon=InvoiceDirection.incoming,
        kaynak_alani="subcontractor_progress_payment_id",
        kaynak_id=b.id,
        matrah=TASERON_BRUT,  # FAT-HAK: fatura ara toplamı hakedişin BRÜTÜ
        advance_rate=Decimal("10"),
        retention_rate=Decimal("5"),
        no="MTB-AL-B",
    )
    await invoicing_state.perform_transition(
        seeded_db, kullanici, b_fatura.id, InvoiceAction.approve
    )

    # C — KİRA, FATURALANMAMIŞ.
    c, _s = await kira_hakedisi(seeded_db, invoice_amount=str(KIRA_TABAN))
    await rental_service.approve_invoice(seeded_db, kullanici, c.id)

    # D — İŞVEREN, FATURALANMAMIŞ: hasılatı defterde KALIR.
    d, _ct, _p = await isveren_hakedisi(seeded_db, kullanici, kod="MTB-ID")
    await isveren_transitions.perform(seeded_db, kullanici, d.id, PaymentAction.approve)

    # E — İŞVEREN, FATURALANMIŞ.
    e, _ct, _p = await isveren_hakedisi(seeded_db, kullanici, kod="MTB-IE")
    await isveren_transitions.perform(seeded_db, kullanici, e.id, PaymentAction.approve)
    e_fatura = await _fatura_kes(
        seeded_db,
        kullanici,
        yon=InvoiceDirection.outgoing,
        kaynak_alani="progress_payment_id",
        kaynak_id=e.id,
        matrah=ISVEREN_BRUT,  # FAT-HAK: fatura ara toplamı hakedişin BRÜTÜ
        advance_rate=Decimal("20"),
        retention_rate=Decimal("5"),
    )
    await invoicing_state.perform_transition(seeded_db, kullanici, e_fatura.id, InvoiceAction.send)
    return kullanici


def _ay():
    gun = bugun()
    return (gun.year, gun.month)


async def test_KDV_KIMLIGI_HAKEDIS_FISLERI_VARKEN_de_TUTAR(seeded_db, user_factory):
    """🔴 İŞ 4/1 — ÖNCEKİ ŞEFİN BULDUĞU KÖR NOKTANIN KAPATILMASI.

    MU-3B'nin KDV mutabakatı FIXTURE-KAPSAMLIDIR (hakediş kurmaz). Burada küme
    üç hakediş ailesini de içerir ve kimlik YİNE TUTMALIDIR — çünkü hakediş
    fişi KDV'SİZDİR.

    🔴 Tutmasaydı bu dilim DURDURULMALIYDI: `vat_return` beyannameyi yalnız
    `invoices`tan türetir ve bir hakediş KDV bacağı, beyanname ile yevmiye
    arasına kuruş toleransı olmayan bir fark sokardı.
    """
    await _kumeyi_kur(seeded_db, user_factory)
    yil, ay = _ay()

    beyan = await build_vat_return(seeded_db, year=yil, month=ay)

    # 🔴 PENCERE İKİ TARAFTA DA AYNI (beyanname AYLIKtır).
    assert beyan.calculated_vat == -await hesap_neti(seeded_db, KOD_HES_KDV, ay=(yil, ay)), (
        "HESAPLANAN KDV ayrıştı — bir hakediş fişi `391`e yazmış olabilir"
    )
    assert beyan.deductible_vat == await hesap_neti(seeded_db, KOD_IND_KDV, ay=(yil, ay)), (
        "İNDİRİLECEK KDV ayrıştı — bir hakediş fişi `191`e yazmış olabilir"
    )
    # Küme GERÇEKTEN KDV taşıyor: sıfır ↔ sıfır da "tutar"dı.
    assert beyan.calculated_vat == ISVEREN_KDV
    assert beyan.deductible_vat == TASERON_KDV


async def test_GIDER_MUTABAKATI_hakedis_tarafi_ile_yevmiye_BIREBIR_tutar(seeded_db, user_factory):
    """🔴 İŞ 4/2 — BU DİLİMİN KABUL KAPISI. Kuruş toleransı YOK.

        yevmiye(740) == beyanname(alışlar matrahı) + Σ FATURALANMAMIŞ gider hakedişi

    Faturalanmış taşeron hakedişi (B) SOL tarafta bir kez görünür (kendi fişi
    stornolandı, faturasınınki geçti) ve SAĞ tarafta beyannamede bir kez
    sayılır. İki kez sayılsaydı fark tam olarak `TASERON_TABAN` kadar olurdu.
    """
    await _kumeyi_kur(seeded_db, user_factory)
    yil, ay = _ay()
    beyan = await build_vat_return(seeded_db, year=yil, month=ay)

    faturalanmamis_gider = TASERON_TABAN + KIRA_TABAN  # A + C
    beklenen = beyan.deductions[0].base + faturalanmamis_gider

    assert await hesap_neti(seeded_db, KOD_GIDER, ay=(yil, ay)) == beklenen
    # 🔴 Sayının KENDİSİ de çakılır: iki taraf BİRLİKTE kaysaydı kimlik yine
    #    tutar ama tutar YANLIŞ olurdu.
    assert beklenen == Decimal("117000.00")
    assert beyan.deductions[0].base == TASERON_TABAN


async def test_HASILAT_MUTABAKATI_da_BIREBIR_tutar(seeded_db, user_factory):
    """🔴 AYNANIN öteki yüzü — `600`.

    KDV'nin ve giderin tutması hasılatın tuttuğunu GÖSTERMEZ: işveren ailesinin
    rolleri TERS tohumlansaydı `740` yine tutar, `600` boş kalırdı.
    """
    await _kumeyi_kur(seeded_db, user_factory)
    yil, ay = _ay()
    beyan = await build_vat_return(seeded_db, year=yil, month=ay)

    beyan_matrahi = sum((satir.base for satir in beyan.taxable_rows), Decimal("0"))
    beyan_matrahi += beyan.exempt_base
    faturalanmamis_hasilat = ISVEREN_TABAN  # D

    # `600` bir GELİR hesabıdır: net `Σ borç − Σ alacak` NEGATİFTİR.
    assert -await hesap_neti(seeded_db, KOD_SATIS, ay=(yil, ay)) == (
        beyan_matrahi + faturalanmamis_hasilat
    )
    assert beyan_matrahi == ISVEREN_TABAN
    assert -await hesap_neti(seeded_db, KOD_SATIS, ay=(yil, ay)) == Decimal("90000.00")


async def test_CARI_MUTABAKATI_dort_hesap_AYRI_AYRI_tutar(seeded_db, user_factory):
    """🔴 KIRILIM İDDİASI — parayı YANLIŞ HESABA yazan eşleme hatasını yakalar.

    Yalnız toplam ölçülseydi `740` yerine `600`e yazan bir kural `740 + 600`
    toplamını değiştirmez ve YEŞİL kalırdı.

    Cari bacakları TOPLAM tutar üzerindendir (KDV DAHİL, faturada), hakediş
    bacağı ise KDV'SİZDİR — iki hesabın beklenen değeri bu yüzden gider/hasılat
    bacaklarından FARKLIDIR ve ayrıca çakılır.
    """
    await _kumeyi_kur(seeded_db, user_factory)
    yil, ay = _ay()

    # 320 Satıcılar (pasif → alacak yönlü, net NEGATİF):
    #   A hakediş 8.500 + C kira 100.000 + B faturası (8.500 + 1.700) = 118.700
    assert -await hesap_neti(seeded_db, KOD_SATICILAR, ay=(yil, ay)) == Decimal("118700.00")
    # 120 Alıcılar (aktif → borç yönlü):
    #   D hakediş 45.000 + E faturası (45.000 + 9.000) = 99.000
    assert await hesap_neti(seeded_db, KOD_ALICILAR, ay=(yil, ay)) == Decimal("99000.00")
    # Gider/hasılat bacakları KDV'SİZ olduğu için cariden AYRIŞIR — bu ayrışma
    # BEKLENENDİR ve karıştırılmadığını çakar.
    assert await hesap_neti(seeded_db, KOD_GIDER, ay=(yil, ay)) == Decimal("117000.00")
    assert -await hesap_neti(seeded_db, KOD_SATIS, ay=(yil, ay)) == Decimal("90000.00")


async def test_MUTABAKAT_KUMULATIF_pencerede_de_tutar_ve_AYLIK_pencere_ISLIYOR(
    seeded_db, user_factory
):
    """🔴 PENCERENİN GERÇEKTEN DARALTTIĞINI çakar.

    Aylık pencere hiçbir şeyi süzmüyor olsaydı (yanlış sınır aritmetiği · süzgeç
    hiç uygulanmıyor) yukarıdaki dört test yine yeşil kalırdı — veri tek aya
    sığıyor. Bu test BAŞKA BİR AYA bir hakediş daha koyar ve aylık pencerenin
    onu DIŞARIDA, kümülatifin İÇERİDE bıraktığını iddia eder.

    🔴 Kaynak: kira hakedişinin `period_month`u DEĞİL — fiş ONAY GÜNÜNE yazılır
    ve onay bugündür. O yüzden ayrım `entry_date`i elle geçmişe alınarak kurulur;
    ürün yolu geçmişe fiş YAZMAZ (KARAR-6) ve yazamamalıdır.
    """
    from sqlalchemy import select

    from app.modules.accounting.models import JournalEntry, JournalSourceType

    await _kumeyi_kur(seeded_db, user_factory)
    yil, ay = _ay()
    aylik = await hesap_neti(seeded_db, KOD_GIDER, ay=(yil, ay))
    kumulatif = await hesap_neti(seeded_db, KOD_GIDER)
    assert aylik == kumulatif == Decimal("117000.00")

    # Kira fişini GEÇEN AYA taşı (yalnız ÖLÇÜM için; ürün yolu bunu yapmaz).
    fis = (
        await seeded_db.execute(
            select(JournalEntry).where(
                JournalEntry.source_type == JournalSourceType.equipment_rental_invoice
            )
        )
    ).scalar_one()
    import datetime as _dt

    onceki = fis.entry_date.replace(day=1) - _dt.timedelta(days=1)
    fis.entry_date = onceki
    # 🔴 `ck_journal_entries_period_matches_date` — dönem kolonları `entry_date`
    #    ile TUTMAK ZORUNDADIR. Bu kısıt bu ölçümü yaparken ISIRDI ve iyi ki
    #    ısırdı: fişi başka bir aya taşıyıp dönemini eski bırakmak, mizan ile
    #    dönem raporlarının sessizce ayrışması demekti.
    fis.period_year = onceki.year
    fis.period_month = onceki.month
    await seeded_db.flush()

    assert await hesap_neti(seeded_db, KOD_GIDER, ay=(yil, ay)) == Decimal("17000.00"), (
        "AYLIK pencere DARALTMIYOR — mutabakat, fişi yanlış aya yazan kusuru göremez"
    )
    assert await hesap_neti(seeded_db, KOD_GIDER) == Decimal("117000.00"), (
        "kümülatif pencere de daralmış — süzgeç iki tarafa da sızmış"
    )
