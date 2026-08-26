"""MU-3A sorguları — `posting_rules` okuması ve kaynak damgasından fiş arama."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounting.models import ChartAccount, JournalEntry, JournalSourceType
from app.modules.posting.models import PostingRule

__all__ = ["entry_for_source", "lock_source", "rules_for"]

#: 🔴 Danışma kilidinin AD ALANI. `procurement`/`invoicing` üreticileriyle AYNI
#: `pg_advisory_xact_lock` uzayını paylaşırız; sabit bir birinci anahtar,
#: bir sipariş numarası kilidiyle bir fişleme kilidinin ÇAKIŞMASINI önler.
#: Değer keyfidir ve DEĞİŞMEMELİDİR: değişirse eski ve yeni kod aynı belgeyi
#: AYRI kilitlerle korur ve deploy penceresinde yarış yeniden açılır.
POSTING_LOCK_KEY = 30301


async def lock_source(
    session: AsyncSession, source_type: JournalSourceType, source_id: uuid.UUID
) -> None:
    """🔴 EŞİK = KİLİT — belge başına İŞLEM ÖMÜRLÜ danışma kilidi.

    Kilitlenecek bir SATIR yoktur (fiş henüz doğmamıştır), bu yüzden
    `SELECT … FOR UPDATE` burada kullanılamaz ve `numbering.py`nin
    UPSERT-SONRA-KİLİTLE deseni de uymaz (yazılacak şey sayaç değil FİŞİN
    KENDİSİDİR). Danışma kilidi tam olarak bu boşluk için vardır.

    `_xact_` soneki ŞART: kilit transaction sonunda KENDİLİĞİNDEN bırakılır;
    elle `unlock` unutulsaydı bağlantı havuzunda sızıntı olurdu.

    Kilit alındıktan SONRA yapılan okuma kazananın COMMIT'ini görür (READ
    COMMITTED'da her yeni ifade taze bir anlık görüntü alır) — kaybeden
    `created=False` ile mevcut fişi döndürür, tekillik kısıtına ÇARPMAZ.

    ⚠️ Kilit tekilliği GARANTİ ETMEZ, yalnız kullanıcıya gösterilen davranışı
    düzeltir. Garanti `uq_journal_entries_source`tadır.

    `hashtext` `int4` döndürür ve `pg_advisory_xact_lock(int, int)`in ikinci
    ayağına tam oturur. Çakışma (iki farklı belgenin aynı hash'e düşmesi)
    yalnızca GEREKSİZ SERİLEŞTİRME üretir, yanlışlık üretmez.
    """
    await session.execute(
        select(
            func.pg_advisory_xact_lock(
                POSTING_LOCK_KEY, func.hashtext(f"{source_type.value}:{source_id}")
            )
        )
    )


async def entry_for_source(
    session: AsyncSession, source_type: JournalSourceType, source_id: uuid.UUID
) -> JournalEntry | None:
    """*"Bu belge fişlendi mi?"* — MU-3A'dan önce SORULAMAYAN soru.

    🔴 `populate_existing=True`: kazanan BAŞKA bir oturumda yazdıysa bu
    oturumun kimlik haritasında satır yoktur ve taze yüklenir; ama aynı
    oturumda daha önce bayat bir kopya belirmişse (örneğin çağıranın kendi
    `refresh` etmediği bir nesne) sessizce O dönerdi. Kanon: kilitli/kritik
    okuma DAİMA `populate_existing` taşır.
    """
    stmt = (
        select(JournalEntry)
        .where(JournalEntry.source_type == source_type, JournalEntry.source_id == source_id)
        .execution_options(populate_existing=True)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def rules_for(
    session: AsyncSession, source_type: JournalSourceType
) -> dict[str, ChartAccount]:
    """Ailenin BÜTÜN eşlemesi TEK sorguda — rol başına sorgu ATILMAZ (N+1).

    Hesap `join` ile BİRLİKTE gelir: ayrı çekilseydi yaprak denetimi (K1'in
    üçüncü engeli) her bacak için ikinci bir tur atardı.
    """
    stmt = (
        select(PostingRule.role_key, ChartAccount)
        .join(ChartAccount, ChartAccount.id == PostingRule.account_id)
        .where(PostingRule.source_type == source_type)
    )
    return {role_key: account for role_key, account in (await session.execute(stmt)).all()}
