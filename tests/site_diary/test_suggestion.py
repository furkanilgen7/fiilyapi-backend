"""T5 — hakediş "günlükten doldur" ÖNERİSİ (spec §4, §7 S2/S5; plan T5).

İki SALT-OKUNUR uç:

* `GET /projects/{project_id}/progress-payments/diary-suggestion?year&month`
  — BOQ → `boq_items.contract_item_id` köprüsü; satırlar (kalem, şantiye) kırılımlı.
* `GET /subcontractor-contracts/{contract_id}/progress-payments/diary-suggestion?year&month`
  — `subcontractor_contract_items.source_contract_item_id` köprüsü; YALNIZ
  `contract.site_id = günlük.site_id` (spec §7 S5).

## Bu dosyada TESTLE SABİTLENEN dört karar

1. **Uçlar HİÇBİR ŞEY YAZMAZ** (spec §4: otomasyon yok). Öneriyi uygulamak
   kullanıcının AYRI `PUT …/lines` çağrısıdır. `test_*_salt_okunur` ikisi için de
   DB izini (tablo sayımları + günlük durumları/miktarları) çağrı öncesi/sonrası
   karşılaştırır.
2. **Yanıt satırları mevcut `PUT …/lines` gövdesine BİREBİR uyar** — öneri
   gövdesi olduğu gibi `PUT`a gönderilip 200 alır (kopyala-yapıştır sözleşmesi).
3. **Yalnız `submitted` günlükler** sayılır — T4 `summary` ile AYNI süzgeç, ikinci
   bir toplama kuralı YOK. `test_oneri_miktari_summary_ile_AYNI` bunu bağlar.
4. **İki kapı**: `progress_payments.view` VE `site_diary.view`. `accounting`
   (hakediş onaycısı ama `site_diary=_N`) 403 alır — günlük verisi hakediş
   yolundan sızmaz.
"""

import uuid
from datetime import date
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import AccessLevel
from app.modules.audit.models import AuditLog
from app.modules.contracts.models import SubcontractorContractItem
from app.modules.progress_payments.models import ProgressPayment, ProgressPaymentLine
from app.modules.progress_payments.schemas import ProgressPaymentLinesSave
from app.modules.roles.repository import get_permission
from app.modules.site_diary import guards
from app.modules.site_diary.models import SiteDiaryEntry, SiteDiaryLine
from app.modules.subcontractor_progress_payments.models import (
    SubcontractorProgressPayment,
    SubcontractorProgressPaymentLine,
)
from app.modules.subcontractor_progress_payments.schemas import (
    SubcontractorProgressPaymentLinesSave,
)

pytestmark = pytest.mark.asyncio

DONEM = {"year": 2026, "month": 7}


# --- Yardımcılar ---


async def _gun(
    client: AsyncClient,
    headers: dict[str, str],
    site_id,
    tarih: date,
    satirlar: list[dict],
    *,
    gonder: bool = True,
) -> dict:
    """Bir günlük kaydı açar, miktarları yazar ve (istenirse) GÖNDERİR."""
    kayit = await client.post(
        f"/sites/{site_id}/diary", json={"entry_date": tarih.isoformat()}, headers=headers
    )
    assert kayit.status_code == 201, kayit.text
    entry_id = kayit.json()["id"]
    yanit = await client.put(f"/diary/{entry_id}/lines", json={"lines": satirlar}, headers=headers)
    assert yanit.status_code == 200, yanit.text
    if gonder:
        gonderim = await client.post(f"/diary/{entry_id}/submit", headers=headers)
        assert gonderim.status_code == 200, gonderim.text
        return gonderim.json()
    return yanit.json()


async def _isveren_onerisi(client: AsyncClient, headers: dict[str, str], project_id, **params):
    return await client.get(
        f"/projects/{project_id}/progress-payments/diary-suggestion",
        params=params,
        headers=headers,
    )


async def _taseron_onerisi(client: AsyncClient, headers: dict[str, str], contract_id, **params):
    return await client.get(
        f"/subcontractor-contracts/{contract_id}/progress-payments/diary-suggestion",
        params=params,
        headers=headers,
    )


async def _db_izi(session: AsyncSession) -> dict:
    """Salt-okunurluk KANITININ gövdesi: öneri ucunun dokunabileceği HER tablonun
    sayımı + günlüğün durum/miktar imzası. Tek bir `flush` bile bu sözlüğü
    değiştirir."""

    async def _say(model) -> int:
        return int((await session.execute(select(func.count()).select_from(model))).scalar_one())

    durumlar = sorted(
        (str(satir[0]), satir[1].value)
        for satir in (await session.execute(select(SiteDiaryEntry.id, SiteDiaryEntry.status))).all()
    )
    miktarlar = sorted(
        (str(satir[0]), str(satir[1]))
        for satir in (await session.execute(select(SiteDiaryLine.id, SiteDiaryLine.quantity))).all()
    )
    return {
        "gunluk_kayit": await _say(SiteDiaryEntry),
        "gunluk_satir": await _say(SiteDiaryLine),
        "isveren_hakedis": await _say(ProgressPayment),
        "isveren_satir": await _say(ProgressPaymentLine),
        "taseron_hakedis": await _say(SubcontractorProgressPayment),
        "taseron_satir": await _say(SubcontractorProgressPaymentLine),
        "durumlar": durumlar,
        "miktarlar": miktarlar,
    }


def _satir(govde: dict, contract_item_id, site_id=None) -> dict | None:
    return next(
        (
            s
            for s in govde["lines"]
            if s["contract_item_id"] == str(contract_item_id)
            and (site_id is None or s["site_id"] == str(site_id))
        ),
        None,
    )


# --- İşveren: mutlu yol ---


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


async def test_taseron_sitesiz_sozlesme_BOS_ve_ACIK_GEREKCE(
    client: AsyncClient,
    admin_headers,
    santiye,
    sozlesme_kalemi_fabrikasi,
    taseron_sozlesmesi_fabrikasi,
) -> None:
    """Spec §7 S5: proje-geneli (site'sız) sözleşme kapsam DIŞI. Sessiz boş liste
    DEĞİL — kullanıcı NEDEN boş olduğunu görmelidir."""
    site, project, items = santiye
    kalem = sorted(items, key=lambda i: i.code)[0]
    sozlesme = await sozlesme_kalemi_fabrikasi(kalem, project)
    tas_sozlesme = await taseron_sozlesmesi_fabrikasi(
        project, site=None, kalemler=[("TK-1", sozlesme)], code="TS-GENEL"
    )
    await _gun(
        client,
        admin_headers,
        site.id,
        date(2026, 7, 10),
        [{"boq_item_id": str(kalem.id), "quantity": "9"}],
    )

    govde = (await _taseron_onerisi(client, admin_headers, tas_sozlesme.id, **DONEM)).json()
    assert govde["lines"] == []
    assert govde["site_id"] is None
    assert govde["reason"] == guards.SUGGESTION_CONTRACT_WITHOUT_SITE


async def test_taseron_baska_santiyenin_gunlugu_KARISMAZ(
    client: AsyncClient,
    admin_headers,
    santiye,
    santiye_fabrikasi,
    sozlesme_kalemi_fabrikasi,
    taseron_sozlesmesi_fabrikasi,
    proje,
) -> None:
    """Sözleşme B şantiyesine bağlıysa A şantiyesinin günlüğü öneriye GİREMEZ."""
    site_a, project, items_a = santiye
    site_b, _, _ = await santiye_fabrikasi("SD-B", project=proje)
    kalem_a = sorted(items_a, key=lambda i: i.code)[0]
    sozlesme = await sozlesme_kalemi_fabrikasi(kalem_a, project)
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


async def test_taslak_gunluk_ONERIYE_GIRMEZ(
    client: AsyncClient,
    admin_headers,
    santiye,
    sozlesme_kalemi_fabrikasi,
    taseron_sozlesmesi_fabrikasi,
) -> None:
    """T4 `summary` ile AYNI süzgeç (spec §3/§4): ikinci bir toplama kuralı YOK."""
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
        [{"boq_item_id": str(kalem.id), "quantity": "10"}],
    )
    await _gun(
        client,
        admin_headers,
        site.id,
        date(2026, 7, 12),
        [{"boq_item_id": str(kalem.id), "quantity": "5"}],
        gonder=False,
    )

    isveren = (await _isveren_onerisi(client, admin_headers, project.id, **DONEM)).json()
    assert Decimal(_satir(isveren, sozlesme.id, site.id)["quantity"]) == Decimal("10")

    taseron = (await _taseron_onerisi(client, admin_headers, tas_sozlesme.id, **DONEM)).json()
    assert Decimal(taseron["lines"][0]["quantity"]) == Decimal("10")


async def test_koprusuz_poz_ONERI_URETMEZ_ama_sessizce_atlanmaz(
    client: AsyncClient, admin_headers, santiye, sozlesme_kalemi_fabrikasi
) -> None:
    """`contract_item_id` NULL olan poz hangi sözleşme kalemine yazılacağını
    BİLMEZ; öneri üretilmez ama sayısı BİLDİRİLİR (sessiz atlama yok)."""
    site, project, items = santiye
    kalem_a, kalem_b = sorted(items, key=lambda i: i.code)
    sozlesme_a = await sozlesme_kalemi_fabrikasi(kalem_a, project)  # yalnız A köprülü

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

    govde = (await _isveren_onerisi(client, admin_headers, project.id, **DONEM)).json()
    assert len(govde["lines"]) == 1
    assert _satir(govde, sozlesme_a.id, site.id) is not None
    assert govde["skipped_unbridged_count"] == 1


async def test_hicbiri_koprulu_degilse_bos_liste_ve_KOPRU_GEREKCESI(
    client: AsyncClient, admin_headers, santiye
) -> None:
    site, project, items = santiye
    kalem = sorted(items, key=lambda i: i.code)[0]
    await _gun(
        client,
        admin_headers,
        site.id,
        date(2026, 7, 10),
        [{"boq_item_id": str(kalem.id), "quantity": "10"}],
    )

    govde = (await _isveren_onerisi(client, admin_headers, project.id, **DONEM)).json()
    assert govde["lines"] == []
    assert govde["skipped_unbridged_count"] == 1
    assert govde["reason"] == guards.SUGGESTION_NO_BRIDGE


async def test_sifir_miktarli_poz_oneriye_GIRMEZ(
    client: AsyncClient, admin_headers, santiye, sozlesme_kalemi_fabrikasi
) -> None:
    """Günlük iskeleti TÜM BOQ pozlarını sıfırla açar; sıfır "bu dönem miktar
    gelmedi" demektir, öneri satırı olmamalıdır (aksi hâlde ekran her ay tüm
    pozları sıfırla önerirdi)."""
    site, project, items = santiye
    kalem_a, kalem_b = sorted(items, key=lambda i: i.code)
    sozlesme_a = await sozlesme_kalemi_fabrikasi(kalem_a, project)
    await sozlesme_kalemi_fabrikasi(kalem_b, project)

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

    govde = (await _isveren_onerisi(client, admin_headers, project.id, **DONEM)).json()
    assert len(govde["lines"]) == 1
    assert _satir(govde, sozlesme_a.id, site.id) is not None


async def test_baska_ayin_gunlugu_doneme_GIRMEZ(
    client: AsyncClient, admin_headers, santiye, sozlesme_kalemi_fabrikasi
) -> None:
    site, project, items = santiye
    kalem = sorted(items, key=lambda i: i.code)[0]
    sozlesme = await sozlesme_kalemi_fabrikasi(kalem, project)
    await _gun(
        client,
        admin_headers,
        site.id,
        date(2026, 7, 10),
        [{"boq_item_id": str(kalem.id), "quantity": "10"}],
    )
    await _gun(
        client,
        admin_headers,
        site.id,
        date(2026, 8, 3),
        [{"boq_item_id": str(kalem.id), "quantity": "40"}],
    )

    temmuz = (await _isveren_onerisi(client, admin_headers, project.id, **DONEM)).json()
    assert Decimal(_satir(temmuz, sozlesme.id, site.id)["quantity"]) == Decimal("10")

    tum_yil = (await _isveren_onerisi(client, admin_headers, project.id, year=2026)).json()
    assert Decimal(_satir(tum_yil, sozlesme.id, site.id)["quantity"]) == Decimal("50")


async def test_oneri_miktari_summary_ile_AYNI_sayi(
    client: AsyncClient, admin_headers, santiye, sozlesme_kalemi_fabrikasi
) -> None:
    """İki ekran aynı sayıyı söylemek ZORUNDA: `summary` poz miktarı ile önerinin
    miktarı aynı dönemde BİREBİR eşittir."""
    site, project, items = santiye
    kalem = sorted(items, key=lambda i: i.code)[0]
    sozlesme = await sozlesme_kalemi_fabrikasi(kalem, project)
    await _gun(
        client,
        admin_headers,
        site.id,
        date(2026, 7, 10),
        [{"boq_item_id": str(kalem.id), "quantity": "10.25"}],
    )
    await _gun(
        client,
        admin_headers,
        site.id,
        date(2026, 7, 14),
        [{"boq_item_id": str(kalem.id), "quantity": "1.75"}],
    )

    ozet = (
        await client.get(f"/sites/{site.id}/diary/summary", params=DONEM, headers=admin_headers)
    ).json()
    ozet_miktar = next(
        Decimal(i["quantity"]) for i in ozet["items"] if i["boq_item_id"] == str(kalem.id)
    )
    oneri = (await _isveren_onerisi(client, admin_headers, project.id, **DONEM)).json()
    assert Decimal(_satir(oneri, sozlesme.id, site.id)["quantity"]) == ozet_miktar


# --- SALT OKUNURLUK (en kritik kural) ---


async def test_isveren_onerisi_DB_YE_HICBIR_SEY_YAZMAZ(
    client: AsyncClient, seeded_db: AsyncSession, admin_headers, santiye, sozlesme_kalemi_fabrikasi
) -> None:
    site, project, items = santiye
    kalem = sorted(items, key=lambda i: i.code)[0]
    sozlesme = await sozlesme_kalemi_fabrikasi(kalem, project)
    await _gun(
        client,
        admin_headers,
        site.id,
        date(2026, 7, 10),
        [{"boq_item_id": str(kalem.id), "quantity": "10"}],
    )

    onceki = await _db_izi(seeded_db)
    yanit = await _isveren_onerisi(client, admin_headers, project.id, **DONEM)
    assert yanit.status_code == 200, yanit.text
    assert len(yanit.json()["lines"]) == 1
    sonraki = await _db_izi(seeded_db)

    assert sonraki == onceki, "öneri ucu SALT OKUNURDUR — DB'de tek satır bile değişemez"
    # Uygulamak KULLANICININ ayrı çağrısıdır: uç, hakediş satırı ÜRETMEZ.
    assert sonraki["isveren_satir"] == 0
    assert str(sozlesme.id)  # köprü kurulu ama yine de yazma yok


async def test_taseron_onerisi_DB_YE_HICBIR_SEY_YAZMAZ(
    client: AsyncClient,
    seeded_db: AsyncSession,
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
        [{"boq_item_id": str(kalem.id), "quantity": "10"}],
    )

    onceki = await _db_izi(seeded_db)
    yanit = await _taseron_onerisi(client, admin_headers, tas_sozlesme.id, **DONEM)
    assert yanit.status_code == 200, yanit.text
    assert len(yanit.json()["lines"]) == 1
    sonraki = await _db_izi(seeded_db)

    assert sonraki == onceki, "öneri ucu SALT OKUNURDUR — DB'de tek satır bile değişemez"
    assert sonraki["taseron_hakedis"] == 0 and sonraki["taseron_satir"] == 0


async def test_oneri_ucu_denetim_kaydi_ACMAZ(
    client: AsyncClient, seeded_db: AsyncSession, admin_headers, santiye, sozlesme_kalemi_fabrikasi
) -> None:
    """Okuma uçları denetlenmez (repo deseni): aksi hâlde uç bir YAZMA yolu olurdu."""
    site, project, items = santiye
    kalem = sorted(items, key=lambda i: i.code)[0]
    await sozlesme_kalemi_fabrikasi(kalem, project)
    await _gun(
        client,
        admin_headers,
        site.id,
        date(2026, 7, 10),
        [{"boq_item_id": str(kalem.id), "quantity": "10"}],
    )

    async def _denetim_sayisi() -> int:
        return int(
            (await seeded_db.execute(select(func.count()).select_from(AuditLog))).scalar_one()
        )

    onceki = await _denetim_sayisi()
    await _isveren_onerisi(client, admin_headers, project.id, **DONEM)
    assert await _denetim_sayisi() == onceki


# --- IDOR + izin + doğrulama ---


async def test_isveren_gorunmeyen_proje_404(
    client: AsyncClient, sef_headers, santiye_fabrikasi
) -> None:
    _, gizli_proje, _ = await santiye_fabrikasi("SD-GIZLI")
    yanit = await _isveren_onerisi(client, sef_headers, gizli_proje.id, **DONEM)
    assert yanit.status_code == 404, yanit.text


async def test_taseron_gorunmeyen_proje_404(
    client: AsyncClient, sef_headers, santiye_fabrikasi, taseron_sozlesmesi_fabrikasi
) -> None:
    gizli_site, gizli_proje, _ = await santiye_fabrikasi("SD-GIZLI2")
    tas_sozlesme = await taseron_sozlesmesi_fabrikasi(gizli_proje, site=gizli_site, code="TS-GIZLI")
    yanit = await _taseron_onerisi(client, sef_headers, tas_sozlesme.id, **DONEM)
    assert yanit.status_code == 404, yanit.text


async def test_var_olmayan_kimlikler_404(client: AsyncClient, admin_headers) -> None:
    """Var olmayan ile görünmeyen AYIRT EDİLEMEZ (repo IDOR kuralı)."""
    assert (await _isveren_onerisi(client, admin_headers, uuid.uuid4(), **DONEM)).status_code == 404
    assert (await _taseron_onerisi(client, admin_headers, uuid.uuid4(), **DONEM)).status_code == 404


async def test_gunluk_izni_OLMAYAN_hakedis_onaycisi_403(
    client: AsyncClient, muhasebe_headers, santiye, taseron_sozlesmesi_fabrikasi
) -> None:
    """`accounting`: `progress_payments=_APR` ama `site_diary=_N`. Uç yalnız
    hakediş izniyle korunsaydı günlük verisi bu role SIZARDI."""
    site, project, _ = santiye
    tas_sozlesme = await taseron_sozlesmesi_fabrikasi(project, site=site, code="TS-MUH")
    assert (
        await _isveren_onerisi(client, muhasebe_headers, project.id, **DONEM)
    ).status_code == 403
    assert (
        await _taseron_onerisi(client, muhasebe_headers, tas_sozlesme.id, **DONEM)
    ).status_code == 403


async def test_hakedis_izni_OLMAYAN_gunluk_rolu_403(
    client: AsyncClient, sef_headers, pm_headers, santiye, taseron_sozlesmesi_fabrikasi
) -> None:
    """Karşı yön: `site_chief` (`progress_payments=_DRF`, `site_diary=_F`) ve
    `project_manager` (`_APR`/`_V`) İKİ kapıdan da geçer — çift kapı meşru
    kullanıcıyı KİLİTLEMEZ."""
    site, project, _ = santiye
    tas_sozlesme = await taseron_sozlesmesi_fabrikasi(project, site=site, code="TS-SEF")
    assert (await _isveren_onerisi(client, sef_headers, project.id, **DONEM)).status_code == 200
    assert (await _taseron_onerisi(client, pm_headers, tas_sozlesme.id, **DONEM)).status_code == 200


async def test_hakedis_izni_KALDIRILMIS_gunluk_rolu_403(
    client: AsyncClient,
    seeded_db: AsyncSession,
    sef_headers,
    sef_kullanicisi,
    santiye,
    taseron_sozlesmesi_fabrikasi,
) -> None:
    """Hakediş kapısının ÖLÜ KURAL olmadığının kanıtı.

    Öntanımlı matriste `site_diary`yi gören her rol hakedişi de görür, bu yüzden
    kapı ancak izin satırı DEĞİŞTİRİLEREK sınanabilir — izinler veridir, yönetici
    onları ekrandan kısabilir. `site_chief`in hakediş izni kapatıldığında öneri
    ucu 403 döner: hakediş kalem kimlikleri hakedişi görmeyen role sızmaz.
    """
    site, project, _ = santiye
    tas_sozlesme = await taseron_sozlesmesi_fabrikasi(project, site=site, code="TS-KAPALI")
    izin = await get_permission(seeded_db, sef_kullanicisi.role_id, "progress_payments")
    assert izin is not None
    izin.access_level = AccessLevel.none
    await seeded_db.flush()

    assert (await _isveren_onerisi(client, sef_headers, project.id, **DONEM)).status_code == 403
    assert (
        await _taseron_onerisi(client, sef_headers, tas_sozlesme.id, **DONEM)
    ).status_code == 403
    # Günlüğün KENDİ ucu etkilenmez — kapı yalnız öneri ucundadır.
    assert (
        await client.get(f"/sites/{site.id}/diary/summary", params=DONEM, headers=sef_headers)
    ).status_code == 200


async def test_gunluk_izni_hic_olmayan_rol_403(client: AsyncClient, hr_headers, santiye) -> None:
    _, project, _ = santiye
    assert (await _isveren_onerisi(client, hr_headers, project.id, **DONEM)).status_code == 403


async def test_ay_tek_basina_422(
    client: AsyncClient, admin_headers, santiye, taseron_sozlesmesi_fabrikasi
) -> None:
    """T2/T4 ile TUTARLI: `month` yalnız `year` ile anlamlıdır."""
    site, project, _ = santiye
    tas_sozlesme = await taseron_sozlesmesi_fabrikasi(project, site=site, code="TS-422")
    isveren = await _isveren_onerisi(client, admin_headers, project.id, month=7)
    assert isveren.status_code == 422, isveren.text
    assert guards.YEAR_REQUIRED_FOR_MONTH in isveren.text
    taseron = await _taseron_onerisi(client, admin_headers, tas_sozlesme.id, month=7)
    assert taseron.status_code == 422, taseron.text


async def test_gecersiz_ay_422(client: AsyncClient, admin_headers, santiye) -> None:
    _, project, _ = santiye
    assert (
        await _isveren_onerisi(client, admin_headers, project.id, year=2026, month=13)
    ).status_code == 422


async def test_donemsiz_cagri_tum_gunlugu_kapsar(
    client: AsyncClient, admin_headers, santiye, sozlesme_kalemi_fabrikasi
) -> None:
    site, project, items = santiye
    kalem = sorted(items, key=lambda i: i.code)[0]
    sozlesme = await sozlesme_kalemi_fabrikasi(kalem, project)
    await _gun(
        client,
        admin_headers,
        site.id,
        date(2025, 12, 20),
        [{"boq_item_id": str(kalem.id), "quantity": "3"}],
    )
    await _gun(
        client,
        admin_headers,
        site.id,
        date(2026, 7, 10),
        [{"boq_item_id": str(kalem.id), "quantity": "7"}],
    )

    govde = (await _isveren_onerisi(client, admin_headers, project.id)).json()
    assert Decimal(_satir(govde, sozlesme.id, site.id)["quantity"]) == Decimal("10")
    assert govde["year"] is None and govde["month"] is None
