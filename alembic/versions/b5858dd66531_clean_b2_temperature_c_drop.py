"""CLEAN-B2 — `site_diary_entries.temperature_c` + `ck_site_diary_entries_temperature_range` DROP

Genişlet/daralt'ın DARALT adımı. Geçmiş:
* `b5c6d7e8f9a0` (SD çekirdeği): kolon + CHECK (`-60..60`) açıldı.
* `b877270195d8` (PLN-B2): `temp_min_c`/`temp_max_c` açıldı, eski değer ikisine KOPYALANDI;
  o sürümden beri servis her yazmada `temperature_c = temp_max_c` eşitledi (tek yazar).
* CLEAN-B1 Faz 1: alan API'den kalktı, eşitleyici kaldı.
* CLEAN-B2: model ve eşitleyici kalktı; bu migration kolonu düşürür.

🔴 DAĞITIM SIRASI: bu migration, kolonu ORM'de EŞLEMEYEN kod canlıya çıktıktan SONRAKİ
sürümde uygulanmalıdır. Railway açılışta `alembic upgrade head` koşar; eski konteyner
kolonu eşliyorsa (CLEAN-B1 Faz 1 ve öncesi) DROP'tan sonra her `SiteDiaryEntry` SELECT/
INSERT'i `UndefinedColumnError` → 500 verir.

🔴 UPGRADE VERİ KAYBETTİRİR, GERİ DÖNÜŞSÜZDÜR: `temperature_c`nin `temp_max_c`den FARKLI
olduğu satır varsa (PLN-B2 dağıtım penceresinde eski konteynerin yazdığı ve sonra hiç
dokunulmamış kayıt — kod bunu dışlayamaz), o değer başka hiçbir yerde yoktur. Canlıda
DROP'tan ÖNCE salt okunur sayım koşulur (CLEAN-B2 raporu, `clean-b2-canli-sayim.sql`).

DOWNGRADE: kolonu `Numeric(4,1)` NULL olarak ve CHECK'i aynı adla/tanımla geri açar, sonra
`temperature_c = temp_max_c` ile YENİDEN TÜRETİR. Gerekçe: PLN-B2'den CLEAN-B1 Faz 1'e
kadar kodun koruduğu değişmez tam olarak budur (`temp_max_c` dışında kaynağı yoktu), yani
geri alınan kod kendi yazacağı değeri bulur. Bu bir VERİ GERİ YÜKLEMESİ DEĞİLDİR: upgrade
öncesi `temp_max_c`den farklı olan değerler geri GELMEZ.

Tek ALTER: kolon düşürme PG'de yalnız katalog değişikliğidir (tablo yeniden yazılmaz),
kısa bir ACCESS EXCLUSIVE kilit alır.

🔀 RE-PARENT (KATALOG-UQ K4 notuyla BİREBİR): bu migration ilk yazıldığında `down_revision`
`c7d1e2f3a4b5` idi (DET-1.B ile aynı dal ucu). KATALOG-UQ (`aab10fbf5471`) o uçtan ÖNCE
merge olduğu için zincir ona taşındı — iki migration AYNI ANDA merge edilmiyor, `alembic
heads` tek kalsın diye sonra merge olan kendi `down_revision`ını öbürünün `revision`ına
re-parent ediyor.

Revision ID: b5858dd66531
Revises: aab10fbf5471
Create Date: 2026-09-25

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b5858dd66531"
down_revision: str | Sequence[str] | None = "aab10fbf5471"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "site_diary_entries"
COLUMN = "temperature_c"
CHECK = "ck_site_diary_entries_temperature_range"
CHECK_SQL = "temperature_c IS NULL OR temperature_c BETWEEN -60 AND 60"


def upgrade() -> None:
    op.drop_constraint(CHECK, TABLE, type_="check")
    op.drop_column(TABLE, COLUMN)


def downgrade() -> None:
    op.add_column(TABLE, sa.Column(COLUMN, sa.Numeric(precision=4, scale=1), nullable=True))
    op.execute(
        "UPDATE site_diary_entries SET temperature_c = temp_max_c WHERE temp_max_c IS NOT NULL"
    )
    op.create_check_constraint(CHECK, TABLE, CHECK_SQL)
