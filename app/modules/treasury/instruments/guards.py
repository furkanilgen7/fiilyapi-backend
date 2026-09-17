"""FIN-1 — kullaniciya donuk hata metinleri, TEK yerde.

Metinler servis/uc govdelerine gomulmez: gomulseydi ayni kural iki uctan iki
farkli cumleyle bildirilir ve istemci hangisine bakacagini bilemezdi. Ayrica
denetim/regresyon testleri sabitleri ITHAL EDER — metin degisince test kirmizi
olur ve degisiklik BILINCLI olmak zorunda kalir.

🔴 **GORUNMEYEN KAYIT → 404** (repo kanonu): var olmayanla ayirt edilemez.
Govde ICI varlik referanslari (`project_id`, `bank_account_id`) da 404'tur,
403 DEGIL (ST kanonu) — 403 "bu kayit VAR ama goremezsin" bilgisini sizdirirdi.
"""

__all__ = [
    "BANK_ACCOUNT_INVALID",
    "DIRECTION_LOCKED_BY_PAYMENTS",
    "DIRECTION_MISMATCH",
    "DUE_BEFORE_ISSUE",
    "INSTRUMENT_HAS_PAYMENTS",
    "INSTRUMENT_MISSING",
    "INVALID_TRANSITION",
    "PROJECT_INVALID",
    "REQUIRED_FIELD_CLEARED",
    "TERMINAL_STATUS",
    "TERMINAL_STATUS_DELETE",
    "TERMINAL_STATUS_DIRECTION",
]

#: 404 — hem var olmayan hem GORUNMEYEN kayit. Iki hal ayni govdeyi dondurur.
INSTRUMENT_MISSING = "Çek/senet kaydı bulunamadı"

#: 404 — govde ici referanslar (ST kanonu).
PROJECT_INVALID = "Seçilen proje bulunamadı"
BANK_ACCOUNT_INVALID = "Seçilen banka hesabı bulunamadı"

#: 422 — vade kesideden once olamaz. DB CHECK'i SON savunmadir; bu mesaj
#: kullanicinin duzeltebilecegi hali uretir (CHECK ihlali ham 500 ya da ayrimsiz
#: "Veri butunlugu hatasi" verirdi).
DUE_BEFORE_ISSUE = "Vade tarihi, keşide tarihinden önce olamaz"

#: 422 — PATCH govdesinde zorunlu bir alana acikca `null` gonderilmesi.
#: Sema hepsini `| None` yazmak ZORUNDADIR (govde kismidir), bu yuzden ayrim
#: SERVISTE yapilir.
REQUIRED_FIELD_CLEARED = "Bu alan boş bırakılamaz"

#: 409 — K2 gecis tablosunda olmayan her cift.
INVALID_TRANSITION = "Bu durum geçişi geçerli değil"

#: 409 — 🔴 TERMINAL DURUMDAN CIKIS YOK. Ayri bir metindir cunku kullanicinin
#: yapabilecegi sey de ayridir: gecersiz gecis "baska bir hedef sec" demektir,
#: terminal ise "bu kayit kapandi, yeni kayit ac" demektir.
TERMINAL_STATUS = "Bu kayıt son durumundadır; durumu değiştirilemez"

#: 409 — 🔴 `direction`a aykiri gecis. Alinan cek `paid` OLAMAZ, verilen cek
#: `collected` OLAMAZ. Ayri metin: kullanici hedefi degil YONU yanlis okumustur.
DIRECTION_MISMATCH = "Bu durum, evrakın yönü (alınan/verilen) için geçerli değil"

#: 409 — silme yalniz `portfolio` iken. Tahsil edilmis/odenmis bir evrakin
#: silinmesi MALI IZI yok ederdi.
TERMINAL_STATUS_DELETE = "Yalnızca portföydeki kayıt silinebilir"

#: 409 — 🔴 terminal kayitta `direction`/`instrument_kind` DEGISTIRILEMEZ.
#: Emirde YOKTU, T4'te eklendi: PATCH yonu degistirebilseydi (alinan → verilen)
#: `collected` bir kayit `issued` olur ve K2'nin ASLA uretemeyecegi bir cift
#: PATCH uzerinden dogardi — invaryantin IKINCI yazma kapisi (BOQ-SEC-B kanonu).
TERMINAL_STATUS_DIRECTION = "Portföyden çıkmış bir kaydın türü ve yönü değiştirilemez"

#: 409 — 🔴 bagli odemesi olan evrak SILINEMEZ. FK `ON DELETE SET NULL`dur:
#: silme, bagli odemelerin bagini KOPARIR ve bagsiz odemeyi nakit sayan
#: `balance.cash_realized_condition` yuzunden banka bakiyesi tahsil edilmemis
#: tutar kadar ANINDA siser. Ayri metindir cunku kullanicinin yapabilecegi sey de
#: ayridir: terminal durum "bu kayit kapandi" demektir, bu ise "once bagli
#: odemeyi sil" demektir. `treasury.service.ACCOUNT_HAS_PAYMENTS` kardesidir.
INSTRUMENT_HAS_PAYMENTS = "Bu evrağa bağlı ödeme kayıtları var; önce onları silin"

#: 409 — 🔴 bagli odemesi olan evrakta `direction`/`instrument_kind` DEGISTIRILEMEZ.
#: Bagin yon uyumu odeme YAZILIRKEN bir kez dogrulanir
#: (`payments_service._UYUMLU_YON`, 422); PATCH onu geriye donuk gecersizlestirirdi
#: ve yeniden dogrulanmazdi. `TERMINAL_STATUS_DIRECTION`dan AYRI metindir: kayit
#: terminal DEGILDIR, kilitleyen sey durum degil BAGDIR.
DIRECTION_LOCKED_BY_PAYMENTS = "Bu evrağa bağlı ödeme kayıtları var; türü ve yönü değiştirilemez"
