"""boq procurement izin duzeltmesi

Veri duzeltme migration'i: kullanici karari (2026-07-30) satinalma rolunun
`boq` ("İş Kalemleri") modulundeki erisimini none -> view/limited yukseltir.
Gerekce: satinalma malzemeyi poz uzerinden aliyor, teklif/siparis akisi poz
listesine bakmayi gerektiriyor. Bu artik "sites" satiriyla birebir ayni
(spec §4 kullanici karari, bkz. app/modules/roles/seed_data.py).

Bu migration app.modules.roles.seed_data'yi kasitli olarak import ETMEZ
(bkz. b8a66b6fd431'deki ayni gerekce). Asagidaki MATRIX, seed_data.py'daki
guncel "boq" satirindan birebir kopyalanmistir; esitligi
tests/modules/test_seed_migration_matches_seed_data.py dogrular.

Idempotent: role_permissions.uq_role_module uzerinde UPSERT kullanilir —
satir zaten (none, all) ise (none) -> (view, limited) UPDATE edilir; satir
hic yoksa (elle mudahale/yarim kalmis kosu ihtimaline karsi) once eklenir.

Revision ID: e3a8b4a5b93b
Revises: b8a66b6fd431
Create Date: 2026-07-30 10:36:30.795650

"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e3a8b4a5b93b"
down_revision: str | Sequence[str] | None = "b8a66b6fd431"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# boq modulunde herhangi bir alan (isim/grup/sira) degismiyor — yalniz bir
# izin hucresi duzeltiliyor. Modul zaten var oldugu icin bu alanlar yalniz
# test_seed_migration_matches_seed_data.py'nin uzanti-migration seklini
# (MODULE_KEY/MODULE_NAME/...) izlemek icin tutuluyor; upgrade() modulu
# yeniden EKLEMEZ.
MODULE_KEY = "boq"
MODULE_NAME = "İş Kalemleri"
MODULE_GROUP = "GENEL"
MODULE_SORT_ORDER = 17

# Bu migration hicbir modulu kaydirmiyor/eklemiyor.
SORT_ORDER_UPDATES: dict[str, int] = {}
PREVIOUS_SORT_ORDERS: dict[str, int] = {}

# Sutun sirasi — asagidaki MATRIX satiri bu sirayla okunur (seed_data.ROLE_ORDER).
ROLE_ORDER = [
    "system_admin",
    "patron",
    "site_chief",
    "field_engineer",
    "hr_manager",
    "accounting",
    "project_manager",
    "procurement",
]

# seed_data.py MATRIX["boq"] ile birebir ayni (procurement artik view/limited).
MATRIX: dict[str, list[tuple[str, str]]] = {
    MODULE_KEY: [
        ("admin", "all"),
        ("full", "all"),
        ("view", "limited"),
        ("none", "all"),
        ("none", "all"),
        ("view", "finance"),
        ("full", "all"),
        ("view", "limited"),
    ],
}

_PROCUREMENT_ROLE_KEY = "procurement"

# Yalniz duzeltilen hucre: satinalma x boq. Satir zaten varsa DO UPDATE ile
# dogru degere cekilir; hic yoksa once INSERT edilir.
_UPSERT_PROCUREMENT_BOQ = sa.text(
    "INSERT INTO role_permissions (id, role_id, module_id, access_level, scope) "
    "SELECT CAST(:id AS uuid), r.id, m.id, "
    "CAST(:access_level AS access_level), CAST(:scope AS scope) "
    "FROM roles r, modules m "
    "WHERE r.key = :role_key AND m.key = :module_key "
    "ON CONFLICT ON CONSTRAINT uq_role_module DO UPDATE "
    "SET access_level = EXCLUDED.access_level, scope = EXCLUDED.scope"
)


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        _UPSERT_PROCUREMENT_BOQ.bindparams(
            id=str(uuid.uuid4()),
            role_key=_PROCUREMENT_ROLE_KEY,
            module_key=MODULE_KEY,
            access_level="view",
            scope="limited",
        )
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(
        _UPSERT_PROCUREMENT_BOQ.bindparams(
            id=str(uuid.uuid4()),
            role_key=_PROCUREMENT_ROLE_KEY,
            module_key=MODULE_KEY,
            access_level="none",
            scope="all",
        )
    )
