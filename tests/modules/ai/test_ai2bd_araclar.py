"""AI-2b + AI-2d — on altı okuma aracının bekçileri.

Bu dosya üç işi yapar ve üçü de **koddan ölçer**, emirden değil:

1. **KVKK matrisi** — her aracın yanıt modelini `exposure.sema_anahtarlari` ile
   geçirip yasak/kişi-adı kesişimini ölçer, ve **ham** üst kaynak şemasının
   ne dediğini de ölçer. Daraltmanın gerçekten gerekli olduğu (ya da
   gerekmediği) böyle kayda geçer; grep'le değil.
2. **Beyanların kaynak zinciri** — `SIRKET_GENELI` diyen her araç için OR dalı
   (ya da süzgecin yokluğu) hâlâ kodda mı.
3. **İki SESSİZ delik** — `presenters.SUNUCULAR` ve `navigation.EKRAN_ADLARI`.
   İkisinin de bekçisi bugüne kadar YOKTU; ikisi de eksik girdide **kırmızı
   üretmeden** yanlış davranıyordu (biri boş panel, öteki çalışma anı 500).
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest
from fastapi.routing import APIRoute

from app.main import app
from app.modules.ai import exposure, presenters
from app.modules.ai.navigation import EKRAN_ADLARI, EkranAnahtari
from app.modules.ai.registry import ToolKumesi, ToolSpec
from app.modules.ai.tools.catalog import AI2BD_TOOLS, CATALOG


def _api_rotalari(rotalar) -> list[APIRoute]:
    cikti: list[APIRoute] = []
    for rota in rotalar:
        if isinstance(rota, APIRoute):
            cikti.append(rota)
        elif type(rota).__name__ == "_IncludedRouter":
            cikti.extend(_api_rotalari(rota.original_router.routes))
        elif hasattr(rota, "routes"):
            cikti.extend(_api_rotalari(rota.routes))
    return cikti


def _get_rotalari() -> dict[str, APIRoute]:
    return {r.path: r for r in _api_rotalari(app.routes) if "GET" in (r.methods or set())}


# ############################################################################ #
# ① KVKK MATRİSİ — işlevsel ölçüm, grep DEĞİL
# ############################################################################ #


#: Aracın sardığı ucun **HAM** yanıt modeli — daraltmanın gerekli olup
#: olmadığını ölçmek için. 🔴 Elle yazılmış değil, rota tablosundan çıkarılır.
def _ham_yanit_modeli(spec: ToolSpec):
    return _get_rotalari()[spec.ucler[0]].response_model


@pytest.mark.parametrize("spec", AI2BD_TOOLS, ids=lambda s: s.ad)
def test_ARAC_yanit_semasi_YASAK_ANAHTAR_TASIMAZ(spec: ToolSpec) -> None:
    """Kayıt anındaki kapının (adım 4) araç araç yeniden ölçümü.

    `dogrula_spec` zaten `ToolRegistry.__init__` içinde koşuyor ve ihlalde
    uygulama açılmıyor; bu test onun **yerine geçmez**, ihlali ARAÇ ADIYLA
    raporlar (toplu bir `IfsaIhlali` hangi araç olduğunu söylemez).
    """
    anahtarlar = exposure.sema_anahtarlari(spec.yanit_modeli)
    assert anahtarlar & exposure.YASAK_ALAN_ANAHTARLARI == set()


def test_HICBIR_AI2BD_ARACI_AGREGA_MODUL_BEYAN_ETMEZ() -> None:
    """🔴 SKIP DEĞİL, ADLANDIRILMIŞ BİR OLGU.

    İlk hâlim araç başına parametrize bir testti ve **on altısı da SKIP**
    oluyordu ("AGREGA beyan etmiyor"). Hep atlayan bir bekçi hiçbir şey
    ölçmez; üstelik yeşil göründüğü için ölçtüğü sanılır.

    Ölçülen gerçek olgu şudur: bu dilimdeki hiçbir araç `personnel` ya da
    `payroll` BEYAN ETMEZ, yani kayıt anındaki kişi-adı kapısı (adım 5) bu
    on altı araçta **hiç koşmaz**. Bu bir kusur değil bir karardır
    (`puantaj` kişi satırı basmaz, dolayısıyla beyan da etmez) ama kapının
    ölü olduğu değil, **uygulanmadığı** anlamına gelir — ve kapının canlı
    olduğu bir sonraki testte ayrıca kanıtlanır.
    """
    beyan_edenler = {
        s.ad
        for s in AI2BD_TOOLS
        for m in s.veri_modulleri
        if exposure.seviye(m) is exposure.IfsaSeviyesi.AGREGA
    }
    assert beyan_edenler == set(), (
        f"{sorted(beyan_edenler)} artık AGREGA modül beyan ediyor: yanıt şemaları "
        "kişi adı taşımadığından EMİN OL, kapı artık onlarda koşuyor."
    )


def test_MUTASYON_puantaj_ham_matrisle_personnel_beyan_etseydi_KAYDEDILEMEZDI() -> None:
    """🔴 Kişi-adı kapısının ÖLÜ OLMADIĞININ kanıtı.

    Yukarıdaki test "kapı koşmuyor" diyor; bu test "koşsaydı konuşurdu" diyor.
    İkisi olmadan `veri_modulleri` beyanı sessizce dekoratif olabilirdi —
    `Scope` enum'unun ölçülmüş kaderi.
    """
    import dataclasses

    from app.modules.ai.registry import ToolRegistry

    spec = next(s for s in AI2BD_TOOLS if s.ad == "puantaj")
    mutant = dataclasses.replace(
        spec,
        veri_modulleri=spec.veri_modulleri | {"personnel"},
        yanit_modeli=_ham_yanit_modeli(spec),
    )
    with pytest.raises(exposure.IfsaIhlali, match="KİŞİ ADI"):
        ToolRegistry((mutant,))


#: 🔴 ÖLÇÜLMÜŞ OLGU — emrin §3.1'i **DÖRT** araçta sert daraltma gerektiğini
#: söylüyordu; işlevsel ölçüm **ÜÇ** dedi ve farkın sebebi de ölçüldü:
#: `GET /sites` `SiteCard` DÖNDÜRMEZ, `SiteOptionListResponse` döndürür
#: (`sites/flat_list_router.py`) ve o şemada `address` YOKTUR. `SiteCard`
#: `/projects/{id}/sites` ve `/sites/{id}` uçlarındadır.
HAM_SEMASI_KAYDEDILEMEYEN = {
    "proje_detayi": {"tax_number"},
    "santiye_detayi": {"address"},
    "taseronlar": {"email", "phone", "tax_number"},
}


@pytest.mark.parametrize("spec", AI2BD_TOOLS, ids=lambda s: s.ad)
def test_HAM_SEMA_HANGI_ARACLARDA_KAYDEDILEMEZ_olduğu_OLCUMLE_kilitlidir(
    spec: ToolSpec,
) -> None:
    """🔴 Daraltmanın GEREKLİ olduğu yerler ADIYLA kilitlenir.

    İki yönlü bir iddiadır ve ikisi de anlamlıdır:

    * Listede olan araçta ham şema **gerçekten** yasak anahtar taşır → daraltma
      bir üslup tercihi değil, uygulamayı açan şart.
    * Listede OLMAYAN araçta ham şema **temizdir** → o araçlarda daraltmanın
      gerekçesi KVKK değil, satır tavanı/token'dır ve bu fark kayıtlı kalır.

    Ham şema bir gün kirlenirse (ör. `SiteOptionResponse`a `address` eklenirse)
    burası kırmızı olur ve ekleyen kişi bunu bilerek yapmak zorunda kalır.
    """
    ham = _ham_yanit_modeli(spec)
    yasak = exposure.sema_anahtarlari(ham) & exposure.YASAK_ALAN_ANAHTARLARI
    assert yasak == HAM_SEMASI_KAYDEDILEMEYEN.get(spec.ad, set()), (
        f"`{spec.ad}` ucunun HAM şeması ({ham.__name__}) beklenmedik yasak anahtar "
        f"kümesi taşıyor: {sorted(yasak)}"
    )


def test_POZITIF_KONTROL_ham_semalarin_UCU_GERCEKTEN_kaydedilemez() -> None:
    """İddia boş kümede dolaşmıyor: bu üç ham şema araç olarak KAYDEDİLEMEZ."""
    import dataclasses

    from app.modules.ai.registry import ToolRegistry

    for spec in AI2BD_TOOLS:
        if spec.ad not in HAM_SEMASI_KAYDEDILEMEYEN:
            continue
        mutant = dataclasses.replace(spec, yanit_modeli=_ham_yanit_modeli(spec))
        with pytest.raises(exposure.IfsaIhlali, match="maskelenmiş alan"):
            ToolRegistry((mutant,))


def test_PUANTAJ_ham_matris_KISI_SATIRI_tasir_arac_TASIMAZ() -> None:
    """🔴 `puantaj`ın daraltmasının gerekçesi ÖLÇÜLÜR.

    Ham `TimesheetMatrix` `full_name` taşır (`TimesheetMatrixRow`); araç
    taşımaz. Araç `personnel` BEYAN ETMEDİĞİ için kayıt anındaki kişi-adı
    kapısı bu araçta hiç koşmaz — yani daraltma **bir disiplindir**, yapısal
    bir zorunluluk değil, ve bu yüzden AYRI bir bekçi ister.
    """
    spec = next(s for s in AI2BD_TOOLS if s.ad == "puantaj")
    ham = exposure.sema_anahtarlari(_ham_yanit_modeli(spec))
    assert "full_name" in ham, "ham matris artık kişi adı taşımıyor — gerekçe yeniden ölçülmeli"
    assert "full_name" in exposure.KISI_ADI_ANAHTARLARI
    assert "full_name" not in exposure.sema_anahtarlari(spec.yanit_modeli)
    assert "rows" not in exposure.sema_anahtarlari(spec.yanit_modeli)


def test_ARSA_PAYI_secilen_ucta_buyer_name_HIC_YOK_reddedilende_VAR() -> None:
    """🔴 A1/K1'in bu şemadaki hâli — ve seçimin gerekçesi.

    `…/land-share/units` gövdesi `buyer_name` taşır ve o ad `Customer.name`tir
    (`customers` kapısı `require_permission("sales", …)`, `sales` KAPALI).
    Seçilen `…/land-share/summary` ucunda o alan **hiç yoktur**: düşürülmüş bir
    alan ile var olmayan bir alan aynı güvence DEĞİLDİR.

    `shareholder_name` ise ÖLÇÜLDÜ ve KALDI: `LandShareShareholder`
    `app/modules/projects/models.py`dedir, yani `projects` verisidir.
    """
    from app.modules.projects.land_share_schemas import (
        LandShareSummaryResponse,
        LandShareUnitListResponse,
    )

    ozet = exposure.sema_anahtarlari(LandShareSummaryResponse)
    unite = exposure.sema_anahtarlari(LandShareUnitListResponse)
    assert "buyer_name" in unite, "reddetme gerekçesi çürüdü — seçim yeniden düşünülmeli"
    assert "buyer_name" not in ozet

    spec = next(s for s in AI2BD_TOOLS if s.ad == "arsa_payi")
    assert spec.ucler == ("/projects/{project_id}/land-share/summary",)
    assert "buyer_name" not in exposure.sema_anahtarlari(spec.yanit_modeli)
    assert spec.veri_modulleri == frozenset({"projects"})

    # `shareholder_name`in kaynağı `projects`tir — `sales` DEĞİL.
    from app.modules.projects import models as projects_models

    assert hasattr(projects_models, "LandShareShareholder")


# ############################################################################ #
# ② BEYANLARIN KAYNAK ZİNCİRİ
# ############################################################################ #


#: `SIRKET_GENELI` beyan eden araç → beyanı taşıyan OR dallı süzgeç.
#: 🔴 `taseronlar` LİSTEDE YOKTUR çünkü gerekçesi FARKLIDIR (süzgecin
#: yokluğu); o ayrı bir testle ölçülür.
OR_DALLI_SUZGECLER = {
    "makine_listesi": ("app.modules.equipment.repository", "scope", "Equipment.site_id.is_(None)"),
    "makine_calisma": (
        "app.modules.equipment.repository",
        "work_log_scope",
        "EquipmentWorkLog.site_id.is_(None)",
    ),
    "makine_yakit": (
        "app.modules.equipment.repository",
        "fuel_log_scope",
        "EquipmentFuelLog.site_id.is_(None)",
    ),
    "makine_kira": (
        "app.modules.equipment.rental_repository",
        "invoice_scope",
        "EquipmentRentalInvoice.site_id.is_(None)",
    ),
}


@pytest.mark.parametrize("arac", sorted(OR_DALLI_SUZGECLER), ids=lambda a: a)
def test_SIRKET_GENELI_beyaninin_GEREKCESI_HALA_KODDA(arac: str) -> None:
    """🔴 Beyan bir ÖLÇÜME dayanır; ölçüm değişirse beyan yeniden düşünülmeli.

    `gosterge_ozeti`nin emsalinin (`test_BEYANIN_GEREKCESI_HALA_KODDA_DURUYOR`)
    dört yeni kardeşi. Biri OR dalını silerse (araç gerçekten proje kapsamlı
    olurdu) bu test kırmızı olur ve `kume` beyanı **bilinçli** olarak
    değiştirilmek zorunda kalır — sessizce yalana dönüşemez.
    """
    import importlib

    modul_adi, fonksiyon, dal = OR_DALLI_SUZGECLER[arac]
    modul = importlib.import_module(modul_adi)
    kaynak = inspect.getsource(getattr(modul, fonksiyon))
    assert dal in kaynak and "|" in kaynak, (
        f"`{modul_adi}.{fonksiyon}` artık OR'lu değil: `{arac}` gerçekten proje "
        "kapsamlı hâle gelmiş olabilir ve `kume` DEĞİŞMELİDİR."
    )
    spec = next(s for s in CATALOG if s.ad == arac)
    assert spec.kume is ToolKumesi.SIRKET_GENELI


def test_TASERONLAR_beyaninin_gerekcesi_SUZGECIN_YOKLUGUDUR() -> None:
    """🔴 Öteki beşten FARKLI bir gerekçe: burada OR dalı yok, SÜZGEÇ yok.

    Uç imzası `user` parametresi bile almaz; kapsamı hiç hesaplamaz. Bir gün
    `user` eklenir ve süzgeç kurulursa burası kırmızı olur.
    """
    from app.modules.contracts import router as contracts_router

    imza = inspect.signature(contracts_router.list_subcontractors_endpoint)
    assert "user" not in imza.parameters, (
        "`GET /subcontractors` artık aktör alıyor — kapsam süzgeci eklenmiş "
        "olabilir ve `taseronlar.kume` yeniden ölçülmelidir."
    )
    govde = inspect.getsource(contracts_router.list_subcontractors_endpoint)
    assert "visible_projects" not in govde, (
        "`GET /subcontractors` artık kapsam süzgeci kuruyor — `taseronlar.kume` "
        "yeniden ölçülmelidir."
    )
    spec = next(s for s in CATALOG if s.ad == "taseronlar")
    assert spec.kume is ToolKumesi.SIRKET_GENELI


# ############################################################################ #
# ③ ZORUNLU SORGU PARAMETRELERİ — `BosGirdi` tuzağı
# ############################################################################ #


def _zorunlu_sorgu_parametreleri(yol: str) -> set[str]:
    """Ucun **zorunlu** sorgu parametreleri — AST'den değil, rota tablosundan."""
    rota = _get_rotalari()[yol]
    return {p.alias for p in rota.dependant.query_params if p.field_info.is_required()}


#: 🔴 ÖLÇÜLDÜ. Emir "`makine_calisma` + `makine_yakit` dışında **İKİ** araç
#: daha" diyordu; ölçüm **ÜÇ** dedi (`sozlesmeler` · `puantaj` · `gun_plani`).
#: Yani zorunlu parametre isteyen araç sayısı 4 değil **BEŞ**tir.
ZORUNLU_PARAMETRELI_ARACLAR = {
    "sozlesmeler": {"type"},
    "puantaj": {"year", "month"},
    "gun_plani": {"start"},
    "makine_calisma": {"year", "month"},
    "makine_yakit": {"year", "month"},
}


@pytest.mark.parametrize("spec", AI2BD_TOOLS, ids=lambda s: s.ad)
def test_ZORUNLU_PARAMETRELI_uc_BosGirdi_ile_SARILAMAZ(spec: ToolSpec) -> None:
    """🔴 `BosGirdi` ile sarılan zorunlu-parametreli uç HER çağrıda 422 verir.

    Bekçi iki yönlüdür: zorunlu parametre varsa girdi modeli onu ALANIYLA
    taşımalı; yoksa `BosGirdi` meşrudur.
    """
    zorunlu = _zorunlu_sorgu_parametreleri(spec.ucler[0])
    assert zorunlu == ZORUNLU_PARAMETRELI_ARACLAR.get(spec.ad, set()), (
        f"`{spec.ad}` ucunun zorunlu parametre kümesi değişti: {sorted(zorunlu)}"
    )
    if not zorunlu:
        return
    alanlar = set(spec.girdi.model_fields)
    assert spec.girdi.__name__ != "BosGirdi", f"`{spec.ad}` zorunlu parametreli ama BosGirdi"
    # `contract_type` python adıdır, tel adı `type` — girdi modeli python adını
    # taşır, handler tele ALIAS ile yazar.
    beklenen = {"contract_type"} if spec.ad == "sozlesmeler" else zorunlu
    assert beklenen <= alanlar, f"`{spec.ad}` girdi modeli {sorted(beklenen - alanlar)} taşımıyor"


def test_POZITIF_KONTROL_ZORUNLU_PARAMETRESIZ_uclar_da_VAR() -> None:
    """İddia boş kümede dolaşmıyor: on bir araç gerçekten parametresizdir."""
    parametresiz = {s.ad for s in AI2BD_TOOLS if not _zorunlu_sorgu_parametreleri(s.ucler[0])}
    assert len(parametresiz) == 11, sorted(parametresiz)


# ############################################################################ #
# ④ SESSİZ DELİK 1 — `presenters.SUNUCULAR`
# ############################################################################ #


def _sunucusuz_araclar(sunucular, sunucusuz, katalog) -> set[str]:
    """Kataloğa girip sunucusu da istisnası da olmayan araçlar."""
    return {s.ad for s in katalog} - set(sunucular) - set(sunucusuz)


def test_SUN_her_arac_ya_SUNUCU_ya_ISTISNA_tasir() -> None:
    """🔴 BU BEKÇİ BUGÜNE KADAR YOKTU ve deliği ölçüldü.

    `presenters.bloklari_uret` bilinmeyen araç adı için sessizce
    `.get(…, lambda _: ())` döner ve `test_aichat2_bloklar.py:125` bunu KANON
    yazmıştır (`"uydurma_arac"` → `()`). Sonuç: on altı araç eklenip sunucu
    yazılmasaydı **AI panelinde sıfır yapısal blok** çizilir ve hiçbir test
    kırmızı olmazdı.

    İstisna listesi (`SUNUCUSUZ_ARACLAR`) `UNGATED_ALLOWLIST` emsalidir:
    "sunucusu yok" bir KARAR olmalı, bir unutma değil.
    """
    eksik = _sunucusuz_araclar(presenters.SUNUCULAR, presenters.SUNUCUSUZ_ARACLAR, CATALOG)
    assert eksik == set(), (
        f"Sunucusu ve istisnası olmayan araç(lar): {sorted(eksik)}. Bu araçlar AI "
        "panelinde SIFIR yapısal blok çizer ve bu SESSİZDİR."
    )


def test_SUN_sunucu_haritasinda_KATALOGDA_OLMAYAN_ad_YOKTUR() -> None:
    """Ters yön: ölü bir eşleyici, kaldırılmış bir aracın kartını hayatta tutar."""
    fazla = set(presenters.SUNUCULAR) - {s.ad for s in CATALOG}
    assert fazla == set(), f"katalogda olmayan sunucu(lar): {sorted(fazla)}"


def test_SUN_MUTASYON_sunucusu_silinen_arac_YAKALANIR() -> None:
    """Bekçinin eşdeğer olmadığının kanıtı — aynı denetleyici, eksik haritada."""
    mutant = dict(presenters.SUNUCULAR)
    del mutant["makine_kira"]
    assert _sunucusuz_araclar(mutant, presenters.SUNUCUSUZ_ARACLAR, CATALOG) == {"makine_kira"}


def test_SUN_MUTASYON_istisna_listesi_KOR_NOKTA_URETMEZ() -> None:
    """🔴 İstisna listesinin kendisi de bir kaçış yolu olabilirdi.

    Bu test onu kapatmaz ama **ÖLÇER**: istisna listesi tek üyelidir ve o üye
    `yetkilerim`dir. Biri bekçiyi susturmak için araç adını oraya eklerse bu
    satır kırmızı olur.
    """
    assert presenters.SUNUCUSUZ_ARACLAR == frozenset({"yetkilerim"})


@pytest.mark.parametrize("spec", AI2BD_TOOLS, ids=lambda s: s.ad)
def test_SUN_her_yeni_arac_GERCEKTEN_blok_uretir(spec: ToolSpec) -> None:
    """Harita dolu ama eşleyici hep `()` dönüyorsa bekçi hiçbir şey ölçmez.

    Bu yüzden iddia haritada değil **çıktıdadır**: aracın kendi yanıt modelinin
    örnek gövdesiyle çağrılınca en az bir blok çıkmalı.
    """
    from app.modules.ai.result import Ok

    ornek = _ornek_govde(spec.ad)
    bloklar = presenters.bloklari_uret(spec.ad, Ok(data=ornek, row_count=1))
    assert bloklar, f"`{spec.ad}` örnek gövdeyle SIFIR blok üretti"


def _ornek_govde(ad: str):
    """Her aracın eşleyicisinin beklediği en küçük gövde."""
    liste_araclari = {
        "santiyeleri_listele": [{"id": None, "name": "Ş", "code": "C", "project_name": "P"}],
        "isveren_hakedisleri": [{"id": None, "project_name": "P", "gross_total": "1"}],
        "taseron_hakedisleri": [{"id": None, "subcontractor_name": "T", "gross_total": "1"}],
        "taseronlar": [{"id": None, "name": "T", "category": "k", "is_active": True}],
        "gunluk_kayit": [{"id": None, "entry_date": "2026-07-01", "status": "draft"}],
        "makine_listesi": [{"id": None, "name": "M", "category": "machinery", "site_id": None}],
        "makine_kira": [{"id": None, "supplier_name": "S", "period_year": 2026, "period_month": 7}],
    }
    if ad in liste_araclari:
        return liste_araclari[ad]
    kartlar = {
        "proje_detayi": {"name": "P", "code": "C", "budget": "1", "progress_pct": "10"},
        "santiye_detayi": {"name": "Ş", "code": "C", "project_name": "P", "remaining_days": 3},
        "is_kalemleri": {"grand_total": "1", "kalem_sayisi": 0, "gerceklesen_toplam": "1"},
        "arsa_payi": {
            "our_share_pct": "50",
            "owner_share_pct": "50",
            "adet_dengesi_notu": "n",
            "deger_dengesi_notu": "n",
        },
        "sozlesmeler": {"total_amount": "1", "active_count": 1, "total": 1, "items": []},
        "puantaj": {"worker_count": 1, "total_hours": "9", "year": 2026, "month": 7},
        "gun_plani": {
            "site_name": "Ş",
            "days": [{"plan_date": "2026-07-01", "has_plan": False}],
        },
        "makine_calisma": {"total_hours": "0", "year": 2026, "month": 7, "total_cost": "0"},
        "makine_yakit": {"total_liters": "0", "year": 2026, "month": 7, "total_amount": "0"},
    }
    return kartlar[ad]


# ############################################################################ #
# ⑤ SESSİZ DELİK 2 — `navigation.EKRAN_ADLARI`
# ############################################################################ #


def _etiketsiz_ekranlar(enum_uyeleri, adlar) -> set:
    return set(enum_uyeleri) - set(adlar)


def test_NAV_EKRAN_ADLARI_enum_ile_KUME_ESITTIR() -> None:
    """🔴 BU BEKÇİ DE BUGÜNE KADAR YOKTU — ve `navigation.py` VARDIR DİYORDU.

    Dosyanın kendi yorumu *"Küme eşitliği bekçilidir: enum'a üye eklenip buraya
    eklenmezse test kırmızı olur"* yazıyordu. Ölçüldü: `EKRAN_ADLARI`ya dokunan
    **hiçbir test yoktu**. Eksik bir etiket derleme hatası değil,
    `handlers.navigate_to` içinde `EKRAN_ADLARI[girdi.ekran]` satırında
    **çalışma anı `KeyError`ı** (yani 500) üretirdi.
    """
    assert _etiketsiz_ekranlar(EkranAnahtari, EKRAN_ADLARI) == set()
    assert set(EKRAN_ADLARI) - set(EkranAnahtari) == set()


def test_NAV_MUTASYON_etiketsiz_uye_YAKALANIR() -> None:
    """Bekçinin eşdeğer olmadığının kanıtı: etiketi düşen üye bulunuyor."""
    eksik_harita = {k: v for k, v in EKRAN_ADLARI.items() if k is not EkranAnahtari.puantaj}
    assert _etiketsiz_ekranlar(EkranAnahtari, eksik_harita) == {EkranAnahtari.puantaj}


def test_NAV_MUTASYON_etiketsiz_uye_CALISMA_ANI_500_uretir() -> None:
    """🔴 Ve kaybın BEDELİ ölçülür: eksik etiket sessiz değil, PATLAYICIDIR.

    Bu, "eksik etiket zararsız" savunmasını kapatır.
    """
    eksik_harita = {k: v for k, v in EKRAN_ADLARI.items() if k is not EkranAnahtari.puantaj}
    with pytest.raises(KeyError):
        _ = eksik_harita[EkranAnahtari.puantaj]


def test_NAV_taseron_hakedisleri_EKLENDI_ve_ETIKETI_VAR() -> None:
    """Kapalı yönetim kararı (AI-2b)."""
    assert EkranAnahtari.taseron_hakedisleri.value == "taseron_hakedisleri"
    assert EKRAN_ADLARI[EkranAnahtari.taseron_hakedisleri] == "Taşeron Hakedişleri"


def test_NAV_hicbir_ekran_EYLEM_YUZEYI_DEGILDIR() -> None:
    """S22: bir eylem yüzeyi listeye girerse `navigate_to` vekâleten yazma
    aracına dönüşür. Değer taşıyan sorgu parametresi de yasaktır."""
    for uye in EkranAnahtari:
        assert "=" not in uye.value and "?" not in uye.value and "/" not in uye.value
        for eylem in ("approve", "submit", "mark-paid", "onayla", "sil", "delete"):
            assert eylem not in uye.value


def test_NAV_navigation_yorumu_ARTIK_DOGRU() -> None:
    """🔴 Yalan yorumun kaldırıldığının kanıtı — yorum bir SÖZLEŞMEDİR.

    `navigation.py` VAR OLMAYAN bir `test_ai0b_navigation.py`yi bekçi diye
    gösteriyordu. Gösterdiği dosya artık BU dosyadır ve gerçekten vardır.
    """
    from app.modules.ai import navigation

    kaynak = Path(navigation.__file__).read_text(encoding="utf-8")
    # Eski ad ancak "VAR OLMAYAN" etiketiyle geçebilir — yani bir BEKÇİ ATFI
    # olarak değil, düzeltilmiş bir kusurun KAYDI olarak.
    for satir in kaynak.splitlines():
        if "test_ai0b_navigation.py" in satir:
            assert "VAR OLMAYAN" in satir, satir
    assert "test_ai2bd_araclar.py" in kaynak
    assert Path(__file__).name == "test_ai2bd_araclar.py"
