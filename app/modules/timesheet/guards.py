"""Puantaj korkulukları ve Türkçe hata metinleri (puantaj spec §2, §3, §7).

`site_diary/guards.py` deseninin aynısı: hata SINIFLARI `app/core/errors.py`de,
METİNLER burada TEK kopya sabit olarak durur. `SITE_MISSING` yeniden yazılmaz,
`sites` modülünden ALINIR — görünmeyen şantiye ile var olmayan şantiye AYNI
cümleyi görmelidir (WORKFLOW §4).

## Kararlar ve gerekçeleri

**`overtime_hours` yalnız `overtime` kodunda anlamlıdır.** DB CHECK'i
(`ck_timesheet_entries_overtime_hours_range`) yalnız DEĞER aralığını zorlar,
kodla İLİŞKİSİNİ zorlamaz. Servis korkuluğu bu boşluğu kapatır: ŞP 119'un
"128 saat fazla mesai" toplamı yalnız FM hücrelerinden gelir (spec §7 S2), bu
yüzden `worked` bir hücreye iliştirilen saat ya toplamı YALAN söyletirdi ya da
sessizce yok sayılırdı. İkisi de kabul edilemez → 422.

**Dönem dışı tarih 422'dir, sessizce yazılmaz.** `PUT` gövdesi dönem+şantiye
kapsamının TAM kümesidir (spec §7 S4); kapsamın dışına düşen bir hücre bir
sonraki ayın kaydetmesinde kimsenin fark etmeyeceği şekilde SİLİNİRDİ.
"""

import uuid
from datetime import date

from app.modules.sites.guards import SECTION_MISSING, SITE_MISSING

__all__ = [
    "DATE_OUT_OF_PERIOD",
    "DUPLICATE_CELL",
    "OVERTIME_HOURS_ONLY_FOR_OVERTIME",
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

# 422 — kod/saat uyuşmazlığı (yukarıdaki gerekçe).
OVERTIME_HOURS_ONLY_FOR_OVERTIME = (
    "Fazla mesai saati yalnız fazla mesai (FM) hücresine girilebilir; "
    "hücrenin kodunu değiştirin ya da saat alanını boşaltın."
)

# 422 — dönem dışı hücre. Şablonun İLK parçası sabit metindir (test bu önekle eşleşir).
DATE_OUT_OF_PERIOD = (
    "Puantaj hücresi dönem dışında: {work_date}. Kaydedilen dönem {year}/{month:02d}; "
    "başka bir ayın hücresi bu istekle gönderilemez."
)

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


def format_out_of_period(work_date: date, year: int, month: int) -> str:
    return DATE_OUT_OF_PERIOD.format(work_date=work_date.isoformat(), year=year, month=month)


def cell_key(personnel_id: uuid.UUID, work_date: date) -> tuple[uuid.UUID, date]:
    """Hücrenin kimliği — UQ ile BİREBİR aynı ikili.

    Tek yerde tanımlıdır: gövde-içi çift kontrolü, mevcut kayıtla eşleme ve
    çakışma sorgusu AYNI anahtarı kullanmazsa üçü farklı şeyi "aynı hücre" sanar.
    """
    return (personnel_id, work_date)
