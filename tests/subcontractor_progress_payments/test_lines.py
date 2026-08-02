"""T3 — `PUT /subcontractor-progress-payments/{id}/lines` (spec §2, §4; plan T3).

Kapsam: DEĞİŞTİRME semantiği, snapshot kuralı, katsayı öntanımı, kota tavanı
(spec §4 — tavan `subcontractor_contract_items.quantity`).

İşveren `tests/progress_payments/test_lines.py` deseninin taşeron karşılığıdır;
İKİ FARK bilinçlidir ve burada doğrudan doğrulanır:
* satırda **şantiye kırılımı YOK** (hücre kimliği tek başına `contract_item_id`),
* **fiyat farkı katsayısı KİLİTSİZ** (taşeron sözleşmesinde `has_price_escalation`
  kolonu yoktur — şef kararı 2026-08-02).
"""

import uuid
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.contracts.models import SubcontractorContractItem
from app.modules.subcontractor_progress_payments import guards
from app.modules.subcontractor_progress_payments.models import (
    SubcontractorPaymentStatus,
    SubcontractorProgressPayment,
    SubcontractorProgressPaymentLine,
)

pytestmark = pytest.mark.asyncio


async def _olustur(client: AsyncClient, headers: dict[str, str], contract_id) -> dict:
    yanit = await client.post(
        f"/subcontractor-contracts/{contract_id}/progress-payments", json={}, headers=headers
    )
    assert yanit.status_code == 201, yanit.text
    return yanit.json()


async def _kaydet(client: AsyncClient, headers: dict[str, str], payment_id, satirlar: list[dict]):
    return await client.put(
        f"/subcontractor-progress-payments/{payment_id}/lines",
        json={"lines": satirlar},
        headers=headers,
    )


def _kalemler(contract) -> list[SubcontractorContractItem]:
    return sorted(contract.items, key=lambda item: item.sort_order)


async def _tamamlanmis_hakedis(
    session: AsyncSession,
    hakedis_fabrikasi,
    contract,
    creator,
    *,
    sequence_no: int,
    status: SubcontractorPaymentStatus,
    satirlar: list[tuple[SubcontractorContractItem | None, Decimal]],
    coefficient: Decimal = Decimal("1.000"),
) -> SubcontractorProgressPayment:
    """Durum geçişi uçları T4'te olduğu için tamamlanmış hakediş DOĞRUDAN yazılır."""
    payment = await hakedis_fabrikasi(contract, creator, sequence_no=sequence_no, status=status)
    for sort_order, (item, quantity) in enumerate(satirlar):
        session.add(
            SubcontractorProgressPaymentLine(
                payment_id=payment.id,
                contract_item_id=item.id if item is not None else None,
                code=item.code if item is not None else "SILINMIS",
                description="Kalem",
                unit="Ton",
                contract_unit_price=item.unit_price if item is not None else Decimal("100"),
                coefficient=coefficient,
                quantity=quantity,
                sort_order=sort_order,
            )
        )
    await session.flush()
    return payment


# --- DEĞİŞTİRME (replace) semantiği ---


async def test_govdede_olmayan_satir_silinir(
    client: AsyncClient, admin_headers: dict[str, str], taseron_sozlesmesi
) -> None:
    """İşveren ucuyla AYNI, `PUT …/contract/distribution` BİRLEŞTİRMESİNİN TERSİ."""
    contract, _, _ = taseron_sozlesmesi
    hakedis = await _olustur(client, admin_headers, contract.id)
    kalem = _kalemler(contract)[0]

    yanit = await _kaydet(
        client,
        admin_headers,
        hakedis["id"],
        [{"contract_item_id": str(kalem.id), "quantity": "10"}],
    )
    assert yanit.status_code == 200, yanit.text
    govde = yanit.json()
    assert len(govde["lines"]) == 1
    assert govde["lines"][0]["contract_item_id"] == str(kalem.id)
    assert Decimal(govde["lines"][0]["quantity"]) == Decimal("10")


async def test_bos_govde_tum_satirlari_temizler(
    client: AsyncClient, admin_headers: dict[str, str], taseron_sozlesmesi
) -> None:
    contract, _, _ = taseron_sozlesmesi
    hakedis = await _olustur(client, admin_headers, contract.id)
    yanit = await _kaydet(client, admin_headers, hakedis["id"], [])
    assert yanit.status_code == 200, yanit.text
    assert yanit.json()["lines"] == []


async def test_mevcut_satirin_kimligi_ve_snapshoti_korunur(
    client: AsyncClient, admin_headers: dict[str, str], taseron_sozlesmesi
) -> None:
    contract, _, _ = taseron_sozlesmesi
    hakedis = await _olustur(client, admin_headers, contract.id)
    kalem = _kalemler(contract)[0]
    onceki = next(s for s in hakedis["lines"] if s["contract_item_id"] == str(kalem.id))

    govde = (
        await _kaydet(
            client,
            admin_headers,
            hakedis["id"],
            [{"contract_item_id": str(kalem.id), "quantity": "7.5"}],
        )
    ).json()
    satir = govde["lines"][0]
    assert satir["id"] == onceki["id"], "mevcut satır SİLİNİP yeniden yaratılmamalı"
    assert satir["code"] == onceki["code"]
    assert Decimal(satir["contract_unit_price"]) == Decimal(onceki["contract_unit_price"])


async def test_yeni_satir_snapshot_besliyi_kalemden_alir(
    client: AsyncClient,
    admin_headers: dict[str, str],
    taseron_sozlesmesi,
    seeded_db: AsyncSession,
) -> None:
    contract, _, _ = taseron_sozlesmesi
    hakedis = await _olustur(client, admin_headers, contract.id)
    kalem = _kalemler(contract)[1]
    # Once satirlari temizle, sonra kalemi YENIDEN ekle: yeni satir yolu koşar.
    await _kaydet(client, admin_headers, hakedis["id"], [])
    govde = (
        await _kaydet(
            client,
            admin_headers,
            hakedis["id"],
            [{"contract_item_id": str(kalem.id), "quantity": "3"}],
        )
    ).json()
    satir = govde["lines"][0]
    assert satir["code"] == kalem.code
    assert satir["unit"] == kalem.unit
    assert Decimal(satir["contract_unit_price"]) == kalem.unit_price
    assert satir["group_name"] is not None, "grup adı zinciri snapshot'lanmalı"
    assert satir["quantity_source"] == "manual"


async def test_quantity_source_istekten_alinmaz(
    client: AsyncClient, admin_headers: dict[str, str], taseron_sozlesmesi
) -> None:
    """`diary` değeri site_diary dilimiyle dolar; bu dilimde HEP `manual` (spec §2)."""
    contract, _, _ = taseron_sozlesmesi
    hakedis = await _olustur(client, admin_headers, contract.id)
    kalem = _kalemler(contract)[0]
    govde = (
        await _kaydet(
            client,
            admin_headers,
            hakedis["id"],
            [
                {
                    "contract_item_id": str(kalem.id),
                    "quantity": "1",
                    "quantity_source": "diary",
                }
            ],
        )
    ).json()
    assert govde["lines"][0]["quantity_source"] == "manual"


async def test_sort_order_govde_sirasindan_turer(
    client: AsyncClient, admin_headers: dict[str, str], taseron_sozlesmesi
) -> None:
    contract, _, _ = taseron_sozlesmesi
    hakedis = await _olustur(client, admin_headers, contract.id)
    kalem1, kalem2 = _kalemler(contract)
    govde = (
        await _kaydet(
            client,
            admin_headers,
            hakedis["id"],
            [
                {"contract_item_id": str(kalem2.id), "quantity": "1"},
                {"contract_item_id": str(kalem1.id), "quantity": "2"},
            ],
        )
    ).json()
    assert [s["contract_item_id"] for s in govde["lines"]] == [str(kalem2.id), str(kalem1.id)]
    assert [s["sort_order"] for s in govde["lines"]] == [0, 1]


# --- Katsayı (şef kararı: taşeronda KİLİTSİZ) ---


async def test_katsayi_serbestce_girilir_ff_kilidi_yok(
    client: AsyncClient, admin_headers: dict[str, str], taseron_sozlesmesi
) -> None:
    """Taşeron sözleşmesinde `has_price_escalation` YOK — işverenin
    `ESCALATION_DISABLED` kilidi buraya UYGULANMAZ (şef kararı 2026-08-02)."""
    contract, _, _ = taseron_sozlesmesi
    hakedis = await _olustur(client, admin_headers, contract.id)
    kalem = _kalemler(contract)[0]
    yanit = await _kaydet(
        client,
        admin_headers,
        hakedis["id"],
        [{"contract_item_id": str(kalem.id), "quantity": "1", "coefficient": "1.250"}],
    )
    assert yanit.status_code == 200, yanit.text
    assert Decimal(yanit.json()["lines"][0]["coefficient"]) == Decimal("1.250")


async def test_katsayi_sifir_veya_negatif_422(
    client: AsyncClient, admin_headers: dict[str, str], taseron_sozlesmesi
) -> None:
    contract, _, _ = taseron_sozlesmesi
    hakedis = await _olustur(client, admin_headers, contract.id)
    kalem = _kalemler(contract)[0]
    yanit = await _kaydet(
        client,
        admin_headers,
        hakedis["id"],
        [{"contract_item_id": str(kalem.id), "quantity": "1", "coefficient": "0"}],
    )
    assert yanit.status_code == 422, yanit.text


async def test_negatif_miktar_422(
    client: AsyncClient, admin_headers: dict[str, str], taseron_sozlesmesi
) -> None:
    contract, _, _ = taseron_sozlesmesi
    hakedis = await _olustur(client, admin_headers, contract.id)
    kalem = _kalemler(contract)[0]
    yanit = await _kaydet(
        client,
        admin_headers,
        hakedis["id"],
        [{"contract_item_id": str(kalem.id), "quantity": "-1"}],
    )
    assert yanit.status_code == 422, yanit.text


async def test_ontanimli_katsayi_yalniz_yeni_satira_iner(
    client: AsyncClient, admin_headers: dict[str, str], taseron_sozlesmesi
) -> None:
    """PATCH ile değişen `default_coefficient` MEVCUT satırın katsayısını
    DEĞİŞTİRMEZ (işveren §4.1 deseni, şef kararı 2026-08-02)."""
    contract, _, _ = taseron_sozlesmesi
    hakedis = await _olustur(client, admin_headers, contract.id)
    kalem1, kalem2 = _kalemler(contract)
    # Yalniz kalem1 kalsin (kalem2 satiri duser), sonra ontanim degissin.
    await _kaydet(
        client,
        admin_headers,
        hakedis["id"],
        [{"contract_item_id": str(kalem1.id), "quantity": "1"}],
    )
    patch = await client.patch(
        f"/subcontractor-progress-payments/{hakedis['id']}",
        json={"default_coefficient": "1.400"},
        headers=admin_headers,
    )
    assert patch.status_code == 200, patch.text
    assert Decimal(patch.json()["lines"][0]["coefficient"]) == Decimal("1.000")

    govde = (
        await _kaydet(
            client,
            admin_headers,
            hakedis["id"],
            [
                {"contract_item_id": str(kalem1.id), "quantity": "1"},
                {"contract_item_id": str(kalem2.id), "quantity": "1"},
            ],
        )
    ).json()
    katsayilar = {s["contract_item_id"]: Decimal(s["coefficient"]) for s in govde["lines"]}
    assert katsayilar[str(kalem1.id)] == Decimal("1.000"), "mevcut satır korunmalı"
    assert katsayilar[str(kalem2.id)] == Decimal("1.400"), "yeni satır öntanımı almalı"


# --- Sahiplik / gövde tutarlılığı ---


async def test_baska_sozlesmenin_kalemi_422(
    client: AsyncClient,
    admin_headers: dict[str, str],
    taseron_sozlesmesi,
    taseron_sozlesmesi_fabrikasi,
) -> None:
    contract, _, _ = taseron_sozlesmesi
    yabanci, _, _ = await taseron_sozlesmesi_fabrikasi("THK-Y01")
    hakedis = await _olustur(client, admin_headers, contract.id)
    yanit = await _kaydet(
        client,
        admin_headers,
        hakedis["id"],
        [{"contract_item_id": str(_kalemler(yabanci)[0].id), "quantity": "1"}],
    )
    assert yanit.status_code == 422, yanit.text
    assert yanit.json()["detail"] == guards.ITEM_CONTRACT_MISMATCH


async def test_var_olmayan_kalem_422(
    client: AsyncClient, admin_headers: dict[str, str], taseron_sozlesmesi
) -> None:
    contract, _, _ = taseron_sozlesmesi
    hakedis = await _olustur(client, admin_headers, contract.id)
    yanit = await _kaydet(
        client,
        admin_headers,
        hakedis["id"],
        [{"contract_item_id": str(uuid.uuid4()), "quantity": "1"}],
    )
    assert yanit.status_code == 422, yanit.text
    assert yanit.json()["detail"] == guards.ITEM_CONTRACT_MISMATCH


async def test_ayni_kalem_iki_kez_409(
    client: AsyncClient, admin_headers: dict[str, str], taseron_sozlesmesi
) -> None:
    contract, _, _ = taseron_sozlesmesi
    hakedis = await _olustur(client, admin_headers, contract.id)
    kalem = _kalemler(contract)[0]
    yanit = await _kaydet(
        client,
        admin_headers,
        hakedis["id"],
        [
            {"contract_item_id": str(kalem.id), "quantity": "1"},
            {"contract_item_id": str(kalem.id), "quantity": "2"},
        ],
    )
    assert yanit.status_code == 409, yanit.text
    assert yanit.json()["detail"] == guards.DUPLICATE_LINE


async def test_fiyatsiz_kalem_satira_alinamaz_422(
    client: AsyncClient,
    admin_headers: dict[str, str],
    taseron_sozlesmesi,
    seeded_db: AsyncSession,
) -> None:
    """ "Girilmedi ≠ 0 TL" (spec §2 guard'ı) satır yazma yolunda da koşar."""
    contract, _, _ = taseron_sozlesmesi
    hakedis = await _olustur(client, admin_headers, contract.id)
    kalem = _kalemler(contract)[1]
    kalem.unit_price = None
    await seeded_db.flush()

    await _kaydet(client, admin_headers, hakedis["id"], [])
    yanit = await _kaydet(
        client,
        admin_headers,
        hakedis["id"],
        [{"contract_item_id": str(kalem.id), "quantity": "1"}],
    )
    assert yanit.status_code == 422, yanit.text
    assert yanit.json()["detail"] == guards.ITEM_PRICE_REQUIRED


async def test_draft_disinda_409(
    client: AsyncClient,
    admin_headers: dict[str, str],
    taseron_sozlesmesi,
    hakedis_fabrikasi,
    admin_kullanicisi,
) -> None:
    contract, _, _ = taseron_sozlesmesi
    payment = await hakedis_fabrikasi(
        contract, admin_kullanicisi, status=SubcontractorPaymentStatus.approved
    )
    yanit = await _kaydet(
        client,
        admin_headers,
        payment.id,
        [{"contract_item_id": str(_kalemler(contract)[0].id), "quantity": "1"}],
    )
    assert yanit.status_code == 409, yanit.text
    assert yanit.json()["detail"] == guards.INVALID_STATUS_TRANSITION


async def test_gorunmeyen_hakedise_satir_yazilamaz_404(
    client: AsyncClient, kisitli_headers: dict[str, str], gorunmeyen_hakedis
) -> None:
    yanit = await _kaydet(client, kisitli_headers, gorunmeyen_hakedis, [])
    assert yanit.status_code == 404, yanit.text
    assert yanit.json()["detail"] == guards.PAYMENT_MISSING


async def test_gecersiz_govde_kismi_yazma_birakmaz(
    client: AsyncClient,
    admin_headers: dict[str, str],
    taseron_sozlesmesi,
    seeded_db: AsyncSession,
) -> None:
    """`_resolve` HİÇBİR ŞEY yazmaz: ikinci satır patlarsa birincisi de yazılmaz."""
    contract, _, _ = taseron_sozlesmesi
    hakedis = await _olustur(client, admin_headers, contract.id)
    kalem = _kalemler(contract)[0]
    yanit = await _kaydet(
        client,
        admin_headers,
        hakedis["id"],
        [
            {"contract_item_id": str(kalem.id), "quantity": "9"},
            {"contract_item_id": str(uuid.uuid4()), "quantity": "1"},
        ],
    )
    assert yanit.status_code == 422, yanit.text
    satirlar = (
        (
            await seeded_db.execute(
                select(SubcontractorProgressPaymentLine).where(
                    SubcontractorProgressPaymentLine.payment_id == uuid.UUID(hakedis["id"])
                )
            )
        )
        .scalars()
        .all()
    )
    assert all(satir.quantity == Decimal("0") for satir in satirlar), "kısmi yazma bırakılmış"


# --- Kota (spec §4: tavan = `subcontractor_contract_items.quantity`) ---


async def test_kota_asimi_422_kalem_ve_kalan_mesajda(
    client: AsyncClient, admin_headers: dict[str, str], taseron_sozlesmesi
) -> None:
    contract, _, _ = taseron_sozlesmesi
    hakedis = await _olustur(client, admin_headers, contract.id)
    kalem = _kalemler(contract)[0]  # sözleşme miktarı 200
    yanit = await _kaydet(
        client,
        admin_headers,
        hakedis["id"],
        [{"contract_item_id": str(kalem.id), "quantity": "201"}],
    )
    assert yanit.status_code == 422, yanit.text
    detay = yanit.json()["detail"]
    assert kalem.code in detay, "aşılan kalem mesajda olmalı"
    assert "200" in detay, "kalan miktar mesajda olmalı"


async def test_kota_tam_tavanda_gecer(
    client: AsyncClient, admin_headers: dict[str, str], taseron_sozlesmesi
) -> None:
    contract, _, _ = taseron_sozlesmesi
    hakedis = await _olustur(client, admin_headers, contract.id)
    kalem = _kalemler(contract)[0]
    yanit = await _kaydet(
        client,
        admin_headers,
        hakedis["id"],
        [{"contract_item_id": str(kalem.id), "quantity": "200"}],
    )
    assert yanit.status_code == 200, yanit.text


async def test_kota_onaylanmis_ve_odenmis_hakedisleri_toplar(
    client: AsyncClient,
    admin_headers: dict[str, str],
    taseron_sozlesmesi,
    hakedis_fabrikasi,
    admin_kullanicisi,
    seeded_db: AsyncSession,
) -> None:
    contract, _, _ = taseron_sozlesmesi
    kalem = _kalemler(contract)[0]
    await _tamamlanmis_hakedis(
        seeded_db,
        hakedis_fabrikasi,
        contract,
        admin_kullanicisi,
        sequence_no=1,
        status=SubcontractorPaymentStatus.approved,
        satirlar=[(kalem, Decimal("150"))],
    )
    await _tamamlanmis_hakedis(
        seeded_db,
        hakedis_fabrikasi,
        contract,
        admin_kullanicisi,
        sequence_no=2,
        status=SubcontractorPaymentStatus.paid,
        satirlar=[(kalem, Decimal("30"))],
    )
    hakedis = await _olustur(client, admin_headers, contract.id)

    asan = await _kaydet(
        client,
        admin_headers,
        hakedis["id"],
        [{"contract_item_id": str(kalem.id), "quantity": "21"}],
    )
    assert asan.status_code == 422, asan.text
    gecen = await _kaydet(
        client,
        admin_headers,
        hakedis["id"],
        [{"contract_item_id": str(kalem.id), "quantity": "20"}],
    )
    assert gecen.status_code == 200, gecen.text


async def test_kota_taslak_hakedisi_saymaz(
    client: AsyncClient,
    admin_headers: dict[str, str],
    taseron_sozlesmesi_fabrikasi,
    hakedis_fabrikasi,
    admin_kullanicisi,
    seeded_db: AsyncSession,
) -> None:
    """Kümülatif küme YALNIZ `approved|paid`tir — sonuçlanmamış evrak sayılsaydı
    aynı miktar iki kez muhasebeleşirdi.

    İkinci hakediş DOĞRUDAN DB'ye yazılır: `POST` ucu aynı sözleşmede açık evrak
    varken 409 verir (spec §5), oysa test edilen kural KOTA muhasebesidir.
    """
    contract, _, _ = await taseron_sozlesmesi_fabrikasi("THK-K10")
    kalem = _kalemler(contract)[0]
    await _tamamlanmis_hakedis(
        seeded_db,
        hakedis_fabrikasi,
        contract,
        admin_kullanicisi,
        sequence_no=1,
        status=SubcontractorPaymentStatus.pending_approval,
        satirlar=[(kalem, Decimal("190"))],
    )
    ikinci = await hakedis_fabrikasi(contract, admin_kullanicisi, sequence_no=2)
    yanit = await _kaydet(
        client, admin_headers, ikinci.id, [{"contract_item_id": str(kalem.id), "quantity": "200"}]
    )
    assert yanit.status_code == 200, yanit.text


async def test_kota_bagi_kopmus_satiri_kumulatiften_duser(
    client: AsyncClient,
    admin_headers: dict[str, str],
    taseron_sozlesmesi,
    hakedis_fabrikasi,
    admin_kullanicisi,
    seeded_db: AsyncSession,
) -> None:
    """ONAYLI SAPMA (işveren §6.5 notunun aynısı): `contract_item_id IS NULL`
    satır hangi kaleme yazılacağını KAYBETMİŞTİR, kümülatiften kalıcı düşer."""
    contract, _, _ = taseron_sozlesmesi
    kalem = _kalemler(contract)[0]
    await _tamamlanmis_hakedis(
        seeded_db,
        hakedis_fabrikasi,
        contract,
        admin_kullanicisi,
        sequence_no=1,
        status=SubcontractorPaymentStatus.approved,
        satirlar=[(None, Decimal("150"))],
    )
    hakedis = await _olustur(client, admin_headers, contract.id)
    yanit = await _kaydet(
        client,
        admin_headers,
        hakedis["id"],
        [{"contract_item_id": str(kalem.id), "quantity": "200"}],
    )
    assert yanit.status_code == 200, yanit.text


async def test_kota_yalniz_artista_kosar(
    client: AsyncClient,
    admin_headers: dict[str, str],
    taseron_sozlesmesi,
    seeded_db: AsyncSession,
) -> None:
    """Kota sonradan düşürülürse (sözleşme miktarı revize) taslak KİLİTLENMEZ:
    azaltma ve `0` her zaman serbesttir (işveren H5 denetimi O1 dersi)."""
    contract, _, _ = taseron_sozlesmesi
    hakedis = await _olustur(client, admin_headers, contract.id)
    kalem = _kalemler(contract)[0]
    assert (
        await _kaydet(
            client,
            admin_headers,
            hakedis["id"],
            [{"contract_item_id": str(kalem.id), "quantity": "200"}],
        )
    ).status_code == 200

    kalem.quantity = Decimal("100")
    await seeded_db.flush()

    azaltma = await _kaydet(
        client,
        admin_headers,
        hakedis["id"],
        [{"contract_item_id": str(kalem.id), "quantity": "150"}],
    )
    assert azaltma.status_code == 200, azaltma.text
    artis = await _kaydet(
        client,
        admin_headers,
        hakedis["id"],
        [{"contract_item_id": str(kalem.id), "quantity": "160"}],
    )
    assert artis.status_code == 422, artis.text


async def test_kota_kendi_eski_miktarini_iki_kez_saymaz(
    client: AsyncClient, admin_headers: dict[str, str], taseron_sozlesmesi
) -> None:
    contract, _, _ = taseron_sozlesmesi
    hakedis = await _olustur(client, admin_headers, contract.id)
    kalem = _kalemler(contract)[0]
    govde = [{"contract_item_id": str(kalem.id), "quantity": "120"}]
    assert (await _kaydet(client, admin_headers, hakedis["id"], govde)).status_code == 200
    ikinci = await _kaydet(client, admin_headers, hakedis["id"], govde)
    assert ikinci.status_code == 200, ikinci.text


async def test_denetim_kaydi_yazilir(
    client: AsyncClient,
    admin_headers: dict[str, str],
    taseron_sozlesmesi,
    seeded_db: AsyncSession,
) -> None:
    from app.modules.audit.models import AuditLog

    contract, _, _ = taseron_sozlesmesi
    hakedis = await _olustur(client, admin_headers, contract.id)
    kalem = _kalemler(contract)[0]
    await _kaydet(
        client,
        admin_headers,
        hakedis["id"],
        [{"contract_item_id": str(kalem.id), "quantity": "1"}],
    )
    kayitlar = (await seeded_db.execute(select(AuditLog))).scalars().all()
    assert any("satırları kaydedildi" in kayit.detail for kayit in kayitlar), [
        k.detail for k in kayitlar
    ]


async def test_ayni_hakedis_iki_kez_okunmaz_payment_kilitlenir(
    client: AsyncClient, admin_headers: dict[str, str], taseron_sozlesmesi, monkeypatch
) -> None:
    """Yazma yolu KİLİTLİ satır üzerinden çalışır (yarış koşulu, spec §4)."""
    from app.modules.subcontractor_progress_payments import repository

    contract, _, _ = taseron_sozlesmesi
    hakedis = await _olustur(client, admin_headers, contract.id)
    kalem = _kalemler(contract)[0]

    cagrilar: list[uuid.UUID] = []
    gercek = repository.get_payment_locked

    async def casus(session, payment_id):
        cagrilar.append(payment_id)
        return await gercek(session, payment_id)

    monkeypatch.setattr(repository, "get_payment_locked", casus)
    await _kaydet(
        client,
        admin_headers,
        hakedis["id"],
        [{"contract_item_id": str(kalem.id), "quantity": "1"}],
    )
    assert cagrilar, "PUT …/lines `SELECT … FOR UPDATE` almadan yazıyor"


async def test_bagi_kopmus_satir_duser_ve_sayisi_bildirilir(
    client: AsyncClient,
    admin_headers: dict[str, str],
    taseron_sozlesmesi,
    seeded_db: AsyncSession,
) -> None:
    """Kalemi silinmiş satır gövdeden ADRESLENEMEZ → düşer; sessiz DEĞİL:
    `dropped_orphan_count` ile bildirilir."""
    contract, _, _ = taseron_sozlesmesi
    hakedis = await _olustur(client, admin_headers, contract.id)
    satirlar = (
        (
            await seeded_db.execute(
                select(SubcontractorProgressPaymentLine).where(
                    SubcontractorProgressPaymentLine.payment_id == uuid.UUID(hakedis["id"])
                )
            )
        )
        .scalars()
        .all()
    )
    satirlar[0].contract_item_id = None
    await seeded_db.flush()

    kalem = _kalemler(contract)[1]
    govde = (
        await _kaydet(
            client,
            admin_headers,
            hakedis["id"],
            [{"contract_item_id": str(kalem.id), "quantity": "1"}],
        )
    ).json()
    assert govde["dropped_orphan_count"] == 1
    assert len(govde["lines"]) == 1


async def test_sort_order_istekten_alinabilir(
    client: AsyncClient, admin_headers: dict[str, str], taseron_sozlesmesi
) -> None:
    contract, _, _ = taseron_sozlesmesi
    hakedis = await _olustur(client, admin_headers, contract.id)
    kalem1, kalem2 = _kalemler(contract)
    govde = (
        await _kaydet(
            client,
            admin_headers,
            hakedis["id"],
            [
                {"contract_item_id": str(kalem1.id), "quantity": "1", "sort_order": 5},
                {"contract_item_id": str(kalem2.id), "quantity": "1", "sort_order": 2},
            ],
        )
    ).json()
    # `lines` ilişkisi `sort_order` ile sıralanır — gönderilen sıra otoritedir.
    assert [s["sort_order"] for s in govde["lines"]] == [2, 5]
    assert govde["lines"][0]["contract_item_id"] == str(kalem2.id)
