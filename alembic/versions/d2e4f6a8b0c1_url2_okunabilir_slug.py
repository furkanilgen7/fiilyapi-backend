"""url2 okunabilir slug

URL-2 — `projects` · `sites` · `sections` tablolarina okunabilir URL kimligi.

## Neden

Kullanici canlida `panel.fiilyapi.com/projeler/049e058b-42d9-4e46-aafe-4bcf629e80cd`
gordu. Kullanici karari (2026-08-29): **AD SLUG'I** -> `/projeler/kopru-guclendirme`.
`code` (`PRJ-2026-002`) migration'siz bir cozum sunuyordu ama kullanici slug'i
SECTI; karar verilmistir.

## Uc kolon, UC AYRI TEKILLIK KAPSAMI (mevcut kisitlarin aynasi, olculdu)

* `projects.slug`  -> **global** tekil       (projenin ustunde kapsam YOK)
* `sites.slug`     -> **proje icinde** tekil (`uq_sites_project_code` emsali)
* `sections.slug`  -> **santiye icinde**     (`uq_sections_site_code` emsali)

Ucu de KISMI benzersiz indekstir (`WHERE slug IS NOT NULL`): kolonlar
NULLABLE'dir ve coklu NULL serbest kalmalidir.

## 🔴 NEDEN NULLABLE (emirdeki "olmayacaksa gerekcelendir")

1. Adi tamamen noktalama/ASCII-disi olan bir kayit slug URETEMEZ (`"???"`).
   NOT NULL boyle bir adi ya reddederdi ya uydurma bir taban yazardi.
2. Slug'in tek mesru ureticisi SERVIS katmanidir; NOT NULL, ORM nesnesini
   dogrudan kuran her ic yolu slug vermeye zorlardi (`sections.code` emsali).

NULL slug ZARARSIZDIR: o kaydin URL'i UUID olarak yasar — URL-2 karari 2 eski
UUID baglantilarini KALICI olarak destekler.

## 🔴 GERI DOLDURMA PATLAMAZ

`Dockerfile` acilisi `alembic upgrade head && uvicorn`dur: bu satirda atilan
bir istisna `&&`yi kisa devre yapar ve UVICORN HIC BASLAMAZ. Bu yuzden geri
doldurma:

* cakismayi COZER (sayi eki: `kopru-a`, `kopru-a-2`, ...),
* slug uretemeyen kaydi ATLAR (NULL birakir),
* olcumu `logger.warning` ile deploy gunlugune YAZAR,
* `raise` ETMEZ.

Railway yalniz GUNCEL deployment'in gunlugunu tutar; olcum oraya yazilir.

## Transliterasyon burada KOPYADIR ve oyle KALMALIDIR

`app/core/slug.py` ile ayni tabloyu tasir ama onu IMPORT ETMEZ. Migration
gecmis bir ana dondurulmus bir kayittir: uygulama kodu yarin degisirse bu
dosyanin uc yil once uretmis oldugu slug'lar degismemelidir. (Depoda hicbir
migration `app.*` import etmez — desen olculdu.)

## `str.lower()` TUZAGI

`"I".lower()` (U+0049, noktasiz BUYUK I) -> `"i"`; Turkce'de kucugu `"ı"`dir.
`"İ".lower()` (U+0130, noktali BUYUK I) -> `"i"` + U+0307 BIRLESIK NOKTA:
TEK harf gibi GORUNUR, IKI kod noktasidir ve `[a-z0-9]` suzgecinden GECMEZ
(`İstanbul` -> `-stanbul`). Bu yuzden Turkce harfler `lower()`dan ONCE
acik tabloyla cevrilir.

Elle yazilmistir (autogenerate DEGIL) — repo deseni.

Revision ID: d2e4f6a8b0c1
Revises: a7c3d1e5b204
Create Date: 2026-08-29

"""

import logging
import re
import unicodedata
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d2e4f6a8b0c1"
down_revision: str | Sequence[str] | None = "a7c3d1e5b204"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

logger = logging.getLogger("alembic.runtime.migration")

# `app/core/slug.py`nin KOPYASI — bkz. modul docstring'i "KOPYADIR".
_TURKISH_TO_ASCII = str.maketrans(
    {
        "Ç": "c",
        "Ğ": "g",
        "İ": "i",
        "I": "i",
        "Ö": "o",
        "Ş": "s",
        "Ü": "u",
        "ç": "c",
        "ğ": "g",
        "ı": "i",
        "ö": "o",
        "ş": "s",
        "ü": "u",
    }
)
_NON_SLUG = re.compile(r"[^a-z0-9]+")
_MAX = 100


def _slugify(value: str | None) -> str | None:
    if value is None:
        return None
    ascii_text = value.translate(_TURKISH_TO_ASCII)
    decomposed = unicodedata.normalize("NFKD", ascii_text)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    slug = _NON_SLUG.sub("-", stripped.lower()).strip("-")
    if not slug:
        return None
    return slug[:_MAX].strip("-") or None


def _unique(base: str, used: set[str]) -> str:
    if base not in used:
        return base
    suffix = 2
    while f"{base}-{suffix}" in used:
        suffix += 1
    return f"{base}-{suffix}"


def _backfill(table: str, scope_column: str | None) -> None:
    """Mevcut satirlara slug yazar. `scope_column` None ise kapsam globaldir.

    Siralama `created_at, id`dir ve DETERMINISTIKTIR: en eski kayit EKSIZ
    slug'i alir, sonrakiler sayi eki. Aksi hâlde ayni veritabanina iki kez
    kosuldugunda (staging/prod) farkli kayitlar eksiz slug'i kapardi.
    """
    bind = op.get_bind()
    scope_select = f"{scope_column}, " if scope_column else ""
    rows = bind.execute(
        sa.text(f"SELECT id, {scope_select}name FROM {table} ORDER BY created_at, id")
    ).fetchall()

    used: dict[object, set[str]] = {}
    written = 0
    collided = 0
    skipped = 0
    for row in rows:
        scope = row[1] if scope_column else None
        name = row[-1]
        base = _slugify(name)
        if base is None:
            skipped += 1
            logger.warning(
                "URL-2 geri doldurma: %s.%s slug uretilemedi (ad=%r) — NULL birakildi",
                table,
                row[0],
                name,
            )
            continue
        taken = used.setdefault(scope, set())
        slug = _unique(base, taken)
        if slug != base:
            collided += 1
            logger.warning(
                "URL-2 geri doldurma: %s.%s slug cakismasi %r -> %r (kapsam=%r)",
                table,
                row[0],
                base,
                slug,
                scope,
            )
        taken.add(slug)
        bind.execute(
            sa.text(f"UPDATE {table} SET slug = :slug WHERE id = :id"),
            {"slug": slug, "id": row[0]},
        )
        written += 1

    # 🔴 OLCUM DEPLOY GUNLUGUNE — Railway yalniz guncel deployment'i tutar.
    logger.warning(
        "URL-2 geri doldurma OLCUMU %s: satir=%d yazildi=%d cakisma=%d atlandi=%d",
        table,
        len(rows),
        written,
        collided,
        skipped,
    )


def upgrade() -> None:
    for table in ("projects", "sites", "sections"):
        op.add_column(table, sa.Column("slug", sa.String(length=160), nullable=True))

    # Kolonlar ACILDIKTAN sonra, indeksler KURULMADAN once: indeks kurulurken
    # cakisma kalmamis olmali. `_unique` kapsam ici cakismayi YAPISAL OLARAK
    # imkansiz kilar, indeks yine de son bekcidir.
    _backfill("projects", None)
    _backfill("sites", "project_id")
    _backfill("sections", "site_id")

    op.create_index(
        "uq_projects_slug",
        "projects",
        ["slug"],
        unique=True,
        postgresql_where=sa.text("slug IS NOT NULL"),
    )
    op.create_index(
        "uq_sites_project_slug",
        "sites",
        ["project_id", "slug"],
        unique=True,
        postgresql_where=sa.text("slug IS NOT NULL"),
    )
    op.create_index(
        "uq_sections_site_slug",
        "sections",
        ["site_id", "slug"],
        unique=True,
        postgresql_where=sa.text("slug IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_sections_site_slug", table_name="sections")
    op.drop_index("uq_sites_project_slug", table_name="sites")
    op.drop_index("uq_projects_slug", table_name="projects")
    for table in ("sections", "sites", "projects"):
        op.drop_column(table, "slug")
