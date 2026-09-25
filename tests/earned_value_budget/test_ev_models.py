"""EV modelleri — `models.py`nin iki iddiasının bekçisi (EV-BORC-5; atıf eskiden var olmayan
bir dosyaya gidiyordu).

1. `DISTRIBUTION_VALUES` (DB enum'u `ev_distribution`) motorun `Distribution` enum'uyla AYNI
   küme ve sıra — model motor sürümüne kilitlenmesin diye bağımsız tanımlanır, eşitliği burada.
2. "Σ eğri = bütçe" VERİTABANINDAN okununca da `==`: eğri kolonu Numeric(24,8), yayma kuantumu
   1e-6 + Hamilton artığı kayıpsız sığar. Kurgu (`baseline`): Bölümsüz yaprak 20 a-s, 22 iş
   gününe yayılır (20/22 sonlanmaz) → artık yolu gerçekten çalışır. Toplam SQL'de alınır
   (ORM önbelleği değil, sütunun kendisi).
"""

from __future__ import annotations

from sqlalchemy import func, select

from app.modules.earned_value.engine import Distribution
from app.modules.earned_value.models import (
    DISTRIBUTION_VALUES,
    EvBaselineCurve,
    EvBaselineLeaf,
)


def test_distribution_values_match_engine_enum() -> None:
    assert DISTRIBUTION_VALUES == tuple(d.value for d in Distribution)


async def test_frozen_curve_sums_to_leaf_budget_exactly_in_db(seeded_db, baseline) -> None:
    rows = (
        await seeded_db.execute(
            select(EvBaselineLeaf.id, EvBaselineLeaf.budget_mhr, func.sum(EvBaselineCurve.mhr))
            .join(EvBaselineCurve, EvBaselineCurve.leaf_id == EvBaselineLeaf.id)
            .group_by(EvBaselineLeaf.id, EvBaselineLeaf.budget_mhr)
        )
    ).all()
    assert len(rows) >= 4, "kurgu bozuk: yapraklar eğri taşımıyor"
    mismatches = [(leaf, budget, total) for leaf, budget, total in rows if total != budget]
    assert mismatches == []
    days = await seeded_db.scalar(select(func.count()).select_from(EvBaselineCurve))
    assert days > len(rows)  # yaprak başına çok gün: gerçekten yayıldı
