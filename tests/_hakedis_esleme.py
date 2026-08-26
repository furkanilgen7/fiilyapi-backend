"""🔴 MU-3D — hakediş ailelerinin `posting_rules` ÜRÜN eşlemesini kuran ORTAK yardımcı.

Canlıda bu satırları `a4b5c6d7e8f9` migration'ı tohumlar; test kümesi migration
KOŞMAZ (`Base.metadata.create_all`), bu yüzden bir hakedişi `approved`a taşıyan
HER test onu kurmak zorundadır. Eksik olduğunda onay **422** verir — fail-closed
olan ve olması gereken taraf budur.

🔴 **Neden ÜRÜN demetinden kurulur:** eşleme testte elle yazılsaydı üründeki
demet bozulduğunda (bir rol yanlış hesaba çevrildiğinde) bu kurulum YEŞİL
kalırdı.

🔴 **Neden hesabın TÜRÜ elle yazılmaz:** `600`ü `expense` sayan bir kurulum
`balance.SIGN`ın işaretini sessizce ters çevirir ve mutabakat testi YANLIŞ bir
büyüklükle tutardı. Tür TDHP tohumundan (`chart_seed_data`) okunur.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounting.chart_seed_data import CHART_ACCOUNTS
from app.modules.accounting.models import ChartAccount, JournalSourceType
from app.modules.posting.models import PostingRule

_TOHUM = {satir.code: satir for satir in CHART_ACCOUNTS}


async def esleme_kur(
    session: AsyncSession,
    source_type: JournalSourceType,
    kurallar: tuple[tuple[str, str], ...],
) -> None:
    """`(rol, hesap kodu)` demetini `posting_rules`a yazar; hesabı yoksa AÇAR.

    Hesap VARSA yeniden açılmaz: aynı oturumda iki aile birden kurulduğunda
    (`740` hem taşeron hem kira ailesinde geçer) `uq_chart_of_accounts_code`a
    çarpılırdı.
    """
    for role_key, kod in kurallar:
        account = (
            await session.execute(select(ChartAccount).where(ChartAccount.code == kod))
        ).scalar_one_or_none()
        if account is None:
            kart = _TOHUM[kod]
            account = ChartAccount(
                code=kart.code,
                name=kart.name,
                account_type=kart.account_type,
                is_contra=kart.is_contra,
            )
            session.add(account)
            await session.flush()
        session.add(PostingRule(source_type=source_type, role_key=role_key, account_id=account.id))
    await session.flush()
