"""Taşeron hakedişi hesap bloğu (T3, spec §3) — `calculations.py`nin ÇAĞRILDIĞI yer.

## Kopya değil, paylaşım

Hesabın kendisi `app/modules/progress_payments/calculations.py`de TEK kopyadır
(saf, DB'siz). Bu modül yalnız o zinciri taşeron verisiyle BESLER:

    brüt → KDV → avans mahsubu (kümülatif tavanlı) → teminat → net

**ONAYLI SAPMA (geri alınmaz):** mockup tfoot'unda OLMAYAN *teminat kesintisi*
satırı ve *fiyat farkı katsayısı* hesaba dahildir; liste ekranındaki
"Net = Brüt − KDV" görünümü (L146) mockup HESAP HATASIDIR, altın sayı değildir.
KDV tevkifatı (`vat_withholding`) bu dilimde hesaba GİRMEZ (spec §8 S4) — bayrak
bilgi olarak kalır, fatura/muhasebe dilimine aittir.

## İşverenden tek yapısal fark: sözleşme bedeli TÜREVDİR

`subcontractor_contracts`ta `amount` kolonu YOKTUR (K3): avans tavanının dayandığı
bedel `Σ kalem quantity × unit_price`tır ve `repository.get_contract_amount`tan
okunur.
"""

import uuid
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.progress_payments import calculations
from app.modules.subcontractor_progress_payments import repository
from app.modules.subcontractor_progress_payments.models import SubcontractorProgressPayment
from app.modules.subcontractor_progress_payments.schemas import SubcontractorPaymentCalculation


def build_block(
    payment: SubcontractorProgressPayment,
    contract_amount: Decimal | None,
    advance_recovered: Decimal,
) -> SubcontractorPaymentCalculation:
    """O147-163 tfoot'u. `advance_recovered` ÇAĞIRANDAN gelir (önceki tamamlanmış
    hakedişlerin kurtardığı avans) — bu fonksiyon SORGU KOŞMAZ."""
    gross = calculations.gross_total(payment.lines)
    vat = calculations.vat_amount(gross, payment.vat_pct)
    advance = calculations.advance_or_uncapped(
        gross, payment.advance_pct, contract_amount, advance_recovered
    )
    retention = calculations.retention_amount(gross, payment.retainage_pct)
    return SubcontractorPaymentCalculation(
        gross=gross,
        vat=vat,
        advance_deduction=advance,
        retention=retention,
        net=calculations.net_amount(gross, vat, advance, retention),
    )


def advance_recovered(
    prior_payments: list[SubcontractorProgressPayment], contract_amount: Decimal | None
) -> Decimal:
    """Önceki tamamlanmış hakedişlerin kurtardığı avans — ZİNCİRLEME (basit toplam
    DEĞİL): her adımın tavanı bir öncekinin sonucuna bağlıdır (spec §3).

    `prior_payments` `sequence_no` ARTAN sırada olmalıdır (repository öyle döner).
    """
    return calculations.cumulative_state(prior_payments, contract_amount).advance_recovered


async def calculation_for(
    session: AsyncSession, payment: SubcontractorProgressPayment
) -> SubcontractorPaymentCalculation:
    """TEK hakedişin hesabı — detay ucu (`read.build_detail`) buradan okur.

    Liste ucu bu fonksiyonu KULLANMAZ: hakediş başına iki sorgu koşardı (N+1);
    orada `bulk_calculations` toplu çekimi vardır.
    """
    contract_amount = await repository.get_contract_amount(session, payment.contract_id)
    prior = await repository.list_completed_payments(
        session, payment.contract_id, before_sequence_no=payment.sequence_no
    )
    return build_block(payment, contract_amount, advance_recovered(prior, contract_amount))


async def bulk_calculations(
    session: AsyncSession, payments: list[SubcontractorProgressPayment]
) -> dict[uuid.UUID, SubcontractorPaymentCalculation]:
    """Liste ucunun N+1 çözümü (işveren `list_payments` deseni): sözleşme bedelleri
    ve tamamlanmış hakedişler İKİ toplu sorguda okunur, zincir bellekte kurulur.
    """
    contract_ids = sorted({payment.contract_id for payment in payments})
    amounts = await repository.get_contract_amounts(session, contract_ids)
    completed = await repository.list_completed_payments_by_contracts(session, contract_ids)

    blocks: dict[uuid.UUID, SubcontractorPaymentCalculation] = {}
    for payment in payments:
        contract_amount = amounts.get(payment.contract_id, Decimal("0.00"))
        prior = [
            other
            for other in completed.get(payment.contract_id, [])
            if other.sequence_no < payment.sequence_no
        ]
        blocks[payment.id] = build_block(
            payment, contract_amount, advance_recovered(prior, contract_amount)
        )
    return blocks
