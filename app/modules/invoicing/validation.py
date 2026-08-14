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
    "DEDUCTION_RATES_EXCEED_TOTAL",
    "GATE_ACTIONS",
    "INCOMING_NUMBER_REQUIRED",
    "LINES_REQUIRED",
    "OUTGOING_NUMBER_IS_SERVER_ASSIGNED",
    "body_blockers",
    "gate_blockers",
    "invoice_no_blockers",
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

_TAM_ORAN = Decimal("100")
_SIFIR_ORAN = Decimal("0")


def gate_blockers(action: InvoiceAction, lines: Sequence[object]) -> list[str]:
    """K6 — `send`/`approve` geçişini ENGELLEYEN eksiklerin listesi.

    Boş liste "kapıdan geçebilir" demektir.
    """
    if action not in GATE_ACTIONS:
        return []
    if not lines:
        return [LINES_REQUIRED]
    return []


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
