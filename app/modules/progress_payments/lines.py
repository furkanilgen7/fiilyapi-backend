"""Hakediş satırlarının TEK yazma yolu — task H5 (spec §6.5, §9.2, §5).

## ⚠️ Semantik: DEĞİŞTİRME (replace), P5'in TERSİ

`PUT /progress-payments/{id}/lines` gövdesi ekranın TAMAMIDIR: gövdede geçmeyen
satır **SİLİNİR**. Bu, `contracts/distribution.py`'nin `PUT …/contract/distribution`
**BİRLEŞTİRME** semantiğinin TERSİDİR — orada gövdede geçmeyen hücre KORUNUR ve
silmek için açıkça `quantity: null` gerekir. İki uç frontend'de yan yana
kullanılacağı için karıştırılması en tehlikeli kontrat hatasıdır (spec §10/2);
`tests/progress_payments/test_lines.py::test_degistirme_semantigi_govdede_olmayan_satir_silinir`
farkı doğrudan doğrular.

## Tek yol

Satır üreten HER yol buradan geçer: `PUT …/lines` *ve* `POST /projects/{id}/progress-payments`
gövdesindeki iç içe `lines[]`. Korkulukları yalnız `PUT`'a koymak, aynı geçersiz
veriyi `POST` üzerinden yazmaya izin veren bir arka kapı bırakırdı — spec §6.5
başlığı "her durumda koşar" der.

## Sıra — ÖNCE TÜM DOĞRULAMALAR, SONRA TEK YAZMA (P5 C8 dersi)

Doğrulama yazmanın arasına serpiştirilirse, ikinci satırda patlayan bir istek
birincisini çoktan session'a eklemiş olur; `get_db` rollback'i yalnız DIŞ
katmandır. İç katman — hiç yazmamak — `_resolve` ile `_apply`'ın AYRIK olmasıyla
kurulur: `_resolve` hiçbir şey yazmaz, `_apply` hiçbir şey doğrulamaz.
"""

import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import DuplicateError, SiteValidationError
from app.modules.contracts.models import EmployerContractItem
from app.modules.progress_payments import calculations, guards, repository
from app.modules.progress_payments.models import ProgressPayment, ProgressPaymentLine
from app.modules.progress_payments.schemas import ProgressPaymentLineInput
from app.modules.projects.models import Project, ProjectContract

_ZERO = Decimal("0")
_UNIT_COEFFICIENT = Decimal("1")

# (contract_item_id, site_id) — hakediş satırının hücre kimliği; kısmi benzersiz
# indeks `uq_progress_payment_lines_item_site` ile aynı üçlünün son iki alanı.
LineKey = tuple[uuid.UUID, uuid.UUID]


@dataclass(frozen=True)
class _ResolvedLine:
    """Doğrulaması BİTMİŞ satır planı — henüz hiçbir şey yazılmadı."""

    key: LineKey
    item: EmployerContractItem
    group_name: str | None
    quantity: Decimal
    coefficient: Decimal


async def prior_completed_totals(
    session: AsyncSession, project_id: uuid.UUID, before_sequence_no: int
) -> dict[LineKey, tuple[Decimal, Decimal]]:
    """(kalem, şantiye) → (önceki miktar, önceki tutar); `prev = sequence_no daha
    küçük VE status ∈ {approved, paid}` (spec §6.6).

    **Kota tavanı (§6.5/2) ile E15'in "Önceki" kolonu (§6.6) BU TEK TANIMDAN
    okur.** GOREV-SIRASI §2/1'deki P5 bulgusu tam olarak buydu: aşım kontrolü ile
    kullanıcıya gösterilen "kalan" farklı kümelerden toplanınca, ekranda kalan
    görünürken kaydetmenin 422 vermesi (veya tersi) mümkün olur. `service._line_rows`
    de buradan besleniyor; ikinci bir toplama kopyası AÇILMAZ.
    """
    prior_payments = await repository.list_prior_completed_payments(
        session, project_id, before_sequence_no
    )
    totals: dict[LineKey, tuple[Decimal, Decimal]] = {}
    for prior in prior_payments:
        for line in prior.lines:
            if line.contract_item_id is None:
                continue
            key = (line.contract_item_id, line.site_id)
            prev_qty, prev_amt = totals.get(key, (_ZERO, _ZERO))
            line_amt = calculations.line_total(
                line.contract_unit_price, line.coefficient, line.quantity
            )
            totals[key] = (prev_qty + line.quantity, prev_amt + line_amt)
    return totals


async def _resolve(
    session: AsyncSession,
    project: Project,
    contract: ProjectContract,
    inputs: list[ProgressPaymentLineInput],
    *,
    default_coefficient: Decimal,
    sequence_no: int,
    existing_coefficients: dict[LineKey, Decimal],
) -> list[_ResolvedLine]:
    """Spec §6.5'in DÖRT kuralı + FF kilidi (§10/5). **Hiçbir yazma YAPMAZ.**

    Sıra plandaki sırayla birebir: gövde-içi çift → şantiye-proje → kalem-sözleşme
    → dağıtım ön şartı → kota tavanı → FF kilidi. Sorgular satır başına DEĞİL,
    gövdenin tamamı için toplu koşar (N+1 yok).
    """
    item_ids = [entry.contract_item_id for entry in inputs]
    site_ids = [entry.site_id for entry in inputs]
    items_with_group = await repository.get_employer_items_with_group_by_ids(session, item_ids)
    sites = await repository.get_sites_by_ids(session, site_ids)
    quotas = await repository.get_distributed_quotas(session, item_ids, site_ids)
    prior_totals = await prior_completed_totals(session, project.id, sequence_no)

    seen: set[LineKey] = set()
    resolved: list[_ResolvedLine] = []
    for entry in inputs:
        key: LineKey = (entry.contract_item_id, entry.site_id)
        if key in seen:
            raise DuplicateError(guards.DUPLICATE_CELL)
        seen.add(key)

        site = sites.get(entry.site_id)
        if site is None or site.project_id != project.id:
            raise SiteValidationError(guards.SITE_PROJECT_MISMATCH)

        item_and_group = items_with_group.get(entry.contract_item_id)
        if item_and_group is None or item_and_group[0].project_id != project.id:
            raise SiteValidationError(guards.ITEM_PROJECT_MISMATCH)
        item, group_name = item_and_group

        quota = quotas.get(key)
        if quota is None:
            raise SiteValidationError(guards.ITEM_NOT_DISTRIBUTED)

        # Kümülatif = ÖNCEKİ tamamlanmış hakedişler + bu satır. Bu hakedişin
        # KENDİ eski miktarı toplama GİRMEZ: değiştirme semantiğinde eski satır
        # yerini yenisine bırakır, iki kez sayılırsa aynı taslağı yeniden
        # kaydetmek aşım verirdi.
        previous_quantity = prior_totals.get(key, (_ZERO, _ZERO))[0]
        if previous_quantity + entry.quantity > quota:
            raise SiteValidationError(guards.QUANTITY_EXCEEDS_QUOTA)

        # §4.1: öntanım YALNIZ yeni satıra iner; var olan satırın katsayısı
        # gönderilmediğinde KORUNUR (sessizce 1.000'e düşmez).
        coefficient = entry.coefficient
        if coefficient is None:
            coefficient = existing_coefficients.get(key, default_coefficient)
        if not contract.has_price_escalation and coefficient != _UNIT_COEFFICIENT:
            # Spec §10/5. Kontrol GÖNDERİLEN değil SATIRA YAZILACAK katsayı
            # üzerindedir: hakedişin `default_coefficient`'ı 1 değilken satır
            # katsayısız gönderilirse de FF'siz sözleşmeye 1 olmayan katsayı
            # YAZILMIŞ olurdu — kilit saklanan veriyi korur, gövde alanını değil.
            raise SiteValidationError(guards.ESCALATION_DISABLED)

        resolved.append(
            _ResolvedLine(
                key=key,
                item=item,
                group_name=group_name,
                quantity=entry.quantity,
                coefficient=coefficient,
            )
        )
    return resolved


def _new_line(plan: _ResolvedLine) -> ProgressPaymentLine:
    """Snapshot beşlisi (spec §5/D3-D5) YALNIZ yeni satırda kalemden kopyalanır —
    otorite sözleşme kalemidir, BOQ satırı değil. Mevcut satırın snapshot'ı
    DONMUŞTUR; tazeleme yalnız `refresh-prices` ucundadır (H7)."""
    return ProgressPaymentLine(
        contract_item_id=plan.item.id,
        site_id=plan.key[1],
        code=plan.item.code,
        description=plan.item.description,
        unit=plan.item.unit,
        contract_unit_price=plan.item.unit_price,
        coefficient=plan.coefficient,
        quantity=plan.quantity,
        group_name=plan.group_name,
    )


async def build_lines(
    session: AsyncSession,
    project: Project,
    contract: ProjectContract,
    inputs: list[ProgressPaymentLineInput],
    *,
    default_coefficient: Decimal,
    sequence_no: int,
) -> list[ProgressPaymentLine]:
    """Oluşturma yolunun (`POST …/progress-payments` iç içe `lines[]`) satırları.

    `PUT …/lines` ile AYNI `_resolve` korkuluklarından geçer — tek yol.
    """
    resolved = await _resolve(
        session,
        project,
        contract,
        inputs,
        default_coefficient=default_coefficient,
        sequence_no=sequence_no,
        existing_coefficients={},
    )
    lines = []
    for sort_order, plan in enumerate(resolved):
        line = _new_line(plan)
        line.sort_order = sort_order
        lines.append(line)
    return lines


async def apply_lines(
    session: AsyncSession,
    project: Project,
    contract: ProjectContract,
    payment: ProgressPayment,
    inputs: list[ProgressPaymentLineInput],
) -> None:
    """`PUT …/lines` gövdesini hakedişe uygular (DEĞİŞTİRME semantiği).

    Var olan hücre KORUNUR (kimliği ve snapshot'ı ile), yalnız miktar/katsayı/sıra
    güncellenir; gövdede geçmeyen hücre `delete-orphan` ile SİLİNİR. Bağı kopmuş
    (`contract_item_id IS NULL`) satırlar gövdeden ADRESLENEMEZ — gövde tablonun
    tamamı olduğu için onlar da silinir.
    """
    existing = {
        (line.contract_item_id, line.site_id): line
        for line in payment.lines
        if line.contract_item_id is not None
    }
    resolved = await _resolve(
        session,
        project,
        contract,
        inputs,
        default_coefficient=payment.default_coefficient,
        sequence_no=payment.sequence_no,
        existing_coefficients={key: line.coefficient for key, line in existing.items()},
    )

    # --- Buradan itibaren yazma; doğrulama YOK (yukarıdaki sıra kısıtı). ---
    lines: list[ProgressPaymentLine] = []
    for sort_order, plan in enumerate(resolved):
        line = existing.get(plan.key)
        if line is None:
            line = _new_line(plan)
        else:
            line.quantity = plan.quantity
            line.coefficient = plan.coefficient
        line.sort_order = sort_order
        lines.append(line)
    payment.lines = lines
    await session.flush()
