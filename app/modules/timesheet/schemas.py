"""Puantaj matris şemaları — puantaj spec §2, §3 · mockup ŞP + E5.

Alanların TAMAMI mockup'tan gelir ve satır numarasıyla gerekçelidir (WORKFLOW §3):

| Alan | Kaynak |
|---|---|
| `full_name` / `trade` | ŞP 149 (ad + meslek alt satırı) · E5 92-93 (ayrı sütun) |
| `source` | ŞP 150/170 "Şirket" / "Taşeron" rozeti |
| `subcontractor_name` | ŞP 169 "Demir Ustası — **Akın İnşaat**" |
| `cells[].code` | ŞP 107-111 renk açıklaması (Ç/İ/T/FM/G) |
| `cells[].overtime_hours` | ŞP 119 "128 saat" — onaylı sapma (spec §7 S2) |
| `man_days` | ŞP 166/186/206/226 "Toplam" sütunu |
| `day_totals[].worked_count` | ŞP 232-246 · E5 198-211 "Günlük Toplam" |
| `day_totals[].has_overtime` | ŞP 237 "4+" |
| `day_totals[].temporary_duty_count` | ŞP 245 "3G" |
| `worker_count` | ŞP 118 "48 işçi" |
| `total_man_days` | ŞP 119 "864 adam/gün" + ŞP 248 "86" |
| `total_overtime_hours` | ŞP 119 "128 saat fazla mesai" |
| `section_name` | ŞP 117 "Kat 6–10 Kaba İnşaat" |

**Toplam kolonu AÇILMAZ** (spec §2): buradaki her toplam TÜREVDİR, her istekte
hücrelerden hesaplanır.

**Onay/durum alanı YOKTUR** (spec §7 S3): mockup'ta yalnız "Kaydet" vardır
(ŞP 101); `status`/`submitted_at` benzeri bir alan bu şemalara EKLENMEZ.
"""

import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.site_diary.models import WorkerSource
from app.modules.timesheet.models import TimesheetCode


class TimesheetCell(BaseModel):
    """Tek gün hücresi. Girilmemiş gün hücre ÜRETMEZ — matris SEYREKTİR.

    Ayın her günü için boş hücre üretmek 31×48 = 1488 nesnelik bir gövdeyi
    çoğunlukla `null` ile doldururdu; ekran gün iskeletini `day_totals`ten alır.
    """

    work_date: date
    code: TimesheetCode
    overtime_hours: Decimal | None
    section_id: uuid.UUID | None


class TimesheetMatrixRow(BaseModel):
    """Bir personelin ay satırı (ŞP 148-167)."""

    personnel_id: uuid.UUID
    full_name: str
    trade: str | None
    source: WorkerSource
    # Meslek ile firma AYRI alanlardır: ŞP 169'daki "Demir Ustası — Akın İnşaat"
    # birleştirmesi bir SUNUM kararıdır, backend iki bilgiyi yapıştırmaz.
    subcontractor_name: str | None
    man_days: int
    cells: list[TimesheetCell]


class TimesheetDayTotal(BaseModel):
    """Bir gün sütununun ayak satırı (ŞP 230-247).

    `worked_count` FM'li günü SAYAR (E5 203: FM'li 6. sütun "4"tür), geçici
    görevi SAYMAZ (ŞP 245: dört kişinin kayıtlı olduğu sütun "3G"dir). `G` bu
    yüzden ayrı bir sayaçtır, `+` ise yalnız bir işarettir — sayıyı değiştirmez.
    """

    work_date: date
    worked_count: int
    has_overtime: bool
    temporary_duty_count: int


class TimesheetMatrix(BaseModel):
    """ŞP/E5 puantaj ekranının tamamı: başlık şeridi + satırlar + ayak satırı."""

    site_id: uuid.UUID
    site_name: str
    project_id: uuid.UUID
    project_name: str
    year: int
    month: int
    # Bölüm süzgeci (ŞP 99). Seçilmemişse şerit bir bölüm adı İDDİA ETMEZ.
    section_id: uuid.UUID | None
    section_name: str | None
    # ŞP 116-119 başlık şeridi. Ayrı bir `header` nesnesi AÇILMAZ: aynı sayılar
    # ekranın iki yerinde iki kaynaktan gelirse zamanla ayrışır.
    worker_count: int
    total_man_days: int
    total_overtime_hours: Decimal
    rows: list[TimesheetMatrixRow]
    day_totals: list[TimesheetDayTotal]


class TimesheetCellInput(BaseModel):
    """`PUT` gövdesinin tek hücresi.

    `project_id` gövdede YOKTUR: kapsam alanı şantiyeden KOPYALANIR, istemciden
    alınsaydı görünür bir şantiyeye görünmez bir projenin hücresi yazılabilirdi.
    """

    model_config = ConfigDict(extra="forbid")

    personnel_id: uuid.UUID
    work_date: date
    code: TimesheetCode
    # Aralık DB CHECK'i (`0 < saat <= 24`) ile BİREBİR aynı; kodla ilişkisi
    # `guards.OVERTIME_HOURS_ONLY_FOR_OVERTIME` korkuluğundadır (Pydantic tek
    # alana bakar, kural iki alanı birlikte ilgilendirir).
    overtime_hours: Decimal | None = Field(default=None, gt=0, le=24, decimal_places=1)
    section_id: uuid.UUID | None = None


class TimesheetSave(BaseModel):
    """⚠️ **DEĞİŞTİRME semantiği** (spec §7 S4): gövde dönem+şantiye kapsamının

    TAM kümesidir; gönderilmeyen hücre SİLİNİR. Mockup'ta tek "Kaydet" düğmesi
    vardır (ŞP 101) — ekran matrisi bütün olarak kaydeder.
    """

    model_config = ConfigDict(extra="forbid")

    cells: list[TimesheetCellInput] = Field(default_factory=list)
