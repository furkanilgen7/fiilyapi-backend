"""Şantiye günlüğü korkulukları ve Türkçe hata metinleri (spec §2, §3).

Metinler TEK yerde durur; router'a ya da servise gömülü string YAZILMAZ
(`subcontractor_progress_payments/guards.py` deseninin aynısı).

`sites` modülünün "bulunamadı" cümleleri KOPYALANMAZ, İMPORT edilir: günlük ucu
görünmeyen bir şantiye için `sites` ucundan FARKLI bir cümle dönerse, elinde bir
UUID olan kullanıcı iki uç arasındaki farktan kaydın var olduğunu çıkarabilir.
"""

from app.modules.sites.guards import SITE_MISSING

__all__ = [
    "DELETE_NOT_ALLOWED",
    "ENTRY_DATE_TAKEN",
    "ENTRY_MISSING",
    "ENTRY_NOT_DELETABLE",
    "ENTRY_NOT_EDITABLE",
    "SECTION_MISMATCH",
    "SITE_MISSING",
    "YEAR_REQUIRED_FOR_MONTH",
]

# 404 — kayıt yok VEYA kapsam dışında. İki hâl AYIRT EDİLEMEZ (spec §3 IDOR
# kuralı): görünmeyen projedeki gerçek kayıt için 403 dönmek, kaydın varlığını
# sızdırmanın en kısa yoludur.
ENTRY_MISSING = "Günlük kayıt bulunamadı"

# 409 (`DuplicateError`) — UQ (site_id, entry_date) ihlali. Servis `IntegrityError`a
# DÜŞMEDEN ÖNCE açık bir SELECT ile bunu fırlatır; kullanıcı "Veri bütünlüğü
# hatası" gibi anlamsız bir cümle değil NE YAPACAĞINI görür. Genel `IntegrityError`
# handler'ı (409) yarış durumu emniyet ağı olarak KALIR.
ENTRY_DATE_TAKEN = "Bu şantiyede bu güne ait günlük kayıt zaten var"

# 409 (`ConflictError`) — gönderilmiş kayda YAZMA yasağı. Durumu geri almanın tek
# yolu `reopen` ucudur (T4); PATCH sessizce başarısız olmaz, açıkça çakışır.
ENTRY_NOT_EDITABLE = "Gönderilmiş günlük kayıt düzenlenemez"

# 409 (`ConflictError`) — silme kuralının BİRİNCİ katmanı: gönderilmiş kayıt
# ADMİN DAHİL kimseye silinmez. `can_delete` (ikinci katman) admin'e koşulsuz
# izin verdiği için bu kontrol ondan ÖNCE koşmak zorundadır.
ENTRY_NOT_DELETABLE = "Gönderilmiş günlük kayıt silinemez"

# 403 (`DeleteNotAllowedError`) — silme kuralının İKİNCİ katmanı (`app/core/access.py`):
# admin olmayan aktör yalnız KENDİ açtığı TASLAĞI siler.
DELETE_NOT_ALLOWED = "Bu kaydı silme yetkiniz yok"

# 422 — bölüm bilgi alanıdır ama SAHİPSİZ olamaz: günlüğün şantiyesine ait
# olmalıdır. Var OLMAYAN bölüm de AYNI 422'yi alır — bölüm bir alan DEĞERİDİR,
# ayrı bir kaynak değil (`subcontractor_progress_payments.guards.SECTION_MISMATCH`
# gerekçesinin aynısı).
SECTION_MISMATCH = "Seçilen bölüm bu şantiyeye ait değil"

# 422 — `month` tek başına anlamsızdır ("her yılın temmuzu" bir dönem değildir).
# Sessizce yok saymak, kullanıcının filtrelediğini sandığı bir listeyi filtresiz
# göstermek olurdu.
YEAR_REQUIRED_FOR_MONTH = "Ay filtresi için yıl da belirtilmelidir"
