"""ik3 bordro cekirdegi

İK-3 T1 — bordro şeması (backend spec
`docs/superpowers/specs/2026-08-13-ik3-bordro-design.md` §4).

Üç tablo:
  1. `payroll_periods` — bordro dönemi (ay). UQ (year, month): bir ay için TEK
     bordro. BG kartlarındaki toplamlar KOLON DEĞİLDİR (satırlardan türev).
  2. `payroll_lines`   — personel başına brüt/kesinti/net + banka/elden bölüşümü.
     `personnel_id` **RESTRICT**: bordro satırı bir PARA izidir. Beş para kolonu
     nullable ve SUNUCU VARSAYILANSIZDIR (S4 fail-closed: ücretsiz personelde
     uydurma 0 basılmaz).
  3. `payroll_rates`   — yapılandırılabilir oran tablosu (K1) + **2026 SEED'i**.

İki yeni enum: `payroll_period_status` · `payroll_line_status`. Downgrade'de
AÇIKÇA `DROP TYPE` edilir — yoksa ikinci `upgrade` "type already exists" ile
patlar (d4e5f6a7b8c9 dersi), bu yalnız CANLIDA görülürdü.

--------------------------------------------------------------------------
PAYLAŞILAN `worker_source` TİPİNİN TAKASI (`freelance` + `intern` eklenir)
--------------------------------------------------------------------------
NEDEN: oran tablosu DÖRT tip üzerindedir (spec §4, S2) — BY 127 "ŞİRKET KADROSU
— SGK 4a" · BY 175 "TAŞERON İŞÇİSİ" · BY 243 "SERBEST MESLEK · %20 Stopaj" ·
BY 271 "STAJYER". Mevcut `worker_source` yalnız üç değer taşıyor. İK-1 bu işi
açıkça bu dilime ertelemişti (`personnel/models.py`: "`Serbest Meslek`/`Stajyer`
… takas SGK 4a/4b ayrımı netleşince İK-3'te yapılır"). Yeni bir
`personnel_source` TİPİ AÇILMAZ — aynı anlam kümesinin iki DB tipi doğardı
(puantaj spec §2).

NEDEN `ALTER TYPE ... ADD VALUE` DEĞİL: eklenen değer AYNI işlemde
KULLANILAMAZ (d4e5f6a7b8c9 notu) ve bu migration onu aynı işlemde kullanır
(`payroll_rates` seed'i). Ayrıca `ADD VALUE` **GERİ ALINAMAZ**. Bu yüzden
f1b2c3d4e5a6 (`site_status`) deseni uygulanır: tip TAKAS edilir — yeni tip aynı
işlemde yaratıldığı için değerleri hemen kullanılabilir ve takas tersine
çevrilebilir.

Tipi kullanan sütunlar SABİT LİSTEDEN DEĞİL, katalogdan (`pg_attribute`)
okunur: bugün `personnel.source` ve `site_diary_worker_counts.source`, yarın
başkası. Elle yazılmış bir liste, yeni bir sütun eklendiğinde takası SESSİZCE
eksik bırakırdı.

**DOWNGRADE FAIL-LOUD KARARI:** downgrade, `freelance`/`intern` değerini
kullanan satır varsa `RuntimeError` ile DURUR (sessizce `general`e çevirmez).
Gerekçe PARA sınıfıdır: serbest meslekli %20 stopaj rejimindedir, stajyer
kesintisizdir; bunları "genel işçi"ye çevirmek personelin vergi rejimini sessizce
DEĞİŞTİRİR ve bir sonraki `compute` yanlış kesinti üretirdi. Operatör önce
kayıtları açıkça çözmek zorundadır. (`payroll_*` tabloları takastan ÖNCE
düşürüldüğü için oran seed'i bu kapıya takılmaz.)

Elle yazılmıştır (autogenerate DEĞİL) — repo deseni.

Revision ID: c5d6e7f8a9b0
Revises: b2c3d4e5f6a7
Create Date: 2026-08-13

"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c5d6e7f8a9b0"
down_revision: str | Sequence[str] | None = "b2c3d4e5f6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

payroll_period_status_enum = sa.Enum(
    "draft", "pending_approval", "approved", "paid", name="payroll_period_status"
)
payroll_line_status_enum = sa.Enum(
    "uncomputed", "pending", "approved", "paid", "excluded", name="payroll_line_status"
)

# `worker_source` BU LISTEDE YOK — paylasilan tip, TAKAS edilir (asagi bak).
NEW_ENUMS = (payroll_period_status_enum, payroll_line_status_enum)

WORKER_SOURCE_OLD = ("company", "subcontractor", "general")
WORKER_SOURCE_NEW = ("company", "subcontractor", "general", "freelance", "intern")
WORKER_SOURCE_ADDED = ("freelance", "intern")

# --------------------------------------------------------------------------- #
# 2026 oran SEED'i (K1 · S1 · S2)
# --------------------------------------------------------------------------- #
# S1: BY tablosundaki tutarlar (%29,81 kesinti) ile SGK sayfasındaki AÇIK oranlar
# ayni anda dogru olamaz; ACIKCA YAZILI oranlar seed olur. Mockup kaynaklari:
#   SGK 70 "SGK Isci Payi (%14)"            SGK 79 "SGK Isveren Payi (%20,5)"
#   SGK 71 "Issizlik Sigortasi Isci (%1)"   SGK 80 "Issizlik Sigortasi Isveren (%2)"
#   SGK 72 "Gelir Vergisi Stopaji (%10)"    SGK 81 "Kisa Calisma Odenegi (%1)"
#   SGK 73 "Damga Vergisi (%0,759)"
SGK_4A = {
    "sgk_employee_pct": "14",
    "unemployment_employee_pct": "1",
    "income_tax_pct": "10",
    "stamp_tax_pct": "0.759",
    "sgk_employer_pct": "20.5",
    "unemployment_employer_pct": "2",
    "short_work_pct": "1",
}
SIFIR = dict.fromkeys(SGK_4A, "0")

RATE_SEED_2026 = {
    # BY 127 "SIRKET KADROSU — SGK 4a".
    "company": SGK_4A,
    # BY 175 "TASERON ISCISI — SGK Taseron". Kesinti sutunu "—" DEGILDIR
    # (BY 186: 26.400 brut -> 7.064 kesinti), yani taseron iscisi de kesintiye
    # tabidir -> 4a oranlarinin AYNISI. Odeme onayina girmemesi K2 kararidir ve
    # SERVIS katmanindadir; oran tablosuyla ilgisi yoktur.
    "subcontractor": SGK_4A,
    # BY 243 "SERBEST MESLEK — Serbest Makbuz · %20 Stopaj"; BY 254-255 veriyle
    # dogruluyor (12.500 brut -> 2.500 kesinti = tam %20). SGK payi YOK.
    "freelance": {**SIFIR, "income_tax_pct": "20"},
    # BY 285: stajyer satirinda kesinti sutunu "—" -> TUM oranlar 0.
    "intern": SIFIR,
}
# `general` ("genel isci", GK418-430) bordro tipi DEGILDIR: BY dort bolum ciziyor.
# Bes yil seed edilmez — oran tablosu YILLIKTIR, 2027'yi uydurmak mevzuat icat
# etmek olurdu (K1).
RATE_SEED_YEAR = 2026

RATE_COLUMNS = tuple(SGK_4A)


# --------------------------------------------------------------------------- #
# `worker_source` takasi
# --------------------------------------------------------------------------- #


def _columns_using_enum(bind, type_name: str) -> list[tuple[str, str, str | None]]:
    """Verilen enum tipini kullanan (tablo, sutun, sunucu varsayilani) uclulari.

    Katalogdan okunur: elle yazilmis bir liste, yeni bir sutun eklendiginde
    takasi SESSIZCE eksik birakirdi.
    """
    rows = bind.execute(
        sa.text(
            "SELECT c.relname, a.attname, pg_get_expr(d.adbin, d.adrelid) "
            "FROM pg_attribute a "
            "JOIN pg_class c ON c.oid = a.attrelid "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "JOIN pg_type t ON t.oid = a.atttypid "
            "LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum "
            "WHERE t.typname = :type_name AND t.typtype = 'e' "
            "  AND c.relkind = 'r' AND n.nspname = 'public' "
            "  AND a.attnum > 0 AND NOT a.attisdropped "
            "ORDER BY c.relname, a.attname"
        ),
        {"type_name": type_name},
    ).fetchall()
    return [(row[0], row[1], row[2]) for row in rows]


def _checks_on_columns(bind, columns: Sequence[tuple[str, str, str | None]]) -> list[tuple]:
    """Enum sutunlarina DEGEN CHECK kisitlari: (tablo, ad, tanim).

    Bunlar takastan ONCE dusurulmeli, SONRA aynen geri konmalidir. Aksi halde
    `ALTER COLUMN ... TYPE` "operator does not exist: worker_source_swap =
    worker_source" ile patlar — kisit ifadesi hala ESKI tipin literalini
    tasidigi icin. Bu kapiyi `personnel`in
    `ck_personnel_subcontractor_only_for_subcontractor_source` kisiti acti;
    yine katalogdan okunur, elle liste tutulmaz.
    """
    bulunan: list[tuple] = []
    for table, column, _ in columns:
        rows = bind.execute(
            sa.text(
                "SELECT con.conname, pg_get_constraintdef(con.oid) "
                "FROM pg_constraint con "
                "JOIN pg_class c ON c.oid = con.conrelid "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "JOIN pg_attribute a ON a.attrelid = c.oid AND a.attname = :column "
                "WHERE con.contype = 'c' AND n.nspname = 'public' "
                "  AND c.relname = :table AND a.attnum = ANY(con.conkey) "
                "ORDER BY con.conname"
            ),
            {"table": table, "column": column},
        ).fetchall()
        bulunan.extend((table, row[0], row[1]) for row in rows)
    return bulunan


def _swap_worker_source(bind, labels: Sequence[str]) -> None:
    """`worker_source` tipini `labels` kumesiyle YENIDEN KURAR (f1b2c3d4e5a6 deseni).

    Sunucu varsayilanlari ve sutuna degen CHECK kisitlari once DUSURULUR, tip
    cevrildikten sonra AYNEN geri konur — `DROP DEFAULT` atlanirsa
    `ALTER COLUMN ... TYPE` "default for column cannot be cast automatically",
    CHECK birakilirsa "operator does not exist" ile patlar.
    """
    columns = _columns_using_enum(bind, "worker_source")
    checks = _checks_on_columns(bind, columns)
    yeni_tip = ", ".join(f"'{label}'" for label in labels)
    op.execute(f"CREATE TYPE worker_source_swap AS ENUM ({yeni_tip})")
    for table, name, _ in checks:
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT {name}")
    for table, column, _ in columns:
        op.execute(f"ALTER TABLE {table} ALTER COLUMN {column} DROP DEFAULT")
    for table, column, _ in columns:
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN {column} TYPE worker_source_swap "
            f"USING {column}::text::worker_source_swap"
        )
    op.execute("DROP TYPE worker_source")
    op.execute("ALTER TYPE worker_source_swap RENAME TO worker_source")
    for table, column, default in columns:
        if default is not None:
            op.execute(f"ALTER TABLE {table} ALTER COLUMN {column} SET DEFAULT {default}")
    for table, name, definition in checks:
        op.execute(f"ALTER TABLE {table} ADD CONSTRAINT {name} {definition}")


def _assert_no_rows_use_added_labels(bind) -> None:
    """FAIL-LOUD (PARA sinifi): eklenen degerleri kullanan satir varsa DURDUR.

    Sessizce `general`e cevirmek personelin VERGI REJIMINI degistirirdi (serbest
    meslek %20 stopaj, stajyer kesintisiz) ve bir sonraki `compute` yanlis
    kesinti uretirdi. Operator kayitlari ACIKCA cozmek zorundadir.
    """
    kullanilan = ", ".join(f"'{label}'" for label in WORKER_SOURCE_ADDED)
    engeller: list[str] = []
    for table, column, _ in _columns_using_enum(bind, "worker_source"):
        adet = bind.execute(
            sa.text(f"SELECT count(*) FROM {table} WHERE {column}::text IN ({kullanilan})")
        ).scalar_one()
        if adet:
            engeller.append(f"{table}.{column}: {adet} satir")
    if engeller:
        raise RuntimeError(
            "İK-3 downgrade DURDURULDU: `worker_source` tipinden düşürülecek "
            f"{kullanilan} değerlerini kullanan satırlar var → {'; '.join(engeller)}. "
            "Bu satırlar sessizce 'general'e çevrilmez (PARA sınıfı: serbest meslek "
            "%20 stopaj, stajyer kesintisiz rejimdedir). Önce kayıtları elle çözün."
        )


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()

    # 0. Paylasilan tipin TAKASI — tablolardan ONCE, cunku iki tablo bu tipi
    #    kolon olarak kullanir ve seed yeni degerleri AYNI islemde yazar.
    _swap_worker_source(bind, WORKER_SOURCE_NEW)

    for enum_type in NEW_ENUMS:
        enum_type.create(bind, checkfirst=True)

    # 1. payroll_periods — bordro donemi (ay).
    op.create_table(
        "payroll_periods",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("month", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(name="payroll_period_status", create_type=False),
            server_default=sa.text("'draft'::payroll_period_status"),
            nullable=False,
        ),
        sa.Column("payment_due_date", sa.Date(), nullable=True),
        sa.Column("approved_by_id", sa.UUID(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sgk_submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("month >= 1 AND month <= 12", name="ck_payroll_periods_month_range"),
        # SET NULL: onaylayan kullanici silinse de donem ve onay ZAMANI kalir.
        sa.ForeignKeyConstraint(["approved_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("year", "month", name="uq_payroll_periods_year_month"),
    )
    op.create_index("ix_payroll_periods_status", "payroll_periods", ["status"])

    # 2. payroll_lines — personel basina satir.
    op.create_table(
        "payroll_lines",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("payroll_period_id", sa.UUID(), nullable=False),
        sa.Column("personnel_id", sa.UUID(), nullable=False),
        sa.Column(
            "personnel_source",
            postgresql.ENUM(name="worker_source", create_type=False),
            nullable=False,
        ),
        sa.Column("days", sa.Integer(), nullable=True),
        sa.Column("gross_amount", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("deduction_amount", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("net_amount", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("bank_amount", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("cash_amount", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("is_overridden", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("overridden_by_id", sa.UUID(), nullable=True),
        sa.Column("overridden_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("previous_gross_amount", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM(name="payroll_line_status", create_type=False),
            server_default=sa.text("'uncomputed'::payroll_line_status"),
            nullable=False,
        ),
        sa.Column("excluded_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("days IS NULL OR days >= 0", name="ck_payroll_lines_days_positive"),
        sa.CheckConstraint(
            "gross_amount IS NULL OR gross_amount >= 0", name="ck_payroll_lines_gross_positive"
        ),
        sa.CheckConstraint(
            "deduction_amount IS NULL OR deduction_amount >= 0",
            name="ck_payroll_lines_deduction_positive",
        ),
        sa.CheckConstraint(
            "net_amount IS NULL OR net_amount >= 0", name="ck_payroll_lines_net_positive"
        ),
        sa.CheckConstraint(
            "bank_amount IS NULL OR bank_amount >= 0", name="ck_payroll_lines_bank_positive"
        ),
        sa.CheckConstraint(
            "cash_amount IS NULL OR cash_amount >= 0", name="ck_payroll_lines_cash_positive"
        ),
        # CASCADE: donem silinince satirlari duser (yetim satir yok).
        sa.ForeignKeyConstraint(["payroll_period_id"], ["payroll_periods.id"], ondelete="CASCADE"),
        # RESTRICT: bordro satiri olan personel SILINEMEZ — para izi (spec §4).
        sa.ForeignKeyConstraint(["personnel_id"], ["personnel.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["overridden_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "payroll_period_id", "personnel_id", name="uq_payroll_lines_period_personnel"
        ),
    )
    op.create_index("ix_payroll_lines_payroll_period_id", "payroll_lines", ["payroll_period_id"])
    op.create_index("ix_payroll_lines_personnel_id", "payroll_lines", ["personnel_id"])
    op.create_index("ix_payroll_lines_status", "payroll_lines", ["status"])

    # 3. payroll_rates — yapilandirilabilir oran tablosu (K1).
    op.create_table(
        "payroll_rates",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column(
            "personnel_source",
            postgresql.ENUM(name="worker_source", create_type=False),
            nullable=False,
        ),
        *(
            sa.Column(name, sa.Numeric(precision=6, scale=3), nullable=False)
            for name in RATE_COLUMNS
        ),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            " AND ".join(f"{name} >= 0" for name in RATE_COLUMNS),
            name="ck_payroll_rates_non_negative",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("year", "personnel_source", name="uq_payroll_rates_year_source"),
    )
    op.create_index("ix_payroll_rates_year", "payroll_rates", ["year"])

    # 4. 2026 SEED'i. Sabit UUID DEGILDIR: downgrade tabloyu dusurdugu icin
    #    ikinci upgrade'de cakisma riski yoktur (İK-1/İK-2 emsali).
    kolonlar = ", ".join(RATE_COLUMNS)
    for source, oranlar in RATE_SEED_2026.items():
        degerler = ", ".join(oranlar[name] for name in RATE_COLUMNS)
        op.execute(
            sa.text(
                f"INSERT INTO payroll_rates (id, year, personnel_source, {kolonlar}, is_active) "
                f"VALUES (:id, :year, '{source}'::worker_source, {degerler}, true)"
            ).bindparams(id=uuid.uuid4(), year=RATE_SEED_YEAR)
        )


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()

    op.drop_index("ix_payroll_rates_year", table_name="payroll_rates")
    op.drop_table("payroll_rates")

    op.drop_index("ix_payroll_lines_status", table_name="payroll_lines")
    op.drop_index("ix_payroll_lines_personnel_id", table_name="payroll_lines")
    op.drop_index("ix_payroll_lines_payroll_period_id", table_name="payroll_lines")
    op.drop_table("payroll_lines")

    op.drop_index("ix_payroll_periods_status", table_name="payroll_periods")
    op.drop_table("payroll_periods")

    # Enum tipleri tablolarla birlikte SILINMEZ — acikca dusurulur, yoksa ikinci
    # `upgrade` "type already exists" ile patlar (d4e5f6a7b8c9 dersi).
    for enum_type in NEW_ENUMS:
        enum_type.drop(bind, checkfirst=False)

    # Paylasilan tipin takasi GERI ALINIR — ama once fail-loud kapisi.
    _assert_no_rows_use_added_labels(bind)
    _swap_worker_source(bind, WORKER_SOURCE_OLD)
