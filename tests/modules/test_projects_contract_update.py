"""KUSUR 298: işveren sözleşmesi kurulduktan sonra HİÇBİR uçtan düzenlenemiyor.

`_apply_contract` yalnız `create_project`te çağrılır (service.py:568) ve
`ProjectUpdate` sözleşme nesnesini taşımaz; `/projects/{id}/contract` yalnız
GET'tir, `DELETE /projects/{id}` ucu YOKTUR. Yanlış girilen bir `advance_pct`
o projedeki HER hakedişte kalıcı yanlış avans mahsubu üretir
(progress_payments/calculations.py:100).
"""

from decimal import Decimal

from sqlalchemy import func, select

from app.modules.contracts.models import (
    ContractStatus,
    EmployerContractGroup,
    EmployerContractItem,
)
from app.modules.projects.models import ProjectContract


async def _login(client, user_factory, role_key: str) -> str:
    await user_factory(email=f"{role_key}@t.co", password="parola1234", role_key=role_key)
    resp = await client.post(
        "/auth/login", json={"email": f"{role_key}@t.co", "password": "parola1234"}
    )
    return resp.json()["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _contract_body(**overrides) -> dict:
    body = {
        "contract_no": "SZL-2026-001",
        "signature_date": "2026-01-15",
        "amount": "11200000.00",
        "advance_pct": "20",
        "retainage_pct": "5",
        "vat_pct": "20",
        "late_penalty_daily": "1500.00",
        "has_price_escalation": True,
        "index_type": "ufe",
        "base_index_value": "100.00",
    }
    body.update(overrides)
    return body


async def _project_with_contract(db_session, project_factory, code: str):
    project = await project_factory(
        code,
        name="Sözleşmeli Proje",
        contract_no="SZL-2026-001",
        contract_amount="11200000.00",
    )
    db_session.add(
        ProjectContract(
            project_id=project.id,
            contract_no="SZL-2026-001",
            amount=Decimal("11200000.00"),
            advance_pct=Decimal("30"),
            retainage_pct=Decimal("5"),
            vat_pct=Decimal("20"),
            has_price_escalation=True,
            index_type="ufe",
            base_index_value=Decimal("100.00"),
        )
    )
    await db_session.flush()
    return project


async def test_patch_ile_sozlesme_orani_duzeltilebilir(
    client, db_session, user_factory, project_factory
):
    """Avans yüzdesi 30 yerine 20 girilmişse PATCH ile düzeltilebilmeli.

    Bugün kırmızı: `ProjectUpdate`te `contract` alanı olmadığı için gövdedeki
    sözleşme nesnesi SESSİZCE yok sayılır, uç 200 döner ve oran 30'da kalır.
    """
    project = await _project_with_contract(db_session, project_factory, "SZL-DZL")
    token = await _login(client, user_factory, "system_admin")

    resp = await client.patch(
        f"/projects/{project.id}",
        json={"contract": _contract_body(advance_pct="20", late_penalty_daily="2000.00")},
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.text

    detay = await client.get(f"/projects/{project.id}", headers=_auth(token))
    assert detay.status_code == 200, detay.text
    sozlesme = detay.json()["contract"]
    assert Decimal(sozlesme["advance_pct"]) == Decimal("20")
    assert Decimal(sozlesme["late_penalty_daily"]) == Decimal("2000.00")


async def test_patch_sozlesme_bedeli_hem_otoriteyi_hem_anlik_goruntuyu_yazar(
    client, db_session, user_factory, project_factory
):
    """Sözleşme nesnesiyle gelen bedel `projects.contract_amount` kopyasına da işlemeli.

    Otorite `project_contracts.amount`tır (models.py:199-200); kopya ayrışırsa
    maliyet/kâr projeksiyonu (costs.py:324) ve Gantt (timeline.py:89) yanlış
    rakam basar.
    """
    project = await _project_with_contract(db_session, project_factory, "SZL-BDL")
    token = await _login(client, user_factory, "system_admin")

    resp = await client.patch(
        f"/projects/{project.id}",
        json={"contract": _contract_body(contract_no="SZL-2026-009", amount="12000000.00")},
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.text

    govde = (await client.get(f"/projects/{project.id}", headers=_auth(token))).json()
    assert Decimal(govde["contract"]["amount"]) == Decimal("12000000.00")
    assert Decimal(govde["contract_amount"]) == Decimal("12000000.00")
    assert govde["contract"]["contract_no"] == "SZL-2026-009"
    assert govde["contract_no"] == "SZL-2026-009"


async def test_sozlesme_duzeltmesi_poz_kalemlerini_SILMEZ(
    client, db_session, user_factory, project_factory
):
    """🔴 Sözleşme düzeltmesi POZ kalemlerini ve hakedişleri GÖTÜRMEMELİ.

    `employer_contract_groups.project_id`, `employer_contract_items.project_id` ve
    `progress_payments.project_id` `project_contracts` satırına `ondelete="CASCADE"`
    ile bağlıdır (contracts/models.py:55,93 · progress_payments/models.py:83).
    ÖLÇÜLDÜ: `_apply_contract`in yeniden ataması bugün gerçek bir DELETE üretmiyor —
    SQLAlchemy aynı kimlikli DELETE+INSERT'i tek UPDATE'e indirgiyor ("row switch",
    `before_cursor_execute` dinleyicisiyle doğrulandı). Bu test o indirgemenin
    BOZULMADIĞINI bekçiler: araya bir `flush` giren gelecekteki bir düzenleme
    silmeyi tek başına gönderir ve bu sayaç 0'a düşer.
    """
    project = await _project_with_contract(db_session, project_factory, "SZL-POZ")
    grup = EmployerContractGroup(project_id=project.id, name="A — Kaba İnşaat", sort_order=0)
    db_session.add(grup)
    await db_session.flush()
    db_session.add(
        EmployerContractItem(
            project_id=project.id,
            group_id=grup.id,
            code="POZ-90",
            description="Beton",
            unit="m3",
            quantity=Decimal("100.000"),
            unit_price=Decimal("1500.00"),
        )
    )
    await db_session.flush()
    token = await _login(client, user_factory, "system_admin")

    resp = await client.patch(
        f"/projects/{project.id}",
        json={"contract": _contract_body(advance_pct="20")},
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.text

    gruplar = await db_session.scalar(
        select(func.count())
        .select_from(EmployerContractGroup)
        .where(EmployerContractGroup.project_id == project.id)
    )
    kalemler = await db_session.scalar(
        select(func.count())
        .select_from(EmployerContractItem)
        .where(EmployerContractItem.project_id == project.id)
    )
    assert (gruplar, kalemler) == (1, 1)


async def test_taahhut_disi_projeye_patch_ile_sozlesme_yazilamaz(
    client, user_factory, project_factory
):
    """Kural 7 create'te uygulanır (service.py:441-443); PATCH yolu da aynı kapıdır."""
    project = await project_factory("SZL-YAT", name="Yatırım", project_type="kendi_yatirim")
    token = await _login(client, user_factory, "system_admin")

    resp = await client.patch(
        f"/projects/{project.id}",
        json={"contract": _contract_body()},
        headers=_auth(token),
    )
    assert resp.status_code == 422, resp.text


async def test_fiyat_farki_acikken_endekssiz_sozlesme_patchi_reddedilir(
    client, db_session, user_factory, project_factory
):
    """Kural 5 create'te uygulanır (service.py:458-460); PATCH yolu da aynı kapıdır."""
    project = await _project_with_contract(db_session, project_factory, "SZL-END")
    token = await _login(client, user_factory, "system_admin")

    resp = await client.patch(
        f"/projects/{project.id}",
        json={
            "contract": _contract_body(
                has_price_escalation=True, index_type=None, base_index_value=None
            )
        },
        headers=_auth(token),
    )
    assert resp.status_code == 422, resp.text


async def test_sozlesme_duzeltmesi_DURUMU_sifirlamaz(
    client, db_session, user_factory, project_factory
):
    """🔴 `project_contracts.status` (models.py:248) `ProjectContractInput`te YOKTUR.

    Gönderilmeyen alan DEĞİŞMEZ. Satır gerçekten silinip yeniden yazılsaydı
    sunucu varsayılanına (`active`) dönerdi: tamamlanmış/askıdaki bir işveren
    sözleşmesi tek bir oran düzeltmesiyle yeniden "Aktif" olur ve `/contracts`
    sayacına geri girerdi (contracts/service.py:204).
    """
    project = await _project_with_contract(db_session, project_factory, "SZL-DRM")
    sozlesme = await db_session.get(ProjectContract, project.id)
    sozlesme.status = ContractStatus.completed
    await db_session.flush()
    token = await _login(client, user_factory, "system_admin")

    resp = await client.patch(
        f"/projects/{project.id}",
        json={"contract": _contract_body(advance_pct="20")},
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.text

    durum = await db_session.scalar(
        select(ProjectContract.status).where(ProjectContract.project_id == project.id)
    )
    assert durum is ContractStatus.completed
    # Kimlik haritası da tutarlı kalmalı: aynı oturumda okunan NESNE de aynı durumu
    # taşımalı (satırı silip yeniden yazan uygulama burada `None` bırakır).
    nesne = await db_session.get(ProjectContract, project.id)
    assert nesne.status is ContractStatus.completed
