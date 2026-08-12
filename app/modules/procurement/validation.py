"""Talebin SIKI tarafi: `submit` anindaki zorunluluklar (SA spec §3).

## Neden ayri bir modul

Talep TASLAK-FARKINDALIKLIDIR (P6 emsali, `SiteValidationError` docstring'i):
`draft` kaydederken yalniz PROJE zorunludur — FST'nin "Taslak Kaydet" dugmesi
yarim formu saklayabilmelidir. Zorunluluk kurallari yalnizca taslak DISINDA
kosar; tutarlilik kurallari (XOR, `quantity > 0`, uzunluk tavanlari) HER ZAMAN
kosar ve sema katmanindadir.

`submit` UCU **T3'undur** ve bu modulu cagirir. Kural buraya T2'de yazilir ki
T3 ikinci bir kopya uretmesin: iki kopya olsaydi "onaya gonderilebilir" tanimi
uc ile ekran arasinda sessizce ayrisirdi.

Fonksiyon ISTISNA ATMAZ, ENGEL LISTESI dondurur: T3 hepsini tek 422'de
gosterebilsin — kullaniciya eksikleri birer birer keşfettirmek FST gibi uzun
bir formda kabul edilemez.
"""

from collections.abc import Sequence
from typing import Protocol

__all__ = [
    "LINES_REQUIRED",
    "LINE_PRICE_REQUIRED",
    "LINE_SOURCE_REQUIRED",
    "NEEDED_BY_REQUIRED",
    "lines_missing_price",
    "submit_blockers",
]

# FST 58 "Ihtiyac Tarihi *" — yildiz "Onaya Gonder" icindir, "Taslak Kaydet"
# icin degil. Tarih olmadan teklif toplama takvimi kurulamaz.
NEEDED_BY_REQUIRED = "İhtiyaç tarihi zorunludur"

# Kalemsiz talep icin teklif ISTENEMEZ: tedarikciye sorulacak bir sey yoktur.
LINES_REQUIRED = "En az bir malzeme kalemi gereklidir"

# XOR'un DB'de zorlanmayan tarafi (T1 karari: CHECK taslagi kilitlerdi).
# Sema katmani her yazmada zaten uygular; burada IKINCI katman olarak kalir —
# DB'ye elle ya da eski bir surumle girmis bozuk satir onaya GECMEMELIDIR.
LINE_SOURCE_REQUIRED = "Her kalem ya stok kartına bağlı ya da adı ve birimi dolu olmalıdır"

# T5 BULGUSU (esik atlatma). Tahmini fiyat TASLAKTA opsiyoneldir ama ONAYA
# GONDERIRKEN ZORUNLUDUR — cunku ₺500K esigi (FST 166) tahmini TOPLAMDAN
# hesaplanir ve fiyatsiz kalem toplama GIRMEZ (`SUM` NULL'lari atlar). Alan bos
# birakilabilseydi ₺2M'lik bir talep toplam 0 gorunur, esik hic devreye girmez
# ve dusuk yetkili onaycidan gecerdi — DB'ye dokunmadan, yalnizca bir alani bos
# birakarak. Mockup da bunu soyler: FST 168 kutusu ("₺340.900 · Patron onayi
# gerekmiyor") HUKMUNU tahmini toplamdan verir, yani toplam ONAY AKISININ
# girdisidir, susleme degil.
LINE_PRICE_REQUIRED = "Her kalem için tahmini birim fiyat gereklidir (onay eşiği bundan hesaplanır)"


class _Request(Protocol):
    needed_by: object | None


class _Line(Protocol):
    stock_item_id: object | None
    free_text_name: str | None
    free_text_unit: str | None
    estimated_unit_price: object | None


def submit_blockers(request: _Request, lines: Sequence[_Line]) -> list[str]:
    """`draft → pending_approval` gecisini ENGELLEYEN eksiklerin listesi.

    Bos liste "onaya gonderilebilir" demektir. Sira sabittir (baslik alanlari
    once, kalemler sonra) — kullanici hatalari formdaki sirayla gorsun.

    ONAY ESIGI (₺500K) BURADA DEGILDIR: o bir YETKI kuralidir (kim onaylayabilir),
    talebin eksik olup olmadigiyla ilgisi yoktur ve T3'un `approve` ucuna aittir.
    """
    engeller: list[str] = []
    if request.needed_by is None:
        engeller.append(NEEDED_BY_REQUIRED)
    if not lines:
        engeller.append(LINES_REQUIRED)
    if any(not _line_has_source(line) for line in lines):
        engeller.append(LINE_SOURCE_REQUIRED)
    if lines_missing_price(lines):
        engeller.append(LINE_PRICE_REQUIRED)
    return engeller


def lines_missing_price(lines: Sequence[_Line]) -> bool:
    """Fiyati EKSIK kalem var mi — esigin "bilinmiyor" hali.

    `submit` bunu ENGEL sayar; `transitions._assert_approver_level` ise IKINCI
    KATMAN olarak kullanir ve fiyatsiz kalemi esigin USTU sayar (fail-closed).
    Iki katmanin gerekcesi `LINE_SOURCE_REQUIRED`inkiyle aynidir: DB'ye elle ya
    da eski bir surumle girmis fiyatsiz satir, "toplam 0" diye en dusuk
    yetkiliden gecmemelidir. Bilinmeyen tutar KUCUK degil BUYUK sayilir.
    """
    return any(line.estimated_unit_price is None for line in lines)


def _line_has_source(line: _Line) -> bool:
    """Kalem IKI KAPILIDIR: stok karti VEYA (ad + birim). Ikisi birden dolu olan
    satir sema katmaninda zaten reddedilir, bu yuzden burada "en az biri"
    yeterlidir."""
    if line.stock_item_id is not None:
        return True
    return bool(line.free_text_name) and bool(line.free_text_unit)
