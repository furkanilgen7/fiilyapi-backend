"""Puantaj korkulukları ve Türkçe hata metinleri (puantaj spec §2, §3, §7).

`site_diary/guards.py` deseninin aynısı: hata SINIFLARI `app/core/errors.py`de,
METİNLER burada TEK kopya sabit olarak durur. `SITE_MISSING` yeniden yazılmaz,
`sites` modülünden ALINIR — görünmeyen şantiye ile var olmayan şantiye AYNI
cümleyi görmelidir (WORKFLOW §4).

## Kararlar ve gerekçeleri

**Saat XOR kod kuralı BURADA DEĞİLDİR** (PUAN-SAAT): metni `schemas.
TimesheetCellInput._hours_xor_code` üretir, çünkü kural TEK hücrenin ALAN
doğrulamasıdır ve Pydantic onu alan yolu (`cells.3.hours`) ile birlikte bildirir.
Asıl bekçi DB'dedir (`ck_timesheet_entries_hours_xor_code`) — şema kapısı onun
İKİZİDİR, yerine geçmez.

**Hafta dışı tarih 422'dir, sessizce yazılmaz.** `PUT` gövdesi **hafta**+şantiye
kapsamının TAM kümesidir; kapsamın dışına düşen bir hücre bir sonraki haftanın
kaydetmesinde kimsenin fark etmeyeceği şekilde SİLİNİRDİ.
"""

import uuid
from datetime import date

from app.modules.sites.guards import SECTION_MISSING, SITE_MISSING

__all__ = [
    "DATE_OUT_OF_WEEK",
    "WEEK_MISSING",
    "DUPLICATE_CELL",
    "PERSONNEL_UNKNOWN",
    "SECTION_MISMATCH",
    "SECTION_MISSING",
    "SITE_MISSING",
    "person_day_conflict",
]

# 422 — bölüm sahipliği. `site_diary.guards.SECTION_MISMATCH` ile AYNI cümle:
# aynı kural iki modülde iki farklı metinle konuşmamalı.
SECTION_MISMATCH = "Seçilen bölüm bu şantiyeye ait değil"

# 422 — gövdedeki personel kartotekste yok. Var olmayan kimlik ile silinmiş kayıt
# AYNI cümleyi alır (kimlik varlığı sızdırılmaz).
PERSONNEL_UNKNOWN = "Seçilen personel bulunamadı"

# 422 — hafta dışı hücre. Şablonun İLK parçası sabit metindir (test bu önekle eşleşir).
DATE_OUT_OF_WEEK = (
    "Puantaj hücresi hafta dışında: {work_date}. Kaydedilen hafta "
    "{iso_year}-W{iso_week:02d} ({start} – {end}); başka bir haftanın hücresi bu "
    "istekle gönderilemez."
)

# 422 — takvimde OLMAYAN ISO haftası (53 haftası bulunmayan bir yılın 53'ü).
WEEK_MISSING = "{iso_year} ISO yılında {iso_week}. hafta yoktur; hafta numarasını düzeltin."


# 409 — gövde içi çift. DB'ye hiç gitmeden yakalanır (`site_diary.lines` deseni).
DUPLICATE_CELL = "Aynı personel ve gün için gövdede birden fazla hücre gönderildi"


def person_day_conflict(full_name: str, work_date: date) -> str:
    """409 — UQ (personnel_id, work_date) ihlali.

    Genel `IntegrityError` handler'ı da 409 verir ama gövdesi "Veri bütünlüğü
    hatası"dır; kullanıcı hangi satırı düzelteceğini ÖĞRENEMEZ. Bu yüzden servis
    açık bir SELECT ile çakışmayı önce bulur ve adı/günü söyler. Handler yarış
    durumu emniyet ağı olarak KALIR.
    """
    return (
        f"{full_name} adlı personelin {work_date.isoformat()} günü başka bir şantiyede "
        "kayıtlı; bir kişi aynı günde tek şantiyede puantaj alabilir."
    )


def format_out_of_week(
    work_date: date, iso_year: int, iso_week: int, start: date, end: date
) -> str:
    return DATE_OUT_OF_WEEK.format(
        work_date=work_date.isoformat(),
        iso_year=iso_year,
        iso_week=iso_week,
        start=start.isoformat(),
        end=end.isoformat(),
    )


def format_week_missing(iso_year: int, iso_week: int) -> str:
    return WEEK_MISSING.format(iso_year=iso_year, iso_week=iso_week)


def cell_key(personnel_id: uuid.UUID, work_date: date) -> tuple[uuid.UUID, date]:
    """Hücrenin kimliği — UQ ile BİREBİR aynı ikili.

    Tek yerde tanımlıdır: gövde-içi çift kontrolü, mevcut kayıtla eşleme ve
    çakışma sorgusu AYNI anahtarı kullanmazsa üçü farklı şeyi "aynı hücre" sanar.
    """
    return (personnel_id, work_date)
