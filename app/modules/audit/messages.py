"""Denetim gunlugu detay metinleri.

Kullaniciya gorunen tum detay metinleri Turkce ve TEK yerde tutulur; router'lara
string gomulmez. Metinlere parola, token veya baska gizli deger YAZILMAZ.
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


def site_created(name: str) -> str:
    return f"Yeni şantiye oluşturuldu: {name}"


def site_draft_created(name: str) -> str:
    """Taslak olusturma yayin olusturmadan AYRI metindir (spec §10).

    Denetim ekraninda "gercekten bir santiye acildi mi" sorusu metinden
    cevaplanabilmelidir; tek metin kullanmak yarim kalmis bir taslagi tamamlanmis
    bir acilis gibi gosterirdi.
    """
    return f"Yeni şantiye taslağı oluşturuldu: {name}"


def site_sections_created(site_name: str, count: int) -> str:
    """Bolumlu form icin TEK OZET satir (`units_bulk_created` deseni, spec §10).

    Bolum basina ayri satir yazilmaz: 5 bolumlu bir form 6 denetim satiri
    uretmez, 2 uretir — gunluk okunabilirligi kaydin sayisindan daha degerlidir.
    """
    return f"Şantiye bölümleri oluşturuldu: {site_name} · {count} bölüm"


def site_updated(name: str) -> str:
    return f"Şantiye güncellendi: {name}"


def site_published(name: str) -> str:
    """`is_draft: true -> false` gecisi (spec §5.3, §10) — duz guncellemeden AYRI."""
    return f"Şantiye taslaktan yayına alındı: {name}"


def site_deleted(project_name: str, name: str) -> str:
    """Metin santiye satiri SILINMEDEN ONCE kurulmalidir (spec §10).

    Sonra kurulursa `project.name` ve `site.name` guvenilir okunamaz ve satir bos
    adla yazilir — yani silinen kaydin NE OLDUGU tamamen kaybolur.
    """
    return f"Şantiye silindi: {project_name} · {name}"


def section_created(site_name: str, name: str) -> str:
    """Bolum adlari santiyeden bagimsiz tekrar edebilir ("Kat 6-10" her blokta
    olabilir); santiye adi olmadan denetim satiri anlamsizlasir."""
    return f"Yeni bölüm oluşturuldu: {site_name} · {name}"


def section_updated(site_name: str, name: str) -> str:
    return f"Bölüm güncellendi: {site_name} · {name}"


def section_deleted(site_name: str, name: str) -> str:
    """`site_deleted` ile ayni kural: metin `session.delete`ten ONCE kurulur."""
    return f"Bölüm silindi: {site_name} · {name}"


def boq_group_created(name: str) -> str:
    return f"İş kalemi grubu oluşturuldu: {name}"


def boq_group_updated(name: str) -> str:
    return f"İş kalemi grubu güncellendi: {name}"


def boq_item_created(code: str, description: str) -> str:
    return f"İş kalemi oluşturuldu: {code} — {description}"


def boq_item_updated(code: str, description: str) -> str:
    return f"İş kalemi güncellendi: {code} — {description}"


def block_created(project_name: str, block_name: str) -> str:
    return f"Yeni blok oluşturuldu: {project_name} · {block_name}"


def block_updated(project_name: str, block_name: str) -> str:
    return f"Blok güncellendi: {project_name} · {block_name}"


def block_deleted(project_name: str, block_name: str) -> str:
    return f"Blok silindi: {project_name} · {block_name}"


def unit_created(project_name: str, block_name: str, unit_no: str) -> str:
    """Unite adlari projeler arasinda tekrar eder ("A Blok · Daire 1" her projede
    olabilir); proje adi olmadan denetim satiri anlamsizlasir (`section_created`
    ile ayni gerekce)."""
    return f"Yeni ünite oluşturuldu: {project_name} · {block_name} · {unit_no}"


def unit_updated(project_name: str, block_name: str, unit_no: str) -> str:
    return f"Ünite güncellendi: {project_name} · {block_name} · {unit_no}"


def unit_deleted(project_name: str, block_name: str, unit_no: str) -> str:
    return f"Ünite silindi: {project_name} · {block_name} · {unit_no}"


def units_bulk_created(project_name: str, block_name: str, count: int) -> str:
    return f"Toplu ünite üretildi: {project_name} · {block_name} · {count} ünite"


def units_imported(project_name: str, count: int) -> str:
    return f"Üniteler Excel'den içe aktarıldı: {project_name} · {count} ünite"


def unit_allocation_updated(project_name: str, count: int) -> str:
    return f"Ünite paylaşımı güncellendi: {project_name} · {count} ünite"


def boq_item_deleted(code: str, description: str) -> str:
    return f"İş kalemi silindi: {code} — {description}"


# --- Sözleşmeler (P5, spec §8, task C13) ---
#
# C6-C12 bu aileleri `contracts/router.py`de geçici, modül-içi yardımcılar
# olarak yazdı (task brief kararı — henüz burada yoklardı). C13 onları TEK
# yere taşır; metinler değişmedi, yalnız yerleri değişti.


def employer_contract_group_created(project_name: str, name: str) -> str:
    return f"Sözleşme poz grubu oluşturuldu: {project_name} · {name}"


def employer_contract_group_updated(project_name: str, name: str) -> str:
    return f"Sözleşme poz grubu güncellendi: {project_name} · {name}"


def employer_contract_group_deleted(project_name: str, name: str) -> str:
    return f"Sözleşme poz grubu silindi: {project_name} · {name}"


def employer_contract_item_created(project_name: str, code: str, description: str) -> str:
    """`boq_item_created` deseninin aynısı: kod TEK BAŞINA anlamsız, açıklama

    olmadan denetim satırı hangi kalemin oluştuğunu göstermez (spec §8'in
    kısaltılmış imzası `(project_name, code)` yalnız özet listedir — gerçek
    metin `boq_item_*` ailesinin deseni izlenerek `description` de taşır).
    """
    return f"Sözleşme poz kalemi oluşturuldu: {project_name} · {code} — {description}"


def employer_contract_item_updated(project_name: str, code: str, description: str) -> str:
    return f"Sözleşme poz kalemi güncellendi: {project_name} · {code} — {description}"


def employer_contract_item_deleted(project_name: str, code: str, description: str) -> str:
    return f"Sözleşme poz kalemi silindi: {project_name} · {code} — {description}"


def contract_distribution_saved(project_name: str, count: int) -> str:
    return f"Poz dağılımı kaydedildi: {project_name} · {count} eşleştirme"


def subcontractor_created(name: str) -> str:
    return f"Taşeron oluşturuldu: {name}"


def subcontractor_updated(name: str) -> str:
    return f"Taşeron güncellendi: {name}"


def subcontractor_deleted(name: str) -> str:
    return f"Taşeron silindi: {name}"


def subcontract_label(contract_no: str | None, subcontractor_name: str | None) -> str:
    """Sözleşme no yoksa taşeron adı, o da yoksa "taslak" — taslak aşamasında

    henüz doldurulmamış alanlar için anlamlı bir denetim etiketi üretir.
    """
    return contract_no or subcontractor_name or "taslak"


def subcontract_created(project_name: str, label: str) -> str:
    return f"Taşeron sözleşmesi oluşturuldu: {project_name} · {label}"


def subcontract_updated(project_name: str, label: str) -> str:
    return f"Taşeron sözleşmesi güncellendi: {project_name} · {label}"


def subcontract_published(project_name: str, label: str) -> str:
    """`site_published` deseninin aynısı: `is_draft: true -> false` geçişi

    (spec §5.3/§8, §10) — düz güncellemeden AYRI metindir.
    """
    return f"Taşeron sözleşmesi taslaktan yayına alındı: {project_name} · {label}"


def subcontract_deleted(project_name: str, label: str) -> str:
    return f"Taşeron sözleşmesi silindi: {project_name} · {label}"


def subcontract_item_created(contract_no: str | None, code: str) -> str:
    return f"Taşeron sözleşmesi kalemi oluşturuldu: {contract_no or 'taslak'} · {code}"


def subcontract_item_updated(contract_no: str | None, code: str) -> str:
    return f"Taşeron sözleşmesi kalemi güncellendi: {contract_no or 'taslak'} · {code}"


def subcontract_item_deleted(contract_no: str | None, code: str) -> str:
    return f"Taşeron sözleşmesi kalemi silindi: {contract_no or 'taslak'} · {code}"


def subcontract_items_loaded(contract_no: str | None, count: int) -> str:
    label = contract_no or "taslak"
    return f"Taşeron sözleşmesi kalemleri işverenden yüklendi: {label} · {count} kalem"
