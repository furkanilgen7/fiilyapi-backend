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
    "DUPLICATE_LINE",
    "INVALID_STATUS_TRANSITION",
    "DUPLICATE_WORKER_COUNT",
    "ENTRY_DATE_TAKEN",
    "ENTRY_MISSING",
    "ENTRY_NOT_DELETABLE",
    "ENTRY_NOT_EDITABLE",
    "LINE_ITEM_MISMATCH",
    "SECTION_MISMATCH",
    "SITE_MISSING",
    "TRADE_REQUIRED",
    "WORKER_COUNTS_NULL",
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

# --- T3: satır + işçi kırılımı yazma ---

# 422 — `PUT …/lines` gövdesindeki poz günlüğün ŞANTİYESİNİN BOQ'suna ait değil.
# Var OLMAYAN poz da AYNI cümleyi alır: `boq_item_id` bir alan DEĞERİDİR, ayrı bir
# kaynak değil — iki hâl ayrıştırılsaydı elinde UUID olan kullanıcı komşu
# şantiyenin pozunun varlığını 404/422 farkından çıkarabilirdi.
LINE_ITEM_MISMATCH = "Seçilen poz bu şantiyenin BOQ'suna ait değil"

# 409 (`DuplicateError`) — kısmi UQ `uq_site_diary_lines_boq_item` ihlali GÖVDE
# İÇİNDE yakalanır. `IntegrityError` emniyet ağı olarak kalır ama kullanıcının
# normalde göreceği cümle budur ("Veri bütünlüğü hatası" değil).
DUPLICATE_LINE = "Aynı poz gövdede birden fazla kez gönderildi"

# 409 (`DuplicateError`) — UQ (entry_id, trade, source) ihlali. Aynı meslek FARKLI
# kaynakla meşrudur (GK418-430 rozetleri); çakışan yalnız ÜÇLÜNÜN tamamıdır.
DUPLICATE_WORKER_COUNT = "Aynı meslek ve kaynak için birden fazla işçi satırı gönderildi"

# 422 — `trade` serbest metindir (katalog YOK, spec §2); katalogsuz bir alanın tek
# korkuluğu boşluğun reddidir. Kırpılmadan kabul edilseydi " Kalıpçı" ile "Kalıpçı"
# UQ'da AYRI iki satır olur, ekranda aynı meslek iki kez görünürdü.
TRADE_REQUIRED = "Meslek adı boş olamaz"

# 422 — `worker_counts: null`. `null` bir NİYET DEĞİLDİR: sessizce yok sayılsaydı
# "hepsini sil" demek isteyen kullanıcı sildiğini sanırdı. Temizlemenin tek yolu
# BOŞ LİSTEDİR; alanın hiç gönderilmemesi ise "dokunma" demektir.
WORKER_COUNTS_NULL = "İşçi kırılımı listesi null olamaz; temizlemek için boş liste gönderin"

# --- T4: durum akışı ---

# 409 (`ConflictError`) — geçiş tablosunda (`transitions.TRANSITIONS`) OLMAYAN
# hücre. Sessiz/idempotent geçiş YOKTUR: ikinci kez "Gönder"e basan kullanıcıya
# "gönderdim" demek ilk gönderimin damgasını sessizce üzerine yazmak olurdu,
# taslak bir kaydı "geri al"mak da hiç yapılmamış bir işi yapılmış göstermek.
# TEK cümle iki yönü de kapsar (`subcontractor_progress_payments.guards`
# deseninin aynısı): hangi geçişin neden reddedildiğini ayrıştırmak, kaydın
# durumunu bilmeyen bir istemciye durum bilgisi sızdırmaktır.
INVALID_STATUS_TRANSITION = "Bu durum geçişi yapılamaz"

# 422 — `month` tek başına anlamsızdır ("her yılın temmuzu" bir dönem değildir).
# Sessizce yok saymak, kullanıcının filtrelediğini sandığı bir listeyi filtresiz
# göstermek olurdu.
YEAR_REQUIRED_FOR_MONTH = "Ay filtresi için yıl da belirtilmelidir"
