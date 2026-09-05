"""AI-CHAT-2 / K1 — yapısal bloklar **modelin metninden ASLA üretilmez**.

Bu dosyanın tek meselesi şudur: mockup'ın metrik kartları, kâr barı, varlık
listeleri, "Kaynak" rozetleri ve derin bağlantıları **araç sonucunun yapısal
gövdesinden** doğar. Model bir bloğun varlığını da içeriğini de etkileyemez.
"""

from __future__ import annotations

import dataclasses
import json
import re
from pathlib import Path

import pytest

from app.modules.ai import blocks, presenters
from app.modules.ai.blocks import (
    AksiyonBloku,
    BaglantiKalemi,
    BlokTonu,
    KaynakBloku,
    MetrikBloku,
    UyariBloku,
    VarlikListesiBloku,
    YapisalBlok,
)
from app.modules.ai.navigation import EkranAnahtari
from app.modules.ai.providers.base import (
    SAGLAYICI_OLAYLARI,
    AracSonuclandi,
    YapisalBloklar,
)
from app.modules.ai.result import (
    Empty,
    NotFound,
    Ok,
    Restricted,
    ScopedEmpty,
    ToolError,
    Truncated,
)
from app.modules.ai.stream import sse_kodla
from app.modules.ai.tools import schemas as arac_semalari

AI_KOK = Path(blocks.__file__).parent


# --------------------------------------------------------------------------- #
# Birleşim KAPALI
# --------------------------------------------------------------------------- #


def test_blok_tipleri_KAPALI_ve_her_alt_sinif_KAYITLI() -> None:
    """Kayıtsız bir blok sınıfı akışa giremez: `tip` erişimi `KeyError` atar.

    ⚠️ ÖLÇÜM (dürüstlük): bu bekçi önce `YapisalBlok.__subclasses__()` ile
    yazıldı ve **her sınıfı İKİ KEZ** gördü. Sebep ölçüldü:
    `@dataclass(slots=True)` **YENİ bir sınıf nesnesi üretir** ve slots'suz
    orijinali `__subclasses__()` kaydında ölü olarak bırakır. Yani `__subclasses__`
    bu depoda bir sınıf sicili DEĞİLDİR. Sicil, modülün **dışa verdiği** adlardır.
    """
    dısa_verilen = {
        deger
        for deger in vars(blocks).values()
        if isinstance(deger, type) and issubclass(deger, YapisalBlok) and deger is not YapisalBlok
    }
    assert dısa_verilen == set(blocks._BLOK_TIPLERI), (
        "Yeni bir blok sınıfı `_BLOK_TIPLERI`ne eklenmemiş; `tip` KeyError atardı."
    )
    assert len(blocks.BLOK_TIPLERI) == len(blocks._BLOK_TIPLERI)
    # POZİTİF KONTROL: `tip` gerçekten sicilden okunuyor.
    assert MetrikBloku(baslik="b", deger_metni="1").tip == "metrik"


def test_hicbir_blok_alaninda_URL_ya_da_HTML_TASIYICISI_YOK() -> None:
    """🔴 K1: derin bağlantı hedefi modelden GELMEZ — `ekran` anahtarı taşınır.

    `url`/`href`/`html` adlı bir alan açılırsa istemci onu doğrudan basacak bir
    yer bulur ve `navigate_to`nun kapalı-enum kararı (S22) dolanılır.
    """
    yasak = {"url", "href", "src", "html", "markdown", "link"}
    for sinif in blocks._BLOK_TIPLERI:
        adlar = {f.name for f in dataclasses.fields(sinif)}
        assert not (adlar & yasak), f"{sinif.__name__} yasak alan taşıyor: {adlar & yasak}"
    for sinif in (BaglantiKalemi, blocks.VarlikKalemi, blocks.OranDilimi):
        adlar = {f.name for f in dataclasses.fields(sinif)}
        assert not (adlar & yasak), f"{sinif.__name__} yasak alan taşıyor"


def test_baglanti_kaleminin_ekrani_KAPALI_ENUM() -> None:
    alan = next(f for f in dataclasses.fields(BaglantiKalemi) if f.name == "ekran")
    assert alan.type in (EkranAnahtari, "EkranAnahtari"), (
        "`ekran` serbest `str` OLAMAZ: model bir URL uydurabilirdi (S22)."
    )


def test_YapisalBloklar_SAGLAYICI_OLAYI_DEGIL() -> None:
    """Bir sağlayıcı adaptörünün bu olayı üretmesi bir HATADIR."""
    assert YapisalBloklar not in SAGLAYICI_OLAYLARI
    assert AracSonuclandi not in SAGLAYICI_OLAYLARI


# --------------------------------------------------------------------------- #
# 🔴 EN ÖNEMLİ BEKÇİ: bloklar MODEL METNİNDEN üretilmiyor
# --------------------------------------------------------------------------- #


#: 🔴 Eşleyici katmanının **TÜM** parçaları. `presenters.py` 800 satır tavanını
#: aşınca üçe bölündü (`presenters_base` · `presenters_ai2bd`) ve tek dosya
#: okuyan bir bekçi **iki yeni dosyayı sessizce atlardı** — aynı PR'de params
#: bekçisi tam bu şekilde körleşmişti. Küme `glob`la kurulur, elle sayılmaz.
def _esleyici_kaynaklari() -> list[Path]:
    return sorted(AI_KOK.glob("presenters*.py"))


#: Modelin ürettiği metni taşıyan adlar. Bu katmanda HİÇBİRİ geçemez.
_MODEL_METNI_ADLARI = ("MetinParcasi", "Mesaj", "gecmis", "kullanici_mesaji", "re.", "import re")


def _model_metnine_dokunanlar(kaynak: str) -> list[str]:
    return [y for y in _MODEL_METNI_ADLARI if y in kaynak]


def test_POZITIF_KONTROL_TARANAN_esleyici_dosyalari_UCTEN_AZ_DEGIL() -> None:
    """Tarama kümesi daralırsa bekçi sessizce körleşir."""
    adlar = {y.name for y in _esleyici_kaynaklari()}
    assert {"presenters.py", "presenters_base.py", "presenters_ai2bd.py"} <= adlar, adlar


@pytest.mark.parametrize("yol", _esleyici_kaynaklari(), ids=lambda p: p.name)
def test_presenters_MODEL_METNINE_hicbir_yerden_ULASMAZ(yol: Path) -> None:
    """Eşleyiciler yalnız `AracSonucu` görür — `Mesaj`/`MetinParcasi` değil.

    Bu bir tip kısıtı değil bir **erişim** kısıtıdır: modelin ürettiği metni
    taşıyan sınıflar bu katmanda import EDİLEMEZ. Edilirse bir gün biri
    "metinden şu kalıbı ayıkla" yazar ve K1 sessizce düşer.
    """
    dokunanlar = _model_metnine_dokunanlar(yol.read_text(encoding="utf-8"))
    assert dokunanlar == [], f"{yol.name} model metnine dokunuyor: {dokunanlar}"


def test_MUTASYON_model_metnine_dokunan_esleyici_YAKALANIR() -> None:
    """Bekçinin eşdeğer olmadığının kanıtı: aynı denetleyici, ihlalli kaynakta."""
    mutant = "from app.modules.ai.providers.base import MetinParcasi\nx = MetinParcasi\n"
    assert _model_metnine_dokunanlar(mutant) == ["MetinParcasi"]
    assert _model_metnine_dokunanlar("temiz kaynak\n") == []


def test_bloklar_ARAC_ADINDAN_secilir_modelin_METNINDEN_degil() -> None:
    """Aynı gövde, farklı araç adı → farklı (ya da hiç) blok."""
    veri = {"ekran": "stok", "ekran_adi": "Stok"}
    assert presenters.bloklari_uret("navigate_to", Ok(data=veri, row_count=1)) != ()
    # Adı kataloğda olmayan araç blok üretmez — model "navigate_to gibi davran"
    # diye yazsa bile.
    assert presenters.bloklari_uret("uydurma_arac", Ok(data=veri, row_count=1)) == ()
    # `yetkilerim` bilerek yok: meta cevap, kart değil.
    assert presenters.bloklari_uret("yetkilerim", Ok(data=veri, row_count=1)) == ()


# --------------------------------------------------------------------------- #
# Zarf hâlleri
# --------------------------------------------------------------------------- #


def test_govdesiz_zarflar_HIC_BLOK_URETMEZ() -> None:
    """🔴 `Restricted`ta `data` alanı YOKTUR; boş kart basmak yalan olurdu."""
    for zarf in (
        Restricted("projects"),
        Empty(),
        ScopedEmpty("projects"),
        NotFound(),
        ToolError("butce_asildi"),
    ):
        assert presenters.bloklari_uret("projeleri_listele", zarf) == (), type(zarf).__name__


def test_Truncated_KRITIK_UYARI_blogunu_ONE_koyar() -> None:
    """B19'un görsel hâli: kırpılmış kümeden çizilen kart "tablo bu" der."""
    veri = [
        {
            "id": "11111111-1111-1111-1111-111111111111",
            "code": "P1",
            "name": "A",
            "status": "active",
            "type": "taahhut",
            "progress_pct": "10.00",
        }
    ]
    bloklar = presenters.bloklari_uret(
        "projeleri_listele", Truncated(data=veri, total=99, returned=1)
    )
    assert isinstance(bloklar[0], UyariBloku)
    assert bloklar[0].ton is BlokTonu.kritik
    assert "99" in bloklar[0].metin and "KIRPILDI" in bloklar[0].metin
    # Ve liste yine de çizilir — kullanıcı hem uyarıyı hem kısmi kümeyi görür.
    assert any(isinstance(b, VarlikListesiBloku) for b in bloklar)


# --------------------------------------------------------------------------- #
# `MetricPlaceholder` üç hâli DÜZLEŞTİRİLMEZ (S25/B18)
# --------------------------------------------------------------------------- #


def test_yer_tutucu_CUMLESI_SAYI_gibi_cizilmez() -> None:
    veri = {
        "role_name": "Patron",
        "active_project_count": 4,
        "gorunur_proje_sayisi": 3,
        "portfoy": arac_semalari.IZIN_YOK,
        "alacaklar": arac_semalari.MODUL_BEKLIYOR.format(modul="treasury"),
        "ortalama_marj": "%18,4",
        "risk_notu": "3 uyarı, 2 kaynaktan.",
    }
    bloklar = presenters.bloklari_uret("gosterge_ozeti", Ok(data=veri, row_count=1))
    kartlar = {b.baslik: b for b in bloklar if isinstance(b, MetrikBloku)}

    # 🔴 Üç hâl AYRI: yer tutucu cümlesi büyük punto bir metrik DEĞİLDİR.
    assert kartlar["Portföy"].deger_metni == "—"
    assert kartlar["Portföy"].ton is BlokTonu.notr
    assert kartlar["Portföy"].alt_metin == arac_semalari.IZIN_YOK

    assert kartlar["Alacaklar"].deger_metni == "—"
    assert "treasury" in (kartlar["Alacaklar"].alt_metin or "")

    # Gerçek değer düzleştirilmez: sayı sayı gibi çizilir.
    assert kartlar["Ortalama Marj"].deger_metni == "%18,4"
    assert kartlar["Ortalama Marj"].ton is BlokTonu.olumlu


def test_iki_proje_sayisi_BIRBIRINDEN_TURETILMEZ() -> None:
    veri = {
        "role_name": "Patron",
        "active_project_count": 4,
        "gorunur_proje_sayisi": 3,
        "portfoy": "₺1",
        "alacaklar": "₺2",
        "ortalama_marj": "%3",
        "risk_notu": "n",
    }
    bloklar = presenters.bloklari_uret("gosterge_ozeti", Ok(data=veri, row_count=1))
    kart = next(b for b in bloklar if isinstance(b, MetrikBloku) and b.baslik == "Aktif proje")
    assert kart.deger_metni == "4"
    assert "3" in (kart.alt_metin or ""), "görünür proje sayısı ayrı ayrı söylenmeli"


# --------------------------------------------------------------------------- #
# Para biçimlemesi
# --------------------------------------------------------------------------- #


def test_para_TR_bicimi_ve_COZULEMEYEN_deger_0_YAZMAZ() -> None:
    assert presenters._para("2100000") == "₺2.100.000,00"
    assert presenters._para("1160000.50") == "₺1.160.000,50"
    # 🔴 Çözülemeyen değer `None` — `0` yazmak uydurulmuş bir olgudur.
    assert presenters._para(None) is None
    assert presenters._para("abc") is None


def test_ilerleme_yuzdesi_YOKSA_cubuk_CIZILMEZ() -> None:
    veri = [
        {
            "id": "11111111-1111-1111-1111-111111111111",
            "code": "P1",
            "name": "A",
            "status": "active",
            "type": "taahhut",
            "progress_pct": None,
        }
    ]
    bloklar = presenters.bloklari_uret("projeleri_listele", Ok(data=veri, row_count=1))
    liste = next(b for b in bloklar if isinstance(b, VarlikListesiBloku))
    # 🔴 `0` DEĞİL `None`: 0 "hiç ilerlemedi" demektir.
    assert liste.kalemler[0].doluluk_yuzde is None
    assert liste.kalemler[0].rozet_metni is None


# --------------------------------------------------------------------------- #
# Tel biçimi (SSE)
# --------------------------------------------------------------------------- #


def _kare(bloklar: tuple[YapisalBlok, ...]) -> dict:
    ham = sse_kodla(YapisalBloklar(cagri_id="c1", arac_adi="t", bloklar=bloklar)).decode()
    assert ham.startswith("event: yapisal_blok\n")
    return json.loads(ham.split("data: ", 1)[1])


def test_sse_karesi_ekran_anahtarini_DEGERIYLE_yazar() -> None:
    """🔴 `default=str` YETMEZ: `"EkranAnahtari.stok"` yazsaydı istemcinin rota
    kataloğu onu çözemez ve derin bağlantı SESSİZCE ölürdü."""
    kare = _kare((KaynakBloku((BaglantiKalemi(etiket="Stok", ekran=EkranAnahtari.stok),)),))
    assert kare["bloklar"][0]["kalemler"][0]["ekran"] == "stok"
    assert "EkranAnahtari" not in json.dumps(kare)


def test_sse_karesi_TIP_ayiricisini_TASIR() -> None:
    """`tip` bir `@property`dir ve `dataclasses.asdict` property OKUMAZ."""
    kare = _kare(
        (
            MetrikBloku(baslik="B", deger_metni="1"),
            UyariBloku(metin="u"),
            AksiyonBloku((BaglantiKalemi(etiket="Aç", ekran=EkranAnahtari.stok, birincil=True),)),
        )
    )
    assert [b["tip"] for b in kare["bloklar"]] == ["metrik", "uyari", "aksiyon"]
    assert {b["tip"] for b in kare["bloklar"]} <= blocks.BLOK_TIPLERI


def test_sse_karesinde_HAM_HTML_gecmez() -> None:
    kare = _kare((UyariBloku(metin="<script>alert(1)</script>", vurgular=("<b>",)),))
    ham = json.dumps(kare, ensure_ascii=False)
    # Metin **taşınır** (düz metindir) ama istemci onu basmadan önce
    # `dangerouslySetInnerHTML` kullanmaz; burada ölçülen şey, bloğun ayrı bir
    # "html" kanalı AÇMADIĞIDIR.
    assert "html" not in kare["bloklar"][0]
    assert re.search(r'"tip":\s*"uyari"', ham)
