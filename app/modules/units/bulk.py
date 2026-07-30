"""Toplu unite uretiminin SAF cekirdegi (spec §6.3).

Servisten AYRI tutulur ki numaralandirma DB'siz, HTTP'siz test edilebilsin:
"24 daire hangi numaralari alir" sorusu bir veritabanina ihtiyac duymaz ve
oraya karisirsa yalnizca entegrasyon testiyle dogrulanabilir hâle gelir.

Burada DOGRULAMA YOKTUR: kat araligi (`end_floor >= start_floor`) ve uretim
siniri (`_MAX_BULK_UNITS`) `UnitBulkCreate`'in `model_validator`'undadir (B2,
spec §6.3) — ayni kurali iki yerde tutmak zamanla ayrisir.
"""

from app.modules.units.schemas import UnitBulkCreate, UnitNumberingPattern

# `floor_based` deseninde kat icindeki sira iki haneye tamamlanir (spec §6.3):
# 1. kat 1. daire "101"dir, "11" degil — aksi hâlde 1. kat 11. daire ile
# 11. kat 1. daire ayni numarayi alirdi.
_FLOOR_SEQUENCE_WIDTH = 2


def generate_unit_numbers(data: UnitBulkCreate) -> list[str]:
    """Uretilecek `unit_no` listesini SIRAYLA dondurur (spec §6.3).

    `sequential`  → `prefix + str(start_number + i)`      (SY 76-99, 132-135)
    `floor_based` → `prefix + f"{floor}{sira:02d}"`       (101, 102, 201, 202)

    Negatif katlar (bodrum, `ge=-5`) formule HARFI HARFINE girer: kat -1 →
    "-101". Spec bodrum icin ayri bir gosterim TANIMLAMIYOR ve icat edilmez;
    farkli bir gosterim isteniyorsa `prefix` alani bunun icin vardir.
    """
    floors = range(data.start_floor, data.end_floor + 1)
    if data.numbering is UnitNumberingPattern.floor_based:
        return [
            f"{data.prefix}{floor}{sequence:0{_FLOOR_SEQUENCE_WIDTH}d}"
            for floor in floors
            for sequence in range(1, data.units_per_floor + 1)
        ]
    total = len(floors) * data.units_per_floor
    return [f"{data.prefix}{data.start_number + index}" for index in range(total)]
