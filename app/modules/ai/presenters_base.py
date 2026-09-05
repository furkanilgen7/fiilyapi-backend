"""Eşleyicilerin ortak yardımcıları — **TEK KOPYA**.

`presenters.py` 800 satır tavanını aşınca bölündü (`_journal.py` emsali; aynı
PR `tools/reads/handlers.py`yi tam bu tavan için bölmüştü). Üç parça:

* `presenters_base.py` — biçimleme + ortak blok kalıpları (bu dosya),
* `presenters_ai2bd.py` — AI-2b/2d'nin on altı eşleyicisi,
* `presenters.py` — AI-0b'nin beşi + `SUNUCULAR` + `bloklari_uret`.

🔴 **YARDIMCILAR KOPYALANMADI, TAŞINDI.** İkinci bir `_para` kopyası bekçi
değil **eşdeğer mutant yatağı** olurdu: TR ondalık takasını bir kopyada bozmak
ötekini kırmızı yapmaz.

🔴 **BU DOSYADA DA MODELİN YAZDIĞI HİÇBİR BAYT OKUNMAZ.** `presenters.py`nin
erişim kısıtı üç parçanın ÜÇÜNE birden uygulanır
(`test_aichat2_bloklar.py::test_presenters_MODEL_METNINE_hicbir_yerden_ULASMAZ`).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any, Final

from app.modules.ai.blocks import (
    AksiyonBloku,
    BaglantiKalemi,
    BlokTonu,
    KaynakBloku,
    VarlikKalemi,
    VarlikListesiBloku,
    YapisalBlok,
)
from app.modules.ai.navigation import EkranAnahtari
from app.modules.ai.tools import schemas

#: `metrik_metni`nin üretebileceği **sabit** cümleler. Bunlardan biri gelirse
#: değer bir sayı DEĞİLDİR ve kart o şekilde çizilir.
_YER_TUTUCU_ONEKLERI: Final[tuple[str, ...]] = (
    schemas.IZIN_YOK,
    schemas.DEGER_YOK,
    schemas.MODUL_BEKLIYOR.split("{", 1)[0],
)


def _yer_tutucu_mu(metin: str) -> bool:
    return any(metin.startswith(on) for on in _YER_TUTUCU_ONEKLERI)


def _para(deger: Any) -> str | None:
    """`Decimal`/dize → `₺1.234.567,89`. 🔴 Çözülemezse `None` — 0 YAZILMAZ."""
    if deger is None:
        return None
    try:
        sayi = Decimal(str(deger))
    except (InvalidOperation, ValueError):
        return None
    tam = f"{sayi:,.2f}"
    # `,` binlik → `.`, `.` ondalık → `,` (TR). İki adımda takas.
    return "₺" + tam.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def _yuzde(deger: Any) -> float | None:
    if deger is None:
        return None
    try:
        return max(0.0, min(100.0, float(Decimal(str(deger)))))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _ilerleme_tonu(yuzde: float | None) -> BlokTonu:
    if yuzde is None:
        return BlokTonu.notr
    if yuzde >= 75:
        return BlokTonu.olumlu
    if yuzde >= 35:
        return BlokTonu.bilgi
    return BlokTonu.uyari


def _sayi(deger: Any) -> str:
    return "—" if deger is None else str(deger)


def _kaynak_ve_aksiyon(
    etiket: str, ekran: EkranAnahtari, ac_etiketi: str
) -> tuple[YapisalBlok, ...]:
    return (
        KaynakBloku((BaglantiKalemi(etiket=etiket, ekran=ekran),)),
        AksiyonBloku((BaglantiKalemi(etiket=ac_etiketi, ekran=ekran, birincil=True),)),
    )


def _varlik_listesi(
    veri: Any,
    baslik: str,
    ad_anahtari: str,
    alt_yapici: Callable[[Mapping], str | None],
    ekran: EkranAnahtari | None,
    *,
    ton: BlokTonu = BlokTonu.notr,
) -> tuple[YapisalBlok, ...]:
    """Liste zarflarının ortak gövdesi — TEK kopya (ikinci kopya = eşdeğer mutant)."""
    if not isinstance(veri, Sequence) or isinstance(veri, str | bytes):
        return ()

    def _kalem(k: Mapping) -> VarlikKalemi:
        ad = str(k.get(ad_anahtari) or "")
        bag = None if ekran is None else BaglantiKalemi(ad, ekran, kimlik=k.get("id"))
        return VarlikKalemi(ad=ad, alt_metin=alt_yapici(k), ton=ton, baglanti=bag)

    kalemler = [_kalem(k) for k in veri if isinstance(k, Mapping)]
    if not kalemler:
        return ()
    return (VarlikListesiBloku(baslik=baslik, kalemler=tuple(kalemler)),)
