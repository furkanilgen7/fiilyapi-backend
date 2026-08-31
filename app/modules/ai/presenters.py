"""Araç sonucu → yapısal blok eşleyicileri (AI-CHAT-2 / K1).

🔴 **BU DOSYADA MODELİN YAZDIĞI HİÇBİR BAYT OKUNMAZ.** Her eşleyici yalnız
`AracSonucu`nun **yapısal** gövdesini alır — yani `tools/schemas.py`teki
pydantic modelinin `model_dump(mode="json")` çıktısını. Hangi eşleyicinin
koşacağı **çağrılan aracın adına** bağlıdır; model bir bloğun varlığını da
içeriğini de etkileyemez.

## Neden `Ok`/`Truncated` dışında blok YOK

`Restricted` zarfında `data` alanı **yoktur** (yapısal kilit, `result.py`).
`Empty`/`ScopedEmpty`/`NotFound`/`ToolError` gövdesizdir. Bu hâllerde blok
üretmek, olmayan veriden kart çizmek olurdu — mockup'ın metrik kartı boş
basılmaz, **hiç basılmaz** ve kullanıcı zarf cümlesini `AiToolTrace`te okur.

## `Truncated` bir UYARI BLOĞU doğurur (B19'un görsel hâli)

Kırpılmış bir kümeden çizilen bir kart, kullanıcıya "tablo bu" der. B19 modele
bunu yasaklıyordu; burada aynı yasak **ekrana** taşınır.

## `MetricPlaceholder` üç hâli DÜZLEŞTİRİLMEZ (S25/B18)

`gosterge_ozeti` alanları zaten üç sabit cümleden birine çevrilmiş **metinlerdir**
(`schemas.metrik_metni`). Eşleyici bu cümleleri tanır ve o kartı bir **sayı** gibi
değil, `notr` tonda bir **durum** olarak çizer. Aksi hâlde "Bu değeri görme
yetkiniz yok." cümlesi mavi büyük punto bir metrik gibi görünürdü.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any, Final

from app.modules.ai import guards
from app.modules.ai.blocks import (
    AksiyonBloku,
    BaglantiKalemi,
    BlokTonu,
    KaynakBloku,
    MetrikBloku,
    UyariBloku,
    VarlikKalemi,
    VarlikListesiBloku,
    YapisalBlok,
)
from app.modules.ai.navigation import EkranAnahtari
from app.modules.ai.result import AracSonucu, Ok, Truncated
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


# --------------------------------------------------------------------------- #
# Araç başına eşleyiciler
# --------------------------------------------------------------------------- #


def _projeleri_listele(veri: Any) -> tuple[YapisalBlok, ...]:
    if not isinstance(veri, Sequence) or isinstance(veri, str | bytes):
        return ()
    kalemler = []
    for p in veri:
        if not isinstance(p, Mapping):
            continue
        yuzde = _yuzde(p.get("progress_pct"))
        kalemler.append(
            VarlikKalemi(
                ad=str(p.get("name", "")),
                alt_metin=f"{p.get('code', '')} · {p.get('status', '')}",
                doluluk_yuzde=yuzde,
                ton=_ilerleme_tonu(yuzde),
                rozet_metni=None if yuzde is None else f"%{yuzde:.0f}".replace(".", ","),
                baglanti=BaglantiKalemi(
                    etiket=str(p.get("name", "")),
                    ekran=EkranAnahtari.projeler,
                    kimlik=p.get("id"),
                ),
            )
        )
    if not kalemler:
        return ()
    return (
        VarlikListesiBloku(baslik="Görünür projeleriniz", kalemler=tuple(kalemler)),
        KaynakBloku((BaglantiKalemi(etiket="Projeler", ekran=EkranAnahtari.projeler),)),
        AksiyonBloku(
            (BaglantiKalemi(etiket="Projeleri Aç", ekran=EkranAnahtari.projeler, birincil=True),)
        ),
    )


def _onay_kutum(veri: Any) -> tuple[YapisalBlok, ...]:
    if not isinstance(veri, Mapping):
        return ()
    items = veri.get("items") or []
    toplam = veri.get("total")
    bloklar: list[YapisalBlok] = [
        MetrikBloku(
            baslik="Onayınızda bekleyen",
            deger_metni=f"{toplam} belge" if isinstance(toplam, int) else "—",
            ton=BlokTonu.bilgi if toplam else BlokTonu.notr,
            # 🔴 Boş küme "yetki reddi DEĞİLDİR" (catalog.py birebir). Cümle o
            # farkı taşır; renk taşımaz.
            alt_metin=(
                "Size düşen imza yok — bu yetki reddi değildir."
                if not items
                else f"{len(items)} kalem listelendi"
            ),
        )
    ]
    kalemler = [
        VarlikKalemi(
            ad=str(k.get("title") or k.get("document_type") or "Belge"),
            alt_metin=" · ".join(
                p
                for p in (
                    k.get("subtitle"),
                    k.get("created_by_name"),
                    _para(k.get("gross_amount")),
                )
                if p
            )
            or None,
            ton=BlokTonu.uyari,
            rozet_metni=f"Adım {k['current_step_no']}" if k.get("current_step_no") else None,
            baglanti=BaglantiKalemi(etiket="Onay Kutusu", ekran=EkranAnahtari.onay_kutusu),
        )
        for k in items
        if isinstance(k, Mapping)
    ]
    if kalemler:
        bloklar.append(VarlikListesiBloku(kalemler=tuple(kalemler)))
    bloklar.append(
        KaynakBloku((BaglantiKalemi(etiket="Onay Kutusu", ekran=EkranAnahtari.onay_kutusu),))
    )
    bloklar.append(
        AksiyonBloku(
            (
                BaglantiKalemi(
                    etiket="Onay Kutusunu Aç", ekran=EkranAnahtari.onay_kutusu, birincil=True
                ),
            )
        )
    )
    return tuple(bloklar)


def _puantaj_haftasi(veri: Any) -> tuple[YapisalBlok, ...]:
    if not isinstance(veri, Mapping):
        return ()
    return (
        MetrikBloku(
            baslik="Aktif işçi",
            deger_metni=str(veri.get("worker_count", "—")),
            ton=BlokTonu.bilgi,
            alt_metin=str(veri.get("site_name") or "") or None,
        ),
        MetrikBloku(
            baslik="Dönem",
            deger_metni=f"{veri.get('iso_year')}-H{veri.get('iso_week')}",
            ton=BlokTonu.notr,
            alt_metin=f"{veri.get('start_date')} – {veri.get('end_date')}",
        ),
        KaynakBloku((BaglantiKalemi(etiket="Puantaj", ekran=EkranAnahtari.puantaj),)),
        AksiyonBloku(
            (BaglantiKalemi(etiket="Puantajı Aç", ekran=EkranAnahtari.puantaj, birincil=True),)
        ),
    )


def _gosterge_ozeti(veri: Any) -> tuple[YapisalBlok, ...]:
    if not isinstance(veri, Mapping):
        return ()

    def metrik(baslik: str, anahtar: str, ton: BlokTonu) -> MetrikBloku:
        ham = str(veri.get(anahtar) or "")
        # 🔴 ÜÇ HÂL DÜZLEŞTİRİLMEZ: yer tutucu cümlesi bir SAYI gibi çizilmez.
        yer_tutucu = _yer_tutucu_mu(ham)
        return MetrikBloku(
            baslik=baslik,
            deger_metni="—" if yer_tutucu else ham,
            ton=BlokTonu.notr if yer_tutucu else ton,
            alt_metin=ham if yer_tutucu else None,
        )

    return (
        metrik("Portföy", "portfoy", BlokTonu.bilgi),
        metrik("Alacaklar", "alacaklar", BlokTonu.uyari),
        metrik("Ortalama Marj", "ortalama_marj", BlokTonu.olumlu),
        MetrikBloku(
            baslik="Aktif proje",
            deger_metni=str(veri.get("active_project_count", "—")),
            ton=BlokTonu.bilgi,
            # 🔴 İki sayı BİRBİRİNDEN TÜRETİLMEZ (catalog.py). Kart ikisini
            # ayrı ayrı söyler; farkı "hata" gibi göstermez.
            alt_metin=f"görünür proje: {veri.get('gorunur_proje_sayisi', '—')}",
        ),
        UyariBloku(metin=str(veri.get("risk_notu") or ""), ton=BlokTonu.uyari),
        KaynakBloku(
            (BaglantiKalemi(etiket="Gösterge Paneli", ekran=EkranAnahtari.gosterge_paneli),)
        ),
        AksiyonBloku(
            (
                BaglantiKalemi(
                    etiket="Paneli Aç", ekran=EkranAnahtari.gosterge_paneli, birincil=True
                ),
            )
        ),
    )


def _navigate_to(veri: Any) -> tuple[YapisalBlok, ...]:
    """🔴 Derin bağlantının **tek** meşru üreticisi. URL yok, anahtar var."""
    if not isinstance(veri, Mapping):
        return ()
    try:
        ekran = EkranAnahtari(veri["ekran"])
    except (KeyError, ValueError):
        return ()
    return (
        AksiyonBloku(
            (
                BaglantiKalemi(
                    etiket=f"{veri.get('ekran_adi') or ekran.value} ekranını aç",
                    ekran=ekran,
                    birincil=True,
                ),
            )
        ),
    )


#: 🔴 ARAÇ ADINDAN eşleyiciye — modelin metninden DEĞİL. Adı burada olmayan bir
#: araç blok üretmez (`yetkilerim` bilerek yok: meta cevap, kart değil).
SUNUCULAR: Final[dict[str, Callable[[Any], tuple[YapisalBlok, ...]]]] = {
    "projeleri_listele": _projeleri_listele,
    "onay_kutum": _onay_kutum,
    "puantaj_haftasi": _puantaj_haftasi,
    "gosterge_ozeti": _gosterge_ozeti,
    "navigate_to": _navigate_to,
}


def bloklari_uret(arac_adi: str, sonuc: AracSonucu) -> tuple[YapisalBlok, ...]:
    """Zarftan blokları üretir. 🔴 `Ok`/`Truncated` dışında **her zaman boş**."""
    if isinstance(sonuc, Truncated):
        # B19'un görsel hâli: kırpılmış kümeden çizilen kart "tablo bu" der.
        uyari = UyariBloku(
            metin=guards.KIRPILDI.format(toplam=sonuc.total, donen=sonuc.returned),
            ton=BlokTonu.kritik,
        )
        return (uyari, *SUNUCULAR.get(arac_adi, lambda _: ())(sonuc.data))
    if isinstance(sonuc, Ok):
        return SUNUCULAR.get(arac_adi, lambda _: ())(sonuc.data)
    return ()
