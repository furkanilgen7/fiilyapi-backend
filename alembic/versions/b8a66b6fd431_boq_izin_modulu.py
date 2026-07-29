"""boq izin modulu

Izin matrisine 17. modulu ekler: boq / "İş Kalemleri" (GENEL grubu).

Spec §4 (2026-07-30) — kullanici karari: "santiye sefi gorsun de saha
muhendisi gormesin". Mevcut matriste `sites` satiri `site_chief` ve
`field_engineer` icin BIREBIR AYNI (_LIM, _LIM) oldugu icin bu iki rolu
ayirmanin tek yolu ayri bir izin modulu acmaktir. `Ayarlar - Izin Matrisi`
mockup'inda bu satir YOK — bilincli sapma, geri alinmaz (spec §4).

`procurement=none` GECICIDIR: kullaniciya soruldu, cevap gelmedi (spec §4
"uygulamadan once kullaniciya teyit edilecek" notu); `accounting`/
`project_manager` seviyeleri `sites`/`projects` satirindan turetildi.

Revision ID: b8a66b6fd431
Revises: 7abe87671979
Create Date: 2026-07-30 00:46:28.917467

"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b8a66b6fd431"
down_revision: str | Sequence[str] | None = "7abe87671979"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Bu migration app.modules.roles.seed_data'yi kasitli olarak import ETMEZ:
# uygulanmis bir migration donmus olmalidir, uygulama kodu zamanla degisir.
# Asagidaki veriler seed_data.py'daki MODULES/MATRIX'ten birebir kopyalanmistir;
# esitligi tests/modules/test_seed_migration_matches_seed_data.py dogrular.

MODULE_KEY = "boq"
MODULE_NAME = "İş Kalemleri"
MODULE_GROUP = "GENEL"
MODULE_SORT_ORDER = 17

# boq son siraya eklendigi icin baska hicbir modul kaymaz.
SORT_ORDER_UPDATES: dict[str, int] = {}

# downgrade()'in geri yazacagi degerler — kaydirma olmadigi icin bos.
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

# Spec §4: system_admin=admin, patron=full, site_chief=view/limited,
# field_engineer=none (kullanici karari: sefi gorsun, saha muhendisi gormesin),
# hr_manager=none, accounting=view/finance, project_manager=full,
# procurement=none (GECICI — teyit bekliyor).
MATRIX: dict[str, list[tuple[str, str]]] = {
    MODULE_KEY: [
        ("admin", "all"),
        ("full", "all"),
        ("view", "limited"),
        ("none", "all"),
        ("none", "all"),
        ("view", "finance"),
        ("full", "all"),
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
