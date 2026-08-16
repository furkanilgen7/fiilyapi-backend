"""`summary.cumulative_gross_by_contracts` — sözleşme listesi (SZL) KPI'ının
toplu kümülatif brüt sorgusu; işveren `cumulative_gross_by_projects`in eşleniği.

Bu dosya bu modüldeki `test_summary.py`den AYRI bir davranışı ölçer: oradaki
`total_gross` kartı TÜM statüleri (taslak dahil) sayar ve `/hakedisler/taseron`
ekranına aittir; buradaki fonksiyon yalnız `approved|paid` sayar ve sözleşme
listesine aittir. İkisi karıştırılırsa taslak hakedişler sözleşme kartında
"gerçekleşmiş" gibi görünür.

Kurulumdaki tutarlar bilerek BİRBİRİNDEN FARKLIDIR: eşit tutarlar toplama ve
anahtar karışması hatalarını maskeler.
"""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.contracts.models import SubcontractorContract, SubcontractorContractItem
from app.modules.subcontractor_progress_payments import summary
from app.modules.subcontractor_progress_payments.models import (
    SubcontractorPaymentStatus,
    SubcontractorProgressPayment,
    SubcontractorProgressPaymentLine,
)
from app.modules.users.models import User

pytestmark = pytest.mark.asyncio

# Fixture kalem birim fiyatları: kalem#0 = 21.500, kalem#1 = 1.850.
BIRIM_A = Decimal("21500")
BIRIM_B = Decimal("1850")


def _kalemler(contract: SubcontractorContract) -> list[SubcontractorContractItem]:
    return sorted(contract.items, key=lambda item: item.sort_order)


async def _hakedis(
    session: AsyncSession,
    hakedis_fabrikasi,
    contract: SubcontractorContract,
    creator: User,
    *,
    sequence_no: int,
    status: SubcontractorPaymentStatus,
    miktar: Decimal,
    kalem_index: int = 0,
) -> SubcontractorProgressPayment:
    payment = await hakedis_fabrikasi(
        contract,
        creator,
        sequence_no=sequence_no,
        status=status,
        period_year=2026,
        period_month=7,
    )
    item = _kalemler(contract)[kalem_index]
    session.add(
        SubcontractorProgressPaymentLine(
            payment_id=payment.id,
            contract_item_id=item.id,
            code=item.code,
            description=item.description,
            unit=item.unit,
            contract_unit_price=item.unit_price,
            coefficient=Decimal("1.000"),
            quantity=miktar,
            sort_order=0,
        )
    )
    await session.flush()
    return payment


async def test_iki_onayli_hakedisin_brutu_toplanir(
    seeded_db: AsyncSession,
    taseron_sozlesmesi_fabrikasi,
    hakedis_fabrikasi,
    sozlesme_sahibi: User,
) -> None:
    # Arrange — iki hakedişin brütü FARKLI: eşit olsaydı toplama hatası gizlenirdi.
    contract, _, _ = await taseron_sozlesmesi_fabrikasi("THK-C01")
    await _hakedis(  # 10 × 21.500 = 215.000
        seeded_db,
        hakedis_fabrikasi,
        contract,
        sozlesme_sahibi,
        sequence_no=1,
        status=SubcontractorPaymentStatus.approved,
        miktar=Decimal("10"),
    )
    await _hakedis(  # 3 × 1.850 = 5.550
        seeded_db,
        hakedis_fabrikasi,
        contract,
        sozlesme_sahibi,
        sequence_no=2,
        status=SubcontractorPaymentStatus.approved,
        miktar=Decimal("3"),
        kalem_index=1,
    )

    # Act
    sonuc = await summary.cumulative_gross_by_contracts(seeded_db, [contract.id])

    # Assert
    assert sonuc[contract.id] == Decimal("220550.00")


async def test_taslak_ve_onay_bekleyen_toplama_girmez(
    seeded_db: AsyncSession,
    taseron_sozlesmesi_fabrikasi,
    hakedis_fabrikasi,
    sozlesme_sahibi: User,
) -> None:
    # Arrange — aynı sözleşmede bir approved + bir draft + bir pending_approval,
    # üçünün brütü de FARKLI (dışlananlar sonuçta görülmemeli).
    contract, _, _ = await taseron_sozlesmesi_fabrikasi("THK-C02")
    await _hakedis(  # 10 × 21.500 = 215.000 (SAYILIR)
        seeded_db,
        hakedis_fabrikasi,
        contract,
        sozlesme_sahibi,
        sequence_no=1,
        status=SubcontractorPaymentStatus.approved,
        miktar=Decimal("10"),
    )
    await _hakedis(  # 7 × 21.500 = 150.500 (SAYILMAZ)
        seeded_db,
        hakedis_fabrikasi,
        contract,
        sozlesme_sahibi,
        sequence_no=2,
        status=SubcontractorPaymentStatus.draft,
        miktar=Decimal("7"),
    )
    await _hakedis(  # 2 × 1.850 = 3.700 (SAYILMAZ)
        seeded_db,
        hakedis_fabrikasi,
        contract,
        sozlesme_sahibi,
        sequence_no=3,
        status=SubcontractorPaymentStatus.pending_approval,
        miktar=Decimal("2"),
        kalem_index=1,
    )

    # Act
    sonuc = await summary.cumulative_gross_by_contracts(seeded_db, [contract.id])

    # Assert — yalnız approved'ın brütü.
    assert sonuc[contract.id] == Decimal("215000.00")


async def test_odenmis_hakedis_sayilir(
    seeded_db: AsyncSession,
    taseron_sozlesmesi_fabrikasi,
    hakedis_fabrikasi,
    sozlesme_sahibi: User,
) -> None:
    # Arrange — bir approved + bir paid, brütleri FARKLI.
    contract, _, _ = await taseron_sozlesmesi_fabrikasi("THK-C03")
    await _hakedis(  # 4 × 21.500 = 86.000
        seeded_db,
        hakedis_fabrikasi,
        contract,
        sozlesme_sahibi,
        sequence_no=1,
        status=SubcontractorPaymentStatus.paid,
        miktar=Decimal("4"),
    )
    await _hakedis(  # 6 × 1.850 = 11.100
        seeded_db,
        hakedis_fabrikasi,
        contract,
        sozlesme_sahibi,
        sequence_no=2,
        status=SubcontractorPaymentStatus.approved,
        miktar=Decimal("6"),
        kalem_index=1,
    )

    # Act
    sonuc = await summary.cumulative_gross_by_contracts(seeded_db, [contract.id])

    # Assert
    assert sonuc[contract.id] == Decimal("97100.00")


async def test_iki_sozlesmenin_tutarlari_karismaz(
    seeded_db: AsyncSession,
    taseron_sozlesmesi_fabrikasi,
    hakedis_fabrikasi,
    sozlesme_sahibi: User,
) -> None:
    # Arrange — iki sözleşmenin TOPLAMLARI da farklı.
    a, proje, _ = await taseron_sozlesmesi_fabrikasi("THK-C04")
    b, _, _ = await taseron_sozlesmesi_fabrikasi("THK-C05", project=proje)
    await _hakedis(  # A: 10 × 21.500 = 215.000
        seeded_db,
        hakedis_fabrikasi,
        a,
        sozlesme_sahibi,
        sequence_no=1,
        status=SubcontractorPaymentStatus.approved,
        miktar=Decimal("10"),
    )
    await _hakedis(  # B: 8 × 1.850 = 14.800
        seeded_db,
        hakedis_fabrikasi,
        b,
        sozlesme_sahibi,
        sequence_no=1,
        status=SubcontractorPaymentStatus.paid,
        miktar=Decimal("8"),
        kalem_index=1,
    )

    # Act
    sonuc = await summary.cumulative_gross_by_contracts(seeded_db, [a.id, b.id])

    # Assert — her tutar KENDİ anahtarında; öbürünün anahtarında GÖRÜNMEZ.
    assert sonuc[a.id] == Decimal("215000.00")
    assert sonuc[b.id] == Decimal("14800.00")
    assert sonuc[b.id] != Decimal("215000.00")
    assert sonuc[a.id] != Decimal("14800.00")


async def test_bos_kimlik_listesi_bos_sozluk_dondurur(seeded_db: AsyncSession) -> None:
    # Act
    sonuc = await summary.cumulative_gross_by_contracts(seeded_db, [])

    # Assert
    assert sonuc == {}


async def test_kapsam_disindaki_sozlesme_sonuca_girmez(
    seeded_db: AsyncSession,
    taseron_sozlesmesi_fabrikasi,
    hakedis_fabrikasi,
    sozlesme_sahibi: User,
) -> None:
    # Arrange — üçüncü sözleşmenin hakedişi var ama listeye KONMAZ.
    istenen, proje, _ = await taseron_sozlesmesi_fabrikasi("THK-C06")
    kapsam_disi, _, _ = await taseron_sozlesmesi_fabrikasi("THK-C07", project=proje)
    await _hakedis(  # istenen: 10 × 21.500 = 215.000
        seeded_db,
        hakedis_fabrikasi,
        istenen,
        sozlesme_sahibi,
        sequence_no=1,
        status=SubcontractorPaymentStatus.approved,
        miktar=Decimal("10"),
    )
    await _hakedis(  # kapsam dışı: 9 × 1.850 = 16.650
        seeded_db,
        hakedis_fabrikasi,
        kapsam_disi,
        sozlesme_sahibi,
        sequence_no=1,
        status=SubcontractorPaymentStatus.approved,
        miktar=Decimal("9"),
        kalem_index=1,
    )

    # Act
    sonuc = await summary.cumulative_gross_by_contracts(seeded_db, [istenen.id])

    # Assert
    assert sonuc == {istenen.id: Decimal("215000.00")}
    assert kapsam_disi.id not in sonuc


async def test_hakedissiz_sozlesmenin_anahtari_yok(
    seeded_db: AsyncSession,
    taseron_sozlesmesi_fabrikasi,
    hakedis_fabrikasi,
    sozlesme_sahibi: User,
) -> None:
    # Arrange — B'nin hiç hakedişi yok (çağıran katman `.get(id, 0)` ile sıfırlar).
    a, proje, _ = await taseron_sozlesmesi_fabrikasi("THK-C08")
    b, _, _ = await taseron_sozlesmesi_fabrikasi("THK-C09", project=proje)
    await _hakedis(
        seeded_db,
        hakedis_fabrikasi,
        a,
        sozlesme_sahibi,
        sequence_no=1,
        status=SubcontractorPaymentStatus.approved,
        miktar=Decimal("10"),
    )

    # Act
    sonuc = await summary.cumulative_gross_by_contracts(seeded_db, [a.id, b.id])

    # Assert
    assert b.id not in sonuc
    assert sonuc[a.id] == Decimal("215000.00")


async def test_hicbir_sozlesmenin_hakedisi_yoksa_bos_sozluk(
    seeded_db: AsyncSession, taseron_sozlesmesi_fabrikasi
) -> None:
    # Arrange
    contract, _, _ = await taseron_sozlesmesi_fabrikasi("THK-C10")

    # Act
    sonuc = await summary.cumulative_gross_by_contracts(seeded_db, [contract.id, uuid.uuid4()])

    # Assert
    assert sonuc == {}
