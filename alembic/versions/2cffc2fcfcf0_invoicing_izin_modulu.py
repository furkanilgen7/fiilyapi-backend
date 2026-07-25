"""invoicing izin modulu

Izin matrisine 14. modulu ekler: invoicing / "Fatura Yonetimi" (Mali grubu).
Fatura Yonetimi mockup'ta Muhasebe'den ayri bir ana menu maddesidir, bu yuzden
accounting altina gizlenmez; kendi modul satirini alir.

Revision ID: 2cffc2fcfcf0
Revises: 6c98d5b8b142
Create Date: 2026-07-25 17:40:02.177454

"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "2cffc2fcfcf0"
down_revision: str | Sequence[str] | None = "6c98d5b8b142"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Bu migration app.modules.roles.seed_data'yi kasitli olarak import ETMEZ:
# uygulanmis bir migration donmus olmalidir, uygulama kodu zamanla degisir.
# Asagidaki veriler seed_data.py'daki MODULES/MATRIX'ten birebir kopyalanmistir;
# esitligi tests/modules/test_seed_migration_matches_seed_data.py dogrular.

MODULE_KEY = "invoicing"
MODULE_NAME = "Fatura Yönetimi"
MODULE_GROUP = "MALI"
MODULE_SORT_ORDER = 11

# invoicing 11'e girdigi icin sonrasindaki moduller birer kayar.
SORT_ORDER_UPDATES: dict[str, int] = {
    "treasury": 12,
    "settings": 13,
    "user_management": 14,
}

# downgrade()'in geri yazacagi degerler (a477fdf00fdf'teki orijinal sira).
PREVIOUS_SORT_ORDERS: dict[str, int] = {
    "treasury": 11,
    "settings": 12,
    "user_management": 13,
}

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

# accounting/treasury satirlariyla birebir ayni: en az ayricalik ilkesi.
MATRIX: dict[str, list[tuple[str, str]]] = {
    MODULE_KEY: [
        ("admin", "all"),
        ("full", "all"),
        ("none", "all"),
        ("none", "all"),
        ("none", "all"),
        ("full", "all"),
        ("view", "all"),
        ("none", "all"),
    ],
}

# Canli DB'de satirlar kismen mevcut olabilir (elle mudahale, yarim kalmis kosu):
# her yazma idempotent, boylece yeniden calistirma UNIQUE kisitini ihlal etmez.
_INSERT_MODULE = sa.text(
    'INSERT INTO modules (id, key, name, "group", sort_order) '
    "VALUES (CAST(:id AS uuid), :key, :name, CAST(:group AS module_group), :sort_order) "
    "ON CONFLICT (key) DO NOTHING"
)

# role_id/module_id canli ortamda calisma aninda okunur: ilk seed migration'i
# UUID'leri uuid4() ile uretti, dolayisiyla sabit kodlanamazlar.
_INSERT_PERMISSION = sa.text(
    "INSERT INTO role_permissions (id, role_id, module_id, access_level, scope) "
    "SELECT CAST(:id AS uuid), r.id, m.id, "
    "CAST(:access_level AS access_level), CAST(:scope AS scope) "
    "FROM roles r, modules m "
    "WHERE r.key = :role_key AND m.key = :module_key "
    "ON CONFLICT ON CONSTRAINT uq_role_module DO NOTHING"
)

_UPDATE_SORT_ORDER = sa.text("UPDATE modules SET sort_order = :sort_order WHERE key = :key")

_DELETE_PERMISSIONS = sa.text(
    "DELETE FROM role_permissions WHERE module_id IN (SELECT id FROM modules WHERE key = :key)"
)

_DELETE_MODULE = sa.text("DELETE FROM modules WHERE key = :key")


def _apply_sort_orders(orders: dict[str, int]) -> None:
    for key, sort_order in orders.items():
        op.execute(_UPDATE_SORT_ORDER.bindparams(key=key, sort_order=sort_order))


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        _INSERT_MODULE.bindparams(
            id=str(uuid.uuid4()),
            key=MODULE_KEY,
            name=MODULE_NAME,
            group=MODULE_GROUP,
            sort_order=MODULE_SORT_ORDER,
        )
    )
    _apply_sort_orders(SORT_ORDER_UPDATES)

    for role_key, (access_level, scope) in zip(ROLE_ORDER, MATRIX[MODULE_KEY], strict=True):
        op.execute(
            _INSERT_PERMISSION.bindparams(
                id=str(uuid.uuid4()),
                role_key=role_key,
                module_key=MODULE_KEY,
                access_level=access_level,
                scope=scope,
            )
        )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(_DELETE_PERMISSIONS.bindparams(key=MODULE_KEY))
    op.execute(_DELETE_MODULE.bindparams(key=MODULE_KEY))
    _apply_sort_orders(PREVIOUS_SORT_ORDERS)
