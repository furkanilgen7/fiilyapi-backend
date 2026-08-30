"""Araç sonucu zarfı — spec §2.2 KATMAN 5.

Modelin gördüğü **tek** veri şekli budur. Ham JSON gövdesi hiçbir zaman doğrudan
modele geçmez; her sonuç bir zarfın içinde ve `guards.py`deki **sabit cümleyle**
gider.

## Hâller ve neden HER BİRİ ayrı

| Hâl | Ne demek | Ayrılmazsa ne olur |
|---|---|---|
| `Ok` | veri var | — |
| `Empty` | kapsam içinde arandı, kayıt yok | — |
| `ScopedEmpty` | kayıt olabilir ama kapsam dışı | AI "hiç proje yok" der; **yalan** |
| `Restricted` | yetki yok | AI "kayıt yok" der; **yalan** |
| `NotFound` | o kimlikte kayıt yok *ya da* görünmüyor | varlık sızıntısı (S14) |
| `Truncated` | kısmi küme | model kısmi kümeden toplam hesaplar (B19) |
| `ToolError` | araç koşamadı | hata "veri yok"a düşer |

🔴 `Restricted` sınıfında **`data` alanı BULUNMAZ**. Kilit prompt'ta değil
ŞEKİLDEDİR: taşımadığı bir gövdeyi model "boş liste" diye sunamaz.

⚠️ **Sayım notu (dürüstlük):** spec başlığı "ALTI hâl" der ama listesi YEDİ ad
taşır (`Ok · Empty · ScopedEmpty · Restricted · NotFound · Truncated ·
ToolError`). Yedisi de burada tanımlıdır; "altı" muhtemelen `ToolError`ı bir
*başarı zarfı hâli* saymamaktan geliyor. Sayı bir ölçüt değil, isimler ölçüttür.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from app.modules.ai import guards


@dataclasses.dataclass(frozen=True, slots=True)
class AracSonucu:
    """Ortak taban. Alt sınıflar `mesaj()` ile modele giden cümleyi üretir."""

    def mesaj(self) -> str:  # pragma: no cover - soyut
        raise NotImplementedError

    def govde(self) -> dict[str, Any]:
        """Modele giden **tam** yapı: her zaman `hal` + `mesaj`, veri opsiyonel."""
        temel: dict[str, Any] = {"hal": type(self).__name__, "mesaj": self.mesaj()}
        veri = getattr(self, "data", None)
        if veri is not None:
            temel["veri"] = veri
        return temel


@dataclasses.dataclass(frozen=True, slots=True)
class Ok(AracSonucu):
    data: Any
    row_count: int

    def mesaj(self) -> str:
        return f"{self.row_count} kayıt getirildi."


@dataclasses.dataclass(frozen=True, slots=True)
class Empty(AracSonucu):
    def mesaj(self) -> str:
        return guards.BOS


@dataclasses.dataclass(frozen=True, slots=True)
class ScopedEmpty(AracSonucu):
    module: str

    def mesaj(self) -> str:
        return guards.KAPSAM_DISI_BOS.format(modul=self.module)


@dataclasses.dataclass(frozen=True, slots=True)
class Restricted(AracSonucu):
    """🔴 `data` alanı YOKTUR — bilerek. `dataclasses.fields` ile bekçilenir."""

    module: str

    def mesaj(self) -> str:
        return guards.YETKISIZ.format(modul=self.module)


@dataclasses.dataclass(frozen=True, slots=True)
class NotFound(AracSonucu):
    def mesaj(self) -> str:
        return guards.BULUNAMADI


@dataclasses.dataclass(frozen=True, slots=True)
class Truncated(AracSonucu):
    data: Any
    total: int
    returned: int

    def mesaj(self) -> str:
        return guards.KIRPILDI.format(toplam=self.total, donen=self.returned)


@dataclasses.dataclass(frozen=True, slots=True)
class ToolError(AracSonucu):
    kod: str

    def mesaj(self) -> str:
        return guards.HATA_METINLERI.get(self.kod, guards.HATA_METINLERI["ust_kaynak_hatasi"])


#: `Truncated` kurma kararı TEK YERDE. `total` bilinmiyorsa (uç `total`
#: döndürmüyorsa) `Truncated` **KURULAMAZ** — uydurulmuş bir toplam, B19'un
#: önlemeye çalıştığı yalanın ta kendisidir.
def liste_sonucu(
    *,
    data: list[Any],
    total: int | None,
    kapsam_modulu: str | None = None,
) -> AracSonucu:
    """Liste yanıtını zarfa çevirir.

    `kapsam_modulu` verilirse boş küme `Empty` değil `ScopedEmpty` olur: uç
    kapsam süzgeci taşıyorsa (`visible_projects` gibi) boşluğun sebebi "kayıt
    yok" DEĞİL "senin kapsamında yok" olabilir ve ikisi ayrılmalıdır.
    """
    if not data:
        return ScopedEmpty(kapsam_modulu) if kapsam_modulu else Empty()
    if total is not None and total > len(data):
        return Truncated(data=data, total=total, returned=len(data))
    return Ok(data=data, row_count=len(data))
