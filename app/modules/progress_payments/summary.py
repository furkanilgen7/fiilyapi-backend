"""İşveren hakedişi özeti (spec §9.6) — task H9.

E14 127-147 "Hakediş Özeti" kartı ve SHK 82-84 şantiye kartlarının kaynağı;
aynı zamanda `contracts` modülünün P5'te bıraktığı yer tutucuların (`ContractSummary.
progress_payment_total`, `ContractListItem.progress_pct`, `EmployerContractDetail.
progress_payment_summary`) gerçek verisi buradan gelir.

## Yön (dairesel import)

`contracts` → `progress_payments` yönlüdür ve `contracts/service.py` içinde
**yerel** (fonksiyon içi) import ile kurulur. Ters yön (bu modülden
`contracts.service`) ASLA açılmaz; buradan yalnız `contracts.models` okunur.

## Neden kümülatifler burada da zincirle hesaplanır

Avans mahsubu KÜMÜLATİF TAVANLIDIR (§6.3): toplam kesinti `Σ(brüt × %avans)`
DEĞİLDİR, tavana (`bedel × %avans`) çarpınca durur. Zincirin tek kopyası
`service.cumulative_state`'tir; bu modül onu ÇAĞIRIR, kopyalamaz.
"""

import uuid
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.progress_payments import calculations, repository, service
from app.modules.progress_payments.models import ProgressPaymentStatus
from app.modules.progress_payments.schemas import ProgressPaymentSummary
from app.modules.projects.models import Project, ProjectContract
from app.modules.users.models import User

_ZERO = Decimal("0.00")
_HUNDRED = Decimal("100")


def progress_pct(cumulative_gross: Decimal, contract_amount: Decimal | None) -> Decimal | None:
    """§8 finansal ilerleme: `kümülatif brüt / bedel × 100` (FF **dahil**).

    Bedel yok ya da sıfırsa `None` — sahte %0 yerine dürüst boş durum (§8
    "tarih/tutar eksikse ilgili gösterge `null` döner").
    """
    if contract_amount is None or contract_amount <= 0:
        return None
    return calculations.quantize2(cumulative_gross / contract_amount * _HUNDRED)


async def build_summary(
    session: AsyncSession, project: Project, contract: ProjectContract | None
) -> ProgressPaymentSummary:
    """Özetin GÖVDESİ — görünürlük kontrolü YAPMAZ (çağıran çoktan vermiştir).

    İki çağıranı vardır: `get_summary` (uç, kapsam süzgecinden sonra) ve
    `contracts.service.get_employer_contract_detail` (E14 detayı, kendi kapsam
    süzgecinden sonra).

    `net_total` E14 145'in "Net Ödeme" satırıdır ve **KDV içermez**:
    `kümülatif brüt − avans − teminat`. §6.4'ün tek hakediş `net`i (KDV dâhil)
    ile bilinçli olarak FARKLIDIR — E14 kartı sözleşmenin hakkedilen bedelini
    özetler, tahsil edilecek fatura tutarını değil (mockup kanıtı: 8.400.000 −
    1.680.000 − 420.000 = 6.300.000).
    """
    contract_amount = contract.amount if contract is not None else None
    completed = await repository.list_completed_payments(session, project.id)
    state = service.cumulative_state(completed, contract_amount)
    pending_count = await repository.count_payments_by_status(
        session, project.id, ProgressPaymentStatus.pending_approval
    )

    net_total = state.gross - state.advance_recovered - state.retention
    remaining = None if contract_amount is None else contract_amount - state.gross
    return ProgressPaymentSummary(
        contract_amount=contract_amount,
        cumulative_gross=state.gross,
        progress_pct=progress_pct(state.gross, contract_amount),
        advance_deduction_total=state.advance_recovered,
        retention_total=state.retention,
        net_total=net_total,
        payment_count=len(completed),
        pending_count=pending_count,
        remaining=remaining,
    )


async def get_summary(
    session: AsyncSession, actor: User, project_id: uuid.UUID
) -> ProgressPaymentSummary:
    """`GET /projects/{project_id}/progress-payments/summary` (spec §9.6).

    Kapsam (§9.0): görünmeyen proje ile var olmayan proje AYIRT EDİLEMEZ 404
    (`service._visible_project`, tek "bulunamadı" metni). Sözleşmesi olmayan
    görünür proje 404 DEĞİL, bedeli `None` olan boş bir özet döner: E14 sekmesi
    sözleşme taslakken de açılabilir (§8 zarif düşüş deseni).
    """
    project = await service._visible_project(session, actor, project_id)
    return await build_summary(session, project, project.contract)


async def cumulative_gross_by_projects(
    session: AsyncSession, project_ids: list[uuid.UUID]
) -> dict[uuid.UUID, Decimal]:
    """`contracts` liste ucunun (SZL) proje başına kümülatif brütü — **TEK**
    toplu sorgu (plan H9 Adım 3: "liste yolunda proje başına kümülatif brüt
    toplu çekilir"), proje başına ayrı sorgu KOŞMAZ.

    Toplam SQL'de değil bellekte alınır çünkü `line_total` kuruş yuvarlaması
    (`quantize2`) satır düzeyinde yapılır (§6.1): SQL'de `SUM` almak, para
    matematiğinin ikinci bir kopyasını (ve zamanla ikinci bir doğruluk
    tanımını) doğururdu. Kapsam süzgeci yine SQL'dedir (`project_id IN (…)`).
    """
    grouped = await repository.list_completed_payments_by_projects(session, project_ids)
    return {
        project_id: service.cumulative_state(payments, None).gross
        for project_id, payments in grouped.items()
    }
