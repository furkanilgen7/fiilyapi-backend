"""Denetim gunlugu detay metinleri.

Kullaniciya gorunen tum detay metinleri Turkce ve TEK yerde tutulur; router'lara
string gomulmez. Metinlere parola, token veya baska gizli deger YAZILMAZ.
"""

LOGIN_DETAIL = "Sisteme giriş yapıldı"


def user_created(name: str, role_name: str) -> str:
    return f"Kullanıcı oluşturuldu: {name} · {role_name}"


def user_updated(name: str) -> str:
    return f"Kullanıcı güncellendi: {name}"


def password_reset(name: str) -> str:
    """Parolanin kendisi ASLA metne girmez — yalnizca islemin yapildigi bildirilir."""
    return f"Kullanıcı parolası sıfırlandı: {name}"


def user_deleted(name: str) -> str:
    return f"Kullanıcı silindi: {name}"


def project_access_updated(name: str) -> str:
    return f"Proje erişimi güncellendi: {name}"
