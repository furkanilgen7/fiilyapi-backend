"""Hesap kodu dilbilgisi (MU-1 spec §1a, K4) — 🔴 **SAF** modül.

Bu dosya **DB bilmez, `today` bilmez, Pydantic bilmez**: girdisi bir metin,
çıktısı bir metin/sayıdır. Böyle olması bilinçlidir — hiyerarşi `parent_id` FK
ile DEĞİL **kodun içinde** taşındığı için (K4) kodun okunması hem şemanın
(`schemas.py` deseni), hem servisin (yaprak kuralı, K-Ş3), hem yanıtın
(`class_code`/`level`) ortak ihtiyacıdır. Üç yerde ayrı ayrı parçalansaydı biri
noktadan böler, öteki uzunluğa bakar ve `120.01`in ebeveyni bir yerde `120`,
başka bir yerde `12` çıkardı.

## Kapalı biçim kümesi (mockup'tan ÇIKARILAN, icat edilmeyen)

| Düzey | Biçim | Kanıt | Örnek |
|---|---|---|---|
| Sınıf | tek hane, 🔴 **KAYIT DEĞİL** | HP:69,135,161,187 (kodsuz bant) | `1`,`2`,`6`,`7` |
| Grup | `NN` | HP:72,97,115 | `10`,`12`,`15` |
| Ana hesap | `NNN` | HP:76…204 | `100`,`191`,`257`,`600` |
| Alt hesap | `NNN.NN` | E8:112,120,128,136,144,152 | `120.01`,`320.04` |

İlk hane `0` OLAMAZ (sınıfsız hesap yoktur) ve
🔴 **`NNN.NN.NNN` (üçüncü kırılım) hiçbir mockup'ta YOKTUR → AÇILMAZ.**
Açılsaydı mizanın (MU-2) hiç görmediği bir düzey doğar ve `level` üç değerli
olmaktan çıkardı. Desen aynı zamanda DB CHECK'inin (`models.ACCOUNT_CODE_CHECK`)
Python karşılığıdır; ikisi AYNI kümeyi tarif eder ve DB son savunmadır.

## Sınıf neden bir KAYIT değil

HP:69/135/161/187 bantlarının kod sütunu YOKTUR: bant bir başlıktır, satır
değil. Bu yüzden `parent_code("12")` **`None`**dır — `"1"` dönseydi servis var
olmayan bir ebeveyni aramaya kalkar, K-Ş3 kapısı da sınıf düzeyinde anlamsız
biçimde ısırırdı. Sınıf yalnızca GÖSTERİM için `class_code()` ile türetilir.

🔴 **K15 — satırlar kazanır:** HP:187 bandı `SINIF 5` yazıp altına `600`/`730`/
`760` dizer. `class_code` bant etiketini DEĞİL kodun ilk hanesini okur → `6`/`7`.
Aynısı HP:126 için de geçerlidir: `191` görsel olarak `15 Stoklar` bandının
altındadır ama grubu KODDAN gelir (`19`), yerleşimden değil.
"""

import re

__all__ = [
    "ACCOUNT_CODE_PATTERN",
    "GROUP_LEVEL",
    "MAIN_LEVEL",
    "SUB_LEVEL",
    "child_prefix",
    "class_code",
    "is_valid",
    "level",
    "parent_code",
]

#: Kapalı biçim kümesinin TEK yazımı. `schemas.py` bunu Pydantic `pattern`ı
#: olarak DOĞRUDAN kullanır — ikinci bir regex yazılsaydı biri gevşetilip öteki
#: unutulur ve uç, DB CHECK'inin reddedeceği bir kodu kabul ederdi (kullanıcıya
#: Türkçe 422 yerine ayrımsız bir 409 giderdi).
ACCOUNT_CODE_PATTERN = r"^(?:[1-9][0-9]|[1-9][0-9]{2}(?:\.[0-9]{2})?)$"

_ACCOUNT_CODE_RE = re.compile(ACCOUNT_CODE_PATTERN)

#: 🔴 Düzeyler KAYIT hiyerarşisini sayar, sınıfı DEĞİL: sınıf bir kayıt değildir
#: (bkz. modül docstring'i), dolayısıyla en üst KAYIT düzeyi gruptur.
GROUP_LEVEL = 1
MAIN_LEVEL = 2
SUB_LEVEL = 3

_SEPARATOR = "."


def is_valid(code: str) -> bool:
    """Kod kapalı biçim kümesine giriyor mu?

    Sorgulayıcıdır ve İSTİSNA ATMAZ: çağıranların bir kısmı (süzgeç, sıralama)
    geçersiz kodu yalnızca elemek ister. Kural ihlalini HATA olarak isteyen
    yollar `level()`/`parent_code()` üzerinden gider.
    """
    return bool(_ACCOUNT_CODE_RE.match(code))


def _require_valid(code: str) -> str:
    """Geçersiz kodda `ValueError`.

    Mesaj Türkçe DEĞİLDİR ve kullanıcıya gösterilmez: bu bir PROGRAMLAMA
    hatasıdır. Kullanıcı girdisi buraya gelmeden ÖNCE şemada (aynı desenle)
    reddedilir ve 422 alır.
    """
    if not is_valid(code):
        raise ValueError(f"invalid chart account code: {code!r}")
    return code


def class_code(code: str) -> str:
    """Kodun SINIFI — ilk hane (HP:69,135,161,187 bantlarının karşılığı).

    🔴 K15: bant ETİKETİ değil KOD okunur. `600` → `6`, `730`/`760` → `7`;
    HP:187'nin `SINIF 5` başlığı bir sunucu alanı DEĞİLDİR.
    """
    return _require_valid(code)[0]


def level(code: str) -> int:
    """Kaydın hiyerarşi düzeyi: grup `1` · ana hesap `2` · alt hesap `3`.

    Sınıf sayılmaz (kayıt değildir), bu yüzden en üst düzey `1`dir. Dördüncü bir
    değer YOKTUR: üçüncü kırılım yapısal olarak reddedilir.
    """
    _require_valid(code)
    if len(code) == 2:
        return GROUP_LEVEL
    return SUB_LEVEL if _SEPARATOR in code else MAIN_LEVEL


def parent_code(code: str) -> str | None:
    """Bir düzey yukarıdaki KAYDIN kodu; grupta **`None`**.

    `120.01` → `120` → `12` → `None`. Grubun ebeveyni yoktur çünkü sınıf bir
    kayıt değildir (modül docstring'i); `"1"` dönseydi servis her grup için var
    olmayan bir ebeveyni sorgular ve K-Ş3 kapısı sınıf düzeyinde ısırırdı.
    """
    _require_valid(code)
    if _SEPARATOR in code:
        return code.split(_SEPARATOR)[0]
    if len(code) == 3:
        return code[:2]
    return None


def child_prefix(code: str) -> str | None:
    """Alt düzeyleri arayan LIKE önekinin TEK yazımı; en alt düzeyde **`None`**.

    Önek KENDİSİYLE BAŞLAYAN her kodu kapsar, yani TORUNLARI da: `12` → `120`,
    `127` ve `120.01`. Torunlar dışlansaydı, çocuğu silinmiş ama torunu duran
    bir grup "yaprak" sanılır ve fiş satırı ona kesilebilirdi (§4c).

    `NNN.NN` altına bir şey açılamaz (üçüncü kırılım yok) → `None`. Kodun kendisi
    dönseydi çağıran, sonucu her zaman boş çıkacak bir sorgu koşardı; `None`
    çağırana "hiç sorma" der.

    ⚠️ Çağıran öneki yine de `LIKE`a verirken kaçırmalıdır (`repository`
    `_like_escape`): bugün kod yalnız rakam ve nokta taşır, ama kaçırmayı
    kurala bağlamak deseni tek yerde tutar.
    """
    _require_valid(code)
    return None if level(code) == SUB_LEVEL else code
