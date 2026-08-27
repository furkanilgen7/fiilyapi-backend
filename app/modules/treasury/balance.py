"""Hesap bakiyesinin TEK KAYNAĞI (HZ-1 T2 — spec §3 K2).

`GET /bank-accounts`, `GET /bank-accounts/{id}` ve kart şeridi bakiyeyi
BURADAN türetir. İkinci bir formül yazılsaydı liste ile detay aynı hesap için
farklı sayı basar ve hangisinin doğru olduğu anlaşılamazdı — üstelik bakiye
SAKLANMADIĞI için hiçbir kolon aradaki farkı ele vermezdi.

## Formül (K2 + ODM-1 D2)

    bakiye(hesap) = opening_balance
                  + Σ payments.amount  (bağlı fatura direction = outgoing)
                  − Σ payments.amount  (bağlı fatura direction = incoming)
                  YALNIZ nakde GİRMİŞ ödemeler için
                  (financial_instrument_id IS NULL  VEYA
                   bağlı enstrüman status ∈ {collected, paid})

Formül ODM-1'de üçüncü bir bileşen kazandı: bir **SÜZGEÇ**
(`cash_realized_condition`). Portföydeki bir çeke bağlı ödeme satırı VARDIR
(carinin kapanması ona bağlıdır) ama o para henüz BANKADA DEĞİLDİR; süzgeç
olmasaydı kart, henüz tahsil edilmemiş çekleri nakit gibi gösterirdi ve
kullanıcı elinde olmayan parayı harcanabilir sanırdı. Çek tahsil edilince
(`collected`) ya da verilen çek ödenince (`paid`) aynı satır süzgeçten geçer
ve bakiyeye O AN girer — ikinci bir ödeme kaydı gerekmez.

Yön ödemenin KENDİ kolonundan değil, bağlı faturanın `direction`'ından gelir
(K4): giden fatura bizim kestiğimizdir → tahsilat → hesaba GİRİŞ; gelen fatura
bize kesilmiştir → ödeme → hesaptan ÇIKIŞ. Ödemede ikinci bir yön kolonu
açılsaydı iki gerçek kaynak olur ve biri diğerinden sapabilirdi.

## İki tuzak

🔴 **NULL YUTMASI.** Ödemesi olmayan hesapta `SUM()` **NULL** döner, 0 değil.
`coalesce` olmasaydı `opening_balance + NULL = NULL` olur ve kart açılış
bakiyesi yerine BOŞ basardı. Bu yüzden `coalesce` ŞARTTIR ve testi ayrıdır.

🔴 **N+1.** Hesap başına bakiye sorgusu koşan bir uygulama 3 kartta fark
ettirmez, 20 hesapta patlar. Bu yüzden dışarıya verilen API **TOPLUdur**:
`balances_for()` tek sorguda sözlük döner, `select_accounts_with_balance()`
ise satır + bakiyeyi tek `Select`te birleştirir. `test_hz1_balance.py` iki
uygulamayı da `before_cursor_execute` sayacıyla ÖLÇER.

Para her yerde `Decimal`dir; kayan nokta hiçbir aşamada devreye girmez
(`Numeric(18,2)` → `Decimal`). Hareket tablosu (HZ-3) geldiğinde bu formüle
YALNIZ bir terim eklenir — kolon göçü gerekmez (`inventory/balance.py` emsali).
"""

import uuid
from collections.abc import Sequence
from decimal import Decimal

from sqlalchemy import ColumnElement, Select, Subquery, case, func, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.invoicing.models import Invoice, InvoiceDirection
from app.modules.treasury.models import (
    BankAccount,
    FinancialInstrument,
    FinancialInstrumentStatus,
    Payment,
)

ZERO = Decimal("0")
"""Ödemesiz hesabın `SUM()` NULL'ının yerine geçen nötr eleman."""


def inflow_condition() -> ColumnElement[bool]:
    """🔴 YÖNÜN TEK KAYNAĞI: ödeme hesaba GİRİŞ mi (K2/K4)?

    Giden fatura bizim kestiğimizdir → tahsilat → GİRİŞ; gelen fatura bize
    kesilmiştir → ödeme → ÇIKIŞ. Koşul burada TEK KEZ yazılır çünkü onu okuyan
    iki yer vardır: bakiye (`signed_legs`, T2) ve nakit akışı serisi
    (`cash_flow.py`, T5). İkinci bir yerde `direction == outgoing` yazılsaydı
    biri bir gün değişir, öteki kalır ve grafik ile kart TERS işaret basardı —
    üstelik ikisi de "bir sayı" gösterdiği için kusur ekranda görünmezdi.
    """
    return Invoice.direction == InvoiceDirection.outgoing


#: Enstrümanın "para gerçekten el değiştirdi" damgaları (ODM-1 D2). Demet
#: BURADA tek kez yazılır: `portfolio`/`returned`/`cancelled`i tek tek dışlayan
#: bir NOT IN yazılsaydı, enum'a ileride eklenecek YENİ bir ara durum (örn.
#: "bankaya teminata verildi") sessizce NAKİT sayılırdı. Beyaz liste
#: fail-closed'dır: tanınmayan her durum nakit DEĞİLDİR.
REALIZED_INSTRUMENT_STATUSES = (
    FinancialInstrumentStatus.collected,
    FinancialInstrumentStatus.paid,
)


def cash_realized_condition() -> ColumnElement[bool]:
    """🔴 NAKDİN TEK KAYNAĞI: ödeme gerçekten nakde GİRDİ Mİ (ODM-1 D2)?

        bağsız ödeme (financial_instrument_id IS NULL)  → DAİMA nakit
        bağlı ödeme, enstrüman collected|paid           → nakit
        bağlı ödeme, enstrüman portfolio|returned|cancelled → nakit DEĞİL (0)

    🔴 **Tetikleyici BAĞDIR, `method` ETİKETİ DEĞİL (D1).** `method='cheque'`
    yazıp hiçbir enstrümana bağlanmamış ödeme NAKİTTİR ve bakiyeye girer.
    Gerekçe üç katlıdır: (a) FIN-1 K4 — etiket ile varlık AYRI iki olgudur ve
    biri ötekini İMA ETMEZ; (b) bağsız çekin bir "tahsil olayı" YOKTUR, `method`e
    bağlansaydı o para bakiyeye BİR DAHA hiç giremezdi (onu geri getirecek uç
    yok — kalıcı kayıp); (c) canlıdaki mevcut `method='cheque'` satırlarının
    hepsi bağsızdır, `method`e bağlamak canlı bakiyeleri SESSİZCE değiştirirdi.

    Koşul `inflow_condition` ile TAM AYNI gerekçeyle tek kopyadır: onu okuyan
    İKİ yüzey vardır — bakiye (`signed_legs`; kart/liste/detay) ve nakit akışı
    serisi (`cash_flow.py`; grafik). İkinci bir yerde `status IN (...)`
    yazılsaydı biri bir gün değişir, öteki kalır ve kullanıcı AYNI ekranda aynı
    çek için farklı iki nakit okurdu — ikisi de "bir sayı" bastığı için kusur
    görünmezdi.

    🔴 Bu yüklem `FinancialInstrument` satırına başvurur; onu sorguya
    **`join_instrument()` ile** bağlayın (OUTER olmak ZORUNDA, gerekçesi orada).
    """
    return or_(
        Payment.financial_instrument_id.is_(None),
        FinancialInstrument.status.in_(REALIZED_INSTRUMENT_STATUSES),
    )


def join_instrument(stmt: Select) -> Select:
    """`payments` → `financial_instruments` **OUTER** join (ODM-1 D2).

    🔴 **OUTER olmak ZORUNDADIR.** `financial_instrument_id` NULLABLE'dır (FIN-1
    K4) ve canlıdaki ödemelerin EZİCİ ÇOĞUNLUĞU bağsızdır. INNER olsaydı bağsız
    ödemelerin HEPSİ sorgudan düşer, nakit birdenbire (neredeyse) SIFIRLANIRDI —
    üstelik hata mesajı çıkmaz, kartlar sadece açılış bakiyesini basardı.
    `signed_legs.join(Invoice)` INNER'dır çünkü `invoice_id` NOT NULL'dır; buradaki
    bağ isteğe bağlı olduğu için gerekçe TERSİNE döner. Bekçisi:
    `test_odm1_cash_definition.py::test_BAGSIZ_odeme_nakittir_OUTER_JOIN_BEKCISI`.
    """
    return stmt.outerjoin(
        FinancialInstrument, FinancialInstrument.id == Payment.financial_instrument_id
    )


def signed_legs() -> Subquery:
    """KANONİK kaynak: `(bank_account_id, İŞARETLİ ve SÜZÜLMÜŞ amount)` ikilileri.

    İşaret bağlı faturanın yönünden gelir (K4, `inflow_condition`); tutarın
    bakiyeye KATILIP katılmayacağını ise `cash_realized_condition` (ODM-1 D2)
    söyler — portföydeki çeke bağlı ödeme **0** katar.

    `join(Invoice)` INNER'dır ve öyle kalır: `payments.invoice_id` NOT NULL +
    RESTRICT FK olduğu için faturasız ödeme YAPISAL OLARAK imkânsızdır — OUTER
    yapmak var olmayan bir satır sınıfı için yönsüz (dolayısıyla işaretsiz) bir
    dal açardı. Enstrüman bağı ise tam TERSİ gerekçeyle OUTER'dır
    (`join_instrument`).

    🔴 Süzülen satır sorgudan ATILMAZ, **0** katar (`case`/`else_`). `where` ile
    atılsaydı yalnız portföy çeki olan bir hesap `net_payments` çıktısında hiç
    görünmez, `coalesce` devreye girer ve sonuç yine doğru olurdu — ama bu
    denklik tesadüfidir: gruplamaya bir gün ikinci bir toplam eklendiğinde
    (örn. "bekleyen çek tutarı") atılan satır ORADAN da eksilirdi.
    """
    isaretli = case((inflow_condition(), Payment.amount), else_=-Payment.amount)
    nakit = case((cash_realized_condition(), isaretli), else_=literal(ZERO))
    return join_instrument(
        select(
            Payment.bank_account_id.label("bank_account_id"),
            nakit.label("amount"),
        ).join(Invoice, Invoice.id == Payment.invoice_id)
    ).subquery()


def net_payments() -> Subquery:
    """Hesap başına NET ödeme toplamı.

    Gruplama `bank_account_id` üzerindedir: kaldırılsaydı tek bir toplam tüm
    hesaplara dağılır ve her kart aynı sayıyı basardı.
    """
    bacaklar = signed_legs()
    return (
        select(
            bacaklar.c.bank_account_id.label("bank_account_id"),
            func.sum(bacaklar.c.amount).label("net"),
        )
        .group_by(bacaklar.c.bank_account_id)
        .subquery()
    )


def balance_column(net: Subquery) -> ColumnElement[Decimal]:
    """`opening_balance + coalesce(net, 0)` — bakiye ifadesinin TEK yazımı."""
    return (BankAccount.opening_balance + func.coalesce(net.c.net, literal(ZERO))).label("balance")


def select_accounts_with_balance() -> Select:
    """Hesap satırı + türetilmiş bakiye, **TEK** sorguda.

    `outerjoin`dir: ödemesi hiç olmayan hesap listeden DÜŞMEZ, açılış
    bakiyesiyle görünür (INNER olsaydı yeni açılan her hesap kaybolurdu).
    Süzgeç/sıralama çağıran uca aittir — bu katman politika taşımaz.
    """
    net = net_payments()
    return select(BankAccount, balance_column(net)).outerjoin(
        net, net.c.bank_account_id == BankAccount.id
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
    net = net_payments()
    stmt = (
        select(BankAccount.id, balance_column(net))
        .outerjoin(net, net.c.bank_account_id == BankAccount.id)
        .where(BankAccount.id.in_(account_ids))
    )
    rows = (await session.execute(stmt)).all()
    return {account_id: bakiye for account_id, bakiye in rows}
