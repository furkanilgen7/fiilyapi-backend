"""Banka hesabı veri erişimi (HZ-1 T3) — yalnız SQL, karar yok.

`invoicing/repository.py` deseninin kardeşi. İki farkı vardır ve ikisi de
bilinçlidir:

🔴 **K3 — KAPSAM SÜZGECİ YOKTUR.** Hesap ŞİRKET GENELİDİR: `bank_accounts`
tablosunda `project_id`/`site_id` kolonu yoktur (E9'da hiçbir alan şantiye
göstermez). `suppliers`/`customers` emsali; erişim `treasury` izin modülüyle
denetlenir, IDOR unutulmuş DEĞİLDİR. Buraya `project_ids` parametresi eklemek
olmayan bir süzgeci varmış gibi gösterirdi.

🔴 **BAKİYE BURADA HESAPLANMAZ.** Liste `balance.select_accounts_with_balance()`
üzerine yalnız SÜZGEÇ/SIRA/SAYFA ekler; ikinci bir formül yazılsaydı liste ile
detay aynı hesap için farklı sayı basardı ve bakiye saklanmadığı için hiçbir
kolon farkı ele vermezdi.

## N+1

Liste ucu hesap sayısından BAĞIMSIZ olarak iki sorgu koşar (satırlar + sayım).
Hesap başına bakiye sorgusu 3 kartta fark ettirmez, 20 hesapta patlar —
`test_liste_N_ARTI_1_YAPMAZ` bunu `before_cursor_execute` sayacıyla ÖLÇER.
"""

import uuid
from decimal import Decimal

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.treasury.balance import select_accounts_with_balance
from app.modules.treasury.models import BankAccount, Payment

__all__ = [
    "count_accounts",
    "count_payments_for_account",
    "get_account",
    "iban_exists",
    "list_accounts_with_balance",
]


def _filtered(stmt: Select, *, is_active: bool | None) -> Select:
    """Tek süzgeç (`is_active`) — liste ve sayım AYNI yardımcıdan geçer.

    Kopya açılsaydı `total` ile gösterilen tablo zamanla ayrışır ve kart şeridi
    "eksik hesap" gösterirdi (`invoicing._filtered` dersi).
    """
    if is_active is not None:
        stmt = stmt.where(BankAccount.is_active == is_active)
    return stmt


async def list_accounts_with_balance(
    session: AsyncSession, *, is_active: bool | None, limit: int, offset: int
) -> list[tuple[BankAccount, Decimal]]:
    """Satır + TÜRETİLMİŞ bakiye, hesap sayısından bağımsız TEK sorguda.

    Sıralama DB'dedir: önce banka adı, sonra `id`. İkinci ölçüt olmasaydı aynı
    adlı iki hesap her istekte farklı sırada gelir ve sayfalar arasında satır
    kaybolup tekrarlanabilirdi.
    """
    stmt = _filtered(select_accounts_with_balance(), is_active=is_active)
    stmt = stmt.order_by(BankAccount.bank_name, BankAccount.id).limit(limit).offset(offset)
    return [(account, bakiye) for account, bakiye in (await session.execute(stmt)).all()]


async def count_accounts(session: AsyncSession, *, is_active: bool | None) -> int:
    """Sayım liste ile AYNI süzgeçten geçer — `total` tabloyla ayrışmasın."""
    stmt = _filtered(select(func.count()).select_from(BankAccount), is_active=is_active)
    return (await session.execute(stmt)).scalar_one()


async def get_account(
    session: AsyncSession, account_id: uuid.UUID, *, for_update: bool = False
) -> BankAccount | None:
    """Tekil okuma; `for_update` satırı KİLİTLER.

    `populate_existing` ŞARTTIR: kimlik haritası bayat bir nesne taşıyorsa
    `session.get` onu SORGUSUZ döndürür ve kilit HİÇ ALINMAZ — TOCTOU penceresi
    sessizce açık kalırdı (`invoicing.get_invoice` dersi).
    """
    if not for_update:
        return await session.get(BankAccount, account_id)
    return await session.get(BankAccount, account_id, with_for_update=True, populate_existing=True)


async def iban_exists(
    session: AsyncSession, iban: str, *, exclude_id: uuid.UUID | None = None
) -> bool:
    """`uq_bank_accounts_iban` ön denetimi — NORMALİZE edilmiş değerle çağrılır.

    `exclude_id` PATCH içindir: kaydın kendisi dışlanmasaydı kullanıcı yalnızca
    banka adını düzeltirken kendi IBAN'ı yüzünden 409 alırdı.

    NULL hiç sorgulanmaz (çağıran erken döner): kısmi indeks NULL'ları
    çoklanabilir bırakır, burada aranırsa ikinci kasa hiç açılamazdı.
    """
    stmt = select(func.count()).select_from(BankAccount).where(BankAccount.iban == iban)
    if exclude_id is not None:
        stmt = stmt.where(BankAccount.id != exclude_id)
    return bool((await session.execute(stmt)).scalar_one())


async def count_payments_for_account(session: AsyncSession, account_id: uuid.UUID) -> int:
    """DELETE'in ÖN denetimi (FK RESTRICT'in servis karşılığı).

    ⚠️ Sayım FK ihlaline DÜŞMEDEN önce koşar: düşseydi kullanıcı ya ham bir 500
    ya da `IntegrityError` handler'ının "Veri bütünlüğü hatası" 409'unu alırdı.
    Üstelik SQLSTATE davranışı PG sürümleri arasında (yerel 18 / CI 16)
    birebir aynı değildir — denetim SERVİSTE olmalıdır, testte SQLSTATE
    varsayılmamalıdır.
    """
    stmt = select(func.count()).select_from(Payment).where(Payment.bank_account_id == account_id)
    return (await session.execute(stmt)).scalar_one()
