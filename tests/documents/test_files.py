"""Dosya adı / uzantı / MIME saf yardımcıları (T3) — beyaz liste BYPASS yüzeyi.

Yükleme ucunun ilk savunması burasıdır ve yalnız burada saf fonksiyon olarak
sınanabilir: HTTP testi bir bypass'ı kaçırırsa sebebi genelde yardımcının kendisi
olur.

## DONDURULAN KARAR — OTORİTE UZANTIDIR, `Content-Type` DEĞİL

Config'teki beyaz liste bir UZANTI listesidir (`allowed_document_extensions`;
gerekçesi orada yazılı: mockup dosya adına göre tip ikonu basar ve `dwg` gibi
tiplerin güvenilir tek bir MIME'i yoktur). Bu yüzden:

* İzin kararı YALNIZ dosya adının SON uzantısına bakar.
* Künyeye yazılan `mime_type` istemcinin `Content-Type` başlığından DEĞİL,
  uzantıdan TÜRETİLİR (`mime_for_filename`).

Çelişkide ne olur sorusunun cevabı budur: çelişki diye bir durum KALMAZ, çünkü
istemcinin beyanı hiç kullanılmaz. Alternatif (ikisini de kontrol edip çelişkide
reddetmek) iki yeni kırılma üretirdi: (a) tarayıcılar `dwg`/`heic` için tutarsız
MIME gönderir, meşru yüklemeler reddedilirdi; (b) `Content-Type: text/html`
gönderilen bir `.pdf` kabul edilip künyeye o tip yazılsaydı, indirme ucu saldırgan
HTML'i tarayıcıya `text/html` olarak sunardı (depolanmış XSS). Türetilen tip bu
yüzden aynı zamanda bir GÜVENLİK kararıdır.
"""

import pytest

from app.core.config import settings
from app.core.errors import DocumentValidationError
from app.modules.documents import files

# --- normalize_filename: yol enjeksiyonu ve görünen adın korunması ---


@pytest.mark.parametrize(
    ("ham", "beklenen"),
    [
        ("rapor.pdf", "rapor.pdf"),
        # Türkçe karakter ve boşluk KORUNUR — kullanıcıya görünen ad budur.
        ("Günlük Rapor 17.07.2026.pdf", "Günlük Rapor 17.07.2026.pdf"),
        # Dizin ayracı: yalnız son bileşen kalır (POSIX ve Windows).
        ("../../etc/passwd.pdf", "passwd.pdf"),
        ("klasor/alt/rapor.pdf", "rapor.pdf"),
        (r"C:\Temp\rapor.pdf", "rapor.pdf"),
        ("....//....//rapor.pdf", "rapor.pdf"),
        # Baştaki/sondaki boşluk ve nokta temizlenir.
        ("  rapor.pdf  ", "rapor.pdf"),
        ("rapor.pdf.", "rapor.pdf"),
        ("...rapor.pdf...", "rapor.pdf"),
        # Kontrol karakterleri (başlık enjeksiyonu yüzeyi) atılır.
        ("rapor\r\n.pdf", "rapor.pdf"),
        ("rapor\x00.pdf", "rapor.pdf"),
    ],
)
def test_dosya_adi_normalize_edilir(ham: str, beklenen: str) -> None:
    assert files.normalize_filename(ham) == beklenen


@pytest.mark.parametrize("ham", [None, "", "   ", "...", "/", "../", "\x00"])
def test_bos_ya_da_yalniz_ayrac_olan_ad_reddedilir(ham: str | None) -> None:
    with pytest.raises(DocumentValidationError):
        files.normalize_filename(ham)


def test_cok_uzun_ad_reddedilir() -> None:
    """Kırpılmaz: kırpma uzantıyı yok edip beyaz listeyi anlamsızlaştırırdı."""
    with pytest.raises(DocumentValidationError):
        files.normalize_filename("a" * 300 + ".pdf")


def test_tam_sinirdaki_ad_kabul_edilir() -> None:
    ad = "a" * (files.MAX_FILENAME_LENGTH - 4) + ".pdf"
    assert files.normalize_filename(ad) == ad


# --- Beyaz liste: BYPASS DENEMELERİ ---


@pytest.mark.parametrize("ad", ["rapor.pdf", "tablo.xlsx", "cizim.dwg", "foto.heic", "arsiv.zip"])
def test_beyaz_listedeki_uzanti_gecer(ad: str) -> None:
    files.assert_allowed_extension(ad)


@pytest.mark.parametrize("ad", ["RAPOR.PDF", "Tablo.XlSx", "Foto.JPG"])
def test_buyuk_harfli_uzanti_gecer(ad: str) -> None:
    """Beyaz liste küçük harfe indirgenerek karşılaştırılır; `.PDF` reddedilseydi
    Windows istemcileri sebepsiz 422 alırdı."""
    files.assert_allowed_extension(ad)


@pytest.mark.parametrize(
    "ad",
    [
        # ÇİFT UZANTI: karar veren SON uzantıdır.
        "rapor.pdf.exe",
        "rapor.pdf.sh",
        "arsiv.zip.bat",
        # Beyaz listede olmayan tek uzantı.
        "virus.exe",
        "betik.js",
        "sayfa.html",
        # Uzantısız.
        "LICENSE",
        "rapor",
    ],
)
def test_beyaz_liste_disi_uzanti_reddedilir(ad: str) -> None:
    with pytest.raises(DocumentValidationError):
        files.assert_allowed_extension(ad)


def test_uzanti_bosluk_ve_nokta_ile_gizlenemez() -> None:
    """`rapor.exe .pdf` gibi adlar normalize edildikten SONRA sınanır — ama
    normalize edilmemiş bir ad da doğru sonucu vermelidir."""
    assert files.extension_of("rapor.pdf ") == "pdf"
    assert files.extension_of("rapor.exe") == "exe"
    assert files.extension_of("rapor") is None


# --- MIME türetme ---


@pytest.mark.parametrize(
    ("ad", "beklenen"),
    [
        ("rapor.pdf", "application/pdf"),
        ("RAPOR.PDF", "application/pdf"),
        ("tablo.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        ("foto.jpg", "image/jpeg"),
        ("foto.jpeg", "image/jpeg"),
        ("arsiv.zip", "application/zip"),
    ],
)
def test_mime_uzantidan_turetilir(ad: str, beklenen: str) -> None:
    assert files.mime_for_filename(ad) == beklenen


def test_beyaz_listedeki_her_uzantinin_mime_karsiligi_var() -> None:
    """Beyaz listeye env'den yeni uzantı eklenirse haritada karşılığı olmalı;
    yoksa künye sessizce `application/octet-stream` taşır."""
    eksik = settings.allowed_document_extension_set - set(files.MIME_BY_EXTENSION)
    assert eksik == set()


def test_bilinmeyen_uzanti_octet_streame_duser() -> None:
    assert files.mime_for_filename("dosya.bilinmeyen") == "application/octet-stream"


# --- Content-Disposition ---


def test_content_disposition_turkce_adi_yuzde_kodlar() -> None:
    baslik = files.content_disposition("Günlük Rapor.pdf")

    assert baslik.startswith("attachment;")
    assert "filename*=UTF-8''G%C3%BCnl%C3%BCk%20Rapor.pdf" in baslik


def test_content_disposition_ascii_yedegi_tasir() -> None:
    """Eski istemciler `filename*`i anlamaz; ASCII yedeği olmadan adsız iner."""
    baslik = files.content_disposition("Günlük Rapor.pdf")

    assert 'filename="Gunluk Rapor.pdf"' in baslik


def test_content_disposition_baslik_enjeksiyonuna_kapali() -> None:
    """Tırnak ve CRLF ASCII yedeğinden temizlenir — aksi hâlde ad, başlığı
    bölerek yeni bir HTTP başlığı enjekte edebilirdi."""
    baslik = files.content_disposition('ra"por\r\nX-Zarar: 1.pdf')

    assert "\r" not in baslik
    assert "\n" not in baslik
    ascii_kismi = baslik.split('filename="', 1)[1].split('"', 1)[0]
    assert '"' not in ascii_kismi
