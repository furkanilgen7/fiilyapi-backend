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


# --------------------------------------------------------------------------- #
# AI-2b + AI-2d — on altı aracın eşleyicisi. Üç ortak kural:
#   * zarf şekli beklenmedikse boş demet (uydurma kart YOK);
#   * bilinmeyen sayı `"—"`, **0 DEĞİL** — 0 bir ÖLÇÜMDÜR;
#   * bağlantı yalnız `EkranAnahtari`ndan; karşılığı olmayan araç
#     (`sozlesmeler`, `taseronlar`) bağlantı BASMAZ.
# --------------------------------------------------------------------------- #


def _sayi(deger: Any) -> str:
    return "—" if deger is None else str(deger)


def _kaynak_ve_aksiyon(
    etiket: str, ekran: EkranAnahtari, ac_etiketi: str
) -> tuple[YapisalBlok, ...]:
    return (
        KaynakBloku((BaglantiKalemi(etiket=etiket, ekran=ekran),)),
        AksiyonBloku((BaglantiKalemi(etiket=ac_etiketi, ekran=ekran, birincil=True),)),
    )


def _proje_detayi(veri: Any) -> tuple[YapisalBlok, ...]:
    if not isinstance(veri, Mapping):
        return ()
    yuzde = _yuzde(veri.get("progress_pct"))
    return (
        MetrikBloku(
            baslik=str(veri.get("name") or "Proje"),
            deger_metni=_para(veri.get("contract_amount")) or "—",
            ton=BlokTonu.bilgi,
            alt_metin=f"{veri.get('code', '')} · {veri.get('status', '')}",
        ),
        MetrikBloku(
            baslik="Bütçe",
            deger_metni=_para(veri.get("budget")) or "—",
            ton=BlokTonu.notr,
            alt_metin=f"{veri.get('site_count', '—')} şantiye",
        ),
        MetrikBloku(
            baslik="Mali ilerleme",
            deger_metni="—" if yuzde is None else f"%{yuzde:.0f}".replace(".", ","),
            ton=_ilerleme_tonu(yuzde),
            # 🔴 İki ilerleme AYRI kavramdır; kart hangisini bastığını SÖYLER.
            alt_metin="Fiziksel ilerleme DEĞİL",
        ),
        *_kaynak_ve_aksiyon("Projeler", EkranAnahtari.projeler, "Projeyi Aç"),
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


def _santiyeleri_listele(veri: Any) -> tuple[YapisalBlok, ...]:
    bloklar = _varlik_listesi(
        veri,
        "Görünür şantiyeleriniz",
        "name",
        lambda s: f"{s.get('code', '')} · {s.get('project_name', '')}",
        EkranAnahtari.santiyeler,
        ton=BlokTonu.bilgi,
    )
    if not bloklar:
        return ()
    return (*bloklar, *_kaynak_ve_aksiyon("Şantiyeler", EkranAnahtari.santiyeler, "Şantiyeleri Aç"))


def _santiye_detayi(veri: Any) -> tuple[YapisalBlok, ...]:
    if not isinstance(veri, Mapping):
        return ()
    kalan = veri.get("remaining_days")
    return (
        MetrikBloku(
            baslik=str(veri.get("name") or "Şantiye"),
            deger_metni=str(veri.get("status") or "—"),
            ton=BlokTonu.bilgi,
            alt_metin=f"{veri.get('code', '')} · {veri.get('project_name', '')}",
        ),
        MetrikBloku(
            baslik="Kalan gün",
            deger_metni=_sayi(kalan),
            # 🔴 Negatif kalan gün GECİKMEDİR ve bastırılmaz (uç sözleşmesi).
            ton=BlokTonu.kritik if isinstance(kalan, int) and kalan < 0 else BlokTonu.notr,
            alt_metin=f"{veri.get('section_count', '—')} bölüm",
        ),
        *_kaynak_ve_aksiyon("Şantiyeler", EkranAnahtari.santiyeler, "Şantiyeyi Aç"),
    )


def _is_kalemleri(veri: Any) -> tuple[YapisalBlok, ...]:
    if not isinstance(veri, Mapping):
        return ()
    kalemler = [
        VarlikKalemi(
            ad=str(k.get("code") or ""),
            alt_metin=str(k.get("description") or "") or None,
            ton=BlokTonu.notr,
            rozet_metni=f"{k.get('quantity')} {k.get('unit')}",
        )
        for g in veri.get("gruplar") or []
        if isinstance(g, Mapping)
        for k in g.get("items") or []
        if isinstance(k, Mapping)
    ]
    yer_tutucu = _yer_tutucu_mu(str(veri.get("gerceklesen_toplam") or ""))
    bloklar: list[YapisalBlok] = [
        MetrikBloku(
            baslik="Poz cetveli toplamı",
            deger_metni=_para(veri.get("grand_total")) or "—",
            ton=BlokTonu.bilgi,
            alt_metin=f"{veri.get('kalem_sayisi', '—')} kalem",
        ),
        MetrikBloku(
            baslik="Gerçekleşen",
            # 🔴 ÜÇ HÂL DÜZLEŞTİRİLMEZ: yer tutucu cümlesi SAYI gibi çizilmez.
            deger_metni="—" if yer_tutucu else str(veri.get("gerceklesen_toplam") or "—"),
            ton=BlokTonu.notr if yer_tutucu else BlokTonu.olumlu,
            alt_metin=str(veri.get("gerceklesen_toplam")) if yer_tutucu else None,
        ),
    ]
    if kalemler:
        bloklar.append(VarlikListesiBloku(baslik="İş kalemleri", kalemler=tuple(kalemler)))
    bloklar.extend(_kaynak_ve_aksiyon("Şantiyeler", EkranAnahtari.santiyeler, "Şantiyeyi Aç"))
    return tuple(bloklar)


def _arsa_payi(veri: Any) -> tuple[YapisalBlok, ...]:
    if not isinstance(veri, Mapping):
        return ()
    hissedarlar = [
        VarlikKalemi(
            ad=str(h.get("name") or ""),
            alt_metin=f"%{h.get('share_pct')} · {h.get('unit_count')} ünite",
            ton=BlokTonu.notr,
        )
        for h in veri.get("hissedarlar") or []
        if isinstance(h, Mapping)
    ]
    bloklar: list[YapisalBlok] = [
        MetrikBloku(
            baslik="Bizim pay",
            deger_metni=f"%{veri.get('our_share_pct')}",
            ton=BlokTonu.olumlu,
            alt_metin=(
                f"{veri.get('bizim_unite', '—')} ünite · {_para(veri.get('bizim_deger')) or '—'}"
            ),
        ),
        MetrikBloku(
            baslik="Arsa sahibi payı",
            deger_metni=f"%{veri.get('owner_share_pct')}",
            ton=BlokTonu.bilgi,
            alt_metin=f"{veri.get('arsa_sahibi_unite', '—')} ünite",
        ),
        # 🔴 İKİ DENGE AYRI BLOKTUR (K2): tek karta indirmek "dengede" ile
        # "adette dengede ama değerde sapmış"ı aynı şey gösterirdi.
        UyariBloku(metin=str(veri.get("adet_dengesi_notu") or ""), ton=BlokTonu.uyari),
        UyariBloku(metin=str(veri.get("deger_dengesi_notu") or ""), ton=BlokTonu.uyari),
    ]
    if hissedarlar:
        bloklar.append(VarlikListesiBloku(baslik="Hissedarlar", kalemler=tuple(hissedarlar)))
    bloklar.extend(_kaynak_ve_aksiyon("Projeler", EkranAnahtari.projeler, "Projeyi Aç"))
    return tuple(bloklar)


def _hakedis_alt_metni(k: Mapping) -> str:
    donem = f"{k.get('period_year')}/{k.get('period_month')}" if k.get("period_year") else None
    parcalar = (
        k.get("subcontractor_name"),
        k.get("project_name"),
        donem,
        _para(k.get("gross_total")),
        k.get("status"),
    )
    return " · ".join(str(p) for p in parcalar if p)


def _isveren_hakedisleri(veri: Any) -> tuple[YapisalBlok, ...]:
    bloklar = _varlik_listesi(
        veri,
        "İşveren hakedişleri",
        "project_name",
        _hakedis_alt_metni,
        EkranAnahtari.hakedisler,
        ton=BlokTonu.bilgi,
    )
    if not bloklar:
        return ()
    return (*bloklar, *_kaynak_ve_aksiyon("Hakedişler", EkranAnahtari.hakedisler, "Hakedişleri Aç"))


def _taseron_hakedisleri(veri: Any) -> tuple[YapisalBlok, ...]:
    bloklar = _varlik_listesi(
        veri,
        "Taşeron hakedişleri",
        "subcontractor_name",
        _hakedis_alt_metni,
        EkranAnahtari.taseron_hakedisleri,
        ton=BlokTonu.bilgi,
    )
    if not bloklar:
        return ()
    return (
        *bloklar,
        *_kaynak_ve_aksiyon(
            "Taşeron Hakedişleri", EkranAnahtari.taseron_hakedisleri, "Taşeron Hakedişlerini Aç"
        ),
    )


def _sozlesmeler(veri: Any) -> tuple[YapisalBlok, ...]:
    """🔴 BAĞLANTI BASMAZ: `EkranAnahtari`nde sözleşme ekranı YOKTUR; uydurma
    bir anahtar kullanıcıyı yanlış listeye götürürdü."""
    if not isinstance(veri, Mapping):
        return ()
    kalemler = [
        VarlikKalemi(
            ad=str(k.get("title") or ""),
            alt_metin=" · ".join(
                str(p)
                for p in (k.get("counterparty_name"), _para(k.get("amount")), k.get("status"))
                if p
            )
            or None,
            ton=BlokTonu.notr,
        )
        for k in veri.get("items") or []
        if isinstance(k, Mapping)
    ]
    bloklar: list[YapisalBlok] = [
        MetrikBloku(
            baslik="Sözleşme tutarı",
            deger_metni=_para(veri.get("total_amount")) or "—",
            ton=BlokTonu.bilgi,
            alt_metin=(
                f"{veri.get('active_count', '—')} aktif · "
                f"{veri.get('total', '—')} kayıt ({veri.get('contract_type', '')})"
            ),
        )
    ]
    süresi_dolan = veri.get("expiring_this_month_count")
    if isinstance(süresi_dolan, int) and süresi_dolan > 0:
        bloklar.append(
            UyariBloku(
                metin=f"Bu ay süresi dolan {süresi_dolan} sözleşme var.",
                ton=BlokTonu.uyari,
            )
        )
    if kalemler:
        bloklar.append(VarlikListesiBloku(kalemler=tuple(kalemler)))
    return tuple(bloklar)


def _taseronlar(veri: Any) -> tuple[YapisalBlok, ...]:
    """🔴 BAĞLANTI BASMAZ: taşeron kartoteksi ekranı `EkranAnahtari`nde yok."""
    return _varlik_listesi(
        veri,
        "Taşeron kartoteksi",
        "name",
        lambda t: (
            " · ".join(
                str(p)
                for p in (
                    t.get("category"),
                    t.get("contact_person"),
                    None if t.get("is_active") else "pasif",
                )
                if p
            )
            or None
        ),
        None,
    )


def _puantaj(veri: Any) -> tuple[YapisalBlok, ...]:
    if not isinstance(veri, Mapping):
        return ()
    return (
        MetrikBloku(
            baslik="Aktif işçi",
            deger_metni=_sayi(veri.get("worker_count")),
            ton=BlokTonu.bilgi,
            alt_metin=str(veri.get("site_name") or "") or None,
        ),
        MetrikBloku(
            baslik="Toplam saat",
            deger_metni=_sayi(veri.get("total_hours")),
            ton=BlokTonu.notr,
            # 🔴 Adam-gün SAATTEN türer (÷9), gün SAYMAZ; kart bunu söyler.
            alt_metin=f"{veri.get('total_man_days', '—')} adam-gün (saatten türer)",
        ),
        MetrikBloku(
            baslik="Dönem",
            deger_metni=f"{veri.get('year')}/{veri.get('month')}",
            ton=BlokTonu.notr,
            alt_metin=str(veri.get("section_name") or "Tüm bölümler"),
        ),
        *_kaynak_ve_aksiyon("Puantaj", EkranAnahtari.puantaj, "Puantajı Aç"),
    )


def _gunluk_kayit(veri: Any) -> tuple[YapisalBlok, ...]:
    bloklar = _varlik_listesi(
        veri,
        "Son günlük kayıtlar",
        "entry_date",
        lambda k: " · ".join(
            str(p)
            for p in (
                k.get("status"),
                f"{k.get('worker_total')} işçi",
                "OLAY VAR" if k.get("has_incident") else None,
            )
            if p
        ),
        EkranAnahtari.santiye_gunlugu,
        ton=BlokTonu.notr,
    )
    if not bloklar:
        return ()
    return (
        *bloklar,
        *_kaynak_ve_aksiyon("Şantiye Günlüğü", EkranAnahtari.santiye_gunlugu, "Günlüğü Aç"),
    )


def _gun_plani(veri: Any) -> tuple[YapisalBlok, ...]:
    if not isinstance(veri, Mapping):
        return ()
    kalemler = [
        VarlikKalemi(
            ad=str(g.get("plan_date") or ""),
            # 🔴 "Plan girilmemiş" ile "iş yok" AYRI cümledir.
            alt_metin=(str(g.get("text") or "") if g.get("has_plan") else "Plan girilmemiş"),
            ton=BlokTonu.bilgi if g.get("has_plan") else BlokTonu.notr,
            rozet_metni=f"{g.get('planned_worker_total')} işçi" if g.get("has_plan") else None,
        )
        for g in veri.get("days") or []
        if isinstance(g, Mapping)
    ]
    if not kalemler:
        return ()
    return (
        VarlikListesiBloku(
            baslik=f"{veri.get('site_name', '')} — gün planı", kalemler=tuple(kalemler)
        ),
        *_kaynak_ve_aksiyon("Şantiye Günlüğü", EkranAnahtari.santiye_gunlugu, "Günlüğü Aç"),
    )


def _makine_listesi(veri: Any) -> tuple[YapisalBlok, ...]:
    bloklar = _varlik_listesi(
        veri,
        "Makine ve ekipman",
        "name",
        lambda m: " · ".join(
            str(p)
            for p in (
                m.get("category"),
                m.get("plate_no"),
                m.get("status"),
                # 🔴 Depodaki makine hiçbir projeye bağlı DEĞİLDİR; kart bunu
                # yazar, yoksa kullanıcı onu kendi projesinin makinesi sanar.
                None if m.get("site_id") else "DEPODA",
            )
            if p
        ),
        EkranAnahtari.makineler,
        ton=BlokTonu.notr,
    )
    if not bloklar:
        return ()
    return (
        *bloklar,
        *_kaynak_ve_aksiyon("Makine & Ekipman", EkranAnahtari.makineler, "Makineleri Aç"),
    )


def _makine_calisma(veri: Any) -> tuple[YapisalBlok, ...]:
    if not isinstance(veri, Mapping):
        return ()
    return (
        MetrikBloku(
            baslik="Çalışma saati",
            deger_metni=_sayi(veri.get("total_hours")),
            ton=BlokTonu.bilgi,
            alt_metin=f"{veri.get('year')}/{veri.get('month')}",
        ),
        MetrikBloku(
            baslik="Arıza saati",
            deger_metni=_sayi(veri.get("total_breakdown_hours")),
            ton=BlokTonu.uyari,
        ),
        MetrikBloku(
            baslik="Maliyet",
            deger_metni=_para(veri.get("total_cost")) or "—",
            ton=BlokTonu.notr,
        ),
        # 🔴 Bedeli bilinmeyen makine toplama girmedi; bu bir UYARIDIR, dipnot değil.
        UyariBloku(metin=str(veri.get("bilinmeyen_bedel_notu") or ""), ton=BlokTonu.uyari),
        *_kaynak_ve_aksiyon("Makine & Ekipman", EkranAnahtari.makineler, "Makineleri Aç"),
    )


def _makine_yakit(veri: Any) -> tuple[YapisalBlok, ...]:
    if not isinstance(veri, Mapping):
        return ()
    anormal = veri.get("abnormal_count")
    bloklar: list[YapisalBlok] = [
        MetrikBloku(
            baslik="Yakıt",
            deger_metni=f"{_sayi(veri.get('total_liters'))} lt",
            ton=BlokTonu.bilgi,
            alt_metin=f"{veri.get('year')}/{veri.get('month')}",
        ),
        MetrikBloku(
            baslik="Tutar",
            deger_metni=_para(veri.get("total_amount")) or "—",
            ton=BlokTonu.notr,
        ),
        MetrikBloku(
            baslik="Ortalama lt/saat",
            # 🔴 `None` = o dönemde ÇALIŞMA KAYDI yok. "0" yazmak "hiç yakıt
            # harcamadı" demek olurdu ve YALANDIR.
            deger_metni=_sayi(veri.get("lt_per_hour_avg")),
            ton=BlokTonu.notr,
            alt_metin=(
                None
                if veri.get("lt_per_hour_avg") is not None
                else "Çalışma kaydı yok — sıfır tüketim DEĞİL"
            ),
        ),
    ]
    if isinstance(anormal, int) and anormal > 0:
        bloklar.append(
            UyariBloku(metin=f"{anormal} makinede anormal tüketim var.", ton=BlokTonu.kritik)
        )
    bloklar.extend(_kaynak_ve_aksiyon("Makine & Ekipman", EkranAnahtari.makineler, "Makineleri Aç"))
    return tuple(bloklar)


def _makine_kira(veri: Any) -> tuple[YapisalBlok, ...]:
    bloklar = _varlik_listesi(
        veri,
        "Kira hakedişleri",
        "supplier_name",
        lambda f: " · ".join(
            str(p)
            for p in (
                f.get("invoice_no"),
                f"{f.get('period_year')}/{f.get('period_month')}",
                f.get("site_name") or "Tüm Projeler",
                _para(f.get("payable_total")),
                f.get("status"),
            )
            if p
        ),
        EkranAnahtari.makineler,
        ton=BlokTonu.notr,
    )
    if not bloklar:
        return ()
    return (
        *bloklar,
        *_kaynak_ve_aksiyon("Makine & Ekipman", EkranAnahtari.makineler, "Makineleri Aç"),
    )


#: 🔴 SUNUCUSU BİLEREK OLMAYAN araçlar — `UNGATED_ALLOWLIST` emsali.
#: "Sunucusu yok" ile "yazmayı unuttum" farklı iki şeydir ve ikincisi
#: SESSİZDİR: `bloklari_uret` bilinmeyen ad için `.get(…, lambda _: ())` döner
#: → araç eklenir, panelde **sıfır blok** çizilir, hiçbir test kırmızı olmaz.
#: Kümesi `CATALOG` ile bekçilidir (`test_ai2bd_araclar.py::test_SUN_*`).
SUNUCUSUZ_ARACLAR: Final[frozenset[str]] = frozenset(
    {
        #: Meta cevap, kart değil: "hangi modülleri görebiliyorum" sorusunun
        #: cevabı bir metrik kartı olarak çizilirse yetki haritası bir ÖLÇÜM
        #: gibi görünürdü.
        "yetkilerim",
    }
)

#: 🔴 ARAÇ ADINDAN eşleyiciye — modelin metninden DEĞİL. Adı burada olmayan bir
#: araç blok üretmez.
SUNUCULAR: Final[dict[str, Callable[[Any], tuple[YapisalBlok, ...]]]] = {
    "projeleri_listele": _projeleri_listele,
    "onay_kutum": _onay_kutum,
    "puantaj_haftasi": _puantaj_haftasi,
    "gosterge_ozeti": _gosterge_ozeti,
    "navigate_to": _navigate_to,
    # --- AI-2b + AI-2d ---------------------------------------------------- #
    "proje_detayi": _proje_detayi,
    "santiyeleri_listele": _santiyeleri_listele,
    "santiye_detayi": _santiye_detayi,
    "is_kalemleri": _is_kalemleri,
    "arsa_payi": _arsa_payi,
    "isveren_hakedisleri": _isveren_hakedisleri,
    "taseron_hakedisleri": _taseron_hakedisleri,
    "sozlesmeler": _sozlesmeler,
    "taseronlar": _taseronlar,
    "puantaj": _puantaj,
    "gunluk_kayit": _gunluk_kayit,
    "gun_plani": _gun_plani,
    "makine_listesi": _makine_listesi,
    "makine_calisma": _makine_calisma,
    "makine_yakit": _makine_yakit,
    "makine_kira": _makine_kira,
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
