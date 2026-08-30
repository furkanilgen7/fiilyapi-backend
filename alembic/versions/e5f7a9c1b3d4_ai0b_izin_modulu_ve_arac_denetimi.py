"""ai0b izin modulu ve arac denetimi

AI-0b T4 — **TEK migration**, uc is:

  1. 22. izin modulu `ai` (SISTEM, sort_order 22) + izin satirlari.
  2. `ai_tool_calls` tablosu + uc yeni enum
     (`ai_tool_decision` / `ai_tool_call_phase` / `ai_tool_call_origin`).
  3. `audit_action` enum'una `ai_turn` uyesi — **TIP TAKASI** ile.

Izin modulu MIGRATION ISTER (`documents`/`equipment` emsali): `seed_data.py`yi
degistirmek canlidaki MEVCUT kayitlara satir eklemez, yalnizca bos bir DB'nin
ilk kurulumunu etkiler. Ustelik `seed_reference_data`nin uygulama kodunda
CAGIRANI YOKTUR (olculdu) — modul YALNIZ bu migration ile iner.

---

## 🔴 SAPMA 1 — izin satirlari `FROM roles r` ile TUM roller icin yazilir

Dokuz emsal migration `FROM roles r, modules m` kullanir ama **`WHERE
r.key = :role_key`** ile suzer ve cagiran dongu sabit `ROLE_ORDER` uzerinde
doner. Bu migration o desenden **BILEREK SAPAR** ve `role_key` suzgecini
kaldirir; `ROLE_ORDER`daki sekiz rol icin MATRIX satirindaki hucre, kalan HER
rol icin `varsayilan hucre` yazilir.

Gerekce ÖLÇÜLDÜ ve iki katmanlidir:

* `roles.service.update_role_permission` izin satiri yoksa `NotFoundError`
  (404) atar (`app/modules/roles/service.py`). Yani migration'dan ONCE acilmis
  bir ozel rol icin Ayarlar - Izin Matrisi ekrani `ai` hucresini
  **OLUSTURAMAZ** — kalici ve sessiz.
* Asil belirti Ayarlar ekrani DEGILDIR: `auth/router.py::me`
  `permissions={module.key: perm.access_level ...}` haritasini
  `roles.repository.get_role_matrix` besler ve o **INNER JOIN**'dir. Izin
  satiri olmayan modulun anahtari `/auth/me` yanitinda **HIC BULUNMAZ**.

Ozel rollere yazilan varsayilan hucre `('view','all')`dir — `_V`, yani
kullanici karari "AI'i herkes kendi kapsaminda kullanabilsin"in ta kendisi.
`('none','all')` yazmak fail-closed gorunurdu ama gercek etkisi FARKLIDIR:
`ai` modulunde yazma yetkisi zaten seviyede degil ROL ANAHTARINDADIR
(`SYSTEM_ADMIN_KEY`), yani `view` hicbir yazma yuzeyi acmaz; `none` yazmak
yalnizca "ozel rolun AI'i hic kullanamamasi"na yol acardi ve bu kullanici
kararina aykiridir. Kilit nokta: **satirin VAR OLMASI**.

## 🔴 SAPMA 2 — `audit_action` TIP TAKASI, `ALTER TYPE ... ADD VALUE` DEGIL

Secim kriteri depoda YAZILIDIR (`f1b2c3d4e5a6` ve `c5d6e7f8a9b0` docstring'leri):
`ADD VALUE` (a) eklenen degeri AYNI islemde kullandirmaz, (b) **GERI ALINAMAZ**.

Burada (b) baglayicidir: CI kapisi `alembic upgrade head -> downgrade -1 ->
upgrade head`tir (`.github/workflows/ci.yml`), yani **TEK ADIM asagi** — ve bu
TEK migration oldugu icin o tek adim TAM OLARAK bu revizyondur. `ADD VALUE` ile
downgrade `ai_turn`i tipte birakirdi: asimetrik, ve bir sonraki `upgrade`
`checkfirst` hilesine muhtac olurdu. Takas simetriktir.

Enum takasini AYRI/izole bir revizyona koymak da denenebilirdi (`f1b2c3d4e5a6`
dersi "enum takasi izole edilir") ama o zaman CI'in `downgrade -1`i **yalnizca
tablo revizyonunu** olcerdi ve enum takasinin downgrade'i hicbir kapida
kosmazdi. Emir "TEK migration" der; bu ikisi ayni yone bakiyor ve **daha genis
olcen** secenek TEK migration'dir. Bilerek secildi.

⚠️ `audit_log.action` sunucu varsayilani TASIMAZ (`578d2211a14f` olculdu), bu
yuzden `DROP DEFAULT` / `SET DEFAULT` dansi GEREKMEZ. Tipi kullanan sutunlar
SABIT LISTEDEN DEGIL katalogdan (`pg_attribute`) okunur — `c5d6e7f8a9b0`
dersi: elle yazilmis bir liste, yeni bir sutun eklendiginde takasi SESSIZCE
eksik birakirdi.

**DOWNGRADE FAIL-LOUD:** downgrade, `ai_turn` degerini kullanan `audit_log`
satiri varsa `RuntimeError` ile DURUR (sessizce `update`e cevirmez). `ai_turn`
bir AI turudur; onu "guncelleme" diye yeniden etiketlemek denetim gunlugunu
yalanci yapardi (`c5d6e7f8a9b0`nin fail-loud karari).

Elle yazilmistir (autogenerate DEGIL) — repo deseni.

Revision ID: e5f7a9c1b3d4
Revises: d2e4f6a8b0c1
Create Date: 2026-08-30

"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e5f7a9c1b3d4"
down_revision: str | Sequence[str] | None = "d2e4f6a8b0c1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# --------------------------------------------------------------------------- #
# 1. Izin modulu (spec §8 T4)
# --------------------------------------------------------------------------- #
# Bu migration app.modules.roles.seed_data'yi kasitli olarak import ETMEZ:
# uygulanmis bir migration donmus olmalidir, uygulama kodu zamanla degisir.
# Asagidaki veriler seed_data.py'daki MODULES/MATRIX'ten birebir kopyalanmistir;
# esitligi tests/modules/test_seed_migration_matches_seed_data.py dogrular.

MODULE_KEY = "ai"
MODULE_NAME = "FİİL AI"
MODULE_GROUP = "SISTEM"
MODULE_SORT_ORDER = 22

# ai son siraya eklendigi icin baska hicbir modul kaymaz
# (boq 17 / contracts 18 / sales 19 / documents 20 / equipment 21 deseni).
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

# Kullanici karari 2026-08-29: "AI'i herkes KENDI KAPSAMINDA kullanabilsin."
# system_admin=admin (test_system_admin_has_admin_level_everywhere zorunlu
# kilar), kalan yedi rol=view. `full` yazilmaz: `ai` modulunde yazma yetkisi
# seviyede degil rol anahtarindadir, `full` ekranda var olmayan bir yetki
# gosterirdi.
MATRIX: dict[str, list[tuple[str, str]]] = {
    MODULE_KEY: [
        ("admin", "all"),
        ("view", "all"),
        ("view", "all"),
        ("view", "all"),
        ("view", "all"),
        ("view", "all"),
        ("view", "all"),
        ("view", "all"),
    ],
}

#: SAPMA 1 — `ROLE_ORDER` disinda kalan (migration'dan once acilmis ozel)
#: roller icin yazilan hucre.
OZEL_ROL_HUCRESI = ("view", "all")

_INSERT_MODULE = sa.text(
    'INSERT INTO modules (id, key, name, "group", sort_order) '
    "VALUES (CAST(:id AS uuid), :key, :name, CAST(:group AS module_group), :sort_order) "
    "ON CONFLICT (key) DO NOTHING"
)

# role_id/module_id calisma aninda okunur: ilk seed migration'i UUID'leri
# uuid4() ile uretti, dolayisiyla sabit kodlanamazlar.
_INSERT_PERMISSION_FOR_ROLE = sa.text(
    "INSERT INTO role_permissions (id, role_id, module_id, access_level, scope) "
    "SELECT CAST(:id AS uuid), r.id, m.id, "
    "CAST(:access_level AS access_level), CAST(:scope AS scope) "
    "FROM roles r, modules m "
    "WHERE r.key = :role_key AND m.key = :module_key "
    "ON CONFLICT ON CONSTRAINT uq_role_module DO NOTHING"
)

#: 🔴 SAPMA 1'in ta kendisi: `WHERE r.key = ...` YOK. `gen_random_uuid()`
#: kullanilir cunku satir sayisi calisma aninda belli olur (kac ozel rol var
#: bilinmiyor) ve Python tarafinda tek bir `:id` baglamak COKLU satirda ayni
#: UUID'yi uretirdi -> birincil anahtar catismasi.
_INSERT_PERMISSION_FOR_ALL_ROLES = sa.text(
    "INSERT INTO role_permissions (id, role_id, module_id, access_level, scope) "
    "SELECT gen_random_uuid(), r.id, m.id, "
    "CAST(:access_level AS access_level), CAST(:scope AS scope) "
    "FROM roles r, modules m "
    "WHERE m.key = :module_key "
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


# --------------------------------------------------------------------------- #
# 2. `ai_tool_calls` enum'lari
# --------------------------------------------------------------------------- #

ai_tool_decision_enum = sa.Enum(
    "allowed",
    "denied_permission",
    "denied_unknown_tool",
    "denied_write_role",
    "denied_budget",
    name="ai_tool_decision",
)
ai_tool_call_phase_enum = sa.Enum("started", "finished", name="ai_tool_call_phase")
ai_tool_call_origin_enum = sa.Enum("ai", "human", name="ai_tool_call_origin")

NEW_ENUMS = (ai_tool_decision_enum, ai_tool_call_phase_enum, ai_tool_call_origin_enum)


# --------------------------------------------------------------------------- #
# 3. `audit_action` tip takasi
# --------------------------------------------------------------------------- #

AUDIT_ACTION_ONCE = ("login", "create", "update", "delete", "approve", "backup")
AUDIT_ACTION_SONRA = (*AUDIT_ACTION_ONCE, "ai_turn")

#: Tipi kullanan sutunlar KATALOGDAN okunur — elle liste, yeni bir sutunda
#: takasi sessizce eksik birakirdi (`c5d6e7f8a9b0` dersi).
_TIPI_KULLANAN_SUTUNLAR = sa.text(
    "SELECT c.relname AS tablo, a.attname AS sutun "
    "FROM pg_attribute a "
    "JOIN pg_class c ON c.oid = a.attrelid "
    "JOIN pg_type t ON t.oid = a.atttypid "
    "JOIN pg_namespace n ON n.oid = c.relnamespace "
    "WHERE t.typname = :tip AND a.attnum > 0 AND NOT a.attisdropped "
    "AND c.relkind = 'r' AND n.nspname = current_schema()"
)


def _audit_action_takas(hedef_degerler: tuple[str, ...]) -> None:
    """`audit_action` tipini `hedef_degerler` ile YENIDEN kurar (takas)."""
    bind = op.get_bind()
    sutunlar = list(bind.execute(_TIPI_KULLANAN_SUTUNLAR.bindparams(tip="audit_action")))
    degerler = ", ".join(f"'{d}'" for d in hedef_degerler)
    op.execute(f"CREATE TYPE audit_action_swap AS ENUM ({degerler})")
    for satir in sutunlar:
        op.execute(
            f"ALTER TABLE {satir.tablo} ALTER COLUMN {satir.sutun} "
            f"TYPE audit_action_swap USING {satir.sutun}::text::audit_action_swap"
        )
    op.execute("DROP TYPE audit_action")
    op.execute("ALTER TYPE audit_action_swap RENAME TO audit_action")


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()

    # --- 1. Izin modulu ---------------------------------------------------
    op.execute(
        _INSERT_MODULE.bindparams(
            id=uuid.uuid4(),
            key=MODULE_KEY,
            name=MODULE_NAME,
            group=MODULE_GROUP,
            sort_order=MODULE_SORT_ORDER,
        )
    )
    _apply_sort_orders(SORT_ORDER_UPDATES)

    # 1a. Sekiz standart rolun MATRIX hucreleri (emsal desen).
    for role_key, (access_level, scope) in zip(ROLE_ORDER, MATRIX[MODULE_KEY], strict=True):
        op.execute(
            _INSERT_PERMISSION_FOR_ROLE.bindparams(
                id=uuid.uuid4(),
                role_key=role_key,
                module_key=MODULE_KEY,
                access_level=access_level,
                scope=scope,
            )
        )
    # 1b. 🔴 SAPMA 1: KALAN HER ROL. `ON CONFLICT ... DO NOTHING` yukaridaki
    #     sekiz satiri korur, yani standart roller `OZEL_ROL_HUCRESI`ne
    #     EZILMEZ; yalnizca satiri OLMAYAN roller doldurulur.
    op.execute(
        _INSERT_PERMISSION_FOR_ALL_ROLES.bindparams(
            module_key=MODULE_KEY,
            access_level=OZEL_ROL_HUCRESI[0],
            scope=OZEL_ROL_HUCRESI[1],
        )
    )

    # --- 2. `ai_tool_calls` ----------------------------------------------
    for enum_type in NEW_ENUMS:
        enum_type.create(bind, checkfirst=True)

    op.create_table(
        "ai_tool_calls",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        # UNIQUE DEGIL: tam olarak iki satir (`started` + `finished`) paylasir.
        sa.Column("call_id", sa.UUID(), nullable=False),
        sa.Column(
            "phase",
            postgresql.ENUM(name="ai_tool_call_phase", create_type=False),
            nullable=False,
        ),
        sa.Column("user_id", sa.UUID(), nullable=True),
        # FK YOK: `ai_conversations` bu dilimde ACILMAZ (§9-A3 karari semadan
        # once gelir). Olmayan bir tabloya FK yazilamaz.
        sa.Column("conversation_id", sa.UUID(), nullable=True),
        sa.Column("provider", sa.String(length=50), nullable=True),
        sa.Column("model", sa.String(length=100), nullable=True),
        sa.Column("tool_name", sa.String(length=100), nullable=False),
        # 🔴 SABLON DEGIL COZULMUS yol (S27).
        sa.Column("resolved_path", sa.Text(), nullable=True),
        sa.Column("module_keys", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("arguments", postgresql.JSONB(), nullable=False),
        sa.Column(
            "decision",
            postgresql.ENUM(name="ai_tool_decision", create_type=False),
            nullable=False,
        ),
        # S24: sunucuda set edilir, istemciden ALINMAZ.
        sa.Column(
            "origin",
            postgresql.ENUM(name="ai_tool_call_origin", create_type=False),
            nullable=False,
        ),
        sa.Column("ai_session_id", sa.UUID(), nullable=True),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        # ON DELETE SET NULL: kullanici silinince erisim izi silinmez.
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_tool_calls_occurred_at", "ai_tool_calls", [sa.text("occurred_at DESC")])
    op.create_index("ix_ai_tool_calls_user_id", "ai_tool_calls", ["user_id"])
    op.create_index("ix_ai_tool_calls_call_id", "ai_tool_calls", ["call_id"])

    # --- 3. `audit_action` += `ai_turn` (TIP TAKASI) ----------------------
    _audit_action_takas(AUDIT_ACTION_SONRA)


def downgrade() -> None:
    """Downgrade schema — uc isin de simetrik tersi."""
    bind = op.get_bind()

    # --- 3'. `audit_action` -= `ai_turn`. FAIL-LOUD: veri varsa DURUR. ----
    kalan = bind.execute(
        sa.text("SELECT count(*) FROM audit_log WHERE action = 'ai_turn'")
    ).scalar_one()
    if kalan:
        raise RuntimeError(
            f"downgrade DURDURULDU: `audit_log`da {kalan} adet `ai_turn` satiri var. "
            "Bunlari `update` gibi baska bir eyleme cevirmek denetim gunlugunu YALANCI "
            "yapar (c5d6e7f8a9b0 fail-loud karari). Once o satirlarin ne yapilacagina "
            "karar verilmeli."
        )
    _audit_action_takas(AUDIT_ACTION_ONCE)

    # --- 2'. `ai_tool_calls` ---------------------------------------------
    op.drop_index("ix_ai_tool_calls_call_id", table_name="ai_tool_calls")
    op.drop_index("ix_ai_tool_calls_user_id", table_name="ai_tool_calls")
    op.drop_index("ix_ai_tool_calls_occurred_at", table_name="ai_tool_calls")
    op.drop_table("ai_tool_calls")
    # Tabloyla birlikte otomatik dusmez: PG enum tipleri acikca kaldirilir.
    for enum_type in NEW_ENUMS:
        enum_type.drop(bind, checkfirst=True)

    # --- 1'. Izin modulu --------------------------------------------------
    op.execute(_DELETE_PERMISSIONS.bindparams(key=MODULE_KEY))
    op.execute(_DELETE_MODULE.bindparams(key=MODULE_KEY))
    _apply_sort_orders(PREVIOUS_SORT_ORDERS)
