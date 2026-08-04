"""Belge çekirdeği (T1) fixture'ları — bağımsız kurulum.

`tests/site_planning/conftest.py` deseninin kardeşi: kök `tests/conftest.py`in
`db_session`/`seeded_db`/`user_factory`/`project_factory` fixture'ları üzerine
kurulur, kardeş test paketlerinden HİÇBİR ŞEY miras alınmaz (pytest onları
yüklemez) ve `tests/progress_payments/test_concurrency.py`nin bilinen seed
sızıntısı borcuna BULAŞILMAZ.

İzin matrisi (`roles/seed_data.py`, **`documents`** — 20. modül, grup MALI;
belge çekirdeği spec §6 / §7 S2): system_admin=_A · patron=_F · site_chief=_F ·
field_engineer=_F · hr_manager=_V · accounting=_F · project_manager=_V ·
procurement=_V.

Yani: şef ve saha mühendisi belge yükleyebilir (arşivi sahada onlar besler),
muhasebe de tam yetkilidir (fatura/sözleşme eki); İK, proje müdürü ve satınalma
SALT OKUR. Silme yalnız system_admin'dedir (`_A`).

T1 testleri doğrudan DB katmanına bakar; T2 ile birlikte KLASÖR uçlarının HTTP
fixture'ları (kimlik + kapsam) eklendi. Yetki fixture'ları seçilirken üç seviyeyi
de temsil eden roller alındı:

* `admin_headers` — `system_admin` (`_A`): DELETE'i yalnız o geçer, tüm projeleri görür.
* `sef_headers` — `site_chief` (`_F`), kapsamı TEK projeye kısıtlı: yazar, SİLEMEZ.
* `pm_headers` — `project_manager` (`_V`), aynı kapsam: okur, YAZAMAZ.

`documents` satırında hiçbir rol `_N` DEĞİLDİR (spec §6 gerekçesi: arşiv ortak
hafızadır), bu yüzden "okumada 403" senaryosu YOKTUR — izin ayrımı ancak
`full` (POST/PATCH) ve `admin` (DELETE) kapılarında sınanabilir.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.documents.models import Document, DocumentBlob, DocumentFolder
from app.modules.projects.models import Project
from app.modules.sites.models import Site
from app.modules.users.models import User, UserProjectAccess

# Beyaz listeye göre tipik bir künye (spec §4): PDF, 48 MB'ın çok altında.
ORNEK_MIME = "application/pdf"


@pytest.fixture
async def proje(seeded_db: AsyncSession, project_factory) -> Project:
    return await project_factory(code="BC-P01", name="Güneşkent Konut")


@pytest.fixture
async def ikinci_proje(seeded_db: AsyncSession, project_factory) -> Project:
    return await project_factory(code="BC-P02", name="Marina Ofis")


@pytest.fixture
async def santiye(seeded_db: AsyncSession, proje: Project) -> Site:
    site = Site(project_id=proje.id, code="BC-A", name="A-Blok Şantiyesi")
    seeded_db.add(site)
    await seeded_db.flush()
    return site


@pytest.fixture
def klasor_fabrikasi(seeded_db: AsyncSession):
    """`site` verilmezse PROJE DÜZEYİ klasör açılır (`site_id IS NULL`, spec §2)."""

    async def _create(
        project: Project,
        name: str,
        *,
        site: Site | None = None,
        parent: DocumentFolder | None = None,
    ) -> DocumentFolder:
        folder = DocumentFolder(
            project_id=project.id,
            site_id=site.id if site is not None else None,
            parent_id=parent.id if parent is not None else None,
            name=name,
        )
        seeded_db.add(folder)
        await seeded_db.flush()
        return folder

    return _create


@pytest.fixture
def belge_fabrikasi(seeded_db: AsyncSession):
    """Künye + (istenirse) ikili içerik. Blob AYRI tabloya yazılır (spec §2)."""

    async def _create(
        project: Project,
        filename: str,
        *,
        site: Site | None = None,
        folder: DocumentFolder | None = None,
        description: str | None = None,
        uploaded_by_name: str | None = None,
        size_bytes: int = 1024,
        mime_type: str = ORNEK_MIME,
        data: bytes | None = None,
    ) -> Document:
        document = Document(
            project_id=project.id,
            site_id=site.id if site is not None else None,
            folder_id=folder.id if folder is not None else None,
            filename=filename,
            mime_type=mime_type,
            size_bytes=size_bytes,
            description=description,
            uploaded_by_name=uploaded_by_name,
        )
        seeded_db.add(document)
        await seeded_db.flush()
        if data is not None:
            seeded_db.add(DocumentBlob(document_id=document.id, data=data))
            await seeded_db.flush()
        return document

    return _create


# --- Kapsam dışı kayıtlar (IDOR yüzeyi) ---


@pytest.fixture
async def gorunmeyen_santiye(seeded_db: AsyncSession, ikinci_proje: Project) -> Site:
    """Kapsamı kısıtlı kullanıcıların ASLA göremediği projenin şantiyesi.

    İki işi birden görür: (a) görünmeyen kapsamda gerçek bir kayıt üretir, (b)
    `site_id` başka projeye aitken 422 dönen kural için hedef sağlar.
    """
    site = Site(project_id=ikinci_proje.id, code="BC-G", name="Görünmeyen Şantiye")
    seeded_db.add(site)
    await seeded_db.flush()
    return site


# --- Kimlik / yetki ---


async def _login(client: AsyncClient, user_factory, role_key: str, email: str) -> dict[str, str]:
    await user_factory(email=email, password="parola1234", role_key=role_key)
    resp = await client.post("/auth/login", json={"email": email, "password": "parola1234"})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _scoped_headers(
    client: AsyncClient,
    seeded_db: AsyncSession,
    user_factory,
    role_key: str,
    email: str,
    project: Project,
) -> dict[str, str]:
    """Rolü verilen ama kapsamı TEK projeye kısıtlanmış kullanıcı (IDOR yüzeyi)."""
    headers = await _login(client, user_factory, role_key, email)
    user = (await seeded_db.execute(select(User).where(User.email == email))).scalar_one()
    seeded_db.add(UserProjectAccess(user_id=user.id, project_id=project.id, all_projects=False))
    await seeded_db.flush()
    return headers


@pytest.fixture
async def admin_headers(
    client: AsyncClient, seeded_db: AsyncSession, user_factory
) -> dict[str, str]:
    """`system_admin` (`documents=_A`) — silme kapısını yalnız bu rol geçer."""
    return await _login(client, user_factory, "system_admin", "admin@bc-t2.co")


@pytest.fixture
async def sef_headers(
    client: AsyncClient, seeded_db: AsyncSession, user_factory, proje: Project
) -> dict[str, str]:
    """`site_chief` (`documents=_F`), kapsamı `proje` ile SINIRLI — yazar, silemez."""
    return await _scoped_headers(
        client, seeded_db, user_factory, "site_chief", "sef@bc-t2.co", proje
    )


@pytest.fixture
async def pm_headers(
    client: AsyncClient, seeded_db: AsyncSession, user_factory, proje: Project
) -> dict[str, str]:
    """`project_manager` (`documents=_V`), aynı kapsam — okur, YAZAMAZ."""
    return await _scoped_headers(
        client, seeded_db, user_factory, "project_manager", "pm@bc-t2.co", proje
    )
