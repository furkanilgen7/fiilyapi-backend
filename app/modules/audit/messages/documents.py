"""Denetim metinleri — belge arsivi (documents T2/T3): klasor + kunye."""

# --- Belge arşivi (documents T2 — klasör uçları) ---
#
# Kaydın kimliği UUID değil İNSAN-OKUR kapsamdır: proje · (varsa) şantiye · ad.
# Şantiyesiz klasör PROJE DÜZEYİDİR (spec §2) ve metinde şantiye parçası hiç
# görünmez — "—" gibi bir yer tutucu koymak günlüğü gürültüye boğardı.


def _document_scope(project_name: str, site_name: str | None) -> str:
    if site_name is None:
        return project_name
    return f"{project_name} · {site_name}"


def document_folder_created(project_name: str, site_name: str | None, folder_name: str) -> str:
    return f"Belge klasörü oluşturuldu: {_document_scope(project_name, site_name)} · {folder_name}"


def document_folder_renamed(
    project_name: str, site_name: str | None, old_name: str, new_name: str
) -> str:
    """Eski ad çağrı noktasında değişiklikten ÖNCE okunmalı (`role_renamed` dersi);
    sonra okunursa günlükte yeni ad iki kez çıkar."""
    return (
        f"Belge klasörü yeniden adlandırıldı: {_document_scope(project_name, site_name)} "
        f"· {old_name} → {new_name}"
    )


def document_folder_deleted(project_name: str, site_name: str | None, folder_name: str) -> str:
    """Metin `session.delete`ten ÖNCE kurulur — sonra kurulsaydı proje/şantiye
    adları güvenilir okunamaz ve silinenin NE OLDUĞU kaybolurdu."""
    return f"Belge klasörü silindi: {_document_scope(project_name, site_name)} · {folder_name}"


# --- Belge künyeleri (documents T3 — yükleme/güncelleme/silme) ---
#
# Kimlik yine UUID değil DOSYA ADIDIR: denetim günlüğünü okuyan kişi arşivde
# hangi dosyanın konuşulduğunu adından tanır. Boyut/uzantı YAZILMAZ — künye
# ekranda zaten görünür ve günlük satırını gürültüye boğardı.


def document_uploaded(project_name: str, site_name: str | None, filename: str) -> str:
    return f"Belge yüklendi: {_document_scope(project_name, site_name)} · {filename}"


def document_updated(project_name: str, site_name: str | None, filename: str) -> str:
    """Ad değiştiyse metin YENİ adı taşır (kayıt o addan aranır); klasör
    taşımasında da aynı satır düşer — hangi alanın değiştiği künyenin kendisinden
    okunur, günlük NE OLDUĞUNU değil NEYE DOKUNULDUĞUNU kaydeder."""
    return f"Belge güncellendi: {_document_scope(project_name, site_name)} · {filename}"


def document_deleted(project_name: str, site_name: str | None, filename: str) -> str:
    """Metin `session.delete`ten ÖNCE kurulur (klasör silme dersiyle aynı)."""
    return f"Belge silindi: {_document_scope(project_name, site_name)} · {filename}"
