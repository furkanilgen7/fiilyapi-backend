"""belge cekirdegi

Uc yeni tablo (`document_folders` / `documents` / `document_blobs`) ve 20. izin
modulu ("documents" satiri + 8 role_permissions) — belge cekirdegi spec §2/§6,
Task T1. YENI ENUM YOKTUR.

Baytlar KUNYEDEN AYRI tabloda tutulur (spec §7 S1): liste/arama sorgulari
`documents`a dokunur, 48 MB'lik sutun onlara hic girmez ve TOAST sismesi izole
kalir. Object storage'a gecis KUNYE SEMASINI DEGISTIRMEZ (T2 `StorageBackend`).

Kapsam disi (spec §1/§5, kasitli): versiyon tablosu YOK · onay akisi YOK ·
etiket YOK · thumbnail/onizleme YOK · form belge-slot tablosu YOK · otomatik
klasor/kategori seed'i YOK (§7 S3 — klasorler serbest).

Elle yazilmistir (autogenerate DEGIL) — repo deseni.

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-08-03

"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b8c9d0e1f2a3"
down_revision: str | Sequence[str] | None = "a7b8c9d0e1f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Bu migration app.modules.roles.seed_data'yi kasitli olarak import ETMEZ:
# uygulanmis bir migration donmus olmalidir, uygulama kodu zamanla degisir.
# Asagidaki veriler seed_data.py'daki MODULES/MATRIX'ten birebir kopyalanmistir;
# esitligi tests/modules/test_seed_migration_matches_seed_data.py dogrular.

MODULE_KEY = "documents"
MODULE_NAME = "Belgeler"
MODULE_GROUP = "MALI"
MODULE_SORT_ORDER = 20

# documents son siraya eklendigi icin baska hicbir modul kaymaz
# (boq 17 / contracts 18 / sales 19 deseni).
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

# spec §6: system_admin=admin, patron=full, site_chief/field_engineer=full
# (sahanin belgesini onlar uretir), hr_manager=view, accounting=full
# (fatura/sozlesme ekini muhasebe yukler), project_manager=view, procurement=view.
# `contracts`/`sales`ten BILINCLI ayrim: arsiv gizli veri degil ortak hafizadir,
# hicbir rol `none` degildir.
MATRIX: dict[str, list[tuple[str, str]]] = {
    MODULE_KEY: [
        ("admin", "all"),
        ("full", "all"),
        ("full", "all"),
        ("full", "all"),
        ("view", "all"),
        ("full", "all"),
        ("view", "all"),
        ("view", "all"),
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
    # 1. document_folders — serbest klasor agaci.
    op.create_table(
        "document_folders",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        # NULL = proje duzeyi klasor (spec §2).
        sa.Column("site_id", sa.UUID(), nullable=True),
        sa.Column("parent_id", sa.UUID(), nullable=True),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="CASCADE"),
        # SET NULL: ust klasor silinince alt klasor koke duser, veri kaybolmaz.
        sa.ForeignKeyConstraint(["parent_id"], ["document_folders.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        # DIKKAT: Postgres'in varsayilan NULLS DISTINCT semantigi yuzunden
        # site_id/parent_id NULL olan dalda bu kisit fiilen ISLEMEZ; tekillik
        # orada yazma ucunun sorumlulugundadir (SitePlanRow.section_id deseni).
        sa.UniqueConstraint(
            "project_id",
            "site_id",
            "parent_id",
            "name",
            name="uq_document_folder_scope_name",
        ),
    )
    op.create_index("ix_document_folders_parent_id", "document_folders", ["parent_id"])
    op.create_index(
        "ix_document_folders_project_site", "document_folders", ["project_id", "site_id"]
    )

    # 2. documents — KUNYE (blob YOK).
    op.create_table(
        "documents",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("folder_id", sa.UUID(), nullable=True),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("site_id", sa.UUID(), nullable=True),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("mime_type", sa.String(length=100), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("uploaded_by_user_id", sa.UUID(), nullable=True),
        sa.Column("uploaded_by_name", sa.String(length=200), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        # SET NULL: klasor silinince belge kaybolmaz, kapsamin kokune duser.
        sa.ForeignKeyConstraint(["folder_id"], ["document_folders.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["uploaded_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_documents_project_site", "documents", ["project_id", "site_id"])
    op.create_index("ix_documents_folder_id", "documents", ["folder_id"])
    # "Son Eklenenler" siralamasi (spec §3).
    op.create_index("ix_documents_created_at", "documents", ["created_at"])

    # 3. document_blobs — baytlar; document_id hem PK hem FK (belge basina tek icerik).
    op.create_table(
        "document_blobs",
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("document_id"),
    )

    # 4. Izin modulu: documents satiri (20.) + 8 role_permissions (spec §6 / §7 S2)
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

    op.drop_table("document_blobs")

    op.drop_index("ix_documents_created_at", table_name="documents")
    op.drop_index("ix_documents_folder_id", table_name="documents")
    op.drop_index("ix_documents_project_site", table_name="documents")
    op.drop_table("documents")

    op.drop_index("ix_document_folders_project_site", table_name="document_folders")
    op.drop_index("ix_document_folders_parent_id", table_name="document_folders")
    op.drop_table("document_folders")
