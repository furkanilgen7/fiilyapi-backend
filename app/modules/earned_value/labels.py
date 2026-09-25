"""Ad/birim NORMALIZASYONU — katalog eslesmesinin VE katalog tekilliginin TEK kurali.

EV-BORC-5 (cürütme bulgusu): tekillik BIREBIR (harf duyarli) karsilastirmayla sinaniyor,
oneri eslesmesi ise normalize ediyordu → "Beton" ve "BETON" ikisi de kaydedilebilir, sonra
oneri kalemi BELIRSIZ sayardi. Artik ikisi de bu fonksiyonu kullanir.
"""

from __future__ import annotations

import re


def normalize_label(text: str) -> str:
    """Ad/birim karsilastirmasi: Turkce harf duzeltmesi + ust simge + bosluk.

    🔴 `"İ".casefold()` "i̇" (i + birlesik nokta) verir, "i" DEGIL — Turkce bir ad
    kendi kucuk harfli yaziminla eslesmezdi. Once I/İ elle cevrilir.
    """
    s = text.replace("İ", "i").replace("I", "ı").lower()
    s = s.replace("³", "3").replace("²", "2")
    return re.sub(r"\s+", " ", s).strip()
