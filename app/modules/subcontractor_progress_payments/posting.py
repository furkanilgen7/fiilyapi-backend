"""🔴 MU-3D — TAŞERON HAKEDİŞİNİN FİŞİ (KDV'SİZ).

İşveren ailesinin (`progress_payments.posting`) AYNASIDIR: orası bizim
KESTİĞİMİZ hakediştir (alacak + hasılat), burası bize KESİLENDİR (gider +
cari borç).

    B 740 Hizmet Üretim Maliyeti = taban
    A 320 Satıcılar              = taban

Aynı yön `invoicing.posting._incoming_lines` ile birebir uyumludur (GELEN
fatura da `740`a borç, `320`ye alacak yazar) ve uyumlu olması ZORUNLUDUR: bu
hakedişten kesilen fatura GELEN faturadır ve İŞ 2 bu fişi STORNO edip onunkini
yazar.

## 🔴 FİŞ NE ZAMAN DOĞAR — `transitions.py`den ÖLÇÜLDÜ

Matris işveren ailesiyle AYNI şekli paylaşır (`_TRANSITION_SHAPE` TEK KOPYA) ve
`PaymentAction` de ORADAN import edilir:

    draft ──submit──▶ pending_approval ──approve──▶ approved ──mark-paid──▶ paid
                              ▲                         │
                              └────── unapprove ────────┘
                      pending_approval ──reject──▶ draft

Mali olarak BAĞLAYICI geçiş **BİRDİR**: `pending_approval ──approve──▶
approved`. `mark-paid` bir ÖDEMEDİR (nakit bacağı MU-3C'nindir), `reject`
kaydı `draft`a atar, `submit` para taşımaz.

🔴 **KANCA GEÇİŞE DEĞİL BELGEYE BAĞLIDIR**: onay zinciri (OK-1A) tamamlanmadıysa
`perform` erken döner ve durum `pending_approval` KALIR. Fiş bu yüzden eylemden
değil, kaydın `approved` durumuna FİİLEN geçmesinden doğar.

## GERİ ALMA = STORNO (KARAR-5) · TUTARIN DONMASI

Gerekçelerin tamamı kardeş modülün (`progress_payments.posting`) docstring'inde
TEK KOPYA olarak durur ve burada TEKRARLANMAZ. Özetle: `unapprove` fişi storno
eder; tutar fişin kendisinde donar çünkü bu ailede de para SAKLANMAZ.

🔴 Bu ailede `contract_amount` DAHA DA CANLIDIR: `subcontractor_contracts`ta bir
`amount` kolonu YOKTUR, bedel her okumada sözleşme KALEMLERİNDEN toplanır
(`repository.get_contract_amounts`). Yani bir kalem düzeltildiğinde avans tavanı
—ve dolayısıyla net— değişir. Fişin donmuş tutarı bu yüzden burada daha da
gereklidir.
"""

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounting import state_service as accounting_state_service
from app.modules.accounting.models import JournalSourceType
from app.modules.accounting.transitions import JournalAction
from app.modules.posting import repository as posting_repository
from app.modules.posting import service as posting_service
from app.modules.posting.service import PostingLine, PostingOutcome
from app.modules.progress_payments import calculations
from app.modules.subcontractor_progress_payments.models import SubcontractorProgressPayment
from app.modules.users.models import User

__all__ = [
    "ROLE_EXPENSE",
    "ROLE_PAYABLE",
    "SOURCE_TYPE",
    "SUBCONTRACTOR_POSTING_RULES",
    "description_for",
    "lines_for",
    "post_subcontractor_payment",
    "posting_base_for",
    "reverse_subcontractor_payment",
]

#: üye = TABLO (`subcontractor_progress_payments`).
SOURCE_TYPE = JournalSourceType.subcontractor_progress_payment

ROLE_EXPENSE = "expense"
ROLE_PAYABLE = "payable"

#: 🔴 TOHUMUN KAYNAĞI — KARAR-1 (`740`, `170` DEĞİL) ve KARAR-2 (`320`, alt
#: hesap AÇILMAZ) tam olarak BU SATIRLARDA yaşar.
SUBCONTRACTOR_POSTING_RULES: tuple[tuple[str, str], ...] = (
    (ROLE_EXPENSE, "740"),
    (ROLE_PAYABLE, "320"),
)

_ZERO = Decimal("0")


def description_for(payment: SubcontractorProgressPayment, subcontractor_name: str | None) -> str:
    """`2. Taşeron Hakedişi — Çelik Kalıp Ltd.`

    🔴 TUTAR metne GİRMEZ (HZ-1 kanonu). Taşeron adı sözleşmenin
    `subcontractor_name` SNAPSHOT'undan okunur, cari kartından DEĞİL.
    """
    taraf = (subcontractor_name or "").strip()
    baslik = f"{payment.sequence_no}. Taşeron Hakedişi"
    return f"{baslik} — {taraf}" if taraf else baslik


def lines_for(base: Decimal) -> list[PostingLine]:
    """İKİ bacak — sıra SABİTTİR (borç önce, alacak sonra)."""
    return [
        PostingLine(role_key=ROLE_EXPENSE, debit=base),
        PostingLine(role_key=ROLE_PAYABLE, credit=base),
    ]


def posting_base_for(
    payment: SubcontractorProgressPayment,
    contract_amount: Decimal | None,
    advance_recovered: Decimal,
) -> Decimal:
    """Fişin KDV'siz tabanı — `calculations.posting_base`in ÇAĞRISI.

    Kardeş modülle AYNI gövde ve BİLEREK ayrı: iki ailenin `lines`ı farklı
    tiplerdir ve ortak bir sarmalayıcı, tip düzeyindeki ayrımı silerdi. Asıl
    aritmetik zaten TEK kopyadır (`calculations`).
    """
    gross = calculations.gross_total(payment.lines)
    advance = calculations.advance_or_uncapped(
        gross, payment.advance_pct, contract_amount, advance_recovered
    )
    retention = calculations.retention_amount(gross, payment.retainage_pct)
    return calculations.posting_base(gross, advance, retention)


async def post_subcontractor_payment(
    session: AsyncSession,
    actor: User,
    payment: SubcontractorProgressPayment,
    *,
    base: Decimal,
    entry_date: date,
    subcontractor_name: str | None,
) -> PostingOutcome | None:
    """Hakedişi fişler. `None` = *"fişlenecek para yok"*. COMMIT ETMEZ."""
    if base <= _ZERO:
        return None
    return await posting_service.post_document(
        session,
        actor,
        source_type=SOURCE_TYPE,
        source_id=payment.id,
        entry_date=entry_date,
        description=description_for(payment, subcontractor_name),
        lines=lines_for(base),
    )


async def reverse_subcontractor_payment(
    session: AsyncSession, actor: User, payment_id: uuid.UUID
) -> bool:
    """🔴 KARAR-5 — CANLI fişi STORNO eder. Gerekçe kardeş modüldedir."""
    entry = await posting_repository.entry_for_source(session, SOURCE_TYPE, payment_id)
    if entry is None:
        return False
    await accounting_state_service.perform_transition(
        session, actor, entry.id, JournalAction.reverse
    )
    return True
