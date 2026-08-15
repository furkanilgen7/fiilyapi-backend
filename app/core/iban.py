"""IBAN normalizasyonu + biçim/mod-97 doğrulaması — **TEK KAYNAK**.

## Neden burada (ve neden tek yerde)

Canlı smoke'ta `POST /bank-accounts` gövdesine `BUNUBIRIBANDEGIL!!` gönderildi
ve **201** döndü; `TR` + 24 sıfır da kabul edildi. Ne uzunluk, ne ülke kodu, ne
sağlama vardı. Alan bir PARA yüzeyidir: ödeme talimatı buradan çıkar ve yanlış
bir hesap numarası hiçbir aşağı katmanda yakalanmaz.

Gerçek `iban` KOLONU repoda İKİ tablodadır — `bank_accounts.iban` (hazine) ve
`personnel.iban` (bordro) — ve giriş noktası DÖRTtür (her tablo için Create +
Update). Kural dört yere kopyalansaydı biri güncellenip öteki unutulur, kapı o
uçtan atlatılırdı; bu yüzden kural TEK modüldedir ve dört şema da buradan çağırır
(`app/core/text.py`nin paylaşılan tavan emsali).

## Kurallar

* `None` → `None`. Kolon her iki tabloda da **nullable'dır ve öyle kalır**:
  E9:83'te Kasa satırının IBAN'ı yoktur, personelde ise elden ödeme meşrudur.
  Bu düzeltme alanı ZORUNLU yapmaz — yalnız DOLU geldiğinde biçimi sınar.
* Boş/yalnız boşluk → `None`. Boş metin saklansaydı `uq_bank_accounts_iban`
  KISMİ indeksi (`WHERE iban IS NOT NULL`) onu "dolu" sayar ve ikinci boş-IBAN'lı
  kasa 409 alırdı (mevcut hazine davranışı korunur).
* Dolu değer: tüm boşluklar atılır, harfler BÜYÜTÜLÜR (saklama biçimi
  NORMALİZEDİR — aynı IBAN iki kayıtta iki türlü durmasın), sonra
  `^[A-Z]{2}[0-9]{2}[A-Z0-9]{11,30}$` **ve** ISO 13616 mod-97 == 1.
* `TR` için uzunluk **tam 26**'dır (ISO 13616 kayıt defteri). Ülkeye özgü
  uzunluk mod-97'den AYRI bir kapıdır: sağlaması tutan 27 haneli bir "TR"
  IBAN'ı üretmek kolaydır ve yalnız sağlamaya bakılsaydı geçerdi.

## Kapsam DIŞI (bilinçli)

* **Mevcut veri doğrulanmaz/temizlenmez.** Bu modül yalnız YENİ girişleri
  kapatır; geçmiş bozuk kayıtların taranması ayrı bir iştir (şema değişmez,
  migration yazılmaz).
* Ülke kodunun ISO 3166 kayıt defterinde OLUP OLMADIĞI denetlenmez ve TR
  dışındaki ülkeler için uzunluk tablosu tutulmaz: repo TR odaklıdır, eksik bir
  tablo meşru bir yabancı IBAN'ı sessizce reddederdi. Biçim + mod-97 o durumda
  da koşar.
"""

import re

from pydantic import field_validator

__all__ = [
    "IBAN_INVALID",
    "iban_field_validator",
    "normalize_iban",
    "validate_iban",
]

#: Kullanıcıya dönen TEK mesaj. Hangi kapının (uzunluk/biçim/sağlama) düştüğü
#: SÖYLENMEZ: ayrıştırılmış mesaj, geçerli bir IBAN'ı deneme-yanılma ile
#: üretmek isteyene sağlama hanesini tek tek aratırdı ve kullanıcıya da bir şey
#: kazandırmazdı — düzeltilecek şey her hâlükârda "IBAN'ı doğru gir"dir.
IBAN_INVALID = "IBAN geçersiz: biçim ya da sağlama hatası"

#: ISO 13616: 2 harf ülke + 2 rakam sağlama + 11-30 alfanümerik BBAN
#: (toplam 15-34). `max_length=34` şemalarda ayrıca durur; buradaki tavan
#: şemadan BAĞIMSIZ ikinci kattır (savunma derinliği).
_IBAN_PATTERN = re.compile(r"^[A-Z]{2}[0-9]{2}[A-Z0-9]{11,30}$")

#: ISO 13616 kayıt defteri — TR IBAN'ı TAM 26 hanedir.
_ULKE_UZUNLUKLARI = {"TR": 26}


def normalize_iban(iban: str | None) -> str | None:
    """Boşluksuz + BÜYÜK harf. `None` ve boşa dönen değer NULL'dır.

    Biçime BAKMAZ — doğrulama `validate_iban`ındır. İkisi ayrıdır çünkü
    normalizasyon servis katmanında da (yeniden) çağrılır ve orada bir
    reddediş üretmesi beklenmez.

    NULL'a dönüş bilinçlidir: Kasa satırında IBAN YOKTUR (E9:83) ve boş metin
    saklansaydı kısmi indeks onu "dolu" sayar, İKİNCİ boş-IBAN'lı kasa 409
    alırdı.
    """
    if iban is None:
        return None
    sikistirilmis = "".join(iban.split()).upper()
    return sikistirilmis or None


def _mod97(iban: str) -> int:
    """ISO 7064 MOD 97-10: ilk dört karakter sona alınır, harfler 10-35'e
    çevrilir, kalan 1 olmalıdır.

    `int(c, 36)` A→10 … Z→35 karşılığını verir; rakamlar olduğu gibi kalır.
    """
    dondurulmus = iban[4:] + iban[:4]
    sayisal = "".join(str(int(karakter, 36)) for karakter in dondurulmus)
    return int(sayisal) % 97


def validate_iban(iban: str | None) -> str | None:
    """Normalize eder ve sınar; geçersizse `ValueError` fırlatır.

    Pydantic `field_validator` içinden çağrılır, dolayısıyla reddediş istemciye
    **422** olarak döner — istisna dışarı SIZMAZ.
    """
    normalize = normalize_iban(iban)
    if normalize is None:
        return None
    if not _IBAN_PATTERN.match(normalize):
        raise ValueError(IBAN_INVALID)
    beklenen = _ULKE_UZUNLUKLARI.get(normalize[:2])
    if beklenen is not None and len(normalize) != beklenen:
        raise ValueError(IBAN_INVALID)
    if _mod97(normalize) != 1:
        raise ValueError(IBAN_INVALID)
    return normalize


def _iban_alani(cls, deger: str | None) -> str | None:  # noqa: ANN001, N805
    return validate_iban(deger)


def iban_field_validator():
    """`iban` alanına bağlanan, YENİDEN KULLANILABİLİR Pydantic doğrulayıcısı.

    Dört giriş noktası (`BankAccountCreate`/`BankAccountUpdate` ·
    `PersonnelCreate`/`PersonnelUpdate`) bunu sınıf gövdesine tek satırla
    yerleştirir. Her sınıfa elle bir `@field_validator` yazılsaydı dördünden
    birini eklemeyi unutmak SESSİZ bir açık kapı bırakırdı — kusur tam olarak
    böyle doğdu.

    Her çağrıda YENİ bir doğrulayıcı nesnesi döner: aynı nesne birden çok
    Pydantic sınıfına paylaştırılmaz.
    """
    return field_validator("iban")(classmethod(_iban_alani))
