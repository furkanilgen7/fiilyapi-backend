"""Muhasebe veri erişimi (MU-1 T3a) — yalnız SQL, karar yok.

`treasury/repository.py` deseninin kardeşi. İki farkı vardır ve ikisi de
bilinçlidir:

🔴 **KAPSAM SÜZGECİ YOKTUR (spec §3).** Hesap planı ŞİRKET GENELİ bir katalogtur:
`chart_of_accounts` tablosunda `project_id`/`site_id` kolonu yoktur ve HP'nin
beş sütununda hiçbir proje/şantiye alanı çizilmemiştir. `suppliers`/`stock_items`
emsali; erişim `accounting` izin modülüyle denetlenir, **IDOR unutulmuş
DEĞİLDİR, yapısal olarak yoktur**. Buraya `project_ids` parametresi eklemek
olmayan bir süzgeci varmış gibi gösterirdi.

🔴 **BAKİYE BURADA HESAPLANMAZ.** Liste `balance.select_accounts_with_balance()`
üzerine yalnız SÜZGEÇ/SIRA/SAYFA ekler; ikinci bir formül yazılsaydı liste ile
detay aynı hesap için farklı sayı basar ve bakiye saklanmadığı için hiçbir kolon
farkı ele vermezdi.

## Hiyerarşi sorgusu

`parent_id` FK YOKTUR (K4): alt hesaplar KODUN ÖNEKİYLE bulunur
(`codes.child_prefix`). Önek torunları da kapsar — çocuğu silinmiş ama torunu
duran bir grup "yaprak" sanılmamalıdır.

## N+1

Liste ucu hesap sayısından BAĞIMSIZ olarak iki sorgu koşar (satırlar + sayım).
`test_liste_N_ARTI_1_YAPMAZ` bunu `before_cursor_execute` sayacıyla ÖLÇER.
"""

import uuid
from decimal import Decimal

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounting import codes
from app.modules.accounting.balance import select_accounts_with_balance
from app.modules.accounting.models import ChartAccount, ChartAccountType, JournalLine

__all__ = [
    "code_exists",
    "count_accounts",
    "count_journal_lines_for_account",
    "get_account",
    "get_account_by_code",
    "has_child_accounts",
    "list_accounts_with_balance",
]

_LIKE_ESCAPE = "\\"


def _like_escape(deger: str) -> str:
    """LIKE joker karakterlerini KAÇIRIR (`invoicing.repository` deseni).

    🔴 R15: kaçırılmazsa arama kutusuna `%` yazan kullanıcı TÜM hesapları, `_`
    yazan ise beklemediği satırları görür. **Kaçış karakterinin kendisi ÖNCE
    kaçırılır** — sonra kaçırılsaydı sonradan eklenen ters bölüler de ikinci
    turda çiftlenirdi.
    """
    return deger.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _filtered(
    stmt: Select,
    *,
    q: str | None,
    account_type: ChartAccountType | None,
    is_active: bool | None,
) -> Select:
    """HP filtre çubuğu (spec §7). Süzgeçler AND'lidir.

    `q` KOD ve AD üzerinde kısmi arar (HP:47 tek kutudur): yalnız adda arasaydı
    kod yazan kullanıcı "hesap yok" sanısına düşerdi.

    🔴 `account_type` (HP:60 `Tür`) ile `is_active` (HP:62 `Durum`) AYRI
    süzgeçlerdir ve birbirinin yerine GEÇMEZ (R3) — ikisi de Türkçe'de "aktif"
    okunur ama biri dört üyeli enum, öteki boolean bir kaldırma bayrağıdır.

    Liste ve sayım AYNI yardımcıdan geçer: kopya açılsaydı `total` ile gösterilen
    tablo zamanla ayrışır ve hesaplar "sayfa dışında kalmış" gibi görünürdü.
    """
    if account_type is not None:
        stmt = stmt.where(ChartAccount.account_type == account_type)
    if is_active is not None:
        stmt = stmt.where(ChartAccount.is_active == is_active)
    if q:
        desen = f"%{_like_escape(q)}%"
        stmt = stmt.where(
            ChartAccount.code.ilike(desen, escape=_LIKE_ESCAPE)
            | ChartAccount.name.ilike(desen, escape=_LIKE_ESCAPE)
        )
    return stmt


async def list_accounts_with_balance(
    session: AsyncSession,
    *,
    q: str | None,
    account_type: ChartAccountType | None,
    is_active: bool | None,
    limit: int,
    offset: int,
) -> list[tuple[ChartAccount, Decimal]]:
    """Satır + TÜRETİLMİŞ bakiye, hesap sayısından bağımsız TEK sorguda.

    Sıralama `code ASC`tir (spec §7) ve hiyerarşiyi KENDİLİĞİNDEN üretir: metin
    sırası `10` · `100` · `12` · `120` · `120.01` verir, yani HP'nin grup-altı
    yerleşimi ikinci bir "ağaç kurma" adımı olmadan çıkar. Kod TEKİL olduğu için
    ikinci bir sıralama ölçütü GEREKMEZ — sayfalar arasında satır kaybolup
    tekrarlayamaz.
    """
    stmt = _filtered(
        select_accounts_with_balance(), q=q, account_type=account_type, is_active=is_active
    )
    stmt = stmt.order_by(ChartAccount.code).limit(limit).offset(offset)
    return [(account, bakiye) for account, bakiye in (await session.execute(stmt)).all()]


async def count_accounts(
    session: AsyncSession,
    *,
    q: str | None,
    account_type: ChartAccountType | None,
    is_active: bool | None,
) -> int:
    """Sayım liste ile AYNI süzgeçten geçer — `total` tabloyla ayrışmasın."""
    stmt = _filtered(
        select(func.count()).select_from(ChartAccount),
        q=q,
        account_type=account_type,
        is_active=is_active,
    )
    return (await session.execute(stmt)).scalar_one()


async def get_account(
    session: AsyncSession, account_id: uuid.UUID, *, for_update: bool = False
) -> ChartAccount | None:
    """Tekil okuma; `for_update` satırı KİLİTLER.

    `populate_existing` ŞARTTIR: kimlik haritası bayat bir nesne taşıyorsa
    `session.get` onu SORGUSUZ döndürür ve kilit HİÇ ALINMAZ — TOCTOU penceresi
    sessizce açık kalırdı (`invoicing.get_invoice` dersi).
    """
    if not for_update:
        return await session.get(ChartAccount, account_id)
    return await session.get(ChartAccount, account_id, with_for_update=True, populate_existing=True)


async def get_account_by_code(session: AsyncSession, code: str) -> ChartAccount | None:
    """Koddan hesap — K-Ş3 kapısının (ebeveyn arama) tek yolu.

    Ebeveynin KAYDI olmayabilir (hesap planı boş açılır, R14): `None` bir hata
    değildir, "kapı ısırmaz" demektir.
    """
    stmt = select(ChartAccount).where(ChartAccount.code == code)
    return (await session.execute(stmt)).scalar_one_or_none()


async def code_exists(
    session: AsyncSession, code: str, *, exclude_id: uuid.UUID | None = None
) -> bool:
    """`uq_chart_of_accounts_code` ön denetimi (R16).

    `exclude_id` PATCH içindir: kaydın kendisi dışlanmasaydı kullanıcı yalnızca
    adı düzeltirken formun geri gönderdiği kendi kodu yüzünden 409 alırdı.
    """
    stmt = select(func.count()).select_from(ChartAccount).where(ChartAccount.code == code)
    if exclude_id is not None:
        stmt = stmt.where(ChartAccount.id != exclude_id)
    return bool((await session.execute(stmt)).scalar_one())


async def has_child_accounts(session: AsyncSession, code: str) -> bool:
    """Hesabın ALTINDA (çocuk ya da TORUN) kayıt var mı? — K4 hiyerarşisi.

    `parent_id` FK olmadığı için sorgu ÖNEK üzerindedir (`codes.child_prefix`).
    En alt düzeyde önek `None`dır ve hiç sorgu koşulmaz: `NNN.NN` altına bir şey
    açılamaz (üçüncü kırılım yoktur).

    Kendisi DIŞLANIR — dışlanmasaydı her hesap kendi çocuğu sayılır ve hiçbir
    hesap ne silinebilir ne de yaprak olabilirdi.
    """
    onek = codes.child_prefix(code)
    if onek is None:
        return False
    desen = f"{_like_escape(onek)}%"
    stmt = (
        select(func.count())
        .select_from(ChartAccount)
        .where(
            ChartAccount.code.like(desen, escape=_LIKE_ESCAPE),
            ChartAccount.code != code,
        )
    )
    return bool((await session.execute(stmt)).scalar_one())


async def count_journal_lines_for_account(session: AsyncSession, account_id: uuid.UUID) -> int:
    """Hesaba kesilmiş fiş satırı sayısı — ÜÇ kapının ortak ölçütü.

    Kullanıcıları: DELETE'in 409'u (FK RESTRICT'in servis karşılığı) · `code`
    değişiminin 409'u · K-Ş3'ün ebeveyn denetimi.

    🔴 DURUM SÜZGECİ YOKTUR ve olmamalıdır: `draft` bir fiş bakiyeye girmese de
    (K3) o hesaba BAĞLIDIR. Süzgeç konsaydı taslak satırı olan bir hesap
    silinebilir, FK RESTRICT ham bir 500 üretir ve kullanıcı ayrımsız bir hata
    alırdı.
    """
    stmt = select(func.count()).select_from(JournalLine).where(JournalLine.account_id == account_id)
    return (await session.execute(stmt)).scalar_one()
