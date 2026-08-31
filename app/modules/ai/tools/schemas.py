"""Araçların **girdi** ve **yanıt** modelleri.

🔴 **ORM ASLA DÖNMEZ** (`ToolSpec.yanit_modeli` zorunlu). Ve bu modeller ucun
kendi `response_model`ının kopyası da DEĞİLDİR: araç, ucun döndürdüğü gövdeyi
**daraltır**. Daraltmanın iki gerekçesi var ve ikisi de ölçüme dayanır:

1. **Alan maskesi VARSAYILANDIR** (§9-A1 fail-closed önerisi). Uç `tc_no`,
   `iban`, `wage_amount` taşıyorsa ve araç gövdeyi düz geçirirse o alanlar
   sağlayıcıya gider. AI-0b'nin dört aracı PII taşıyan uçlara bakmıyor ama
   **desen şimdi kurulur**, sonra değil.
2. Token bütçesi: 140 GET'in gövdeleri geniştir; model kararı için gereken
   alanlar dardır.

🔴 **`MetricPlaceholder`ın ÜÇ HÂLİ DÜZLEŞTİRİLMEZ** (S25/B18). `value or 0`
yazmak üç ayrı gerçeği ("değer 12", "modül henüz yazılmadı", "yetkin yok") tek
sayıya indirir. Burada üçü **üç ayrı sabit dizeye** çevrilir.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any, Final

from pydantic import BaseModel, ConfigDict, Field

from app.modules.ai.navigation import EkranAnahtari

# --------------------------------------------------------------------------- #
# `MetricPlaceholder` üç hâli — SABİT metinler (B18: bayt eşitliği)
# --------------------------------------------------------------------------- #

#: `available=False` + `pending_module` DOLU — alan henüz BAĞLANMADI.
MODUL_BEKLIYOR: Final[str] = "Bu değer henüz bağlanmadı (bekleyen modül: {modul})."
#: `available=False` + `pending_module is None` — 🔴 ROLÜN İZNİ YOK (üçüncü hâl).
IZIN_YOK: Final[str] = "Bu değeri görme yetkiniz yok."
#: 🔴 Sayısal düzleştirme YASAK: `value` `None` iken de `available` `True`
#: olabilir ("hesaplandı, sonuç yok").
DEGER_YOK: Final[str] = "Hesaplandı ama bir değer üretmedi."


def metrik_metni(zarf: dict[str, Any] | None) -> str:
    """`MetricPlaceholder` gövdesini **üç ayrı cümleden birine** çevirir.

    Okuma `available` bayrağından yapılır — `projects/schemas.py` açıkça
    *"çıplak `MetricPlaceholder()` artık ValidationError ATMAZ"* der, yani
    üçüncü hâl yapısal olarak zorlanmıyor, bir **disiplindir**.
    """
    if zarf is None:
        return IZIN_YOK
    if zarf.get("available"):
        deger = zarf.get("value")
        return DEGER_YOK if deger is None else str(deger)
    bekleyen = zarf.get("pending_module")
    return IZIN_YOK if bekleyen is None else MODUL_BEKLIYOR.format(modul=bekleyen)


# --------------------------------------------------------------------------- #
# GİRDİ modelleri
# --------------------------------------------------------------------------- #


class BosGirdi(BaseModel):
    """Parametresiz araçlar. `extra="forbid"`: model uydurduğu bir alanı
    sessizce geçiremez (S21'in okuma tarafı)."""

    model_config = ConfigDict(extra="forbid")


class PuantajHaftasiGirdi(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: 🔴 TİPLİ (S27). `str` olsaydı `..` argümanı tip katmanından geçerdi ve
    #: yalnız nokta-segment reddi kalırdı; iki kilit birden istiyoruz.
    site_id: uuid.UUID
    iso_year: int = Field(ge=2000, le=2100)
    iso_week: int = Field(ge=1, le=53)


class YonlendirGirdi(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: KAPALI ENUM (S22). Serbest `str` DEĞİL.
    ekran: EkranAnahtari


# --------------------------------------------------------------------------- #
# YANIT modelleri
# --------------------------------------------------------------------------- #


class AiProje(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    status: str
    type: str
    #: 🔴 FİNANSAL ilerleme (`ProjectListItem.progress_pct`), FİZİKSEL DEĞİL —
    #: `projects/schemas.py` ikisini KASTEN ayırır. `None` bırakılabilir: uç
    #: alanı taşımazsa 0 yazmak "hiç ilerlemedi" demek olurdu (uydurma).
    progress_pct: Decimal | None = None


class AiProjeListesi(BaseModel):
    items: list[AiProje]
    total: int


class AiOnayKalemi(BaseModel):
    document_type: str
    document_id: uuid.UUID
    title: str | None
    subtitle: str | None
    created_by_name: str | None
    current_step_no: int
    gross_amount: Decimal | None
    net_amount: Decimal | None


class AiOnayKutusu(BaseModel):
    items: list[AiOnayKalemi]
    total: int
    #: 🔴 Bu uç KAPISIZDIR ve dönen küme "bu adım SANA düştü" olgusuyla
    #: sınırlıdır. Aktörün onay rolü yoksa küme boştur ve bu **yetki reddi
    #: değildir** — cümle farkı burada doğar.
    my_approval_roles: list[str]


class AiPuantajHaftasi(BaseModel):
    site_id: uuid.UUID
    site_name: str
    project_name: str
    iso_year: int
    iso_week: int
    start_date: str
    end_date: str
    worker_count: int
    #: Uçtaki `totals` gövdesi aynen taşınır; sayılar türetilmez.
    totals: dict[str, Any]


class AiGostergeOzeti(BaseModel):
    role_name: str
    #: 🔴 ÜÇ AYRI SAYI, biri diğerinden TÜRETİLMEZ (ölçüldü):
    #: `active_project_count` taslakları DIŞLAR; `gorunur_proje_sayisi` dizinin
    #: uzunluğudur; portföyün saydığı küme ise ÜÇÜNCÜ bir kümedir ve buradan
    #: okunamaz. Araç ikisini birbirine eşitlemez.
    active_project_count: int
    gorunur_proje_sayisi: int
    portfoy: str
    alacaklar: str
    ortalama_marj: str
    #: `risks` kartı SESSİZCE KIRPAR (`MAX_ALERTS_PER_SOURCE = 3`, üç kaynağın
    #: üçünde de SQL `.limit(3)`) ve zarfında **`total` ALANI YOKTUR**. Yani
    #: `Truncated` zarfı bu uçtan KURULAMAZ; hâl dürüstçe metinle bildirilir.
    risk_notu: str


class AiYetkilerim(BaseModel):
    role_key: str
    #: modül anahtarı → erişim seviyesi. 🔴 `Scope` TAŞIMAZ: enum dekoratiftir
    #: (14 isabet, hepsi `roles/`, hiçbir süzgeç okumaz) ve kapsam etiketini
    #: yetki gerekçesi diye sunmak ekranın bugünkü yalanını AI'a taşırdı (S1).
    permissions: dict[str, str]
    #: 🔴 `/auth/me` INNER JOIN ile beslenir (`get_role_matrix`): izin satırı
    #: OLMAYAN modülün anahtarı yanıtta HİÇ BULUNMAZ. Bu alan o eksikliği
    #: görünür kılar — yoksa model "böyle bir modül yok" der.
    yaniti_besleyen_not: str


class AiYonlendirme(BaseModel):
    ekran: EkranAnahtari
    ekran_adi: str
