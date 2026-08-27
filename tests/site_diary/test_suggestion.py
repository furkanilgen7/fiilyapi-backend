"""Şantiye günlüğü öneri ucu — İŞVEREN ve TAŞERON MUTLU YOLLARI (S5 köprüsü).

Öneri yanıtı `PUT lines` gövdesine BİREBİR uyar: uyumsuzluk sessiz veri hatası
üretir. Aynı kalem iki şantiyede AYRI satır açar; başka projenin/şantiyenin
kalemi KARIŞMAZ.

⚠️ Dosya 800 satır tavanını aşınca BÖLÜNDÜ (`_journal.py` emsali): ortak
kurallar, SALT OKUNURLUK ve IDOR/izin iddiaları
`test_suggestion_kurallar.py`ye taşındı; paylaşılan yardımcılar
`_suggestion.py`dedir. Hiçbir testin iddiası değişmedi.
"""

from datetime import date
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.contracts.models import SubcontractorContractItem
from app.modules.progress_payments.schemas import ProgressPaymentLinesSave
from app.modules.site_diary import guards
from app.modules.subcontractor_progress_payments.schemas import (
    SubcontractorProgressPaymentLinesSave,
)

from ._suggestion import (
    DONEM,
    _gun,
    _isveren_onerisi,
    _satir,
    _taseron_onerisi,
)

pytestmark = pytest.mark.asyncio


async def test_isveren_mutlu_yol_koprulu_pozlar_santiye_kirilimiyla_toplanir(
    client: AsyncClient, admin_headers, santiye, sozlesme_kalemi_fabrikasi
) -> None:
    """İki gönderilmiş gün → poz bazlı TOPLAM; kırılım (kalem, şantiye) çiftidir
    (işveren `PUT …/lines` hücresinin kimliği)."""
    site, project, items = santiye
    kalem_a, kalem_b = sorted(items, key=lambda i: i.code)
    sozlesme_a = await sozlesme_kalemi_fabrikasi(kalem_a, project)
    sozlesme_b = await sozlesme_kalemi_fabrikasi(kalem_b, project)

    await _gun(
        client,
        admin_headers,
        site.id,
        date(2026, 7, 10),
        [
            {"boq_item_id": str(kalem_a.id), "quantity": "10"},
            {"boq_item_id": str(kalem_b.id), "quantity": "4.5"},
        ],
    )
    await _gun(
        client,
        admin_headers,
        site.id,
        date(2026, 7, 12),
        [{"boq_item_id": str(kalem_a.id), "quantity": "5"}],
    )

    yanit = await _isveren_onerisi(client, admin_headers, project.id, **DONEM)
    assert yanit.status_code == 200, yanit.text
    govde = yanit.json()

    assert govde["project_id"] == str(project.id)
    assert govde["year"] == 2026 and govde["month"] == 7
    assert len(govde["lines"]) == 2
    assert Decimal(_satir(govde, sozlesme_a.id, site.id)["quantity"]) == Decimal("15")
    assert Decimal(_satir(govde, sozlesme_b.id, site.id)["quantity"]) == Decimal("4.5")
    assert govde["skipped_unbridged_count"] == 0
    assert govde["reason"] is None


async def test_isveren_ayni_kalem_iki_santiyede_AYRI_satir(
    client: AsyncClient, admin_headers, santiye, santiye_fabrikasi, sozlesme_kalemi_fabrikasi, proje
) -> None:
    """İşveren sözleşme kalemi PROJE düzeyindedir, hakediş hücresi (kalem, şantiye)
    kırılımlıdır: aynı kaleme köprülü iki şantiye TEK satırda TOPLANAMAZ."""
    site_a, project, items_a = santiye
    site_b, _, items_b = await santiye_fabrikasi("SD-B", project=proje)
    kalem_a = sorted(items_a, key=lambda i: i.code)[0]
    kalem_b = sorted(items_b, key=lambda i: i.code)[0]

    sozlesme = await sozlesme_kalemi_fabrikasi(kalem_a, project)
    kalem_b.contract_item_id = sozlesme.id

    await _gun(
        client,
        admin_headers,
        site_a.id,
        date(2026, 7, 10),
        [{"boq_item_id": str(kalem_a.id), "quantity": "10"}],
    )
    await _gun(
        client,
        admin_headers,
        site_b.id,
        date(2026, 7, 10),
        [{"boq_item_id": str(kalem_b.id), "quantity": "7"}],
    )

    govde = (await _isveren_onerisi(client, admin_headers, project.id, **DONEM)).json()
    assert len(govde["lines"]) == 2
    assert Decimal(_satir(govde, sozlesme.id, site_a.id)["quantity"]) == Decimal("10")
    assert Decimal(_satir(govde, sozlesme.id, site_b.id)["quantity"]) == Decimal("7")


async def test_isveren_yaniti_PUT_lines_govdesine_BIREBIR_uyar(
    client: AsyncClient, admin_headers, santiye, sozlesme_kalemi_fabrikasi
) -> None:
    """Sözleşmenin özü: öneri gövdesi DEĞİŞTİRİLMEDEN `PUT …/lines`a gönderilir."""
    site, project, items = santiye
    kalem = sorted(items, key=lambda i: i.code)[0]
    sozlesme = await sozlesme_kalemi_fabrikasi(kalem, project)
    await _gun(
        client,
        admin_headers,
        site.id,
        date(2026, 7, 10),
        [{"boq_item_id": str(kalem.id), "quantity": "12"}],
    )

    oneri = (await _isveren_onerisi(client, admin_headers, project.id, **DONEM)).json()
    # 1) Şema düzeyinde: gövde `PUT …/lines`ın Pydantic modeliyle DOĞRULANIR.
    ProgressPaymentLinesSave.model_validate({"lines": oneri["lines"]})

    # 2) Uçtan uca: taslak hakedişe olduğu gibi gönderilir.
    hakedis = await client.post(
        f"/projects/{project.id}/progress-payments", json={}, headers=admin_headers
    )
    assert hakedis.status_code == 201, hakedis.text
    kaydet = await client.put(
        f"/progress-payments/{hakedis.json()['id']}/lines",
        json={"lines": oneri["lines"]},
        headers=admin_headers,
    )
    assert kaydet.status_code == 200, kaydet.text
    yazilan = kaydet.json()["lines"]
    assert len(yazilan) == 1
    assert Decimal(yazilan[0]["quantity"]) == Decimal("12")
    assert yazilan[0]["contract_item_id"] == str(sozlesme.id)


# --- Taşeron: mutlu yol + S5 ---


async def test_taseron_mutlu_yol_source_contract_item_koprusu(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers,
    santiye,
    sozlesme_kalemi_fabrikasi,
    taseron_sozlesmesi_fabrikasi,
) -> None:
    site, project, items = santiye
    kalem_a, kalem_b = sorted(items, key=lambda i: i.code)
    sozlesme_a = await sozlesme_kalemi_fabrikasi(kalem_a, project)
    sozlesme_b = await sozlesme_kalemi_fabrikasi(kalem_b, project)
    tas_sozlesme = await taseron_sozlesmesi_fabrikasi(
        project, site=site, kalemler=[("TK-1", sozlesme_a), ("TK-2", sozlesme_b)]
    )

    await _gun(
        client,
        admin_headers,
        site.id,
        date(2026, 7, 10),
        [
            {"boq_item_id": str(kalem_a.id), "quantity": "10"},
            {"boq_item_id": str(kalem_b.id), "quantity": "3"},
        ],
    )
    await _gun(
        client,
        admin_headers,
        site.id,
        date(2026, 7, 11),
        [{"boq_item_id": str(kalem_a.id), "quantity": "2.5"}],
    )

    yanit = await _taseron_onerisi(client, admin_headers, tas_sozlesme.id, **DONEM)
    assert yanit.status_code == 200, yanit.text
    govde = yanit.json()
    assert govde["contract_id"] == str(tas_sozlesme.id)
    assert govde["site_id"] == str(site.id)
    assert govde["reason"] is None
    kalemler = {s["contract_item_id"]: Decimal(s["quantity"]) for s in govde["lines"]}
    ids = {
        kod: kimlik
        for kimlik, kod in (
            await seeded_db.execute(
                select(SubcontractorContractItem.id, SubcontractorContractItem.code).where(
                    SubcontractorContractItem.contract_id == tas_sozlesme.id
                )
            )
        ).all()
    }
    assert kalemler[str(ids["TK-1"])] == Decimal("12.5")
    assert kalemler[str(ids["TK-2"])] == Decimal("3")


async def test_taseron_yaniti_PUT_lines_govdesine_BIREBIR_uyar(
    client: AsyncClient,
    admin_headers,
    santiye,
    sozlesme_kalemi_fabrikasi,
    taseron_sozlesmesi_fabrikasi,
) -> None:
    site, project, items = santiye
    kalem = sorted(items, key=lambda i: i.code)[0]
    sozlesme = await sozlesme_kalemi_fabrikasi(kalem, project)
    tas_sozlesme = await taseron_sozlesmesi_fabrikasi(
        project, site=site, kalemler=[("TK-1", sozlesme)]
    )
    await _gun(
        client,
        admin_headers,
        site.id,
        date(2026, 7, 10),
        [{"boq_item_id": str(kalem.id), "quantity": "9"}],
    )

    oneri = (await _taseron_onerisi(client, admin_headers, tas_sozlesme.id, **DONEM)).json()
    SubcontractorProgressPaymentLinesSave.model_validate({"lines": oneri["lines"]})

    hakedis = await client.post(
        f"/subcontractor-contracts/{tas_sozlesme.id}/progress-payments",
        json={},
        headers=admin_headers,
    )
    assert hakedis.status_code == 201, hakedis.text
    kaydet = await client.put(
        f"/subcontractor-progress-payments/{hakedis.json()['id']}/lines",
        json={"lines": oneri["lines"]},
        headers=admin_headers,
    )
    assert kaydet.status_code == 200, kaydet.text
    yazilan = [s for s in kaydet.json()["lines"] if Decimal(s["quantity"]) != 0]
    assert len(yazilan) == 1
    assert Decimal(yazilan[0]["quantity"]) == Decimal("9")


async def test_taseron_sitesiz_sozlesme_PROJE_TOPLAMINI_verir(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers,
    proje,
    santiye,
    santiye_fabrikasi,
    sozlesme_kalemi_fabrikasi,
    taseron_sozlesmesi_fabrikasi,
) -> None:
    """Spec §7 S5 tersine çevrildi, kullanıcı kararı 2026-08-27.

    ESKİ İDDİA (yerine geçtiği test
    `test_taseron_sitesiz_sozlesme_BOS_ve_ACIK_GEREKCE`): proje-geneli (site'sız)
    sözleşme kapsam DIŞIdır → `lines == []` ve
    `reason == guards.SUGGESTION_CONTRACT_WITHOUT_SITE`.

    YENİ İDDİA: proje-geneli sözleşmenin doğru cevabı PROJENİN TÜM
    ŞANTİYELERİNİN toplamıdır (9 + 4 = 13). Gruplama yalnız KALEMDİR (taşeron
    satırında şantiye kırılımı yoktur), `site_id` yanıtta NULL kalır ve gerekçe
    ÜRETİLMEZ — liste artık boş değildir.
    """
    site_a, project, pozlar_a = santiye
    poz_a = sorted(pozlar_a, key=lambda i: i.code)[0]
    sozlesme = await sozlesme_kalemi_fabrikasi(poz_a, project)

    site_b, _, pozlar_b = await santiye_fabrikasi("SD-GEN-B", project=proje)
    poz_b = sorted(pozlar_b, key=lambda i: i.code)[0]
    poz_b.contract_item_id = sozlesme.id
    await seeded_db.flush()

    tas_sozlesme = await taseron_sozlesmesi_fabrikasi(
        project, site=None, kalemler=[("TK-1", sozlesme)], code="TS-GENEL"
    )
    await _gun(
        client,
        admin_headers,
        site_a.id,
        date(2026, 7, 10),
        [{"boq_item_id": str(poz_a.id), "quantity": "9"}],
    )
    await _gun(
        client,
        admin_headers,
        site_b.id,
        date(2026, 7, 11),
        [{"boq_item_id": str(poz_b.id), "quantity": "4"}],
    )
    tk1 = (
        await seeded_db.execute(
            select(SubcontractorContractItem.id).where(
                SubcontractorContractItem.contract_id == tas_sozlesme.id
            )
        )
    ).scalar_one()

    govde = (await _taseron_onerisi(client, admin_headers, tas_sozlesme.id, **DONEM)).json()
    assert {s["contract_item_id"]: Decimal(s["quantity"]) for s in govde["lines"]} == {
        str(tk1): Decimal("13")
    }
    assert govde["site_id"] is None
    assert govde["reason"] is None


async def test_taseron_baska_santiyenin_gunlugu_KARISMAZ(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers,
    santiye,
    santiye_fabrikasi,
    sozlesme_kalemi_fabrikasi,
    taseron_sozlesmesi_fabrikasi,
    proje,
) -> None:
    """Sözleşme B şantiyesine bağlıysa A şantiyesinin günlüğü öneriye GİREMEZ.

    🔴 GÜÇLENDİRİLDİ (TH-PRJGENEL): proje-geneli sözleşmenin süzgeci PROJE
    olunca, ŞANTİYEYE BAĞLI sözleşmeninkinin de sessizce projeye genişlemesi
    (yani süzgecin tümden kalkması) EN OLASI bozulmadır. Bu yüzden A şantiyesi
    artık B ile AYNI PROJEDEDİR ve pozu B'nin pozuyla AYNI işveren kalemine
    köprülüdür: yalnız ŞANTİYE süzgeci onu dışarıda tutabilir. `reason` da
    ölçülür — süzgeç kalkarsa liste dolar ve gerekçe NULL olur.
    """
    site_a, project, items_a = santiye
    site_b, _, items_b = await santiye_fabrikasi("SD-B", project=proje)
    kalem_a = sorted(items_a, key=lambda i: i.code)[0]
    kalem_b = sorted(items_b, key=lambda i: i.code)[0]
    sozlesme = await sozlesme_kalemi_fabrikasi(kalem_a, project)
    kalem_b.contract_item_id = sozlesme.id
    await seeded_db.flush()

    tas_sozlesme = await taseron_sozlesmesi_fabrikasi(
        project, site=site_b, kalemler=[("TK-1", sozlesme)], code="TS-B"
    )
    await _gun(
        client,
        admin_headers,
        site_a.id,
        date(2026, 7, 10),
        [{"boq_item_id": str(kalem_a.id), "quantity": "9"}],
    )

    govde = (await _taseron_onerisi(client, admin_headers, tas_sozlesme.id, **DONEM)).json()
    assert govde["lines"] == []
    assert govde["site_id"] == str(site_b.id)
    assert govde["reason"] == guards.SUGGESTION_NO_QUANTITY
    assert govde["skipped_unbridged_count"] == 0


async def test_taseron_sifir_miktarli_kalem_oneriye_GIRMEZ(
    client: AsyncClient,
    admin_headers,
    santiye,
    sozlesme_kalemi_fabrikasi,
    taseron_sozlesmesi_fabrikasi,
) -> None:
    """İşverendeki kuralın taşeron ikizi: günlük iskeleti tüm pozları sıfırla
    açar; sıfır bir öneri satırı DEĞİLDİR (yapıştırılan gövde var olan satırları
    sıfırlayan bir silme emrine dönerdi)."""
    site, project, items = santiye
    kalem_a, kalem_b = sorted(items, key=lambda i: i.code)
    sozlesme_a = await sozlesme_kalemi_fabrikasi(kalem_a, project)
    sozlesme_b = await sozlesme_kalemi_fabrikasi(kalem_b, project)
    tas_sozlesme = await taseron_sozlesmesi_fabrikasi(
        project, site=site, kalemler=[("TK-1", sozlesme_a), ("TK-2", sozlesme_b)]
    )

    await _gun(
        client,
        admin_headers,
        site.id,
        date(2026, 7, 10),
        [
            {"boq_item_id": str(kalem_a.id), "quantity": "10"},
            {"boq_item_id": str(kalem_b.id), "quantity": "0"},
        ],
    )

    govde = (await _taseron_onerisi(client, admin_headers, tas_sozlesme.id, **DONEM)).json()
    assert len(govde["lines"]) == 1
    assert Decimal(govde["lines"][0]["quantity"]) == Decimal("10")


async def test_taseron_AYNI_SANTIYEDEKI_BASKA_sozlesmenin_kalemi_karismaz(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers,
    santiye,
    sozlesme_kalemi_fabrikasi,
    taseron_sozlesmesi_fabrikasi,
) -> None:
    """Bir şantiyede BİRDEN FAZLA taşeron sözleşmesi olabilir ve ikisi AYNI
    işveren kalemine bağlanabilir (iş bölüşülmüştür). Öneri, sorulan sözleşmenin
    kalemlerini VERİR; komşu sözleşmenin kalemi listeye SIZAMAZ — sızsaydı
    kullanıcı A taşeronunun hakedişine B'nin kalemini yazardı."""
    site, project, items = santiye
    kalem = sorted(items, key=lambda i: i.code)[0]
    sozlesme = await sozlesme_kalemi_fabrikasi(kalem, project)
    sozlesme_a = await taseron_sozlesmesi_fabrikasi(
        project, site=site, kalemler=[("TK-A", sozlesme)], code="TS-A"
    )
    sozlesme_b = await taseron_sozlesmesi_fabrikasi(
        project, site=site, kalemler=[("TK-B", sozlesme)], code="TS-B2"
    )
    await _gun(
        client,
        admin_headers,
        site.id,
        date(2026, 7, 10),
        [{"boq_item_id": str(kalem.id), "quantity": "10"}],
    )

    b_kalem_ids = {
        str(satir[0])
        for satir in (
            await seeded_db.execute(
                select(SubcontractorContractItem.id).where(
                    SubcontractorContractItem.contract_id == sozlesme_b.id
                )
            )
        ).all()
    }
    govde = (await _taseron_onerisi(client, admin_headers, sozlesme_a.id, **DONEM)).json()
    assert len(govde["lines"]) == 1
    assert govde["lines"][0]["contract_item_id"] not in b_kalem_ids


async def test_isveren_BASKA_PROJENIN_sozlesme_kalemine_koprulu_poz_karismaz(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers,
    santiye,
    santiye_fabrikasi,
    sozlesme_kalemi_fabrikasi,
) -> None:
    """Veri bozulması korkuluğu: köprü BAŞKA projenin sözleşme kalemini
    gösteriyorsa öneri onu VERMEZ — verseydi `PUT …/lines` zaten reddederdi
    (`ITEM_PROJECT_MISMATCH`) ama kullanıcı komşu projenin kalem kimliğini
    yanıtta GÖRMÜŞ olurdu."""
    site, project, items = santiye
    kalem = sorted(items, key=lambda i: i.code)[0]
    _, yabanci_proje, yabanci_items = await santiye_fabrikasi("SD-YABANCI")
    yabanci_kalem = await sozlesme_kalemi_fabrikasi(yabanci_items[0], yabanci_proje)
    kalem.contract_item_id = yabanci_kalem.id
    await seeded_db.flush()

    await _gun(
        client,
        admin_headers,
        site.id,
        date(2026, 7, 10),
        [{"boq_item_id": str(kalem.id), "quantity": "10"}],
    )

    govde = (await _isveren_onerisi(client, admin_headers, project.id, **DONEM)).json()
    assert govde["lines"] == []


async def test_taseron_sozlesmesinde_karsiligi_OLMAYAN_poz_sayilir(
    client: AsyncClient,
    admin_headers,
    santiye,
    sozlesme_kalemi_fabrikasi,
    taseron_sozlesmesi_fabrikasi,
) -> None:
    """Poz işveren kalemine KÖPRÜLÜ ama taşeron sözleşmesinde karşılığı yok:
    kullanıcı için "köprüsüz poz"la aynı şeydir — öneriye girmez, SAYILIR."""
    site, project, items = santiye
    kalem_a, kalem_b = sorted(items, key=lambda i: i.code)
    sozlesme_a = await sozlesme_kalemi_fabrikasi(kalem_a, project)
    await sozlesme_kalemi_fabrikasi(kalem_b, project)  # köprülü ama taşeronda YOK
    tas_sozlesme = await taseron_sozlesmesi_fabrikasi(
        project, site=site, kalemler=[("TK-1", sozlesme_a)]
    )

    await _gun(
        client,
        admin_headers,
        site.id,
        date(2026, 7, 10),
        [
            {"boq_item_id": str(kalem_a.id), "quantity": "10"},
            {"boq_item_id": str(kalem_b.id), "quantity": "6"},
        ],
    )

    govde = (await _taseron_onerisi(client, admin_headers, tas_sozlesme.id, **DONEM)).json()
    assert len(govde["lines"]) == 1
    assert Decimal(govde["lines"][0]["quantity"]) == Decimal("10")
    assert govde["skipped_unbridged_count"] == 1
    assert govde["reason"] is None


async def test_taseron_hicbiri_eslesmiyorsa_KOPRU_GEREKCESI(
    client: AsyncClient,
    admin_headers,
    santiye,
    sozlesme_kalemi_fabrikasi,
    taseron_sozlesmesi_fabrikasi,
) -> None:
    site, project, items = santiye
    kalem = sorted(items, key=lambda i: i.code)[0]
    await sozlesme_kalemi_fabrikasi(kalem, project)
    tas_sozlesme = await taseron_sozlesmesi_fabrikasi(
        project, site=site, kalemler=[("TK-BAGSIZ", None)], code="TS-BAGSIZ"
    )
    await _gun(
        client,
        admin_headers,
        site.id,
        date(2026, 7, 10),
        [{"boq_item_id": str(kalem.id), "quantity": "10"}],
    )

    govde = (await _taseron_onerisi(client, admin_headers, tas_sozlesme.id, **DONEM)).json()
    assert govde["lines"] == []
    assert govde["skipped_unbridged_count"] == 1
    assert govde["reason"] == guards.SUGGESTION_NO_BRIDGE


# --- Ortak kurallar: taslak, köprüsüzlük, sıfır ---
