"""Onay motorunun korkuluk METINLERI — TEK KOPYA.

Testler durum kodunu bu sabitlerle birlikte iddia eder: yalniz "403 geldi"
demek, yanlis sebeple 403 donen bir uygulamada da YESIL kalirdi (bu turda
olculen sahte-yesil hâllerinden biri).

Mesajlar kullaniciya gorunur ve Turkcedir; hicbiri TUTAR, kimlik ya da baska
gizli deger TASIMAZ.
"""

__all__ = [
    "APPROVAL_ROLE_MISSING",
    "CHAIN_ALREADY_EXISTS",
    "CHAIN_COMPLETED",
    "NO_OPEN_CHAIN",
    "OWN_DOCUMENT",
    "REJECT_REASON_REQUIRED",
    "REJECT_REASON_TOO_LONG",
    "SEPARATION_OF_DUTIES",
    "STEP_NOT_CURRENT",
    "UNKNOWN_USER",
]

# --- 409: kaydin DURUMU uygun degil ---
CHAIN_ALREADY_EXISTS = "Bu evrak icin zaten acik bir onay zinciri var"
NO_OPEN_CHAIN = "Bu evragin acik bir onay zinciri yok"
CHAIN_COMPLETED = "Onay zinciri tamamlanmis"
STEP_NOT_CURRENT = "Bu adim siradaki onay adimi degil"

# --- 403: AKTOR uygun degil ---
APPROVAL_ROLE_MISSING = "Bu onay adimi icin gereken onay rolune sahip degilsiniz"
OWN_DOCUMENT = "Kendi olusturdugunuz evrakin onay adimini onaylayamazsiniz"
SEPARATION_OF_DUTIES = "Ayni evrakin ikinci onay adimini onaylayamazsiniz"

# --- 422: GOVDE uygun degil ---
REJECT_REASON_REQUIRED = "Ret gerekcesi zorunludur"
REJECT_REASON_TOO_LONG = "Ret gerekcesi cok uzun"

# --- 404 ---
UNKNOWN_USER = "Kullanici bulunamadi"
