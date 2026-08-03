"""Belge yükleme sınırlarının config varsayılanları (spec §4 / §7 S5).

Sınırlar T2/T3'te uçlara bağlanacak; burada YALNIZ varsayılanların doğru ve
ayrıştırılabilir olduğu dondurulur. `.env`e dokunulmaz — bunlar Settings
varsayılanlarıdır.
"""

from app.core.config import Settings

BEKLENEN_UZANTILAR = {
    "pdf",
    "doc",
    "docx",
    "xls",
    "xlsx",
    "csv",
    "dwg",
    "jpg",
    "jpeg",
    "png",
    "heic",
    "zip",
}


def test_belge_boyut_tavani_50_mb() -> None:
    """Mockup kanıtı: E12'de 48 MB'lık bir ZIP var — tavan onun üstünde olmalı."""
    ayarlar = Settings(_env_file=None)
    assert ayarlar.document_max_bytes == 50 * 1024 * 1024
    assert ayarlar.document_max_bytes > 48 * 1024 * 1024


def test_beyaz_liste_zip_ve_heic_dahil_genis() -> None:
    ayarlar = Settings(_env_file=None)
    assert ayarlar.allowed_document_extension_set == BEKLENEN_UZANTILAR


def test_beyaz_liste_nokta_ve_buyuk_harf_toleransli() -> None:
    """Env'i `.PDF, .Zip` diye yazmak listeyi sessizce boşaltmamalı."""
    ayarlar = Settings(_env_file=None, allowed_document_extensions=".PDF, .Zip ,HEIC")
    assert ayarlar.allowed_document_extension_set == {"pdf", "zip", "heic"}
