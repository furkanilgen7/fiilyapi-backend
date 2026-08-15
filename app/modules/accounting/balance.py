"""Hesap bakiyesinin TEK KAYNAĞI (MU-1 spec §6, K3) — `treasury/balance.py` deseni.

`GET /chart-of-accounts`, `GET /chart-of-accounts/{id}` ve (T3b'de) mizan/defter
bakiyeyi BURADAN türetir. İkinci bir formül yazılsaydı liste ile detay aynı
hesap için farklı sayı basar, üstelik **bakiye SAKLANMADIĞI için hiçbir kolon
farkı ele vermezdi** (HP:61 `Bakiye (₺)` bir kolon DEĞİLDİR).

## Formül (K3)

    net(hesap) = COALESCE(Σ journal_lines.debit − Σ journal_lines.credit, 0)
                 WHERE journal_entries.status IN POSTING_STATUSES
    bakiye     = SIGN[account_type] * net

## 🔴 Üç tuzak

**1. `POSTING_STATUSES` — bu dilimin en sinsi tuzağı.** `draft` GİRMEZ ama
`reversed` **GİRER**:

| | Orijinal | Storno | Net |
|---|---|---|---|
| Yalnız `posted` sayılsaydı | **düşer** | ters bacaklar eklenir | **−orijinal** ❌ |
| `posted + reversed` sayılınca | kalır (+X) | eklenir (−X) | **0** ✅ |

K2'nin mali iz kanonu budur: kayıtlaştırılmış fiş defterden ÇIKMAZ, yalnız ters
kaydıyla NÖTRLENİR. Küme burada TEK kopyadır; T3b'nin defter/özet yolları da
onu okur.

**2. NULL YUTMASI.** Yevmiye satırı olmayan hesapta `SUM()` **NULL** döner, `0`
değil. `COALESCE` olmasaydı kart bakiye yerine BOŞ basardı — ve yeni açılan HER
hesap bu hâldedir, yani kusur ekranın tamamını boşaltırdı. Testi ayrıdır
(`test_satirsiz_hesapta_bakiye_SIFIRDIR_null_degil`).

**3. N+1.** Hesap başına bakiye sorgusu 3 hesapta fark ettirmez, 200 hesaplık
bir tekdüzen hesap planında patlar. Bu yüzden dışarıya verilen API **TOPLUdur**:
`balances_for()` tek sorguda sözlük döner, `select_accounts_with_balance()` ise
satır + bakiyeyi tek `Select`te birleştirir. `test_mu1_balance.py` iki uygulamayı
da `before_cursor_execute` sayacıyla ÖLÇER.

Para her yerde `Decimal`dir; kayan nokta hiçbir aşamada devreye girmez
(`Numeric(18,2)` → `Decimal`). Bu modül BAŞKA BİR MODÜLÜ IMPORT ETMEZ.

## İşaret neden TÜRDEN okunur

`320` Satıcılar (Pasif) ekranda `2.184.000` basar (HP:164) ama ham `net`i
**−2.184.000**dır: alacak bakiyesi verir. `600` Gelir, `730`/`760` Gider ve
`100`…`191` Aktif hesapların hepsi ekranda POZİTİFTİR. Tek uymayan `257`nin
parantezidir ve onun kaynağı `account_type` DEĞİL adın `(-)` son ekidir — bir
SUNUM kuralıdır, `is_contra` kolonu AÇILMAZ (spec §1c, K-Ş2).
"""

import uuid
from collections.abc import Sequence
from decimal import Decimal

from sqlalchemy import ColumnElement, Select, Subquery, case, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounting.models import (
    ChartAccount,
    ChartAccountType,
    JournalEntry,
    JournalEntryStatus,
    JournalLine,
)

__all__ = [
    "POSTING_STATUSES",
    "SIGN",
    "ZERO",
    "balance_column",
    "balances_for",
    "net_by_account",
    "net_expression",
    "posting_filter",
    "select_accounts_with_balance",
    "sign_case",
]

ZERO = Decimal("0")
"""Satırı olmayan hesabın `SUM()` NULL'ının yerine geçen nötr eleman."""

POSTING_STATUSES: tuple[JournalEntryStatus, ...] = (
    JournalEntryStatus.posted,
    JournalEntryStatus.reversed,
)
"""🔴 Bakiyeye giren fiş durumları — **TEK KOPYA** (modül docstring'i, madde 1).

`draft` yoktur: yarım bırakılmış bir fiş mizanı kirletmemelidir. `reversed`
VARDIR ve çıkarılamaz: çıkarılırsa stornolanmış fiş defterden düşer, storno
ters bacaklarıyla eklenir ve net **−orijinal** çıkar (çift ters kayıt).
"""

SIGN: dict[ChartAccountType, int] = {
    ChartAccountType.asset: 1,
    ChartAccountType.expense: 1,
    ChartAccountType.liability: -1,
    ChartAccountType.revenue: -1,
}
"""K3 işaret kuralı — dört türün HEPSİ burada olmak zorundadır.

Eksik bir tür `sign_case()`te `else_` dalı OLMADIĞI için **NULL** üretir ve
yanıt şeması onu okurken GÜRÜLTÜLÜ biçimde patlar. Bilinçlidir: sessizce `0`
ya da `+1` varsaymak, o türdeki her hesabın bakiyesini yanlış basardı ve hiçbir
kolon farkı ele vermezdi.
"""


def posting_filter() -> ColumnElement[bool]:
    """Bakiyeye giren fişlerin süzgeci — `POSTING_STATUSES`in TEK kullanıcısı.

    Ayrı yerlerde `status == posted` yazılsaydı biri `reversed`i unutur ve
    yalnız o yolda çift ters kayıt doğardı.
    """
    return JournalEntry.status.in_(POSTING_STATUSES)


def net_expression() -> ColumnElement[Decimal]:
    """Ham nicelik: `Σ debit − Σ credit`. İşaret dönüşümü YOK (bkz. `sign_case`).

    🔴 `COALESCE` burada da vardır: ifade ileride (T3b defteri) satırsız bir
    kümede tek başına kullanılabilir ve `SUM()` NULL dönerdi.

    İki toplam TEK ifadededir; ayrı okunsaydı biri süzgeci alır öteki almazdı.
    """
    return func.coalesce(func.sum(JournalLine.debit) - func.sum(JournalLine.credit), literal(ZERO))


def net_by_account() -> Subquery:
    """Hesap başına ham `net` — kaç hesap olursa olsun TEK gruplu sorgu.

    Gruplama `account_id` üzerindedir: kaldırılsaydı tek bir toplam tüm
    hesaplara dağılır ve her satır aynı sayıyı basardı.

    `join` INNER'dır ve öyle kalır: `journal_lines.entry_id` NOT NULL + CASCADE
    FK olduğu için başlıksız satır YAPISAL OLARAK imkânsızdır. Satırı hiç
    olmayan hesabın kaybolması bir sorun değildir — dışarıdaki `outerjoin`
    onu `COALESCE` ile 0'a düşürür.
    """
    return (
        select(
            JournalLine.account_id.label("account_id"),
            net_expression().label("net"),
        )
        .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
        .where(posting_filter())
        .group_by(JournalLine.account_id)
        .subquery()
    )


def sign_case() -> ColumnElement[int]:
    """`SIGN` sözlüğünün SQL karşılığı — sözlükten ÜRETİLİR, elle yazılmaz.

    🔴 `else_` dalı BİLİNÇLİ OLARAK YOKTUR: enum'a beşinci bir üye eklenip
    `SIGN`a eklenmezse ifade NULL üretir ve yanıt gürültülü biçimde patlar.
    `else_=1` yazılsaydı o türdeki her hesabın bakiyesi sessizce ters basılırdı.
    """
    return case(
        *[(ChartAccount.account_type == tur, literal(isaret)) for tur, isaret in SIGN.items()]
    )


def balance_column(net: Subquery) -> ColumnElement[Decimal]:
    """`SIGN[tür] * COALESCE(net, 0)` — bakiye ifadesinin TEK yazımı.

    🔴 Dıştaki `COALESCE` ŞARTTIR ve içteki (`net_expression`) onun yerine
    GEÇMEZ: `outerjoin` eşleşmeyen hesapta alt sorgunun sütununu NULL yapar,
    yani satırı olmayan hesabın bakiyesi buradan NULL çıkardı.

    Çarpım `COALESCE` ile BAŞLAR ki sonuç tipi `Numeric` kalsın; işaret sola
    alınsaydı ifade tam sayı tipine düşebilir ve kuruşlar yuvarlanabilirdi.
    """
    return (func.coalesce(net.c.net, literal(ZERO)) * sign_case()).label("balance")


def select_accounts_with_balance() -> Select:
    """Hesap satırı + türetilmiş bakiye, **TEK** sorguda.

    `outerjoin`dir: yevmiye satırı hiç olmayan hesap listeden DÜŞMEZ, `0`
    bakiyeyle görünür (INNER olsaydı yeni açılan her hesap kaybolur ve boş bir
    hesap planı hiç doldurulamazdı).

    Süzgeç/sıralama/sayfalama çağıran uca aittir — bu katman politika taşımaz.
    """
    net = net_by_account()
    return select(ChartAccount, balance_column(net)).outerjoin(
        net, net.c.account_id == ChartAccount.id
    )


async def balances_for(
    session: AsyncSession, account_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, Decimal]:
    """Verilen hesapların bakiyeleri — kaç hesap olursa olsun **TEK** sorgu.

    Boş listede hiç sorgu koşmaz (`IN ()` üretmek yerine erken döner).
    Bulunamayan kimlik sözlükte yer almaz; çağıran 404'ü kendi verir.
    """
    if not account_ids:
        return {}
    net = net_by_account()
    stmt = (
        select(ChartAccount.id, balance_column(net))
        .outerjoin(net, net.c.account_id == ChartAccount.id)
        .where(ChartAccount.id.in_(account_ids))
    )
    rows = (await session.execute(stmt)).all()
    return {account_id: bakiye for account_id, bakiye in rows}
