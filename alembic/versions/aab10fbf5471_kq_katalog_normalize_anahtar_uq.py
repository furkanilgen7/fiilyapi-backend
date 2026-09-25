"""KATALOG-UQ — `ev_catalog_items` normalize anahtar kolonlari + DB tekilligi

EV-BORC-5 katalog tekilligini `labels.normalize_label` ile YALNIZ servis SELECT'inde
sinadi; DB UQ'su birebir (harf duyarli) `(discipline_id, name, uom)` kaldi. Bu migration:

1. `name_key` String(200) / `uom_key` String(50) kolonlarini NULL olarak ekler,
2. mevcut satirlarin anahtarini PYTHON ile doldurur (satir satir SELECT → normalize → UPDATE),
3. doldurmadan ONCE normalize ciftleri arar; varsa ACIK HATAYLA durur (asagida),
4. iki kolonu NOT NULL yapar,
5. `uq_ev_catalog_items_disc_name_uom`u dusurur (yeni UQ onu KAPSAR: ham esitlik → anahtar
   esitligi) ve `uq_ev_catalog_items_disc_name_key_uom_key`i kurar.

## Neden ifade indeksi degil (KATALOG-UQ K1/K2)
Postgres `lower()` DB'nin LC_CTYPE'ina bagli: yerel olcumde "C" ctype'ta 1381 kod noktasi
Python `str.lower()`dan farkli; en_US.utf8/C.UTF-8'de Yunan final sigma ("ΟΔΟΣ"→"οδος")
farkli ve glibc'nin Unicode surumu Python'unkinden yeni (27 kod noktasi). Ifade indeksi bu
yuzden uygulamanin kuraliyla BIREBIR olamaz; glibc guncellemesinde bozulabilir de. Anahtari
uygulama yazar (`EvCatalogItem._sync_key`), DB yalniz duz varchar ESITLIGINI zorlar
(deterministik harmanlamada bayt esitligi: ctype'tan bagimsiz).

## Normalize fonksiyonu DONDURULMUS KOPYADIR
Depo kanonu: migration `app`i import ETMEZ (uygulanmis migration donmus olmalidir;
`tests/modules/test_seed_migration_matches_seed_data.py` ayni gerekceyle). `_normalize`
2026-09-25'teki `app.modules.earned_value.labels.normalize_label`in birebir kopyasidir;
esitligini `tests/earned_value/test_kq_catalog_uq_migration.py` tum Unicode kod noktalari
ve K1 vakalariyla sinar. `normalize_label` ileride DEGISIRSE mevcut anahtarlar eski kuralla
kalir → o degisiklik anahtarlari yeniden hesaplayan YENI bir migration getirmelidir.
Canli sayim betigi (`katalog-tekillik-grupla.py`) bu dosyanin `_duplicate_groups`unu
YUKLER: sayim ile migration'in cift tanimi ayni fonksiyondur.

## Canlida cift varsa
UQ kurulamaz. Migration hicbir seyi degistirmeden (kendi islemi geri alinir,
`transaction_per_migration=True`) `RuntimeError` ile durur; mesaj her grubu disiplin kodu,
anahtar ve satirlarla (id | ad | birim) listeler. Dockerfile `alembic upgrade head && uvicorn`
oldugu icin yeni konteyner ACILMAZ. Cozum kullanici kararidir (katalog kalemi silinmez,
B1-9): PATCH ile birini yeniden adlandirmak, sonra yeniden dagitmak. Otomatik birlestirme/
yeniden adlandirma YAPILMAZ (butce satirlari `catalog_item_id` ile bagli, veri karari).

## Kilit
`LOCK TABLE … SHARE ROW EXCLUSIVE` en basta: SELECT ile UQ arasinda eski konteynerin
INSERT/UPDATE'i araya giremez (okumalar surer). `ADD COLUMN` zaten ACCESS EXCLUSIVE'e
yukseltir; tablo kucuk, islem kisadir.

## 🔴 DAGITIM SIRASI (KATALOG-UQ K4)
Railway'de migration, ESKI konteyner hala trafik alirken kosar. Eski kod anahtari bilmez:
* INSERT → `name_key` NULL → NOT NULL ihlali → 409 (gürültülü, kayip yok);
* ad/birim UPDATE → anahtar BAYAT kalir (SESSIZ) → tekillik o satirda delinir.
Onerilen: katalog yazimi dagitim penceresinde yapilmaz ve dagitim SONRASI
`katalog-tekillik-grupla.py` ile bayat anahtar sayimi 0 olmalidir. Sifir riskli yol iki
dagitimli genislet/daralt'tir (rapor K4).

## 🔀 RE-PARENT NOTU
CLEAN-B2 (`b5858dd66531`, down_revision `c7d1e2f3a4b5`) baska dalda bekliyor; bu migration
da `c7d1e2f3a4b5`e baglidir. Ikisi AYNI ANDA merge EDILMEZ: hangisi once merge olursa
digerinin `down_revision`i onun revision'ina tasinir (`alembic heads` TEK olmali).

DOWNGRADE: yeni UQ'yu ve iki kolonu dusurur, eski birebir UQ'yu geri kurar (yeni UQ'yu
saglayan her veri eskiyi de saglar: kurulumu basarisiz olamaz).

Revision ID: aab10fbf5471
Revises: c7d1e2f3a4b5
Create Date: 2026-09-25

"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Sequence
from typing import Any

import sqlalchemy as sa

from alembic import op

revision: str = "aab10fbf5471"
down_revision: str | Sequence[str] | None = "c7d1e2f3a4b5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "ev_catalog_items"
OLD_UQ = "uq_ev_catalog_items_disc_name_uom"
NEW_UQ = "uq_ev_catalog_items_disc_name_key_uom_key"

#: Sifir genislikli karakterler: bosluk DEGIL, SILINIR (iki harf arasindaysa bitisir).
_ZERO_WIDTH = str.maketrans("", "", "\u200b\u200c\u200d\ufeff")


def _normalize(text: str) -> str:
    """DONDURULMUS kopya: `labels.normalize_label` (2026-09-25, KATALOG-UQ madde 1: NFC +
    sifir genislikli karakter silme eklendi). DEGISTIRME."""
    s = unicodedata.normalize("NFC", text)
    s = s.replace("İ", "i").replace("I", "ı").lower()
    s = s.replace("³", "3").replace("²", "2")
    s = s.translate(_ZERO_WIDTH)
    s = re.sub(r"\s+", " ", s).strip()
    return unicodedata.normalize("NFC", s)


def _duplicate_groups(rows: Iterable[Any]) -> list[tuple[str, str, str, list[tuple[str, ...]]]]:
    """(id, discipline_id, discipline_code, name, uom) satirlarindan normalize ciftleri.

    Donus: [(disiplin_kodu, name_key, uom_key, [(id, ad, birim), …])], adet azalan sirada.
    Canli sayim betigi de BU fonksiyonu kullanir (tek tanim).
    """
    groups: dict[tuple[str, str, str], list[tuple[str, ...]]] = {}
    codes: dict[str, str] = {}
    for row_id, discipline_id, code, name, uom in rows:
        key = (str(discipline_id), _normalize(name), _normalize(uom))
        codes[str(discipline_id)] = code
        groups.setdefault(key, []).append((str(row_id), name, uom))
    return sorted(
        (
            (codes[disc], name_key, uom_key, sorted(members, key=lambda m: (m[1], m[0])))
            for (disc, name_key, uom_key), members in groups.items()
            if len(members) > 1
        ),
        key=lambda g: (-len(g[3]), g[0], g[1], g[2]),
    )


def _duplicate_message(groups: list[tuple[str, str, str, list[tuple[str, ...]]]]) -> str:
    lines = [
        f"KATALOG-UQ: ev_catalog_items'ta {len(groups)} normalize cift grubu var; "
        f"{NEW_UQ} KURULAMAZ. Hicbir sey degismedi. Her gruptan birini PATCH ile yeniden "
        "adlandirip yeniden dagitin (bkz. katalog-tekillik-grupla.py):"
    ]
    for code, name_key, uom_key, members in groups:
        lines.append(f"  [{code}] ({name_key!r}, {uom_key!r}) x{len(members)}")
        lines.extend(f"      {row_id} | {name!r} | {uom!r}" for row_id, name, uom in members)
    return "\n".join(lines)


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text(f"LOCK TABLE {TABLE} IN SHARE ROW EXCLUSIVE MODE"))
    rows = bind.execute(
        sa.text(
            "SELECT c.id, c.discipline_id, d.code, c.name, c.uom "
            f"FROM {TABLE} c JOIN ev_disciplines d ON d.id = c.discipline_id"
        )
    ).all()
    groups = _duplicate_groups(rows)
    if groups:
        raise RuntimeError(_duplicate_message(groups))

    op.add_column(TABLE, sa.Column("name_key", sa.String(length=200), nullable=True))
    op.add_column(TABLE, sa.Column("uom_key", sa.String(length=50), nullable=True))
    if rows:
        bind.execute(
            sa.text(f"UPDATE {TABLE} SET name_key = :nk, uom_key = :uk WHERE id = :id"),
            [{"id": r.id, "nk": _normalize(r.name), "uk": _normalize(r.uom)} for r in rows],
        )
    op.alter_column(TABLE, "name_key", nullable=False)
    op.alter_column(TABLE, "uom_key", nullable=False)
    op.drop_constraint(OLD_UQ, TABLE, type_="unique")
    op.create_unique_constraint(NEW_UQ, TABLE, ["discipline_id", "name_key", "uom_key"])


def downgrade() -> None:
    op.drop_constraint(NEW_UQ, TABLE, type_="unique")
    op.drop_column(TABLE, "uom_key")
    op.drop_column(TABLE, "name_key")
    op.create_unique_constraint(OLD_UQ, TABLE, ["discipline_id", "name", "uom"])
