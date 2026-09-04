"""Faturanın SIKI tarafı: kapı ve gövde kuralları (FAT-1 spec §5 K6, §4 S5).

## K6 — "kalem yok" ile "tutar sıfır" AYNI 0 DEĞİLDİR

NULL-EŞİK kanonunun (SA dersi) kardeşi. Kalemsiz bir fatura `amounts.compute`
tarafından kusursuz biçimde 0,00₺ olarak hesaplanır: HESAP DOĞRUDUR, FATURA
YANLIŞTIR. İki hâli ayıran tek yer burasıdır ve kapı `send`/`approve`
anındadır — `draft` kaydetmek serbesttir, çünkü FK:24 "Taslak Kaydet" düğmesi
yarım formu saklayabilmelidir (`procurement/validation.py` deseninin aynısı,
taslak-farkındalık).

`mark-collected` ve `dispute` kalem denetimi YAPMAZ: ilki zaten kalemli bir
`sent` faturadan gelir, ikincisi bir REDDETMEDİR — eksik kalem, itirazı
engellemek için sebep değildir.

## 🔴 MU-3E İŞ 2 — `mark-collected` ARTIK ÖDEME ARAR (kullanıcı kararı 2026-08-26)

**Ölçülmüş kusur:** uç doğrudan çağrıldığında fatura `collected` oluyordu ama
ORTADA ÖDEME SATIRI YOKTU. Nakit bacağı `payments`ten doğar (MU-3C) ve ödeme
yoksa fiş de yoktur: muhasebede `120 Alıcılar` **AÇIK KALIYOR**, mizan
alıcıları fazla gösteriyor ve kullanıcıya bunu söyleyen HİÇBİR mekanizma yok.
`treasury/posting.py` bu boşluğu yazılı olarak biliyordu ve `KAPSAM DIŞI`na
bırakmıştı; kullanıcı kararı onu **fail-closed** olarak kapattı.

🔴 **Bu, K6 kalem kapısının BİR PARÇASI DEĞİLDİR ve `GATE_ACTIONS`a
EKLENMEZ.** İki kural iki AYRI olguyu ölçer: K6 faturanın KENDİ gövdesine
(kalemi var mı) bakar, bu kural faturanın DIŞINDAKİ bir olguya (parası geldi
mi) bakar. Tek bir kümede toplansaydı `send` de ödeme arar, `mark-collected`
de kalem arardı — ikisi de yanlış.

## 🔴 "Eski kayıt sonsuza dek `sent`te kilitlenir" İTİRAZI — ÖLÇÜLDÜ, GEÇERSİZ

Bu modülün eski metni kapıyı tam bu gerekçeyle reddediyordu. İtiraz bir
KAÇIŞ YOLU YOKLUĞU varsayar; oysa yol VARDIR ve daha doğrusudur: `POST
/payments` ile gerçekten olmuş tahsilatın satırı girilir, `payments_service.
_rederive_status` (K5) faturayı KENDİLİĞİNDEN `collected` damgalar ve aynı
işlemde nakit fişi de yazılır — yani `120` de kapanır. Damgayı ödemesiz
basmak, o faturayı defterde SONSUZA DEK açık bırakırdı; asıl kilitlenen
kayıt oydu.

## 🔴 FAT-HAK — FATURA ↔ HAKEDİŞ TUTAR KAPISI (kullanıcı kararı 2026-09-03)

**Ölçülmüş kusur:** 1.000.000 ₺'lik bir hakedişe 1 ₺'lik fatura kesilebiliyor,
hakediş `paid` oluyor ve kalan 999.999 ₺ iki yüzeyden birden sessizce
siliniyordu. Üstelik `models.SOURCE_UNIQUE_INDEXES` kaynak başına TEK asıl
faturaya izin verdiği için sahte fatura slotu KALICI olarak işgal ediyor,
gerçek fatura o hakedişe bir daha hiç bağlanamıyordu — ve `paid` TERMİNAL.
`treasury/realized.py` bu boşluğu yazılı olarak biliyor ve ürün kararı
bekliyordu.

Kural ve karşılaştırılan alanın seçimi `source_amount_matches`ta TEK KOPYA
olarak durur. Kapının HANGİ geçişlerde koştuğu üç yerde ölçülerek
kararlaştırıldı ve gerekçeleri o üç yerde yazılıdır:
`service.create_invoice` (yalnız GELEN — kayıt orada KALICILAŞIR),
`state_service.perform_transition` (`GATE_ACTIONS`) ve
`treasury.realized.assert_realized_covers` (para kapısı, fail-closed).

## Fonksiyonlar İSTİSNA ATMAZ

Engel LİSTESİ döndürürler; T3/T4 hepsini TEK 422'de gösterir. Kullanıcıya
eksikleri birer birer keşfettirmek FK gibi uzun bir formda kabul edilemez
(ayraç " · ", sıra sabittir).

## Bu modül ORM'e bağlı DEĞİLDİR

`gate_blockers` kalemleri yalnız SAYAR; şekillerine bakmaz. Böylece aynı kural
hem `PUT lines` gövdesinden hem veritabanındaki satırlardan çağrılabilir ve
"kalemsiz fatura" tanımı iki yerde ayrışmaz.
"""

from collections.abc import Sequence
from decimal import Decimal

from app.modules.invoicing.models import InvoiceDirection
from app.modules.invoicing.transitions import InvoiceAction

__all__ = [
    "COLLECTION_REQUIRES_PAYMENT",
    "DEDUCTION_RATES_EXCEED_TOTAL",
    "GATE_ACTIONS",
    "INCOMING_NUMBER_REQUIRED",
    "LINES_REQUIRED",
    "OUTGOING_NUMBER_IS_SERVER_ASSIGNED",
    "SOURCE_AMOUNT_TOLERANCE",
    "body_blockers",
    "collection_blockers",
    "gate_blockers",
    "invoice_no_blockers",
    "source_amount_blockers",
    "source_amount_matches",
    "source_amount_mismatch",
]

#: K6 — kalemsiz fatura gönderilemez/onaylanamaz.
LINES_REQUIRED = "En az bir fatura kalemi gereklidir"

# Toplam %100'ü aşarsa `tax_base` NEGATİF olur (§5 4. adım) ve `total`
# üzerindeki DB CHECK'i bunu ancak KDV'den sonra, kullanıcıya 500 olarak
# gösterirdi. Kural buraya yazılır ki hesap (amounts.py) SAF kalsın.
DEDUCTION_RATES_EXCEED_TOTAL = "Avans ve teminat kesintilerinin toplamı %100'ü aşamaz"

# §4 — numarayı sunucu üretir. İstemci gönderebilseydi `FIL` serisinde
# boşluk/çakışma açar ve danışma kilidinin garantisi anlamsızlaşırdı.
OUTGOING_NUMBER_IS_SERVER_ASSIGNED = "Giden fatura numarası sunucu tarafından atanır"

# S5 — satıcının kendi serisi (FY:165/174/183 üç ayrı seri kökü); sunucu
# üretemez, üretseydi gerçek belgeyle bağ kopardı.
INCOMING_NUMBER_REQUIRED = "Gelen fatura için fatura numarası zorunludur"

#: K6 kapısının uygulandığı işlemler — ötekiler kalem denetimi yapmaz.
GATE_ACTIONS: frozenset[InvoiceAction] = frozenset({InvoiceAction.send, InvoiceAction.approve})

#: MU-3E İŞ 2 — ödemesiz `mark-collected` reddi. Metin kullanıcıya YAPACAĞI İŞİ
#: söyler ("ödeme kaydı girin"), yalnız kuralı değil: kapının tek meşru çıkışı
#: `POST /payments`tir ve kullanıcı onu bilmiyorsa kapı bir çıkmaz sokak olur.
COLLECTION_REQUIRES_PAYMENT = (
    "Tahsil edildi damgası için faturanın toplamını karşılayan ödeme kaydı gereklidir; "
    "önce tahsilatı ödeme olarak girin"
)

#: 🔴 FAT-HAK — fatura brütü ile hakediş brütü arasında TOLERE EDİLEN fark
#: (kullanıcı kararı 2026-09-03: ±0,01 ₺). Sayı İKİ yerde okunur (422 kapısı ve
#: `treasury.realized`in 409 kapısı) ve TEK KOPYADIR: iki yerde yazılsaydı biri
#: gevşetildiğinde ötekinin hâlâ sıkı olduğu hiçbir yerde görünmezdi.
SOURCE_AMOUNT_TOLERANCE = Decimal("0.01")

_TAM_ORAN = Decimal("100")
_SIFIR_ORAN = Decimal("0")


def source_amount_mismatch(invoice_subtotal: Decimal, source_gross: Decimal) -> str:
    """FAT-HAK 422 metni — İKİ SAYIYI DA yazar.

    Sayısız bir cümle ("tutarlar uyuşmuyor") kullanıcıyı hangi tarafı
    düzelteceğini bilmeden bırakırdı: fark kuruşluk bir yuvarlama mı, yoksa
    sıfır mı unutulmuş — cevabı yalnız iki sayıyı yan yana görmek verir.
    """
    return (
        f"Faturanın ara toplamı ({invoice_subtotal}) bağlı olduğu hakedişin brüt "
        f"tutarına ({source_gross}) eşit olmalıdır"
    )


def gate_blockers(action: InvoiceAction, lines: Sequence[object]) -> list[str]:
    """K6 — `send`/`approve` geçişini ENGELLEYEN eksiklerin listesi.

    Boş liste "kapıdan geçebilir" demektir.
    """
    if action not in GATE_ACTIONS:
        return []
    if not lines:
        return [LINES_REQUIRED]
    return []


def collection_blockers(
    action: InvoiceAction, invoice_total: Decimal, paid_total: Decimal
) -> list[str]:
    """MU-3E İŞ 2 — `mark-collected` için `Σ payments >= total` EŞİĞİ.

    Eşiğin metni `payments_service._rederive_status`in K5 kuralıyla BİREBİR
    AYNIDIR (`paid_total >= invoice.total`) ve aynı olmak ZORUNDADIR: ödeme
    yoluyla otomatik damgalanan fatura ile elle damgalanan fatura AYNI koşulu
    sağlamalıdır. İki eşik ayrışsaydı bir fatura elle damgalanabilir ama
    ödemesi girilince damgası geri düşer (ya da tersi) hâle gelirdi.

    🔴 Toplam SIFIR OLAN fatura için eşik KENDİLİĞİNDEN sağlanır
    (`0 >= 0`) ve bu doğrudur: kapatılacak bir alacak yoktur, `120` zaten
    açılmamıştır. Ayrı bir dal yazılsaydı hiçbir şeyi korumayan bir kod olurdu.

    🔴 Bu fonksiyon ORM'e ve DB'ye DOKUNMAZ (modül docstring'i): `paid_total`
    ÇAĞIRANIN kilitli okumasından gelir. Buradan bir sorgu açılsaydı eşik,
    faturanın satır kilidinin DIŞINDA okunur ve EŞİK = KİLİT kanonu delinirdi.
    """
    if action is not InvoiceAction.mark_collected:
        return []
    if paid_total >= invoice_total:
        return []
    return [COLLECTION_REQUIRES_PAYMENT]


def body_blockers(*, advance_rate: Decimal | None, retention_rate: Decimal | None) -> list[str]:
    """Başlık oranlarının alanlar-arası kuralı.

    Tam %100 SERBESTTİR: matrahı sıfırlayan fatura anlamlıdır (tamamı avanstan
    mahsup) ve `amounts` onu 0,00₺ olarak hesaplar — negatif değildir. NULL
    "işaretlenmemiş kesinti"dir (FK:223/229) ve 0 sayılır.
    """
    toplam = (advance_rate or _SIFIR_ORAN) + (retention_rate or _SIFIR_ORAN)
    if toplam > _TAM_ORAN:
        return [DEDUCTION_RATES_EXCEED_TOTAL]
    return []


def source_amount_matches(invoice_subtotal: Decimal, source_gross: Decimal) -> bool:
    """🔴 FAT-HAK — *"bu fatura kaynak hakedişin tutarını mı taşıyor"* sorusunun
    **TEK** karşılaştırma kopyası.

    Kural (kullanıcı kararı 2026-09-03, BAĞLAYICI): bir hakedişe bağlanan ASIL
    faturanın brütü, hakedişin BRÜT tutarına eşit olmalıdır; tolerans ±0,01 ₺.
    Gerekçe kullanıcının kendi cümlesidir: *avans mahsubu ve teminat kesintisi
    ÖDEME anında düşülür, faturaya değil.*

    ## 🔴 KARŞILAŞTIRILAN ALAN `subtotal`DİR — `total` DEĞİL, `tax_base` DEĞİL

    Bu bir üslup tercihi değil, İKİ FORMÜLÜN ÖLÇÜLMÜŞ ŞEKLİDİR:

        hakediş brütü : `calculations.gross_total` = Σ satır tutarı
                        → KDV HARİÇ (KDV `net_amount`ta brütün ÜSTÜNE eklenir:
                          `net = gross + vat − advance − retention`),
                          kesinti ÖNCESİ (kesintiler `gross`tan sonra düşülür)
        fatura        : `amounts.compute` 1. adım `subtotal` = Σ satır tutarı
                        → KDV HARİÇ, kesinti ÖNCESİ  ⇒ **YAPISAL İKİZ**

    Öteki iki aday ÖLÇÜLEREK elendi:

    * **`total`** (= `tax_base + vat − withholding`) KDV İÇERİR. Eşit tutulsaydı
      KDV'siz bir hakediş brütü, KDV'li bir fatura toplamıyla kıyaslanırdı ve
      %20 KDV'li HER geçerli fatura reddedilirdi.
    * **`tax_base`** (= `subtotal − advance_amount − retention_amount`)
      kesintileri DÜŞMÜŞTÜR. Eşit tutulsaydı kullanıcının kararının gerekçesi
      TERSİNE çevrilirdi: kesintiyi faturaya taşıyan bir kullanıcı, kesinti
      kadar ŞİŞİRİLMİŞ bir `subtotal` yazmaya ZORLANIRDI.

    ## Tolerans NEDEN ±0,01

    İki taraf da `Decimal` + `ROUND_HALF_UP` ile 2 haneye yuvarlanır ama
    yuvarlama NOKTALARI farklıdır: hakedişte `quantize2(quantize2(bf × katsayı)
    × miktar)` (İKİ kez), faturada `round_money(miktar × birim fiyat)` (BİR
    kez). Aynı iş için iki taraf tek kuruş ayrışabilir; kullanıcı kararı bu
    kuruşu AÇIKÇA tolere eder. `>` ile kıyaslanır: tam 0,01 fark GEÇER.
    """
    return abs(invoice_subtotal - source_gross) <= SOURCE_AMOUNT_TOLERANCE


def source_amount_blockers(invoice_subtotal: Decimal, source_gross: Decimal | None) -> list[str]:
    """FAT-HAK'ın 422 sarmalayıcısı — `source_gross is None` "hakediş kaynağı
    YOK" demektir ve kural KOŞMAZ.

    `None` sessizce geçilir çünkü kural YALNIZ iki hakediş ailesi içindir:
    makine kira hakedişi ve sipariş kaynaklarının kıyaslanabilir bir "brüt"ü
    yoktur (`source_amounts.SOURCE_GROSS` tablosu bunu tek yerde söyler) ve
    onlara uydurma bir eşitlik dayatmak, bugün çalışan meşru faturaları
    reddederdi.

    🔴 ORM'e DOKUNMAZ (modül docstring'i): brütü ÇAĞIRAN okur. Buradan sorgu
    açılsaydı kural, faturanın satır kilidinin DIŞINDA ölçülürdü.
    """
    if source_gross is None:
        return []
    if source_amount_matches(invoice_subtotal, source_gross):
        return []
    return [source_amount_mismatch(invoice_subtotal, source_gross)]


def invoice_no_blockers(direction: InvoiceDirection, invoice_no: str | None) -> list[str]:
    """Numarayı KİM verir (§4 / S5) — yön başına tek kural.

    Yalnız boşluktan oluşan bir numara YOK sayılır: `invoice_no` NOT NULL
    olduğu için "   " kabul edilseydi kısıt geçilir ama belge izlenemez olurdu.
    """
    if direction is InvoiceDirection.outgoing:
        if invoice_no is not None:
            return [OUTGOING_NUMBER_IS_SERVER_ASSIGNED]
        return []
    if invoice_no is None or not invoice_no.strip():
        return [INCOMING_NUMBER_REQUIRED]
    return []
