"""MU-1 T3a — hesap planı uçlarının login/yetki/veri fixture'ları.

`tests/modules/treasury/conftest.py` deseninin kardeşi: kök `tests/conftest.py`de
hazır başlık fixture'ı YOKTUR, her test paketi kendi `_login`/`_auth` yardımcısını
kurar.

İzin matrisi (`roles/seed_data.py:194`, **`accounting`** — seed'de ZATEN VARDI,
matris DEĞİŞMEDİ):
`"accounting": [_A, _F, _N, _N, _N, _F, _V, _N]` yani
system_admin=**_A** · patron=_F · site_chief=**_N** · field_engineer=_N ·
hr_manager=_N · accounting=**_F** · project_manager=**_V** · procurement=_N.

Seviye sırası `none < view < draft < request < approve < full < admin`
(`app/core/access.py`). T3a'nın üç kapısı buradan çıkar:

* okuma (`view`)   → PM · muhasebe · patron · sysadmin; şef/saha/İK/satınalma 403;
* yazma (`full`)   → muhasebe/patron/sysadmin; **PM yazamaz** (403);
* silme (`admin`)  → YALNIZ sysadmin — `full` silmeyi KAPSAMAZ, muhasebe 403 alır.

🔴 **Kapsam (proje/şantiye) fixture'ı YOKTUR** ve bu bir eksiklik değildir
(spec §3): hesap planı ŞİRKET GENELİ bir katalogtur, üç tabloda da
`project_id`/`site_id` kolonu yoktur. `UserProjectAccess` kurmak, olmayan bir
süzgeci varmış gibi gösteren bir test üretirdi.

Fabrikalar uçtan GEÇMEZ: hesap ve fiş doğrudan ORM ile kurulur. POST ucundan
kurulsalardı liste/detay/bakiye testleri POST'un doğruluğuna bağlanır ve tek bir
kusur bütün dosyayı kırmızıya çevirirdi (`hesap_fabrikasi` dersi, HZ-1).
"""

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounting.models import (
    AccountingPeriod,
    AccountingPeriodStatus,
    ChartAccount,
    ChartAccountType,
    JournalEntry,
    JournalEntryStatus,
    JournalLine,
)
from app.modules.users.models import User


async def _login(client: AsyncClient, user_factory, role_key: str, email: str) -> str:
    await user_factory(email=email, password="parola1234", role_key=role_key)
    resp = await client.post("/auth/login", json={"email": email, "password": "parola1234"})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def admin_headers(
    client: AsyncClient, seeded_db: AsyncSession, user_factory
) -> dict[str, str]:
    """`system_admin` — `accounting=_A`: TEK DELETE geçen rol."""
    return _auth(await _login(client, user_factory, "system_admin", "admin@muhasebe.co"))


@pytest.fixture
async def muhasebe_headers(
    client: AsyncClient, seeded_db: AsyncSession, user_factory
) -> dict[str, str]:
    """`accounting` — `accounting=_F`: yazar ama SİLEMEZ (403)."""
    return _auth(await _login(client, user_factory, "accounting", "muhasebe@muhasebe.co"))


@pytest.fixture
async def pm_headers(client: AsyncClient, seeded_db: AsyncSession, user_factory) -> dict[str, str]:
    """`project_manager` — `accounting=_V`: okur, yazamaz (403)."""
    return _auth(await _login(client, user_factory, "project_manager", "pm@muhasebe.co"))


@pytest.fixture
async def yetkisiz_headers(
    client: AsyncClient, seeded_db: AsyncSession, user_factory
) -> dict[str, str]:
    """`site_chief` — `accounting=_N`: okumada bile 403."""
    return _auth(await _login(client, user_factory, "site_chief", "sef@muhasebe.co"))


@pytest.fixture
def hesap_fabrikasi(seeded_db: AsyncSession):
    """Hesap planı kaydını DOĞRUDAN kurar — uçtan geçilmez."""

    async def _create(
        code: str,
        *,
        name: str | None = None,
        account_type: ChartAccountType = ChartAccountType.asset,
        is_active: bool = True,
    ) -> ChartAccount:
        account = ChartAccount(
            code=code,
            name=name if name is not None else f"Hesap {code}",
            account_type=account_type,
            is_active=is_active,
        )
        seeded_db.add(account)
        await seeded_db.flush()
        return account

    return _create


@pytest.fixture
async def kullanici_id(seeded_db: AsyncSession, user_factory) -> uuid.UUID:
    """Fişin `created_by_id`si — RESTRICT FK olduğu için gerçek bir kullanıcı şart."""
    mevcut = (
        await seeded_db.execute(select(User).where(User.email == "fis@muhasebe.co"))
    ).scalar_one_or_none()
    if mevcut is not None:
        return mevcut.id
    user = await user_factory(
        email="fis@muhasebe.co", password="parola1234", role_key="system_admin"
    )
    return user.id


@pytest.fixture
def donem_fabrikasi(seeded_db: AsyncSession, kullanici_id: uuid.UUID):
    """MU-2 — `accounting_periods` satırını DOĞRUDAN kurar (uçtan geçilmez).

    🔴 Damga BÜTÜNDÜR (`ck_accounting_periods_closed_stamp`): `closed` ise
    `closed_at` + `closed_by_id` birlikte yazılır, `open` ise ikisi de NULL
    kalır. Fabrika bunu kendisi uygular; testler damgayı elle kurmaya
    çalışsaydı biri unutulur ve kırmızı, kuralı değil kurulumu gösterirdi.
    """

    async def _create(
        year: int,
        month: int,
        *,
        status: AccountingPeriodStatus = AccountingPeriodStatus.closed,
    ) -> AccountingPeriod:
        kapali = status is AccountingPeriodStatus.closed
        period = AccountingPeriod(
            year=year,
            month=month,
            status=status,
            closed_at=datetime(2026, 8, 1, tzinfo=UTC) if kapali else None,
            closed_by_id=kullanici_id if kapali else None,
        )
        seeded_db.add(period)
        await seeded_db.flush()
        return period

    return _create


@pytest.fixture
def fis_fabrikasi(seeded_db: AsyncSession, kullanici_id: uuid.UUID):
    """Yevmiye fişi + satırlarını DOĞRUDAN kurar (T3b'nin uçları HENÜZ YOK).

    🔴 Fişin DURUMU parametredir çünkü K3'ün en sinsi tuzağı tam olarak budur:
    `draft` bakiyeye GİRMEZ, `posted` ve `reversed` GİRER. Durum sabitlenmiş bir
    fabrika, `POSTING_STATUSES` mutasyonunu göremezdi.

    Satırlar `(account, debit, credit)` üçlüleridir; `ck_journal_lines_single_side`
    gereği her satır TEK TARAFLIDIR.
    """

    async def _create(
        satirlar: list[tuple[ChartAccount, str, str]],
        *,
        status: JournalEntryStatus = JournalEntryStatus.posted,
        entry_date: date = date(2026, 7, 17),
        description: str = "Test fişi",
        reversal_of: JournalEntry | None = None,
    ) -> JournalEntry:
        toplam_borc = sum((Decimal(borc) for _, borc, _ in satirlar), Decimal("0"))
        toplam_alacak = sum((Decimal(alacak) for _, _, alacak in satirlar), Decimal("0"))
        entry = JournalEntry(
            entry_date=entry_date,
            period_year=entry_date.year,
            period_month=entry_date.month,
            description=description,
            status=status,
            total_debit=toplam_borc,
            total_credit=toplam_alacak,
            reversal_of_id=None if reversal_of is None else reversal_of.id,
            created_by_id=kullanici_id,
        )
        seeded_db.add(entry)
        await seeded_db.flush()
        for sira, (account, borc, alacak) in enumerate(satirlar):
            seeded_db.add(
                JournalLine(
                    entry_id=entry.id,
                    sort_order=sira,
                    account_id=account.id,
                    debit=Decimal(borc),
                    credit=Decimal(alacak),
                )
            )
        await seeded_db.flush()
        return entry

    return _create
