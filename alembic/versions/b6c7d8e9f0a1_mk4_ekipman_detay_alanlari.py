"""mk4 ekipman detay alanlari

MK-4 — Ekipman Detay ekranının (`projedesign/Makine - Ekipman Detay.dc.html`)
besleyemediği ON alan. Ölçüm: mockup 22 alan çiziyor, `EquipmentResponse` 30
alan taşıyordu ve üç kart eksikti (Teknik 5/8 · Kiralama 2/8 · Bakım 1/6).

Bu migration YALNIZ SAKLANAN alanları açar. Ekranın kalan altı sayısı
(`Sonraki Bakım Saati` · `Kalan Çalışma Saati` · `Tahmini Bakım Tarihi` ·
`%57 · 286/500 saat` çubuğu · `Kümülatif Ödenen`) KOLON DEĞİLDİR — hepsi
`maintenance.py` / `detail_service.py` içinde her okumada TÜRER. Kolonlaşsalardı
aynı sayının iki kaynağı olur ve biri güncellenmediğinde ayrışma GÖRÜNMEZ
kalırdı (P10 "tek formül" kanonu).

🔴 `hourmeter_hours` bir İSTİSNADIR ve türev DEĞİLDİR: makinenin üzerindeki
fiziksel sayacın okumasıdır. `SUM(equipment_work_logs.hours)` ile aynı sayı
değildir (kayıtlar ERP dönemini kapsar, sayaç makinenin ömrünü) — türetilseydi
sunucu hiç yapmadığı bir ölçümü uydururdu.

🔴 `rental_min_monthly_hours` `monthly_capacity_hours` DEĞİLDİR: ikincisi bir
PAYDAdır (kullanım yüzdesi + `monthly` bedelin saatlik karşılığı), birincisi
kira sözleşmesinin taahhüt ettiği asgari saattir. Kolon yorumları ayrımı taşır.

TÜM kolonlar `nullable=True`: `equipment` tablosunda mevcut satırlar vardır ve
hiçbirinin bu alanları bilinmiyor. Uydurma varsayılan (0 kW, 0 saat) bir
bilinmeyeni bilinir gibi gösterir ve `%57` çubuğunu YANLIŞ hesaplatırdı (K16
fail-closed).

Yeni enum YOKTUR → `DROP TYPE` işi de yoktur. İzin modülü AÇILMAZ (`equipment`
MK-1'de açıldı). Mevcut satır DOLDURULMAZ (MK-3'ün K4 doldurmasının aksine):
orada bilgi ekipman kartında DURUYORDU, burada hiçbir yerde yok.

Elle yazılmıştır (autogenerate DEĞİL) — repo deseni.

Revision ID: b6c7d8e9f0a1
Revises: a5b6c7d8e9f0
Create Date: 2026-08-25

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b6c7d8e9f0a1"
down_revision: str | Sequence[str] | None = "a5b6c7d8e9f0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "equipment"

#: (ad, tip) — sıra modeldeki sırayla BİREBİRDİR ki iki dosya yan yana okunsun.
COLUMNS: tuple[tuple[str, sa.types.TypeEngine[object]], ...] = (
    ("engine_power_kw", sa.Numeric(10, 2)),
    ("capacity_description", sa.String(200)),
    ("hourmeter_hours", sa.Numeric(10, 2)),
    ("rental_contract_no", sa.String(100)),
    ("rental_start_date", sa.Date()),
    ("rental_end_date", sa.Date()),
    ("rental_min_monthly_hours", sa.Integer()),
    ("rental_payment_terms", sa.String(200)),
    ("last_service_date", sa.Date()),
    ("last_service_hourmeter", sa.Numeric(10, 2)),
)

#: (ad, SQL) — hepsi `X IS NULL OR …` biçimindedir: "bilinmiyor" yazılabilir bir
#: durumdur, kısıt yalnız DOLU değerin anlamlılığını zorlar.
CHECKS: tuple[tuple[str, str], ...] = (
    ("ck_equipment_engine_power_positive", "engine_power_kw IS NULL OR engine_power_kw > 0"),
    ("ck_equipment_hourmeter_non_negative", "hourmeter_hours IS NULL OR hourmeter_hours >= 0"),
    (
        "ck_equipment_last_service_hourmeter_non_negative",
        "last_service_hourmeter IS NULL OR last_service_hourmeter >= 0",
    ),
    (
        "ck_equipment_rental_min_monthly_hours_non_negative",
        "rental_min_monthly_hours IS NULL OR rental_min_monthly_hours >= 0",
    ),
    (
        "ck_equipment_rental_period_order",
        "rental_start_date IS NULL OR rental_end_date IS NULL "
        "OR rental_end_date >= rental_start_date",
    ),
)


def upgrade() -> None:
    """Upgrade schema."""
    for name, column_type in COLUMNS:
        op.add_column(TABLE, sa.Column(name, column_type, nullable=True))
    # Kolonlar YENİ olduğu için tablodaki hiçbir satır kısıtı ihlal EDEMEZ
    # (hepsi NULL) → `NOT VALID` + sayma desenine gerek yoktur; kısıt doğrudan
    # doğrulanmış olarak eklenir.
    for name, sqltext in CHECKS:
        op.create_check_constraint(name, TABLE, sqltext)


def downgrade() -> None:
    """Downgrade schema."""
    for name, _ in reversed(CHECKS):
        op.drop_constraint(name, TABLE, type_="check")
    for name, _ in reversed(COLUMNS):
        op.drop_column(TABLE, name)
