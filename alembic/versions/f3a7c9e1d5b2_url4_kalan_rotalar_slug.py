"""url4 kalan rotalar slug

URL-4 — URL-2'nin actigi okunabilir kimligi KALAN ALTI TABLOYA genisletir.

## Neden

Kullanici (2026-09-05): *"su link isi sadece projeler kismi icin duzeldi diger
sayfalar hâlâ tuhaf linklerde bunu da duzelt"*. URL-2 yalniz `projects` ·
`sites` · `sections` icin slug acti; kalan dokuz dinamik rota UUID gosteriyordu.

Dokuz rotanin ikisi MIGRATION ISTEMEZ — zaten tasidiklari dogal anahtarla
cozulur (`purchase_requests.request_no` GLOBAL tekil + NOT NULL;
`invoices.invoice_no` yon basina tekil, belirsizlik 409 ile karsilanir) — ve
biri `projects.slug`i YENIDEN KULLANIR (isveren sozlesmesi ucu proje anahtarli).
Geriye kalan ALTI tablo bu migration'da slug kolonu alir.

## Alti kolon, ALTI SLUG KAYNAGI (olculdu)

| tablo                              | kaynak                                              |
|------------------------------------|-----------------------------------------------------|
| `equipment`                        | `name` (`plate_no` NULLABLE, anahtar OLAMAZ)        |
| `personnel`                        | `full_name` — 🔴 YALNIZ BU (KVKK, asagida)          |
| `subcontractor_contracts`          | `contract_no`, yoksa ad + is kategorisi             |
| `progress_payments`                | `<proje-slug>-<sira>`                               |
| `subcontractor_progress_payments`  | `<sozlesme-slug>-<sira>`                            |
| `equipment_rental_invoices`        | `invoice_no`                                        |

Altisi da GLOBAL tekil, KISMI benzersiz indeks (`WHERE slug IS NOT NULL`):
kolonlar NULLABLE'dir ve coklu NULL serbest kalmak ZORUNDA.

## 🔴 SIRA BAGIMLIDIR — degistirilemez

`subcontractor_progress_payments` slug'i `subcontractor_contracts.slug`ten
TURER. Sozlesmeler ONCE doldurulmazsa hakedislerin hepsi NULL kalir ve hata
VERMEZ — sessizce yarim bir goc olurdu. Ayni bagimlilik `progress_payments` ->
`projects.slug` (URL-2'de zaten dolduruldu) icin de gecerlidir.

## 🔴 BILESIK ANAHTAR: AYRISTIRILMAZ, SAKLANIR

Hakedisin insan adi bilesiktir (*"Kopru Guclendirme, 5. hakedis"*). Uc secenek
tartisildi; secilen **(b)**: `<ust-slug>-<sira>` URETILIP SAKLANIR. Boylece
URL-2 karar 1 (yol sablonu `/{payment_id}` DEGISMEZ) korunur, `parse_ref`
degismez ve slug AYRISTIRILMAZ — `-` zaten slug alfabesinde oldugu icin
ayristirma girisimi (`son tireden bol`) `kopru-a-2-5` gibi bir slug'da YANLIS
cevap verirdi. Saklanan slug tek bir esitlik karsilastirmasidir.

## 🔴 KVKK — `personnel` slug'ina YALNIZ `full_name` girer

Tablonun TEK tekil anahtari `tc_no`dur (`uq_personnel_tc_no`) ve URL'ye ASLA
konmaz. Telefon / e-posta / TCKN'nin HICBIR PARCASI slug'a girmez. Ayni adli
iki personel sayi eki alir (`ahmet-yilmaz`, `ahmet-yilmaz-2`) — bu, adin zaten
listede gorunur oldugu bir uygulamada yeni bir sizinti ACMAZ.

## 🔴 GERI DOLDURMA PATLAMAZ (URL-2 ile BIREBIR ayni kanon)

`Dockerfile` acilisi `alembic upgrade head && uvicorn`dur: bu satirda atilan
bir istisna `&&`yi kisa devre yapar ve UVICORN HIC BASLAMAZ. Bu yuzden geri
doldurma cakismayi COZER (sayi eki), slug uretemeyen kaydi ATLAR (NULL birakir),
olcumu `logger.warning` ile deploy gunlugune YAZAR ve `raise` ETMEZ.

## Transliterasyon burada KOPYADIR ve oyle KALMALIDIR

`d2e4f6a8b0c1` ile ayni tabloyu tasir ama `app.core.slug`u IMPORT ETMEZ:
migration gecmis bir ana dondurulmus kayittir. (Depoda hicbir migration `app.*`
import etmez — desen olculdu.)

Elle yazilmistir (autogenerate DEGIL) — repo deseni.

Revision ID: f3a7c9e1d5b2
Revises: c5d8e2f1a4b7
Create Date: 2026-09-05

"""

import logging
import re
import unicodedata
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f3a7c9e1d5b2"
down_revision: str | Sequence[str] | None = "c5d8e2f1a4b7"
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

# URL-4'un alti tablosu. Sira ONEMLIDIR: `subcontractor_progress_payments`
# `subcontractor_contracts.slug`ten turer (modul docstring'i "SIRA BAGIMLIDIR").
_TABLES = (
    "equipment",
    "personnel",
    "subcontractor_contracts",
    "progress_payments",
    "subcontractor_progress_payments",
    "equipment_rental_invoices",
)

# Her tablo icin (id, taban_metin) donduren SELECT. `ORDER BY created_at, id`
# DETERMINISTIKTIR: en eski kayit EKSIZ slug'i alir, sonrakiler sayi eki —
# aksi hâlde ayni veritabanina iki kez kosuldugunda (staging/prod) farkli
# kayitlar eksiz slug'i kapardi.
#
# `NULL` taban ATLANIR (slug NULL kalir). Bilesik olanlarda ust slug NULL ise
# `||` zaten NULL uretir ve satir dogal olarak atlanir — ek bir kosula gerek
# YOKTUR ve bu, "ust kaydin slug'i yoksa cocugunki de olmaz" kuralinin ta
# kendisidir.
_SOURCES: dict[str, str] = {
    "equipment": "SELECT id, name FROM equipment ORDER BY created_at, id",
    "personnel": "SELECT id, full_name FROM personnel ORDER BY created_at, id",
    # `contract_no` doldurulmussa O kullanilir (mockup'ta ZORUNLU alan ve
    # `uq_subcontractor_contracts_contract_no` ile tekil); taslakta ad + kategori.
    "subcontractor_contracts": (
        "SELECT id, COALESCE("
        "  NULLIF(TRIM(contract_no), ''),"
        "  NULLIF(TRIM(CONCAT_WS(' ', subcontractor_name, work_category)), '')"
        ") FROM subcontractor_contracts ORDER BY created_at, id"
    ),
    "progress_payments": (
        "SELECT pp.id, pr.slug || '-' || pp.sequence_no "
        "FROM progress_payments pp JOIN projects pr ON pr.id = pp.project_id "
        "ORDER BY pp.created_at, pp.id"
    ),
    "subcontractor_progress_payments": (
        "SELECT sp.id, sc.slug || '-' || sp.sequence_no "
        "FROM subcontractor_progress_payments sp "
        "JOIN subcontractor_contracts sc ON sc.id = sp.contract_id "
        "ORDER BY sp.created_at, sp.id"
    ),
    "equipment_rental_invoices": (
        "SELECT id, NULLIF(TRIM(invoice_no), '') FROM equipment_rental_invoices "
        "ORDER BY created_at, id"
    ),
}


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


def _backfill(table: str) -> None:
    """Mevcut satirlara slug yazar. Kapsam ALTI tabloda da GLOBAL'dir.

    🔴 `used` kumesi VERITABANINDAN degil bu kosudan doldurulur ve kolon bu
    migration'da ACILDIGI icin baslangicta zorunlu olarak bostur — yani
    "onceden yazilmis bir slug'i gormedim" hâli YAPISAL OLARAK imkânsizdir.
    """
    bind = op.get_bind()
    rows = bind.execute(sa.text(_SOURCES[table])).fetchall()

    used: set[str] = set()
    written = collided = skipped = 0
    for row in rows:
        base = _slugify(row[1])
        if base is None:
            skipped += 1
            logger.warning(
                "URL-4 geri doldurma: %s.%s slug uretilemedi (taban=%r) — NULL birakildi",
                table,
                row[0],
                row[1],
            )
            continue
        slug = _unique(base, used)
        if slug != base:
            collided += 1
            logger.warning(
                "URL-4 geri doldurma: %s.%s slug cakismasi %r -> %r",
                table,
                row[0],
                base,
                slug,
            )
        used.add(slug)
        bind.execute(
            sa.text(f"UPDATE {table} SET slug = :slug WHERE id = :id"),
            {"slug": slug, "id": row[0]},
        )
        written += 1

    # 🔴 OLCUM DEPLOY GUNLUGUNE — Railway yalniz guncel deployment'i tutar.
    logger.warning(
        "URL-4 geri doldurma OLCUMU %s: satir=%d yazildi=%d cakisma=%d atlandi=%d",
        table,
        len(rows),
        written,
        collided,
        skipped,
    )


def upgrade() -> None:
    for table in _TABLES:
        op.add_column(table, sa.Column("slug", sa.String(length=160), nullable=True))

    # Kolonlar ACILDIKTAN sonra, indeksler KURULMADAN once: indeks kurulurken
    # cakisma kalmamis olmali. `_unique` cakismayi YAPISAL OLARAK imkânsiz
    # kilar, indeks yine de son bekcidir. `_TABLES` sirasi BAGLAYICIDIR.
    for table in _TABLES:
        _backfill(table)

    for table in _TABLES:
        op.create_index(
            f"uq_{table}_slug",
            table,
            ["slug"],
            unique=True,
            postgresql_where=sa.text("slug IS NOT NULL"),
        )


def downgrade() -> None:
    # `drop_index` cagrilari ESDEGER MUTANT uretir (PostgreSQL kolonu dusururken
    # ona bagli indeksleri de duserur) — URL-2'nin `d2e4f6a8b0c1` migration'inda
    # olculmus ve orada da ACIKCA yazilmisti; niyeti gorunur kilar.
    for table in reversed(_TABLES):
        op.drop_index(f"uq_{table}_slug", table_name=table)
        op.drop_column(table, "slug")
