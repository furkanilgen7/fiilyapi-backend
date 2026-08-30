"""Sağlayıcı seçimi — üç adı **TANIR**, birini kurar (§9-A9).

## 🔴 "Yok" ile "yapılandırılmadı" AYRI hatalardır

`AI_PROVIDER=anthropic` yazan bir operatöre *"sağlayıcı yok"* demek yalandır:
ad tanınıyor, adaptörü bu sürümde yazılmadı. Aynı şekilde `AI_PROVIDER=openai`
ama anahtar boşsa sorun sağlayıcıda değil **yapılandırmadadır**. İkisini tek
mesaja ezmek, operatörü yanlış yerde arattırır — ve bu hattın tüm meselesi
"hata mesajı doğru şeyi söylesin"dir.

## 🔴 Anahtarlar YALNIZ ortamdan

`ai_*_api_key` alanları `Settings` üzerindedir, yani `.env`/ortam
değişkenindedir. **DB'de durmaz.** Ölçülmüş sebep: `company` tablosunda
şirket ayarları düz `String` sütunlar olarak yaşıyor ve o tablo `settings:view`
olan **herkese** açık; oraya bir sağlayıcı anahtarı koymak, anahtarı bir izin
seviyesinin arkasına saklamak olurdu — oysa anahtar bir sırdır, bir ayar değil.
Bekçisi `test_ai1_saglayici.py::test_B_ANAHTAR_DB_SUTUNU_OLARAK_YOK`.

## Açılış KIRILMAZ

`environment == "production"` iken sağlayıcı seçili ama anahtar boşsa uygulama
**açılır**; hata `POST /ai/chat` çağrıldığında dürüstçe döner. Sebep ölçülmüş:
bu turda bir açılış kırıcı değişiklik canlıyı çökertti. Bir AI anahtarının
eksikliği, hakediş girişini durdurmak için bir sebep değildir.
"""

from __future__ import annotations

from typing import Final

from app.core.config import Settings
from app.core.config import settings as varsayilan_ayarlar
from app.modules.ai.providers.base import LLMProvider
from app.modules.ai.providers.openai import OpenAIProvider

#: Sistemin **tanıdığı** adlar. Tanımak ≠ uygulamak.
TANINAN_SAGLAYICILAR: Final[tuple[str, ...]] = ("openai", "anthropic", "gemini")

#: AI-1'de adaptörü fiilen **yazılmış** olanlar.
YAZILMIS_SAGLAYICILAR: Final[frozenset[str]] = frozenset({"openai"})

#: Ad → hangi ayar alanının anahtarı taşıdığı.
ANAHTAR_ALANLARI: Final[dict[str, str]] = {
    "openai": "ai_openai_api_key",
    "anthropic": "ai_anthropic_api_key",
    "gemini": "ai_gemini_api_key",
}


class SaglayiciYok(LookupError):
    """Ad hiç tanınmıyor — yazım hatası ya da var olmayan bir sağlayıcı."""


class SaglayiciYapilandirilmadi(RuntimeError):
    """Ad TANINIYOR ama kurulamıyor: anahtar boş ya da adaptör yazılmamış.

    🔴 `SaglayiciYok`tan ayrı sınıf — çağıran taraf ikisini farklı cümleye
    çevirmek zorunda kalsın diye.
    """


def saglayici_kur(ayarlar: Settings | None = None) -> LLMProvider:
    """Yapılandırılmış sağlayıcıyı kurar; kuramazsa **dürüst** hata verir."""
    ayarlar = ayarlar or varsayilan_ayarlar
    ad = (ayarlar.ai_provider or "").strip().lower()

    if not ad:
        raise SaglayiciYapilandirilmadi(
            "AI sağlayıcısı yapılandırılmadı: `AI_PROVIDER` boş. "
            f"Tanınan adlar: {', '.join(TANINAN_SAGLAYICILAR)}."
        )
    if ad not in TANINAN_SAGLAYICILAR:
        raise SaglayiciYok(
            f"'{ad}' diye bir sağlayıcı YOK. Tanınan adlar: {', '.join(TANINAN_SAGLAYICILAR)}."
        )
    anahtar = (getattr(ayarlar, ANAHTAR_ALANLARI[ad], "") or "").strip()
    if ad not in YAZILMIS_SAGLAYICILAR:
        raise SaglayiciYapilandirilmadi(
            f"'{ad}' sağlayıcısı TANINIYOR ama adaptörü bu sürümde yazılmadı "
            f"(yazılmış olanlar: {', '.join(sorted(YAZILMIS_SAGLAYICILAR))}). "
            "Bu bir yapılandırma eksiği değil, ürün kapsamı kararıdır."
        )
    if not anahtar:
        raise SaglayiciYapilandirilmadi(
            f"'{ad}' sağlayıcısı seçili ama anahtarı yapılandırılmadı "
            f"(`{ANAHTAR_ALANLARI[ad].upper()}` boş). Sağlayıcı YOK DEĞİL; "
            "anahtar eksik."
        )
    return OpenAIProvider(api_key=anahtar, model=ayarlar.ai_model)


__all__ = [
    "ANAHTAR_ALANLARI",
    "SaglayiciYapilandirilmadi",
    "SaglayiciYok",
    "TANINAN_SAGLAYICILAR",
    "YAZILMIS_SAGLAYICILAR",
    "saglayici_kur",
]
