"""Task H1 test yardımcıları — `progress_payments` modülüne özgü fixture'lar.

Kök `tests/conftest.py`'deki `db_session`/`seeded_db`/`user_factory`/`project_factory`
üzerine kurulur (`tests/contracts/conftest.py` deseni). Bu task yalnız model/migration
testlerini kapsadığı için burada henüz HTTP login fixture'ları (`admin_headers` vb.)
YOKTUR — onlar H4'te eklenir.
"""

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.projects.models import Project, ProjectContract
from app.modules.sites.models import Site
from app.modules.users.models import User


@pytest.fixture
async def hakedis_sozlesmesi(
    seeded_db: AsyncSession, project_factory
) -> tuple[Project, ProjectContract]:
    """OLU 92 deseni: sözleşmeli proje — `test_employer_items.py::_contract` varsayılanlarıyla."""
    project = await project_factory(code="PP-001", name="Hakedişli Proje")
    contract = ProjectContract(
        project_id=project.id,
        contract_no="SZL-2026-010",
        amount=Decimal("11200000"),
        advance_pct=Decimal("20"),
        retainage_pct=Decimal("5"),
        vat_pct=Decimal("20"),
    )
    seeded_db.add(contract)
    await seeded_db.flush()
    return project, contract


@pytest.fixture
async def hakedis_santiyesi(seeded_db: AsyncSession, hakedis_sozlesmesi) -> Site:
    project, _ = hakedis_sozlesmesi
    site = Site(project_id=project.id, code="SNT-2026-001", name="Test Şantiyesi")
    seeded_db.add(site)
    await seeded_db.flush()
    return site


@pytest.fixture
async def hakedis_olusturan(seeded_db: AsyncSession, user_factory) -> User:
    return await user_factory(
        email="olusturan@progress-payments.co", password="parola1234", role_key="system_admin"
    )
