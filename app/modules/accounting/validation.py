"""🔴 **K1 — ÇİFT TARAFLI KAYIT, SERVİS KATMANI** (MU-1 spec §4, katman 1).

Yazımdan ÖNCE koşar ve **422** üretir. Katman 2 (DB CHECK'leri, `models.py`) SON
savunma olarak yerinde KALIR; ikisinden hiçbiri tek başına yetmez:

* servis kapısı olmasaydı kullanıcı, ihlal ettiği kuralı öğrenemez ve ayrımsız
  bir 409 "Veri bütünlüğü hatası" alırdı;
* DB kısıtı olmasaydı bu dosyayı çağırmayı unutan bir yol bozuk bir MALİ kaydı
  sessizce tabloya yazardı.

## Üç engel — TEK 422'de toplanır

1. `Σ debit ≠ Σ credit` → 🔴 karşılaştırma `Decimal` üzerinde **kuruş bazında
   TAM, TOLERANS YOKTUR** (HZ-1 K6). Tolerans girseydi her fişte bir kuruş kaçak
   meşrulaşır ve mizan yıl sonunda gözle görünür biçimde kayardı.
2. `len(lines) < 2` → çift taraflı kaydın tanımı gereği en az iki bacak.
   🔴 Satırsız fiş `0 = 0` olduğu için DENGELİ görünür; bu engel olmasaydı boş
   bir fiş kayıtlaştırılabilirdi ("hesap doğru, kayıt yanlış" — NULL-EŞİK
   kanonunun kardeşi).
3. Yaprak olmayan hesaba satır → §4c. Üst hesabın bakiyesi çocuklarının
   toplamıdır; hem üste hem alta kayıt atılırsa MU-2'nin mizanı **ÇİFT SAYAR**.
   Yaprak tanımı burada YENİDEN YAZILMAZ, `accounts_service.is_leaf_account()`
   çağrılır — ayrı yazılsaydı biri torunları (`12` → `120.01`) kapsamayı unutur
   ve tanım iki yerde ayrışırdı.

Engeller LİSTE olarak döner, istisna ATILMAZ: çağıran hepsini TEK 422'de
gösterir (FAT-1 `_raise_blockers` deseni). Kullanıcıya eksikleri birer birer
keşfettirmek çok satırlı bir fişte kabul edilemez.

## 🔴 NULL fail-closed BURADA DEĞİL, ŞEMADA başlar

`debit`/`credit` NULL, eksik ya da boş metin olarak gelirse istek buraya HİÇ
ULAŞMAZ: `schemas.JournalLineInput` onları zorunlu `Decimal` olarak ister
(**422**). `None`ı `0` saymak `Σ`yı sessizce dengeler ve **dengesiz fiş dengede
sayılırdı** (spec §4). Bu dosya bu yüzden `or 0` benzeri bir savunma YAZMAZ:
yazsaydı, şemadaki delik burada maskelenirdi.

## Kapı ÜÇ yolda birden koşar

`POST /journal-entries` · `PUT …/lines` · `POST …/post`. Sonuncusu bilinçli bir
TEKRARDIR (FAT-1 `gate_blockers` deseni): fiş taslakken yaprak olan bir hesabın
altına sonradan çocuk açılabilir ve o fiş artık kayıtlaştırılmamalıdır.
`reverse` kapıdan GEÇMEZ — dengeli bir `posted` fişten gelir ve kendi engelleri
409'dur (spec §7: `reverse`ün 422'si yoktur).

## Bu modül ORM'e bağlı DEĞİLDİR

`amount_blockers` satırların yalnız `.debit`/`.credit` çiftine bakar; böylece
aynı kural hem gövdedeki Pydantic satırlarından hem DB'deki `JournalLine`lardan
çağrılabilir ve "dengesiz fiş" tanımı iki yerde ayrışmaz.
"""

from collections.abc import Sequence
from decimal import Decimal
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounting import accounts_service
from app.modules.accounting.models import ChartAccount
from app.modules.accounting.transitions import JournalAction

__all__ = [
    "GATE_ACTIONS",
    "MINIMUM_LINE_COUNT",
    "MIN_LINES_REQUIRED",
    "NON_LEAF_ACCOUNT",
    "UNBALANCED",
    "amount_blockers",
    "balance_blockers",
    "leaf_blockers",
]

UNBALANCED = "Fiş dengede değil: borç ve alacak toplamları eşit olmalıdır"
MIN_LINES_REQUIRED = "Fişte en az iki satır olmalıdır"
NON_LEAF_ACCOUNT = "Fiş satırı yalnızca alt düzey hesaba kesilebilir"

#: Çift taraflı kaydın tanımı. Sabittir ve adı vardır ki iddia kodun içinde
#: çıplak bir `2` olarak kaybolmasın.
MINIMUM_LINE_COUNT = 2

#: 🔴 K1 kapısının uygulandığı DURUM İŞLEMİ — yalnız `post`. `reverse` dengeli
#: bir `posted` fişten doğar; ona kapı koymak, orijinali kayıtlaştırırken zaten
#: geçilmiş bir denetimi tekrarlamak olurdu ve spec §7'nin kod listesini
#: (reverse: 201 · 404 · 409) bozardı.
GATE_ACTIONS: frozenset[JournalAction] = frozenset({JournalAction.post})

_ZERO = Decimal("0")


class _Tutarli(Protocol):
    """Kapının ihtiyaç duyduğu ASGARİ şekil — ORM ya da Pydantic olması fark etmez."""

    debit: Decimal
    credit: Decimal


def amount_blockers(lines: Sequence[_Tutarli]) -> list[str]:
    """🔴 K1'in SAF kısmı: denge + satır sayısı. DB'ye hiç dokunmaz.

    Sıra sabittir (denge → sayı): kullanıcı aynı 422'yi iki kez aldığında
    cümlelerin yer değiştirmesi "başka bir hata" izlenimi verirdi.

    Boş kümede denge engeli ISIRMAZ (`0 == 0`) ve bu bilinçlidir: eksik olan şey
    dengeleme değil, SATIRIN KENDİSİDİR — ikisini birden söylemek kullanıcıyı
    olmayan bir tutar hatasına yönlendirirdi.
    """
    engeller: list[str] = []
    toplam_borc = sum((satir.debit for satir in lines), _ZERO)
    toplam_alacak = sum((satir.credit for satir in lines), _ZERO)
    if lines and toplam_borc != toplam_alacak:
        engeller.append(UNBALANCED)
    if len(lines) < MINIMUM_LINE_COUNT:
        engeller.append(MIN_LINES_REQUIRED)
    return engeller


async def leaf_blockers(session: AsyncSession, accounts: Sequence[ChartAccount]) -> list[str]:
    """§4c — satır kesilen hesapların HEPSİ yaprak olmalıdır.

    Tek bir engel cümlesi döner (hesap başına değil): mesaj kuralı anlatır ve
    çok satırlı bir fişte aynı cümlenin beş kez tekrarlanması okunmaz olurdu.

    Yaprak tanımı `accounts_service.is_leaf_account()`ten okunur — 🔴 TEK KAYNAK.
    """
    for account in accounts:
        if not await accounts_service.is_leaf_account(session, account):
            return [NON_LEAF_ACCOUNT]
    return []


async def balance_blockers(
    session: AsyncSession,
    lines: Sequence[_Tutarli],
    accounts: Sequence[ChartAccount],
) -> list[str]:
    """🔴 K1'in TEK kapısı — üç engeli tek listede toplar.

    Üç yazma/geçiş yolu da (POST · PUT lines · post) BURADAN geçer; ayrı ayrı
    kurulsalardı biri yaprak denetimini ya da satır sayısını atlar ve delik
    yalnız o uçta açılırdı.
    """
    return amount_blockers(lines) + await leaf_blockers(session, accounts)
