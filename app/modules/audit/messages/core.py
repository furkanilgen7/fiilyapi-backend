"""Denetim metinleri — platform cekirdegi: giris, sirket, kullanici, rol, proje.

Tek basina bir alt modulu hak etmeyecek kadar kucuk olan cekirdek aileler
burada toplandi (`auth` 1 · `company` 3 · `projects` 6 · `users` 11 · `roles`
21 satir).
"""

from app.core.access import AccessLevel

LOGIN_DETAIL = "Sisteme giriş yapıldı"


COMPANY_UPDATED = "Şirket bilgileri güncellendi"


COMPANY_LOGO_UPDATED = "Şirket logosu güncellendi"


COMPANY_LOGO_REMOVED = "Şirket logosu kaldırıldı"


# Erisim seviyelerinin insan-okur karsiliklari — izin matrisi ekranindaki etiketlerle
# ayni dil (frontend permission-presets.ts). Denetim gunlugu enum degeri gostermez.
ACCESS_LEVEL_LABELS: dict[AccessLevel, str] = {
    AccessLevel.none: "Yok",
    AccessLevel.view: "Görüntüle",
    AccessLevel.draft: "Taslak",
    AccessLevel.request: "Talep",
    AccessLevel.approve: "Onay",
    AccessLevel.full: "Tam",
    AccessLevel.admin: "Süper",
}


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


def role_created(name: str) -> str:
    return f"Özel rol oluşturuldu: {name}"


def role_renamed(old_name: str, new_name: str) -> str:
    """Eski ad cagri noktasinda islemden ONCE okunmali; sonra okunursa yeni ad iki kez cikar."""
    return f"Rol yeniden adlandırıldı: {old_name} → {new_name}"


def role_deleted(name: str) -> str:
    return f"Rol silindi: {name}"


def permission_changed(role_name: str, module_name: str, level: AccessLevel) -> str:
    """Modul ADI kullanilir (module_key degil) — denetim gunlugu dili insan-okur."""
    return f"İzin değişti: {role_name} · {module_name} → {ACCESS_LEVEL_LABELS[level]}"


def employer_created(name: str) -> str:
    return f"Yeni işveren oluşturuldu: {name}"


def project_created(name: str) -> str:
    return f"Yeni proje oluşturuldu: {name}"


def project_updated(name: str) -> str:
    return f"Proje güncellendi: {name}"
