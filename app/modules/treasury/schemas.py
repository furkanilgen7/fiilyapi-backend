"""Hazine şemaları (HZ-1 T3) — banka/kasa hesabı gövde ve yanıtları.

`invoicing/schemas.py` üçlüsünün (Create/Update/Response) kardeşi.

## 🔴 `extra="forbid"` — sessiz yok sayma YOK

Gövde şemaları bilinmeyen alanı **422** ile reddeder. Gerekçe bu modülde
doğrudan PARA'dır: `balance` TÜREVDİR (K2, `balance.py`) ve saklanan bir kolonu
yoktur. Pydantic'in varsayılan davranışı gövdedeki `balance`ı SESSİZCE atmak
olurdu; istemci gönderdiği bakiyenin yazıldığını sanır, ekranda ise formülün
ürettiği başka bir sayı görürdü.

Reddedilenler: `balance` (türev) · `id` · `created_at`/`updated_at` (sunucu
damgaları) · isimsiz her alan.

## Normalizasyon: IBAN

IBAN'dan TÜM boşluklar atılır ve harfler BÜYÜTÜLÜR. Tekillik kısmi bir UNIQUE
indeksle kurulduğu için (`uq_bank_accounts_iban`) ham değer saklansaydı
`TR12 0006…` ile `TR120006…` İKİ AYRI satır olurdu ve kural sessizce
anlamsızlaşırdı. Gruplama bir GÖSTERİM kararıdır (E9:73 `TR33 0006 …`) ve
istemciye aittir; ISO 13616 alfabesi zaten büyük harftir.

## AÇILMAYAN alanlar (spec §1, icat yasağı)

Şube · hesap no · SWIFT · kart rengi · para birimi/kur · bakiye bileşenleri
(kullanılabilir/bloke) çizilmemiştir; gövdede gönderilirlerse **422**dir.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.treasury.models import BankAccountType

__all__ = [
    "BankAccountCreate",
    "BankAccountListResponse",
    "BankAccountResponse",
    "BankAccountUpdate",
    "normalize_iban",
]

#: Bilinmeyen alan = 422 (modül docstring'i). TEK sabit: her gövde şeması aynı
#: kararı taşısın, biri unutulduğunda o uçtan türev alan sızmasın.
_SIKI = ConfigDict(extra="forbid")

# Model sınırları: `bank_accounts.bank_name` String(100) · `display_name`
# String(100) · `iban` String(34) (ISO 13616 azamisi; TR'de 26).
_BANK_NAME = Field(min_length=1, max_length=100)
_DISPLAY_NAME = Field(default=None, min_length=1, max_length=100)
#: Girişte boşluklu format kabul edilir (E9:73); normalize edilince KISALIR,
#: yani 34 tavanı saklanan değer için de sağlanır.
_IBAN = Field(default=None, min_length=1, max_length=34)
#: Para ölçeği repo standardı: `Numeric(18, 2)`. Negatif MEŞRUDUR — kredili
#: mevduat hesabı eksi açılışla girilebilir ve `ge=0` bunu yasaklardı.
_OPENING_BALANCE = Field(default=Decimal("0.00"), max_digits=18, decimal_places=2)


def normalize_iban(iban: str | None) -> str | None:
    """Boşluksuz + BÜYÜK harf. `None` ve boşa dönen değer NULL'dır.

    NULL'a dönüş bilinçlidir: Kasa satırında IBAN YOKTUR (E9:83) ve boş metin
    saklansaydı kısmi indeks onu "dolu" sayar, İKİNCİ boş-IBAN'lı kasa 409
    alırdı.
    """
    if iban is None:
        return None
    sikistirilmis = "".join(iban.split()).upper()
    return sikistirilmis or None


class BankAccountCreate(BaseModel):
    """`POST /bank-accounts` (E9:70-84 kartının yazma yolu).

    `account_type` KAPALI kümedir ve yalnız iki değer taşır (K1). `display_name`
    şemada opsiyoneldir ama kural TİPE bağlıdır (`cash` → zorunlu) ve tek kaynağı
    servistedir: şemaya tipe bağlı bir validator yazılsaydı aynı kural PATCH
    yolunda İKİNCİ kez (ve birleşik değerler üzerinde farklı biçimde) yazılırdı.

    `is_active` gövdeden gelebilir çünkü kullanımdan kaldırma yolu odur (repo
    kanonu: DELETE değil `is_active=false`).
    """

    model_config = _SIKI

    bank_name: str = _BANK_NAME
    account_type: BankAccountType
    iban: str | None = _IBAN
    display_name: str | None = _DISPLAY_NAME
    opening_balance: Decimal = _OPENING_BALANCE
    is_active: bool = True


class BankAccountUpdate(BaseModel):
    """`PATCH /bank-accounts/{id}` — KISMİ gövde.

    Her alan `| None`dır ama anlamları AYRIDIR ve servis ikisini ayırır
    (`exclude_unset`): gönderilmeyen alan DEĞİŞMEZ, açıkça `null` gönderilen
    alan TEMİZLENİR. `display_name: null` bir kasada 422'dir (aşağıdaki kural
    birleşik değerler üzerinde koşar).

    `opening_balance` DEĞİŞEBİLİR (spec §4 md.4): elle düzeltme meşrudur ve
    bakiye kendiliğinden yeniden türetilir — saklanan bir bakiye olsaydı bu
    düzeltme iki sayıyı ayrıştırırdı.
    """

    model_config = _SIKI

    bank_name: str | None = Field(default=None, min_length=1, max_length=100)
    account_type: BankAccountType | None = None
    iban: str | None = _IBAN
    display_name: str | None = _DISPLAY_NAME
    opening_balance: Decimal | None = Field(default=None, max_digits=18, decimal_places=2)
    is_active: bool | None = None


class _BankAccountStored(BaseModel):
    """Yalnız SAKLANAN kolonlar — türev alan taşımaz."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    bank_name: str
    account_type: BankAccountType
    iban: str | None
    display_name: str | None
    opening_balance: Decimal
    is_active: bool
    created_at: datetime
    updated_at: datetime


class BankAccountResponse(_BankAccountStored):
    """Kart künyesi + 🔴 TÜRETİLMİŞ `balance` (K2).

    `balance` saklanan bir kolon DEĞİLDİR ve buraya `balance.py`nin TEK
    kaynağından gelir; ikinci bir formül yazılsaydı liste ile detay aynı hesap
    için farklı sayı basar ve hiçbir kolon farkı ele vermezdi.

    `opening_balance` de yanıtta DURUR: kullanıcı düzelteceği değeri görmeden
    düzeltemez ve bakiyenin nereden başladığı ekranda okunabilir olmalıdır.
    """

    balance: Decimal

    @classmethod
    def from_row(cls, account, balance: Decimal) -> "BankAccountResponse":  # noqa: ANN001
        """Satır + bakiye ikilisini TEK yerde birleştirir.

        Üç uç (liste · detay · yazma) da buradan geçer: ayrı ayrı kurulsalardı
        biri `balance`ı `opening_balance`la doldurabilir ve fark yalnız ödemeli
        hesapta ortaya çıkardı.
        """
        return cls(**_BankAccountStored.model_validate(account).model_dump(), balance=balance)


class BankAccountListResponse(BaseModel):
    """TB3 liste zarfı: `items` + `total` + `limit`/`offset` (repo kanonu)."""

    items: list[BankAccountResponse]
    total: int
    limit: int
    offset: int
