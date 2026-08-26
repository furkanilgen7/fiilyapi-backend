"""MU-3A — otomatik fiş altyapısının paylaşılan kurulumu.

🔴 Fabrikalar KOPYALANMAZ, `tests/modules/accounting/conftest.py`ten yeniden
dışa vurulur. Kopyalansaydı hesap planı fabrikası iki yerde yaşar ve biri
(`is_contra` gibi) bir parametre kazandığında öteki kalırdı — MU-3A'nın eşleme
tablosu doğrudan `chart_of_accounts`a bakar, yani iki fabrika AYRIŞAMAZ.

`_login`/`_auth` yardımcıları BURAYA ALINMAZ: bu dilim HİÇBİR HTTP UCU AÇMAZ
(`post_document` bir servis giriş noktasıdır, bir router değil). Rol fixture'ı
kurmak, olmayan bir yetki kapısını varmış gibi gösteren bir test üretirdi.
"""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounting.models import ChartAccount, JournalSourceType
from app.modules.posting.models import PostingRule
from tests.modules.accounting.conftest import (  # noqa: F401
    donem_fabrikasi,
    hesap_fabrikasi,
    kullanici_id,
)

#: Testlerin TEMSİLİ belge ailesi. Tek bir aile seçilir ve sabittir: eşleme
#: iskeleti ailelere göre DEĞİŞMEZ, bu yüzden ikinci bir aileyi taklit etmek
#: aynı yolu iki kez ölçerdi.
KAYNAK = JournalSourceType.invoice

#: 🔴 KARAR-1 (NORMAL TİCARİ REJİM) ve KARAR-2 (CARİ ANA HESAP) burada çakılır:
#: `740`/`320` — `170`/`350` ya da `320.04` DEĞİL. Rol adları eşleme tablosunun
#: sözlüğüdür; hesap kodu KODUN İÇİNDE yazılı DEĞİLDİR, kuraldan okunur.
GIDER_ROL = "expense"
CARI_ROL = "payable"


@pytest.fixture
def kural_fabrikasi(seeded_db: AsyncSession):
    """`posting_rules` satırını DOĞRUDAN kurar — uç YOKTUR, uçtan geçilemez."""

    async def _create(
        role_key: str,
        account: ChartAccount,
        *,
        source_type: JournalSourceType = KAYNAK,
    ) -> PostingRule:
        rule = PostingRule(source_type=source_type, role_key=role_key, account_id=account.id)
        seeded_db.add(rule)
        await seeded_db.flush()
        return rule

    return _create


@pytest.fixture
async def temsili_esleme(hesap_fabrikasi, kural_fabrikasi):  # noqa: ANN001
    """KARAR-1 + KARAR-2'nin temsilî eşlemesi: `740` borç · `320` alacak.

    Kodlar `chart_seed_data`daki TDHP kodlarıyla aynıdır ama hesaplar burada
    FABRİKAYLA kurulur: `seeded_db` hesap planını tohumlamaz ve tohumlasaydı bu
    testler seed'in içeriğine bağlanırdı (`hesap_fabrikasi` dersi, MU-1 T3a).
    """
    gider = await hesap_fabrikasi("740", name="Hizmet Üretim Maliyeti")
    cari = await hesap_fabrikasi("320", name="Satıcılar")
    await kural_fabrikasi(GIDER_ROL, gider)
    await kural_fabrikasi(CARI_ROL, cari)
    return gider, cari


def satirlar(tutar: str = "1000.00") -> list:
    """`post_document`in beklediği en küçük DENGELİ küme."""
    from app.modules.posting.service import PostingLine

    return [
        PostingLine(role_key=GIDER_ROL, debit=Decimal(tutar)),
        PostingLine(role_key=CARI_ROL, credit=Decimal(tutar)),
    ]


def yeni_kaynak_id() -> uuid.UUID:
    """Belge kimliği — FK YOKTUR (çok biçimli referans), uydurulmuş UUID yeter."""
    return uuid.uuid4()
