"""AI-2b + AI-2d — on altı aracın yapısal blok eşleyicisi.

`presenters.py`nin ikinci parçası (**800 satır tavanı bölmesi**). Ortak
yardımcılar `presenters_base.py`dedir; ikinci kopya YAZILMADI.

🔴 **MODELİN YAZDIĞI HİÇBİR BAYT OKUNMAZ** — kısıt bu dosyaya da uygulanır ve
bekçisi `test_aichat2_bloklar.py::test_presenters_MODEL_METNINE_hicbir_yerden_
ULASMAZ`tır (tarama kümesi üç parçayı da kapsar).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.modules.ai.blocks import (
    BlokTonu,
    MetrikBloku,
    UyariBloku,
    VarlikKalemi,
    VarlikListesiBloku,
    YapisalBlok,
)
from app.modules.ai.navigation import EkranAnahtari
from app.modules.ai.presenters_base import (
    _ilerleme_tonu,
    _kaynak_ve_aksiyon,
    _para,
    _sayi,
    _varlik_listesi,
    _yer_tutucu_mu,
    _yuzde,
)

# --------------------------------------------------------------------------- #
# AI-2b + AI-2d — on altı aracın eşleyicisi. Üç ortak kural:
#   * zarf şekli beklenmedikse boş demet (uydurma kart YOK);
#   * bilinmeyen sayı `"—"`, **0 DEĞİL** — 0 bir ÖLÇÜMDÜR;
#   * bağlantı yalnız `EkranAnahtari`ndan; karşılığı olmayan araç
#     (`sozlesmeler`, `taseronlar`) bağlantı BASMAZ.
# --------------------------------------------------------------------------- #


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
