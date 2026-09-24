"""Performans için sentetik proje (spec §2.6 / §7: 1.500 düğüm × 1.000 gün < 2 sn).

Kötü durum seçildi: HER yaprak HER iş gününe miktar alır (~1 M giriş), HER iş tipi her
iş günü bir prorata kodu, HER disiplin bir direct kodu yazar; rapor günü son gündür
(her hareket t <= d). Ağaç: 5 disiplin × 5 alt grup × 10 iş tipi + 1.220 yaprak = 1.500.

`leaf_curves=True` (K9 varyantı): disiplin eğrisi yerine HER yaprağa rastgele bir
başlangıçtan ~60 iş günlük yaprak eğrisi verilir (1.220 × 60 ≈ 73 bin nokta).
"""

from __future__ import annotations

import random
from datetime import date, timedelta
from decimal import Decimal

from app.modules.earned_value.engine import (
    AllocationRule,
    CalendarSettings,
    ContractorType,
    EngineInput,
    HoursEntry,
    Node,
    PlannedMhr,
    QtyEntry,
)

START = date(2024, 1, 1)
SUNDAY = 6
LEAF_CURVE_WORKDAYS = 60


def build(
    disciplines: int = 5,
    subgroups: int = 5,
    job_types: int = 10,
    leaves_total: int = 1220,
    days: int = 1000,
    seed: int = 7,
    leaf_curves: bool = False,
) -> tuple[EngineInput, date]:
    rng = random.Random(seed)
    qty_pool = [Decimal(k) / 4 for k in range(1, 80)]
    hours_pool = [Decimal(k) / 2 for k in range(1, 60)]
    nodes: list[Node] = []
    leaves: list[str] = []
    types_: list[str] = []
    n_types = disciplines * subgroups * job_types
    base, extra = divmod(leaves_total, n_types)
    for d in range(disciplines):
        disc = f"D{d}"
        nodes.append(Node(disc, None, curve_discipline=disc))
        for s in range(subgroups):
            sub = f"{disc}.S{s}"
            nodes.append(Node(sub, disc))
            for t in range(job_types):
                jt = f"{sub}.T{t}"
                nodes.append(Node(jt, sub))
                types_.append(jt)
                count = base + (1 if len(types_) <= extra else 0)
                for leaf_no in range(count):
                    leaf = f"{jt}.L{leaf_no}"
                    nodes.append(
                        Node(
                            leaf,
                            jt,
                            uom="m3",
                            planned_qty=Decimal(rng.randint(500, 5000)),
                            unit_mhr=Decimal(rng.randint(10, 300)) / 100,
                            contractor_type=rng.choice(tuple(ContractorType)),
                            is_direct=rng.random() > 0.02,
                        )
                    )
                    leaves.append(leaf)
    workdays = [
        START + timedelta(days=i)
        for i in range(days)
        if (START + timedelta(days=i)).weekday() != SUNDAY
    ]
    qty = [QtyEntry(leaf, day, rng.choice(qty_pool)) for day in workdays for leaf in leaves]
    prorata = AllocationRule.PRORATA_BY_DAILY_QTY
    hours = [
        HoursEntry(jt, day, rng.choice(hours_pool), prorata) for day in workdays for jt in types_
    ]
    hours += [
        HoursEntry(f"D{d}", day, rng.choice(hours_pool), AllocationRule.DIRECT)
        for day in workdays
        for d in range(disciplines)
    ]
    planned = [
        PlannedMhr(f"D{d}", day, rng.choice(hours_pool))
        for day in workdays
        for d in range(disciplines)
    ]
    if leaf_curves:
        # varsayılan yoldaki rastgele dizi DEĞİŞMESİN diye ek çekilişler en sonda
        span = min(LEAF_CURVE_WORKDAYS, len(workdays))
        planned = []
        for leaf in leaves:
            first = rng.randrange(len(workdays) - span + 1)
            planned += [
                PlannedMhr.for_leaf(leaf, day, rng.choice(hours_pool))
                for day in workdays[first : first + span]
            ]
    end = START + timedelta(days=days - 1)
    inp = EngineInput(
        calendar=CalendarSettings(START, end),
        nodes=tuple(nodes),
        qty_entries=tuple(qty),
        hours_entries=tuple(hours),
        planned_mhr=tuple(planned),
    )
    return inp, end
