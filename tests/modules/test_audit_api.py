"""Denetim gunlugu okuma ucu: GET /audit-log (plan Task 4).

Sozlesme frontend F5 ile paylasilir: filtreler AND'lenir, siralama occurred_at DESC,
`total` filtreden etkilenir, `limit`/`offset` yanitta yankilanir.
"""

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import delete, event, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.models import AuditAction, AuditLog
from app.modules.roles.models import Role
from app.modules.users.models import User
from tests.conftest import test_engine

_IP = "203.0.113.42"
_HEADERS = {"x-forwarded-for": _IP}


async def _auth(client, user_factory, session: AsyncSession, role_key: str) -> dict[str, str]:
    """Verilen rolle giris yapar ve login'in urettigi denetim satirini temizler."""
    await user_factory(email=f"{role_key}@t.co", password="parola1234", role_key=role_key)
    resp = await client.post(
        "/auth/login",
        json={"email": f"{role_key}@t.co", "password": "parola1234"},
        headers=_HEADERS,
    )
    assert resp.status_code == 200
    # Login denetim satiri testin sayimlarini kirletmesin.
    await session.execute(delete(AuditLog))
    return {"Authorization": f"Bearer {resp.json()['access_token']}", **_HEADERS}


async def _make_user(session: AsyncSession, full_name: str, role_key: str) -> User:
    role = (await session.execute(select(Role).where(Role.key == role_key))).scalar_one()
    user = User(
        email=f"{uuid.uuid4().hex[:8]}@t.co",
        password_hash="x",
        full_name=full_name,
        role_id=role.id,
    )
    session.add(user)
    await session.flush()
    return user


async def _add_row(
    session: AsyncSession,
    *,
    action: AuditAction = AuditAction.login,
    detail: str = "Sisteme giriş yapıldı",
    actor: User | None = None,
    ip: str | None = _IP,
    occurred_at: datetime | None = None,
) -> AuditLog:
    row = AuditLog(
        action=action,
        detail=detail,
        actor_user_id=actor.id if actor is not None else None,
        ip_address=ip,
        occurred_at=occurred_at or datetime.now(UTC),
    )
    session.add(row)
    await session.flush()
    return row


async def test_temel_liste_aktor_rol_adiyla_doner(client, user_factory, seeded_db):
    headers = await _auth(client, user_factory, seeded_db, "system_admin")
    actor = await _make_user(seeded_db, "Ahmet Yılmaz", "patron")
    await _add_row(seeded_db, actor=actor)

    resp = await client.get("/audit-log", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["limit"] == 50
    assert body["offset"] == 0
    item = body["items"][0]
    assert item["action"] == "login"
    assert item["detail"] == "Sisteme giriş yapıldı"
    assert item["ip_address"] == _IP
    assert item["actor"]["full_name"] == "Ahmet Yılmaz"
    assert item["actor"]["role_name"] == "Patron"
    assert item["actor"]["id"] == str(actor.id)
    assert uuid.UUID(item["id"])
    assert item["occurred_at"]


async def test_aktorsuz_satirda_actor_ve_ip_null_doner(client, user_factory, seeded_db):
    headers = await _auth(client, user_factory, seeded_db, "system_admin")
    await _add_row(seeded_db, action=AuditAction.backup, detail="Yedekleme", actor=None, ip=None)

    body = (await client.get("/audit-log", headers=headers)).json()
    assert body["items"][0]["actor"] is None
    assert body["items"][0]["ip_address"] is None


async def test_silinen_kullanicinin_satiri_kalir_aktor_null_olur(client, user_factory, seeded_db):
    headers = await _auth(client, user_factory, seeded_db, "system_admin")
    actor = await _make_user(seeded_db, "Silinecek Kişi", "accounting")
    await _add_row(seeded_db, actor=actor)

    # ON DELETE SET NULL: denetim izi silinmez, aktor "Sistem"e duser.
    await seeded_db.execute(delete(User).where(User.id == actor.id))
    await seeded_db.flush()

    body = (await client.get("/audit-log", headers=headers)).json()
    assert body["total"] == 1
    assert body["items"][0]["actor"] is None


async def test_siralama_occurred_at_desc(client, user_factory, seeded_db):
    headers = await _auth(client, user_factory, seeded_db, "system_admin")
    now = datetime.now(UTC)
    for i, detail in enumerate(["eski", "orta", "yeni"]):
        await _add_row(seeded_db, detail=detail, occurred_at=now - timedelta(hours=3 - i))

    items = (await client.get("/audit-log", headers=headers)).json()["items"]
    assert [i["detail"] for i in items] == ["yeni", "orta", "eski"]


async def test_actor_user_id_filtresi(client, user_factory, seeded_db):
    headers = await _auth(client, user_factory, seeded_db, "system_admin")
    a = await _make_user(seeded_db, "Ahmet Yılmaz", "patron")
    b = await _make_user(seeded_db, "Sercan Öztürk", "site_chief")
    await _add_row(seeded_db, actor=a, detail="a1")
    await _add_row(seeded_db, actor=a, detail="a2")
    await _add_row(seeded_db, actor=b, detail="b1")

    body = (await client.get(f"/audit-log?actor_user_id={a.id}", headers=headers)).json()
    assert body["total"] == 2
    assert {i["detail"] for i in body["items"]} == {"a1", "a2"}


async def test_action_filtresi(client, user_factory, seeded_db):
    headers = await _auth(client, user_factory, seeded_db, "system_admin")
    await _add_row(seeded_db, action=AuditAction.create, detail="c1")
    await _add_row(seeded_db, action=AuditAction.delete, detail="d1")

    body = (await client.get("/audit-log?action=create", headers=headers)).json()
    assert body["total"] == 1
    assert body["items"][0]["detail"] == "c1"


async def test_gecersiz_action_422(client, user_factory, seeded_db):
    headers = await _auth(client, user_factory, seeded_db, "system_admin")
    resp = await client.get("/audit-log?action=hacimsiz", headers=headers)
    assert resp.status_code == 422


async def test_tarih_araligi_dahil(client, user_factory, seeded_db):
    headers = await _auth(client, user_factory, seeded_db, "system_admin")
    today = datetime.now(UTC)
    await _add_row(seeded_db, detail="bugun", occurred_at=today)
    await _add_row(seeded_db, detail="dun", occurred_at=today - timedelta(days=1))
    await _add_row(seeded_db, detail="onbes", occurred_at=today - timedelta(days=15))

    d_today = date.today().isoformat()
    d_yesterday = (date.today() - timedelta(days=1)).isoformat()

    # date_to = bugun → bugunun kayitlari DAHIL (gun sonuna kadar).
    body = (await client.get(f"/audit-log?date_to={d_today}", headers=headers)).json()
    assert body["total"] == 3

    # date_from = bugun → bugunun ilk kaydi dahil, gecmis haric.
    body = (await client.get(f"/audit-log?date_from={d_today}", headers=headers)).json()
    assert [i["detail"] for i in body["items"]] == ["bugun"]

    body = (
        await client.get(f"/audit-log?date_from={d_yesterday}&date_to={d_today}", headers=headers)
    ).json()
    assert {i["detail"] for i in body["items"]} == {"bugun", "dun"}


async def test_date_to_bugunun_gec_saatli_kaydini_kirpmaz(client, user_factory, seeded_db):
    """`date_to` dahil-gun: 23:59:59.999999'a kadar (UTC)."""
    headers = await _auth(client, user_factory, seeded_db, "system_admin")
    today = date.today()
    late = datetime(today.year, today.month, today.day, 23, 59, 30, tzinfo=UTC)
    await _add_row(seeded_db, detail="gece", occurred_at=late)

    body = (await client.get(f"/audit-log?date_to={today.isoformat()}", headers=headers)).json()
    assert body["total"] == 1


async def test_filtre_kombinasyonu_and_lenir(client, user_factory, seeded_db):
    headers = await _auth(client, user_factory, seeded_db, "system_admin")
    a = await _make_user(seeded_db, "Ahmet Yılmaz", "patron")
    b = await _make_user(seeded_db, "Sercan Öztürk", "site_chief")
    now = datetime.now(UTC)
    await _add_row(seeded_db, actor=a, action=AuditAction.create, detail="hedef", occurred_at=now)
    await _add_row(seeded_db, actor=a, action=AuditAction.delete, detail="yanlis-action")
    await _add_row(seeded_db, actor=b, action=AuditAction.create, detail="yanlis-aktor")
    await _add_row(
        seeded_db,
        actor=a,
        action=AuditAction.create,
        detail="eski",
        occurred_at=now - timedelta(days=10),
    )

    d_today = date.today().isoformat()
    body = (
        await client.get(
            f"/audit-log?actor_user_id={a.id}&action=create&date_from={d_today}", headers=headers
        )
    ).json()
    assert body["total"] == 1
    assert body["items"][0]["detail"] == "hedef"


async def test_sayfalama_limit_offset_ve_total(client, user_factory, seeded_db):
    headers = await _auth(client, user_factory, seeded_db, "system_admin")
    now = datetime.now(UTC)
    for i in range(5):
        await _add_row(seeded_db, detail=f"r{i}", occurred_at=now - timedelta(minutes=i))

    body = (await client.get("/audit-log?limit=2&offset=1", headers=headers)).json()
    assert body["total"] == 5  # toplam filtreden etkilenir, sayfadan degil
    assert body["limit"] == 2
    assert body["offset"] == 1
    assert [i["detail"] for i in body["items"]] == ["r1", "r2"]


async def test_total_filtreden_etkilenir(client, user_factory, seeded_db):
    headers = await _auth(client, user_factory, seeded_db, "system_admin")
    for i in range(3):
        await _add_row(seeded_db, action=AuditAction.create, detail=f"c{i}")
    await _add_row(seeded_db, action=AuditAction.delete, detail="d")

    body = (await client.get("/audit-log?action=create&limit=1", headers=headers)).json()
    assert body["total"] == 3
    assert len(body["items"]) == 1


@pytest.mark.parametrize("limit,offset", [(0, 0), (201, 0), (50, -1)])
async def test_gecersiz_sayfalama_422(client, user_factory, seeded_db, limit, offset):
    headers = await _auth(client, user_factory, seeded_db, "system_admin")
    resp = await client.get(f"/audit-log?limit={limit}&offset={offset}", headers=headers)
    assert resp.status_code == 422


# --- serbest metin arama (q) -------------------------------------------------


async def test_q_detay_metniyle_eslesir(client, user_factory, seeded_db):
    headers = await _auth(client, user_factory, seeded_db, "system_admin")
    await _add_row(seeded_db, detail="Kullanıcı oluşturuldu: Ayşe Demir")
    await _add_row(seeded_db, detail="Şirket bilgileri güncellendi")

    body = (await client.get("/audit-log?q=oluşturuldu", headers=headers)).json()
    assert body["total"] == 1
    assert body["items"][0]["detail"].startswith("Kullanıcı oluşturuldu")


async def test_q_aktor_adiyla_eslesir(client, user_factory, seeded_db):
    headers = await _auth(client, user_factory, seeded_db, "system_admin")
    a = await _make_user(seeded_db, "Ahmet Yılmaz", "patron")
    b = await _make_user(seeded_db, "Sercan Öztürk", "site_chief")
    await _add_row(seeded_db, actor=a, detail="x")
    await _add_row(seeded_db, actor=b, detail="y")

    body = (await client.get("/audit-log?q=Yılmaz", headers=headers)).json()
    assert body["total"] == 1
    assert body["items"][0]["actor"]["full_name"] == "Ahmet Yılmaz"


async def test_q_buyuk_kucuk_harf_duyarsiz(client, user_factory, seeded_db):
    headers = await _auth(client, user_factory, seeded_db, "system_admin")
    await _add_row(seeded_db, detail="Yedekleme tamamlandı")

    assert (await client.get("/audit-log?q=YEDEKLEME", headers=headers)).json()["total"] == 1
    assert (await client.get("/audit-log?q=yedekleme", headers=headers)).json()["total"] == 1


async def test_q_turkce_karakterli_terim(client, user_factory, seeded_db):
    """`ı ğ ü ş ç ö` iceren terimler oldugu gibi eslesir (ILIKE, dokunulmamis girdi)."""
    headers = await _auth(client, user_factory, seeded_db, "system_admin")
    await _add_row(seeded_db, detail="Yedekleme tamamlandı")
    await _add_row(seeded_db, detail="Baska kayit")

    body = (await client.get("/audit-log?q=tamamlandı", headers=headers)).json()
    assert body["total"] == 1


async def test_q_eslesme_yok_bos_liste(client, user_factory, seeded_db):
    headers = await _auth(client, user_factory, seeded_db, "system_admin")
    await _add_row(seeded_db, detail="Sisteme giriş yapıldı")

    body = (await client.get("/audit-log?q=zzzyok", headers=headers)).json()
    assert body["total"] == 0
    assert body["items"] == []


async def test_q_bos_veya_bosluk_filtre_uygulamaz(client, user_factory, seeded_db):
    headers = await _auth(client, user_factory, seeded_db, "system_admin")
    await _add_row(seeded_db, detail="Sisteme giriş yapıldı")

    assert (await client.get("/audit-log?q=", headers=headers)).json()["total"] == 1
    assert (await client.get("/audit-log?q=%20%20", headers=headers)).json()["total"] == 1


async def test_q_joker_karakterleri_escape_edilir(client, user_factory, seeded_db):
    """Kullanici girdisindeki `%` ve `_` joker degil, duz karakter olarak aranir."""
    headers = await _auth(client, user_factory, seeded_db, "system_admin")
    await _add_row(seeded_db, detail="Ilerleme %75 kaydedildi")
    await _add_row(seeded_db, detail="Baska bir kayit")

    body = (await client.get("/audit-log?q=%25%25", headers=headers)).json()  # q="%%"
    assert body["total"] == 0

    body = (await client.get("/audit-log?q=%2575", headers=headers)).json()  # q="%75"
    assert body["total"] == 1


async def test_q_ve_action_and_lenir(client, user_factory, seeded_db):
    headers = await _auth(client, user_factory, seeded_db, "system_admin")
    await _add_row(seeded_db, action=AuditAction.create, detail="Rol oluşturuldu: Kalite")
    await _add_row(seeded_db, action=AuditAction.delete, detail="Rol silindi: Kalite")

    body = (await client.get("/audit-log?q=Kalite&action=create", headers=headers)).json()
    assert body["total"] == 1
    assert body["items"][0]["action"] == "create"


# --- yetki -------------------------------------------------------------------


async def test_yetkisiz_rol_403(client, user_factory, seeded_db):
    """`settings < view` olan HER rol reddedilir — patron dahil."""
    headers = await _auth(client, user_factory, seeded_db, "patron")
    resp = await client.get("/audit-log", headers=headers)
    assert resp.status_code == 403


@pytest.mark.parametrize("role_key", ["site_chief", "accounting", "hr_manager", "procurement"])
async def test_diger_roller_de_403(client, user_factory, seeded_db, role_key):
    headers = await _auth(client, user_factory, seeded_db, role_key)
    assert (await client.get("/audit-log", headers=headers)).status_code == 403


async def test_kimliksiz_istek_401(client, seeded_db):
    assert (await client.get("/audit-log")).status_code == 401


# --- N+1 -----------------------------------------------------------------


async def test_aktor_join_ile_yuklenir_n_plus_1_yok(client, user_factory, seeded_db):
    """Satir sayisi artsa da `audit_log` sorgusu sabit kalir (liste + sayim = 2)."""
    headers = await _auth(client, user_factory, seeded_db, "system_admin")
    statements: list[str] = []

    def _before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(test_engine.sync_engine, "before_cursor_execute", _before_cursor_execute)
    try:
        await _add_row(seeded_db, actor=await _make_user(seeded_db, "Tek Kişi", "patron"))
        statements.clear()
        assert (await client.get("/audit-log", headers=headers)).status_code == 200
        tek_satir = [s for s in statements if "audit_log" in s]
        tek_toplam = len(statements)

        for i in range(5):
            await _add_row(seeded_db, actor=await _make_user(seeded_db, f"Kişi {i}", "site_chief"))
        statements.clear()
        body = (await client.get("/audit-log", headers=headers)).json()
    finally:
        event.remove(test_engine.sync_engine, "before_cursor_execute", _before_cursor_execute)

    assert body["total"] == 6
    cok_satir = [s for s in statements if "audit_log" in s]
    assert len(tek_satir) == 2  # liste + sayim
    assert len(cok_satir) == 2
    # Satir basina ek sorgu cikmadiginin kaniti: toplam sorgu sayisi satir sayisindan bagimsiz.
    assert len(statements) == tek_toplam
