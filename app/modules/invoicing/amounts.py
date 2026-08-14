"""🔴 FATURA PARA HESABI — TEK KAYNAK (FAT-1 spec §5, K3-K5).

Hiçbir uç/servis kendi toplamını hesaplamaz; `compute` faturanın yedi adımını
FGI:163-186 + FK:246-250 tfoot SIRASIYLA uygular:

    1. subtotal          = Σ round(quantity × unit_price)       (satır bazında)
    2. advance_amount    = round(subtotal × advance_rate   / 100)
    3. retention_amount  = round(subtotal × retention_rate / 100)
    4. tax_base          = subtotal − advance_amount − retention_amount
    5. vat_amount        = Σ_oran round(oran_matrahı × oran / 100)
    6. withholding_amount= round(vat_amount × withholding_rate / 100)   (K4)
    7. total             = tax_base + vat_amount − withholding_amount

Sıra bir üslup tercihi DEĞİLDİR: kesintilerin matrahı `subtotal`, KDV'nin
matrahı `tax_base`, tevkifatın matrahı `vat_amount`tır. Herhangi ikisi yer
değiştirse aynı fatura başka bir para üretir.

K3 — ÇOK ORANLI KDV
-------------------
Mockup tfoot'u tek `%20` çizer (FGI:180) ama kalem tablosu `KDV %`yi SATIR
BAZINDA taşır (FGI:121); kesintiler ise BAŞLIK düzeyindedir. Kesinti bu yüzden
satırlara TUTARLARIYLA ORANTILI dağıtılır (5. adım), sonra KDV **oran grupları
üzerinden** hesaplanır.

🔴 Neden grup, neden satır değil: her satırın KDV'si ayrı yuvarlanıp
toplansaydı TEK oranlı bir fatura bile mockup'ın başlık formülünden SAPARDI —
3 × 0,10₺ @ %15 satır bazlı 0,06₺, `round(0,30 × %15)` ise 0,05₺ verir. K3(a)
"tek oranlı faturada sonuç birebir aynıdır" der; bunu ancak aynı orandaki
matrahları ÖNCE toplayıp SONRA bir kez yuvarlamak sağlar. Tek oranlı faturada
grup sayısı birdir ve grubun matrahı `tax_base`in ta kendisidir.

🔴 YUVARLAMA ARTIĞININ YERİ (K3(b) kararı)
------------------------------------------
Bir toplamı paylara bölerken parçaların toplamı, aşağı yuvarlama yüzünden
toplamın altında kalır. Karar: **artık kaybolmaz ve uydurulmaz — En Büyük
Kalan yöntemiyle paylara geri dağıtılır**, kuruş kuruş, en büyük kesirli
kalandan başlayarak; eşitlikte ÖNCEKİ satır (küçük `sort_order`) kazanır.

Gerekçe: (a) BAŞLIK TOPLAMI OTORİTEDİR — `subtotal`, `tax_base`, `vat_amount`
kolonları mali tabloya girer; satır payları yalnızca onların bölünmesidir, o
yüzden pay toplamı başlığa **kuruşu kuruşuna** eşit olmalıdır. (b) Artık "son
satıra" ya da rastgele atılsaydı aynı fatura iki koşuda farklı satır dağılımı
verebilir ya da sistematik olarak hep aynı satırı şişirirdi. (c) Artık hiç
dağıtılmasaydı satır toplamı başlıktan eksik kalır, ekranda "kalemlerin toplamı
tutmuyor" görünürdü.

Bu modülde İKİ dağıtım vardır ve ikisi de aynı kuralı kullanır: `tax_base`in
satırlara dağıtımı ve grup KDV'sinin grup satırlarına dağıtımı.

`subtotal = 0` (kalemsiz ya da tümü bedelsiz fatura) → ağırlık toplamı sıfırdır
ve dağıtım SIFIRA BÖLMEDEN sıfır döner; KDV de 0'dır.

K5 — YUVARLAMA
--------------
Her ara adım `Decimal` + `ROUND_HALF_UP` ile 2 haneye. **Kayan nokta
KULLANILMAZ** — `0.1 + 0.2 != 0.3` hatası mali tabloda ancak aylar sonra, kuruş
farkı olarak görülür. `test_amounts_modulunde_kayan_nokta_YOK` bunu AST
düzeyinde bekler (yorumdaki örnekleri değil, gerçek kayan nokta değişmezlerini
ve `float` çağrılarını arar).

`tax_base`in NEGATİF olabileceği tek durum `advance_rate + retention_rate > 100`
hâlidir; onu bu modül değil `validation.body_blockers` (422) engeller —
hesap saftır, iş kuralı taşımaz.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal
from typing import Protocol

__all__ = [
    "InvoiceAmounts",
    "LineInput",
    "compute",
    "line_total",
    "round_money",
]

#: Para ölçeği — `Numeric(18, 2)` kolonlarıyla birebir.
KURUS = Decimal("0.01")

_YUZ = Decimal("100")
_SIFIR = Decimal("0")


def round_money(value: Decimal) -> Decimal:
    """2 haneye `ROUND_HALF_UP` (K5). Bankacı yuvarlaması (Python'un `Decimal`
    varsayılanı `ROUND_HALF_EVEN`'dir) KULLANILMAZ: fatura tutarı muhasebe
    geleneğine göre yukarı yuvarlanır ve mockup tfoot'u da öyle okunur."""
    return value.quantize(KURUS, rounding=ROUND_HALF_UP)


class _Line(Protocol):
    """Kalem SÖZLEŞMESİ — modül ORM'e bağlı değildir; T3 hem gövde şemasını
    hem `InvoiceLine` satırını aynı fonksiyona verebilir."""

    quantity: Decimal
    unit_price: Decimal
    vat_rate: Decimal


@dataclass(frozen=True)
class LineInput:
    """Hesap girdisi — testler ve T3'ün gövde dönüşümü için."""

    quantity: Decimal
    unit_price: Decimal
    vat_rate: Decimal


@dataclass(frozen=True)
class InvoiceAmounts:
    """Hesabın TAM çıktısı.

    Başlık alanları `invoices` kolonlarına birebir yazılır. `line_totals`
    `invoice_lines.line_total` kolonudur. `line_tax_bases` ve `line_vat_amounts`
    KOLON DEĞİLDİR — türev oldukları için saklanmazlar (spec §2 "türev olan her
    şey kolon değildir"); dağıtımın başlığa kuruşu kuruşuna toplandığını
    kanıtlamak ve ekranda satır kırılımı göstermek için döndürülürler.
    """

    line_totals: tuple[Decimal, ...]
    line_tax_bases: tuple[Decimal, ...]
    line_vat_amounts: tuple[Decimal, ...]
    subtotal: Decimal
    advance_amount: Decimal
    retention_amount: Decimal
    tax_base: Decimal
    vat_amount: Decimal
    withholding_amount: Decimal
    total: Decimal


def line_total(quantity: Decimal, unit_price: Decimal) -> Decimal:
    """1. adım, satır ayağı: `quantity × unit_price`, 2 haneye yuvarlanır.

    Miktar `Numeric(14, 3)` olduğu için çarpım 5 haneye kadar çıkabilir; kolon
    2 hanelidir ve yuvarlama SATIRDA yapılır (K7: `line_total` donmuş bir
    çarpandır, başlıktan geri türetilmez)."""
    return round_money(quantity * unit_price)


def compute(
    lines: Sequence[_Line],
    *,
    advance_rate: Decimal | None = None,
    retention_rate: Decimal | None = None,
    withholding_rate: Decimal | None = None,
) -> InvoiceAmounts:
    """Faturanın yedi adımı (modül docstring'i). Girdi nesneleri DEĞİŞTİRİLMEZ.

    Oranların `None` olması "kesinti işaretlenmemiş" demektir (FK:223/229/235
    checkbox'ları) ve tutarı 0'dır — kolonlar NOT NULL olduğu için NULL bir
    tutar hiçbir yolda üretilmez.
    """
    # 1
    line_totals = tuple(line_total(line.quantity, line.unit_price) for line in lines)
    subtotal = _topla(line_totals)

    # 2 · 3
    advance_amount = _oran_tutari(subtotal, advance_rate)
    retention_amount = _oran_tutari(subtotal, retention_rate)

    # 4
    tax_base = subtotal - advance_amount - retention_amount

    # 5 — kesinti satırlara orantılı dağıtılır, KDV oran GRUPLARINDA hesaplanır.
    line_tax_bases = _dagit(tax_base, line_totals)
    line_vat_amounts, vat_amount = _kdv(lines, line_totals, line_tax_bases)

    # 6 — K4: matrah KDV'dir.
    withholding_amount = _oran_tutari(vat_amount, withholding_rate)

    # 7 — K4: tevkifat DÜŞÜLÜR.
    total = tax_base + vat_amount - withholding_amount

    return InvoiceAmounts(
        line_totals=line_totals,
        line_tax_bases=line_tax_bases,
        line_vat_amounts=line_vat_amounts,
        subtotal=subtotal,
        advance_amount=advance_amount,
        retention_amount=retention_amount,
        tax_base=tax_base,
        vat_amount=vat_amount,
        withholding_amount=withholding_amount,
        total=total,
    )


# --------------------------------------------------------------------------- #
# Yardımcılar
# --------------------------------------------------------------------------- #


def _topla(degerler: Sequence[Decimal]) -> Decimal:
    """Boş dizide `sum` tam sayı 0 döndürür; ölçek kaybolmasın diye başlangıç
    değeri açıkça 2 haneli `Decimal`dır."""
    return round_money(sum(degerler, _SIFIR))


def _oran_tutari(taban: Decimal, oran: Decimal | None) -> Decimal:
    if oran is None:
        return round_money(_SIFIR)
    return round_money(taban * oran / _YUZ)


def _kdv(
    lines: Sequence[_Line],
    line_totals: Sequence[Decimal],
    line_tax_bases: Sequence[Decimal],
) -> tuple[tuple[Decimal, ...], Decimal]:
    """5. adım — KDV, ORAN GRUPLARI üzerinden (K3, modül docstring'i).

    Aynı orandaki satırların matrahları ÖNCE toplanır, KDV bir kez hesaplanıp
    yuvarlanır; sonra grup KDV'si grubun satırlarına aynı En Büyük Kalan
    kuralıyla bölünür. Böylece tek oranlı faturada sonuç `round(tax_base × oran)`
    ile birebir aynı olur ve satır payları başlığa kuruşu kuruşuna toplanır.
    """
    gruplar: dict[Decimal, list[int]] = {}
    for indeks, line in enumerate(lines):
        gruplar.setdefault(line.vat_rate, []).append(indeks)

    paylar = [round_money(_SIFIR)] * len(line_totals)
    vat_amount = round_money(_SIFIR)

    for oran, indeksler in gruplar.items():
        grup_matrahi = _topla([line_tax_bases[indeks] for indeks in indeksler])
        grup_kdv = round_money(grup_matrahi * oran / _YUZ)
        vat_amount += grup_kdv
        grup_paylari = _dagit(grup_kdv, [line_totals[indeks] for indeks in indeksler])
        for pay, indeks in zip(grup_paylari, indeksler, strict=True):
            paylar[indeks] = pay

    return tuple(paylar), vat_amount


def _dagit(toplam: Decimal, agirliklar: Sequence[Decimal]) -> tuple[Decimal, ...]:
    """`toplam`ı ağırlıklara ORANTILI böler; parçaların toplamı `toplam`a
    BİREBİR eşittir (En Büyük Kalan — artık kararı modül docstring'inde).

    Ağırlık toplamı 0 ise (kalemsiz ya da tümü bedelsiz fatura) sıfıra bölme
    YAPILMAZ, sıfır paylar döner.
    """
    agirlik_toplami = sum(agirliklar, _SIFIR)
    if agirlik_toplami == _SIFIR:
        return tuple(round_money(_SIFIR) for _ in agirliklar)

    idealler = [toplam * agirlik / agirlik_toplami for agirlik in agirliklar]
    paylar = [ideal.quantize(KURUS, rounding=ROUND_DOWN) for ideal in idealler]

    artik_kurus = int((toplam - sum(paylar, _SIFIR)) / KURUS)
    if artik_kurus:
        # En büyük kesirli kalan önce; eşitlikte ÖNCEKİ satır kazanır.
        sira = sorted(range(len(paylar)), key=lambda i: (paylar[i] - idealler[i], i))
        for indeks in sira[:artik_kurus]:
            paylar[indeks] += KURUS

    return tuple(paylar)
