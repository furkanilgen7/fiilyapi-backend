from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.models import AuditAction, AuditLog
from app.modules.audit.service import record_audit


async def test_record_audit_satiri_ayni_session_a_eklenir(
    seeded_db: AsyncSession, user_factory
) -> None:
    user = await user_factory("audit-actor@test.com", "Parola123!", "system_admin")

    await record_audit(
        seeded_db,
        action=AuditAction.login,
        detail="Sisteme giriş yapıldı",
        actor_user_id=user.id,
        ip_address="203.0.113.7",
    )

    rows = (await seeded_db.execute(select(AuditLog))).scalars().all()

    assert len(rows) == 1
    assert rows[0].action is AuditAction.login
    assert rows[0].detail == "Sisteme giriş yapıldı"
    assert rows[0].actor_user_id == user.id
    # INET sutunu okurken ipaddress nesnesi doner; degerin kendisi korunur.
    assert str(rows[0].ip_address) == "203.0.113.7"
    assert rows[0].occurred_at is not None


async def test_record_audit_commit_etmez(db_session: AsyncSession) -> None:
    """Atomiklik güvencesi: kayıt kendi commit'ini yapmaz, işlem geri alınırsa kaybolur."""
    await record_audit(db_session, action=AuditAction.create, detail="Geri alınacak işlem")

    assert db_session.in_transaction()
    assert len((await db_session.execute(select(AuditLog))).scalars().all()) == 1

    await db_session.rollback()

    assert (await db_session.execute(select(AuditLog))).scalars().all() == []


async def test_record_audit_actor_ve_ip_null_olabilir(db_session: AsyncSession) -> None:
    await record_audit(db_session, action=AuditAction.backup, detail="Sistem yedeklemesi alındı")

    row = (await db_session.execute(select(AuditLog))).scalar_one()

    assert row.actor_user_id is None
    assert row.ip_address is None


async def test_record_audit_gecersiz_ip_null_yazilir(db_session: AsyncSession) -> None:
    """Geçersiz IP metni satırı (ve dolayısıyla asıl işlemi) düşürmemeli.

    `ip_address` kolonu INET'tir; sürücüye geçersiz bir metin verilirse insert
    `DataError` fırlatır ve audit satırı asıl işlemle AYNI transaction'da olduğu
    için işlemin kendisi de geri alınır. İstemci `X-Forwarded-For` başlığını
    serbestçe belirlediğinden bu, dışarıdan tetiklenebilir bir kırılmadır:
    denetim alanı sessizce boş bırakılır, işlem korunur.
    """
    await record_audit(
        db_session, action=AuditAction.login, detail="Sisteme giriş yapıldı", ip_address="anonymous"
    )

    assert (await db_session.execute(select(AuditLog))).scalar_one().ip_address is None


async def test_record_audit_ipv6_ve_bosluklu_ip_kabul_edilir(db_session: AsyncSession) -> None:
    await record_audit(
        db_session, action=AuditAction.login, detail="Sisteme giriş yapıldı", ip_address=" ::1 "
    )

    assert str((await db_session.execute(select(AuditLog))).scalar_one().ip_address) == "::1"
