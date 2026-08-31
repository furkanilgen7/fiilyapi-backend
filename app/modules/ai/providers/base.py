"""Sağlayıcı-BAĞIMSIZ olay sözleşmesi (spec §2.2 KATMAN 7).

Bu dosyanın tek işi şudur: **döngü hiçbir sağlayıcının gövde şeklini görmez.**
`loop.py` yalnız buradaki olayları tüketir; OpenAI'ın `delta.tool_calls`ı,
Anthropic'in `content_block_delta`sı ya da Gemini'nin `functionCall`ı buraya
kadar gelmez.

## 🔴 `finish_reason` TEK ALANA İNDİRGENMEZ

Üç sağlayıcı bitiş sebebini farklı sayıda ve farklı anlamda hâlle bildirir.
Hepsini `"stop"`/`"other"` ikilisine ezmek, kullanıcıya **yanlış** cümle
kurdurur: içerik süzgecine takılan bir yanıt ile modelin işini bitirdiği bir
yanıt aynı ekrana düşerse panel "cevap bu" der ve **yalan söyler**. Bu yüzden
`TurSebebi` altı üyeyle açılır ve her adaptör kendi ham sebebini bu kümeye
**eşlemek** zorundadır; eşlenemeyen ham değer `kesildi`ye düşer (fail-closed:
"bitti" demek en tehlikeli varsayılandır).

## 🔴 ARAYÜZ `temperature`/`top_p`/`top_k`/prefill VAAT ETMEZ

Ölçülmüş sebep: bu üç örnekleme parametresi sağlayıcılar arasında **taşınmaz**.
Anthropic `temperature` ile `top_p`in birlikte gönderilmesini 400 ile reddeder,
`top_k`i yalnız o taşır; asistan mesajını önceden doldurma (prefill) OpenAI'da
karşılıksızdır. Ortak arayüzün taşıyamayacağı bir alanı arayüze koymak, "her
sağlayıcıda çalışır" diye yazılmış bir çağrı yerinin ikinci sağlayıcıda 400
almasıdır. Bu yüzden `tur()` imzasında bu adlar **yoktur**; bekçisi
`test_ai1_saglayici.py::test_B_ARAYUZ_ornekleme_parametresi_VAAT_ETMEZ`.

## Yapısal çıktı YALNIZ araç şeması düzeyinde

`arac_semasi()` `strict` bir JSON Schema üretir (`additionalProperties: false`,
tüm alanlar `required`). Yanıtın kendisi JSON'a **zorlanmaz**: modelin
kullanıcıya yazdığı metin serbesttir ve `response_format` gönderilmez. Yanıtı
JSON'a zorlamak, "araç çağırmadan sayı uydurma" korkuluğunu zayıflatırdı —
model bir şema doldurmak zorunda kalınca boş alanı **uydurur**.
"""

from __future__ import annotations

import dataclasses
import enum
from collections.abc import AsyncIterator, Mapping, Sequence
from typing import Any, Protocol, runtime_checkable

from app.modules.ai.blocks import YapisalBlok
from app.modules.ai.registry import ToolSpec


class TurSebebi(str, enum.Enum):
    """Bir turun **neden** bittiği. Altı hâl; hiçbiri diğerinin yerine geçmez."""

    #: Model işini bitirdi, söyleyecek başka şeyi yok.
    bitti = "bitti"
    #: Model araç çağırmak istiyor — tur DEVAM eder.
    arac = "arac"
    #: Tavana/uzunluğa takıldı ya da bağlantı koptu. Cevap **eksiktir**.
    kesildi = "kesildi"
    #: Model isteği reddetti (güvenlik/politika). Bu bir HATA DEĞİLDİR.
    reddetme = "reddetme"
    #: Sağlayıcı turu askıya aldı (dış araç/insan girdisi bekliyor).
    duraklatildi = "duraklatildi"
    #: İçerik süzgeci yanıtı kesti. `bitti` ile aynı ekrana DÜŞMEZ.
    filtrelendi = "filtrelendi"


@dataclasses.dataclass(frozen=True, slots=True)
class Kullanim:
    """Token kullanımı. Sağlayıcı bildirmezse alanlar `None` kalır — **0 DEĞİL**.

    0 yazmak "hiç token harcanmadı" demektir ve bu ölçülmüş bir olgu değil,
    uydurulmuş bir sayıdır.
    """

    girdi: int | None = None
    cikti: int | None = None


@dataclasses.dataclass(frozen=True, slots=True)
class AiOlay:
    """Akışta taşınan olayın ortak tabanı."""

    @property
    def olay_adi(self) -> str:
        """SSE `event:` alanına giden ad — sınıf adından TÜRETİLMEZ değil, türetilir.

        Sınıf adı değişirse akış sözleşmesi de değişir; bunu görünür kılmak için
        bekçi olay adlarını **sabit bir kümeyle** karşılaştırır.
        """
        return _OLAY_ADLARI[type(self)]


@dataclasses.dataclass(frozen=True, slots=True)
class MetinParcasi(AiOlay):
    metin: str


@dataclasses.dataclass(frozen=True, slots=True)
class AracCagrisiBasladi(AiOlay):
    cagri_id: str
    arac_adi: str


@dataclasses.dataclass(frozen=True, slots=True)
class AracArgumanParcasi(AiOlay):
    """Argüman JSON'unun **parçası**. Panel bunu ekrana basmaz, biriktirir."""

    cagri_id: str
    parca: str


@dataclasses.dataclass(frozen=True, slots=True)
class AracCagrisiHazir(AiOlay):
    cagri_id: str
    arac_adi: str
    argumanlar: Mapping[str, Any]


@dataclasses.dataclass(frozen=True, slots=True)
class TurBitti(AiOlay):
    sebep: TurSebebi
    kullanim: Kullanim


@dataclasses.dataclass(frozen=True, slots=True)
class Reddetme(AiOlay):
    """Model isteği reddetti. 🔴 `Hata` DEĞİL: kullanıcıya farklı cümle kurulur."""

    metin: str


@dataclasses.dataclass(frozen=True, slots=True)
class Hata(AiOlay):
    kod: str
    mesaj: str


@dataclasses.dataclass(frozen=True, slots=True)
class AracSonuclandi(AiOlay):
    """🔴 SAĞLAYICI OLAYI **DEĞİL** — yalnız `loop.py` üretir.

    Panelin `AiToolTrace`i bunu basar: her araç çağrısı ve **hangi zarf hâliyle**
    döndüğü ekranda görünür. Bu, prompt enjeksiyonuna karşı kullanıcıya dönük
    korkuluktur (spec §6 korkuluk (c)); modelin özetine güvenmek yerine kullanıcı
    ham hâli görür.

    Bir sağlayıcı adaptörünün bunu üretmesi bir **hata**dır ve bekçisi vardır
    (`SAGLAYICI_OLAYLARI` kümesi).
    """

    cagri_id: str
    arac_adi: str
    hal: str
    mesaj: str
    satir_sayisi: int | None = None


@dataclasses.dataclass(frozen=True, slots=True)
class YapisalBloklar(AiOlay):
    """🔴 SAĞLAYICI OLAYI **DEĞİL** — `AracSonuclandi` gibi yalnız `loop.py` üretir.

    Mockup'ın metrik kartları / kâr barı / stok kartları / "Kaynak" rozetleri bu
    olaydan çizilir. Bloklar **araç sonucunun yapısal gövdesinden** üretilir
    (`presenters.py`); modelin yazdığı hiçbir bayt okunmaz. Bir sağlayıcı
    adaptörünün bunu üretmesi bir HATADIR ve bekçisi `SAGLAYICI_OLAYLARI`dır.

    Blok listesi BOŞSA olay hiç yayılmaz — boş bir kart iskeleti basmak
    "veri var ama gelmedi" yalanını söylerdi.
    """

    cagri_id: str
    arac_adi: str
    bloklar: tuple[YapisalBlok, ...]


_OLAY_ADLARI: dict[type, str] = {
    MetinParcasi: "metin",
    AracCagrisiBasladi: "arac_basladi",
    AracArgumanParcasi: "arac_arguman",
    AracCagrisiHazir: "arac_hazir",
    AracSonuclandi: "arac_sonuc",
    YapisalBloklar: "yapisal_blok",
    TurBitti: "tur_bitti",
    Reddetme: "reddetme",
    Hata: "hata",
}

#: 🔴 Bir **sağlayıcının** üretmesine izin verilen olaylar. `AracSonuclandi`
#: bilerek DIŞARIDA: araç sonucunu sağlayıcı değil huni bilir.
SAGLAYICI_OLAYLARI: frozenset[type] = frozenset(
    {
        MetinParcasi,
        AracCagrisiBasladi,
        AracArgumanParcasi,
        AracCagrisiHazir,
        TurBitti,
        Reddetme,
        Hata,
    }
)


@dataclasses.dataclass(frozen=True, slots=True)
class Mesaj:
    """Sağlayıcıya giden **tek** mesaj şekli.

    🔴 `rol` kapalı bir kümedir (`kullanici` · `asistan` · `arac`). Sistem mesajı
    bu listede TAŞINMAZ; `tur(sistem=...)` ile ayrı geçer — böylece "geçmişe bir
    sistem mesajı enjekte etme" yolu şeklen kapanır (B7'nin ikinci kilidi).
    """

    rol: str
    icerik: str
    #: `rol == "asistan"` iken modelin istediği araç çağrıları.
    arac_cagrilari: tuple[AracCagrisiHazir, ...] = ()
    #: `rol == "arac"` iken hangi çağrıya cevap olduğu.
    cagri_id: str | None = None
    arac_adi: str | None = None


ROLLER: frozenset[str] = frozenset({"kullanici", "asistan", "arac"})


@runtime_checkable
class LLMProvider(Protocol):
    """Sağlayıcı sözleşmesi.

    ⚠️ **İmza notu (dürüstlük):** `tur` burada `def ... -> AsyncIterator[AiOlay]`
    olarak beyan edilir, `async def` olarak DEĞİL. Sebep dilin kendisidir: bir
    `async def` + `yield` gövdesi bir **async üreteçtir** ve çağrıldığında
    beklenmeden yineleyici döner; protokol üyesini `async def` yazmak "önce
    await et, sonra yineleyici al" anlamına gelir ve hiçbir async üreteç bunu
    karşılamaz. Uygulamalar (`OpenAIProvider.tur`) `async def ... ->
    AsyncIterator[AiOlay]` biçiminde yazılır — yani emrin istediği okunuş
    çağrı yerinde birebir korunur.
    """

    #: Sağlayıcının kanonik adı (`factory.TANINAN_SAGLAYICILAR` üyesi).
    ad: str

    def arac_semasi(self, spec: ToolSpec) -> dict[str, Any]:
        """`ToolSpec`i sağlayıcının araç şemasına çevirir (`strict`)."""
        ...

    def tur(
        self,
        *,
        sistem: str,
        gecmis: Sequence[Mesaj],
        araclar: Sequence[ToolSpec],
    ) -> AsyncIterator[AiOlay]:
        """Tek bir model turunu akıtır."""
        ...


def girdi_semasi(spec: ToolSpec) -> dict[str, Any]:
    """`ToolSpec.girdi` pydantic modelinden **strict** JSON Schema üretir.

    OpenAI `strict: true` iki şeyi şart koşar: `additionalProperties: false` ve
    **her** özelliğin `required` içinde olması. Pydantic ikisini de kendiliğinden
    üretmez (opsiyonel alanlar `required` dışında kalır), bu yüzden şema burada
    sertleştirilir. `$defs` referansları da gezilir — iç içe bir model tek
    seviyeli bir düzeltmede sessizce gevşek kalırdı.
    """
    sema = spec.girdi.model_json_schema()
    _sertlestir(sema)
    for alt in (sema.get("$defs") or {}).values():
        _sertlestir(alt)
    return sema


def _sertlestir(dugum: dict[str, Any]) -> None:
    if dugum.get("type") != "object":
        return
    dugum["additionalProperties"] = False
    ozellikler = dugum.get("properties") or {}
    dugum["required"] = sorted(ozellikler)


__all__ = [
    "AiOlay",
    "AracArgumanParcasi",
    "AracCagrisiBasladi",
    "AracCagrisiHazir",
    "AracSonuclandi",
    "Hata",
    "Kullanim",
    "LLMProvider",
    "Mesaj",
    "MetinParcasi",
    "ROLLER",
    "Reddetme",
    "SAGLAYICI_OLAYLARI",
    "TurBitti",
    "TurSebebi",
    "girdi_semasi",
]
