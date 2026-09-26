"""Ad/birim NORMALIZASYONU — katalog eslesmesinin VE katalog tekilliginin TEK kurali.

EV-BORC-5 (cürütme bulgusu): tekillik BIREBIR (harf duyarli) karsilastirmayla sinaniyor,
oneri eslesmesi ise normalize ediyordu → "Beton" ve "BETON" ikisi de kaydedilebilir, sonra
oneri kalemi BELIRSIZ sayardi. Artik ikisi de bu fonksiyonu kullanir.

KATALOG-UQ madde 1 (NFC + sifir genislikli karakterler): kural anahtar kolonuna (name_key/
uom_key) DOGARKEN eklendi — sonradan eklemek anahtarlari yeniden hesaplayan bir migration
gerektirirdi ("normalize_label ileride DEGISIRSE mevcut anahtarlar eski kuralla kalir").

## Sira (olculdu, gerekce asagida)
1. NFC normalizasyonu ONCE: NFD "I"+U+0307 (birlesik nokta) → NFC "İ" (U+0130) → sonraki
   adim bunu "i" yapar. NFC'yi İ/I replace'inden SONRAYA koysaydik, ayrisik "I" tabani ile
   ayrisik birlesik nokta (U+0307) BIRLESMEDEN "ı" + U+0307 kalirdi (yanlis, "i" DEGIL).
2. Turkce İ/I elle cevirisi + `.lower()` — mevcut kural.
3. Ust simge + sifir genislikli karakterlerin SILINMESI (bosluga cevrilmez, iki harf
   bitisir): U+200B (ZWSP) · U+200C (ZWNJ) · U+200D (ZWJ) · U+FEFF (BOM / ZW NBSP).
4. Bosluk daraltma + kirpma.
5. SON NFC: `.lower()` bazi kod noktalarinda NFC-disi cikti verebilir (ör. bazi Yunan/
   birlesik harfler); son adimda tekrar NFC'ye sikistirmak `normalize(normalize(x)) ==
   normalize(x)` idempotensligini garanti eder (bkz. testler — tum kod noktasi taranir).
"""

from __future__ import annotations

import re
import unicodedata

#: Sifir genislikli karakterler: bosluk DEGIL, SILINIR (iki harf arasindaysa bitisir).
_ZERO_WIDTH = str.maketrans("", "", "\u200b\u200c\u200d\ufeff")


def normalize_label(text: str) -> str:
    """Ad/birim karsilastirmasi: NFC + Turkce harf duzeltmesi + ust simge + sifir genislikli
    karakter silme + bosluk.

    🔴 `"İ".casefold()` "i̇" (i + birlesik nokta) verir, "i" DEGIL — Turkce bir ad
    kendi kucuk harfli yaziminla eslesmezdi. Once I/İ elle cevrilir.
    """
    s = unicodedata.normalize("NFC", text)
    s = s.replace("İ", "i").replace("I", "ı").lower()
    s = s.replace("³", "3").replace("²", "2")
    s = s.translate(_ZERO_WIDTH)
    s = re.sub(r"\s+", " ", s).strip()
    return unicodedata.normalize("NFC", s)
