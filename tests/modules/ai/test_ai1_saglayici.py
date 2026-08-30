"""AI-1 sağlayıcı katmanı bekçileri (spec §7 · B13 + arayüz iddiaları).

| Bekçi | Mutasyon (KIRMIZI olmalı) | Pozitif kontrol |
|---|---|---|
| B13 | `"store": False` satırını sil | Gövde `store` **anahtarını taşır** |
| B13b | `store`u `True` yap | Değer `False` |
| ARAYÜZ | İmzaya `temperature` ekle | Adlar imzada YOK |
| STRICT | `_sertlestir`i no-op yap | `additionalProperties: False` + tam `required` |
| SEBEP | Bilinmeyen sebebi `bitti`ye eşle | Bilinmeyen → `kesildi` |
| FABRİKA | Üç hata dalını tek mesaja indir | Üç dal ÜÇ AYRI cümle |

🔴 **Gerçek OpenAI çağrısı YOKTUR.** Sahte akıtıcı istek gövdesini yakalar;
ağa çıkan bir test, anahtar olmadığı için ya atlanırdı (sahte-yeşil) ya da CI'ı
sağlayıcının çalışma süresine bağlardı.
"""

from __future__ import annotations

import dataclasses
import inspect
from collections.abc import AsyncIterator
from typing import Any

import pytest

from app.core.config import Settings
from app.modules.ai.providers import base, factory
from app.modules.ai.providers.base import (
    LLMProvider,
    Mesaj,
    MetinParcasi,
    Reddetme,
    TurBitti,
    TurSebebi,
)
from app.modules.ai.providers.openai import OpenAIProvider
from app.modules.ai.tools.catalog import NAVIGATE_TO, PROJELERI_LISTELE, PUANTAJ_HAFTASI

pytestmark = pytest.mark.asyncio


def _yakalayici(parcalar: list[dict[str, Any]]):
    """İstek gövdesini yakalayan sahte akıtıcı."""
    yakalanan: list[dict[str, Any]] = []

    async def _akit(govde: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
        yakalanan.append(govde)
        for parca in parcalar:
            yield parca

    return _akit, yakalanan


def _saglayici(parcalar: list[dict[str, Any]] | None = None):
    akit, yakalanan = _yakalayici(parcalar or [])
    return OpenAIProvider(api_key="sk-test", model="gpt-test", akitici=akit), yakalanan


# --------------------------------------------------------------------------- #
# B13 — `store=false` İSTEK GÖVDESİNDE
# --------------------------------------------------------------------------- #


async def test_B13_store_false_ISTEK_GOVDESINDE_gonderilir() -> None:
    """🔴 §9-A2. "Kodda `store` geçiyor" bir ölçüm DEĞİLDİR; gövde okunur."""
    saglayici, yakalanan = _saglayici([{"choices": [{"finish_reason": "stop"}]}])
    async for _ in saglayici.tur(
        sistem="S", gecmis=[Mesaj(rol="kullanici", icerik="merhaba")], araclar=[NAVIGATE_TO]
    ):
        pass

    assert len(yakalanan) == 1
    govde = yakalanan[0]
    # Mutant 1: satırı sil → anahtar yok → KIRMIZI.
    assert "store" in govde, "istek gövdesinde `store` anahtarı YOK — §9-A2 düştü"
    # Mutant 2: `True` yap → KIRMIZI.
    assert govde["store"] is False


def test_B13_varsayilana_GUVENILMEZ_store_acikca_yazilir() -> None:
    """Kaynak düzeyinde ikinci kilit: alan `istek_govdesi`nde SABİT yazılır."""
    saglayici, _ = _saglayici()
    govde = saglayici.istek_govdesi(sistem="S", gecmis=[], araclar=[])
    assert govde["store"] is False


async def test_yanit_JSONa_ZORLANMAZ_response_format_gonderilmez() -> None:
    """Yapısal çıktı YALNIZ araç şeması düzeyinde (`strict`)."""
    saglayici, yakalanan = _saglayici([{"choices": [{"finish_reason": "stop"}]}])
    async for _ in saglayici.tur(sistem="S", gecmis=[], araclar=[NAVIGATE_TO]):
        pass
    assert "response_format" not in yakalanan[0]


async def test_ORNEKLEME_parametreleri_govdeye_SIZMAZ() -> None:
    saglayici, yakalanan = _saglayici([{"choices": [{"finish_reason": "stop"}]}])
    async for _ in saglayici.tur(sistem="S", gecmis=[], araclar=[]):
        pass
    for ad in ("temperature", "top_p", "top_k"):
        assert ad not in yakalanan[0], f"`{ad}` gövdeye sızdı"


# --------------------------------------------------------------------------- #
# ARAYÜZ — örnekleme parametresi VAAT EDİLMEZ
# --------------------------------------------------------------------------- #


def test_B_ARAYUZ_ornekleme_parametresi_VAAT_ETMEZ() -> None:
    """🔴 `temperature`+`top_p` birlikte Anthropic'te 400 verir, `top_k`i yalnız o
    taşır, prefill OpenAI'da karşılıksızdır. Ortak arayüz taşıyamayacağını vaat
    edemez.

    Mutasyon: `LLMProvider.tur` imzasına `temperature: float = 0.0` ekle → bu
    test KIRMIZI olur.
    """
    imza = inspect.signature(LLMProvider.tur)
    yasak = {"temperature", "top_p", "top_k", "prefill", "on_dolgu"}
    assert yasak.isdisjoint(imza.parameters), f"arayüz yasak alan taşıyor: {imza.parameters}"
    # Uygulama tarafı da aynı sözü tutmalı.
    assert yasak.isdisjoint(inspect.signature(OpenAIProvider.tur).parameters)


def test_ARAYUZ_tur_imzasi_UC_alan_alir() -> None:
    imza = inspect.signature(LLMProvider.tur)
    assert set(imza.parameters) == {"self", "sistem", "gecmis", "araclar"}


def test_OpenAIProvider_LLMProvider_protokolunu_karsilar() -> None:
    saglayici, _ = _saglayici()
    assert isinstance(saglayici, LLMProvider)
    assert saglayici.ad == "openai"


# --------------------------------------------------------------------------- #
# STRICT araç şeması
# --------------------------------------------------------------------------- #


def test_arac_semasi_STRICT_bayragini_tasir() -> None:
    saglayici, _ = _saglayici()
    sema = saglayici.arac_semasi(PUANTAJ_HAFTASI)
    assert sema["function"]["strict"] is True


def test_arac_semasi_KATALOG_semasi_zaten_KAPALI() -> None:
    """⚠️ DÜRÜSTLÜK NOTU — bu iddia `_sertlestir`i ÖLÇMEZ.

    Ölçüldü: kataloğun ALTI aracının girdi modelinin hepsi
    `model_config = ConfigDict(extra="forbid")` taşır ve pydantic bu durumda
    `additionalProperties: false`u KENDİSİ üretir. Yani `_sertlestir`i no-op'a
    çeviren mutant bu satırı **KIRMAZ** — mutant ilk yazımda gerçekten sağ
    kaldı. Bu test bir regresyon çıpasıdır (katalog girdisi bir gün
    `extra="forbid"`i kaybederse konuşur), `_sertlestir`in bekçisi DEĞİLDİR.
    Onun bekçisi bir alttaki testtir.
    """
    saglayici, _ = _saglayici()
    for spec in (PUANTAJ_HAFTASI, PROJELERI_LISTELE, NAVIGATE_TO):
        sema = saglayici.arac_semasi(spec)
        assert sema["function"]["parameters"]["additionalProperties"] is False


def test_sertlestirme_PYDANTICIN_YAPMADIGINI_yapar() -> None:
    """🔴 `_sertlestir`in GERÇEK bekçisi.

    `extra="forbid"` TAŞIMAYAN ve **opsiyonel** alanı olan bir model kullanılır:
    pydantic böyle bir modelde ne `additionalProperties` üretir ne de opsiyonel
    alanı `required`a koyar. OpenAI `strict: true` ikisini de ŞART koşar.

    Mutasyon: `_sertlestir`i no-op yap → bu test KIRMIZI olur.
    """
    from pydantic import BaseModel

    class _Gevsek(BaseModel):
        zorunlu: int
        istege_bagli: str | None = None

    ham = _Gevsek.model_json_schema()
    # Pozitif kontrol: pydantic'in ham çıktısı gerçekten GEVŞEK.
    assert "additionalProperties" not in ham
    assert set(ham["required"]) == {"zorunlu"}

    spec = dataclasses.replace(PROJELERI_LISTELE, girdi=_Gevsek)
    sema = base.girdi_semasi(spec)
    assert sema["additionalProperties"] is False
    assert set(sema["required"]) == {"zorunlu", "istege_bagli"}


def test_arac_semasi_ACIKLAMAYI_BIREBIR_tasir() -> None:
    """Kataloğun "NE ZAMAN / NE SORMAZ" metninin ikinci bir kopyası olmamalı."""
    saglayici, _ = _saglayici()
    sema = saglayici.arac_semasi(PROJELERI_LISTELE)
    assert sema["function"]["description"] == PROJELERI_LISTELE.aciklama
    assert sema["function"]["name"] == "projeleri_listele"


def test_ic_ice_semada_da_sertlestirme_KOSAR() -> None:
    """`$defs` gezilmezse iç içe bir model sessizce gevşek kalırdı."""
    sema = base.girdi_semasi(NAVIGATE_TO)
    for alt in (sema.get("$defs") or {}).values():
        if alt.get("type") == "object":
            assert alt["additionalProperties"] is False


# --------------------------------------------------------------------------- #
# TurSebebi — TEK `finish_reason`a indirgenmez
# --------------------------------------------------------------------------- #


def test_TurSebebi_ALTI_uye_tasir() -> None:
    assert {u.value for u in TurSebebi} == {
        "bitti",
        "arac",
        "kesildi",
        "reddetme",
        "duraklatildi",
        "filtrelendi",
    }


@pytest.mark.parametrize(
    ("ham", "beklenen"),
    [
        ("stop", TurSebebi.bitti),
        ("tool_calls", TurSebebi.arac),
        ("length", TurSebebi.kesildi),
        ("content_filter", TurSebebi.filtrelendi),
    ],
)
async def test_finish_reason_AYRI_hallere_eslenir(ham: str, beklenen: TurSebebi) -> None:
    """🔴 `content_filter` ile `stop` AYNI ekrana düşerse panel yalan söyler."""
    saglayici, _ = _saglayici([{"choices": [{"finish_reason": ham}]}])
    olaylar = [o async for o in saglayici.tur(sistem="S", gecmis=[], araclar=[])]
    bitis = next(o for o in olaylar if isinstance(o, TurBitti))
    assert bitis.sebep is beklenen


async def test_BILINMEYEN_sebep_kesildiye_duser_BITTIYE_DEGIL() -> None:
    """Mutasyon: `SEBEP_ESLEMESI.get(ham, TurSebebi.bitti)` → KIRMIZI.

    Bilinmeyen bir sebebi "işini bitirdi" saymak, eksik bir cevabı tam gibi
    sunmaktır.
    """
    saglayici, _ = _saglayici([{"choices": [{"finish_reason": "yepyeni_sebep"}]}])
    olaylar = [o async for o in saglayici.tur(sistem="S", gecmis=[], araclar=[])]
    bitis = next(o for o in olaylar if isinstance(o, TurBitti))
    assert bitis.sebep is TurSebebi.kesildi


async def test_hic_sebep_gelmezse_BITTI_VARSAYILMAZ() -> None:
    saglayici, _ = _saglayici([{"choices": [{"delta": {"content": "yarim"}}]}])
    olaylar = [o async for o in saglayici.tur(sistem="S", gecmis=[], araclar=[])]
    assert isinstance(olaylar[0], MetinParcasi)
    assert olaylar[-1].sebep is TurSebebi.kesildi


async def test_reddetme_HATA_DEGIL_ayri_olay() -> None:
    """`Reddetme` bir `Hata` değildir; kullanıcıya farklı cümle kurulur."""
    saglayici, _ = _saglayici(
        [{"choices": [{"delta": {"refusal": "Bunu yapamam."}, "finish_reason": "stop"}]}]
    )
    olaylar = [o async for o in saglayici.tur(sistem="S", gecmis=[], araclar=[])]
    red = next(o for o in olaylar if isinstance(o, Reddetme))
    assert red.metin == "Bunu yapamam."
    assert olaylar[-1].sebep is TurSebebi.reddetme


# --------------------------------------------------------------------------- #
# FABRİKA — üç ad TANINIR, hatalar AYRI
# --------------------------------------------------------------------------- #


def test_factory_UC_adi_TANIR() -> None:
    assert factory.TANINAN_SAGLAYICILAR == ("openai", "anthropic", "gemini")
    assert factory.YAZILMIS_SAGLAYICILAR == {"openai"}


def _ayar(**ek: Any) -> Settings:
    return Settings(jwt_secret="test-secret", **ek)


def test_factory_BOS_ad_yapilandirilmadi_der() -> None:
    with pytest.raises(factory.SaglayiciYapilandirilmadi) as bilgi:
        factory.saglayici_kur(_ayar(ai_provider=""))
    assert "yapılandırılmadı" in str(bilgi.value)


def test_factory_TANINMAYAN_ad_YOK_der() -> None:
    """🔴 "yok" ≠ "yapılandırılmadı". Mutasyon: ikisini tek sınıfa indir."""
    with pytest.raises(factory.SaglayiciYok) as bilgi:
        factory.saglayici_kur(_ayar(ai_provider="llamaviz"))
    assert "YOK" in str(bilgi.value)
    assert "openai, anthropic, gemini" in str(bilgi.value)


def test_factory_TANINAN_ama_YAZILMAMIS_ad_ayri_cumle_verir() -> None:
    """`anthropic` TANINIR; adaptörü bu dilimde yazılmadı — "yok" DEĞİL."""
    with pytest.raises(factory.SaglayiciYapilandirilmadi) as bilgi:
        factory.saglayici_kur(_ayar(ai_provider="anthropic", ai_anthropic_api_key="k"))
    metin = str(bilgi.value)
    assert "TANINIYOR" in metin
    assert "yazılmadı" in metin
    assert "YOK" not in metin


def test_factory_ANAHTAR_bossa_yapilandirilmadi_der_YOK_DEMEZ() -> None:
    with pytest.raises(factory.SaglayiciYapilandirilmadi) as bilgi:
        factory.saglayici_kur(_ayar(ai_provider="openai", ai_openai_api_key=""))
    metin = str(bilgi.value)
    assert "AI_OPENAI_API_KEY" in metin
    assert "YOK DEĞİL" in metin


def test_factory_UC_HATA_DALI_UC_AYRI_CUMLE_uretir() -> None:
    """Mutasyon: üç dalı tek mesaja indir → bu test KIRMIZI olur."""
    mesajlar = set()
    for ayar in (
        _ayar(ai_provider=""),
        _ayar(ai_provider="anthropic", ai_anthropic_api_key="k"),
        _ayar(ai_provider="openai", ai_openai_api_key=""),
    ):
        try:
            factory.saglayici_kur(ayar)
        except (factory.SaglayiciYok, factory.SaglayiciYapilandirilmadi) as exc:
            mesajlar.add(str(exc))
    assert len(mesajlar) == 3


def test_factory_YAPILANDIRILMIS_openai_kurar() -> None:
    saglayici = factory.saglayici_kur(_ayar(ai_provider="OpenAI ", ai_openai_api_key="sk-x"))
    assert isinstance(saglayici, OpenAIProvider)
    assert saglayici.ad == "openai"


def test_ANAHTARSIZ_adapter_kurulamaz() -> None:
    with pytest.raises(ValueError, match="anahtarsız"):
        OpenAIProvider(api_key="", model="m")


# --------------------------------------------------------------------------- #
# Anahtarlar YALNIZ ortamdan — DB SÜTUNU YOK
# --------------------------------------------------------------------------- #


def test_B_ANAHTAR_DB_SUTUNU_OLARAK_YOK() -> None:
    """🔴 Anahtar bir SIR, bir ayar değil.

    `company` tablosu `settings:view` olan HERKESE açık. Bir sağlayıcı anahtarını
    oraya koymak, sırrı bir izin seviyesinin arkasına saklamak olurdu. Mutasyon:
    `Company`ye `ai_openai_api_key` sütunu ekle → KIRMIZI.
    """
    from app.core.db import Base

    supheli = {"api_key", "apikey", "secret", "token"}
    for tablo in Base.metadata.tables.values():
        for sutun in tablo.columns:
            ad = sutun.name.lower()
            if ad.startswith("ai_") and any(s in ad for s in supheli):
                raise AssertionError(f"{tablo.name}.{sutun.name} — AI anahtarı DB'de DURAMAZ")


def test_ai_ayarlari_SETTINGS_uzerinde_ve_bos_varsayilanli() -> None:
    ayar = _ayar()
    assert ayar.ai_openai_api_key == ""
    assert ayar.ai_anthropic_api_key == ""
    assert ayar.ai_gemini_api_key == ""
    assert ayar.ai_provider == ""
    assert ayar.ai_max_tool_calls == 8


def test_PRODUCTION_ortaminda_anahtar_bossa_ACILIS_KIRILMAZ() -> None:
    """🔴 Ölçülmüş sebep: bu turda bir açılış kırıcı değişiklik canlıyı çökertti.

    Bir AI anahtarının eksikliği, hakediş girişini durdurmak için sebep değildir.
    """
    ayar = Settings(environment="production", jwt_secret="gercek", ai_provider="openai")
    assert ayar.ai_openai_api_key == ""  # açılış PATLAMADI
    with pytest.raises(factory.SaglayiciYapilandirilmadi):
        factory.saglayici_kur(ayar)
