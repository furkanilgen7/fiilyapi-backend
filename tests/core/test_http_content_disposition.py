"""`app.core.http` — `Content-Disposition` tek kaynağının bekçisi (EXPORT-XLSX).

Bu dosya İKİ ŞEYİ birden ölçer:

1. **Davranış** — başlık enjeksiyonu, yol kaçışı, aksan koruması. Bunlar
   `openpyxl`in ya da `urllib`in kendi davranışı DEĞİLDİR: `quote` varsayılan
   `safe="/"` ile `/`i geçirir, `str.encode("ascii","ignore")` NFKD olmadan
   "Ç"yi tamamen düşürür. İkisi de burada mutasyonla sınanır.
2. **Yapı** — kuralın İKİNCİ bir kopyasının geri sızmaması. Kopya sayısı
   EXPORT-XLSX öncesi altıydı ve ÜÇ ayrı davranış üretiyordu; davranış testi
   tek başına yeni bir kopyayı göremez, çünkü kopya kendi çağrı yerinden
   çağrılır (§5-20: çağrı yeri de mutanttır).
"""

import pathlib
import re

import pytest

from app.core import http

_APP = pathlib.Path(__file__).resolve().parents[2] / "app"


def test_crlf_baslik_enjeksiyonu_notrlenir():
    """CR/LF başlığı bölüp yeni başlık uydurmanın yoludur — ASCII yedeğinde
    kalmamalı ve `filename*` içinde yüzdelenmiş olmalı."""
    sonuc = http.content_disposition("rapor\r\nX-Evil: 1.xlsx")
    assert "\r" not in sonuc and "\n" not in sonuc
    assert "X-Evil: 1" not in sonuc  # ham hâliyle GEÇMEZ
    assert "%0D%0A" in sonuc


def test_tirnak_ascii_yedeginin_dizesini_erken_kapatamaz():
    sonuc = http.content_disposition('a"b.xlsx')
    ascii_adi = re.search(r'filename="([^"]*)"', sonuc).group(1)
    assert '"' not in ascii_adi
    assert "%22" in sonuc


def test_bolu_isareti_filename_yildizda_kacisir():
    """MUTASYON: `quote(filename)` (varsayılan `safe="/"`) bu testi DÜŞÜRÜR —
    dört eski kopyanın hepsi o hâldeydi."""
    sonuc = http.content_disposition("a/b.xlsx")
    assert "%2F" in sonuc
    assert "filename*=UTF-8''a/b.xlsx" not in sonuc


def test_turkce_harf_ascii_yedeginde_DUSMEZ_yaklastirilir():
    """MUTASYON: NFKD kaldırılırsa "Çankaya" → "ankaya" olur ve bu test düşer.
    Dört eski kopyanın ölçülen davranışı buydu."""
    ascii_adi = re.search(
        r'filename="([^"]*)"', http.content_disposition("is-kalemleri-Çankaya.xlsx")
    ).group(1)
    assert ascii_adi == "is-kalemleri-Cankaya.xlsx"


def test_iki_ad_birlikte_verilir_ve_attachment_zorunlu():
    sonuc = http.content_disposition("Günlük.xlsx")
    assert sonuc.startswith("attachment; ")
    assert 'filename="Gunluk.xlsx"' in sonuc
    assert "filename*=UTF-8''G%C3%BCnl%C3%BCk.xlsx" in sonuc


def test_ascii_yedegi_tamamen_bosalirsa_yedek_ad_kullanilir():
    assert 'filename="dosya"' in http.content_disposition("Ω")
    assert 'filename="puantaj.xlsx"' in http.content_disposition("Ω", "puantaj.xlsx")


# --------------------------------------------------------------------------
# YAPISAL BEKÇİ — kopya geri sızamaz
# --------------------------------------------------------------------------

_HAM_BASLIK = re.compile(r"""["']attachment;\s*filename=""")
"""Ham `attachment; filename=` interpolasyonu — `audit` ve `procurement`
EXPORT-XLSX'ten önce tam olarak böyleydi ve `filename*` TAŞIMIYORDU."""

_MUAF = {
    # Tek kaynağın KENDİSİ.
    "core/http.py",
    # Şirket logosu bir Excel dışa aktarımı değildir; kendi `safe_logo_filename`i
    # vardır ve EXPORT-XLSX kapsamı dışında bırakıldı (raporda açık borç).
    "modules/company/router.py",
}


def _kaynak_dosyalar():
    for yol in _APP.rglob("*.py"):
        bagil = yol.relative_to(_APP).as_posix()
        if bagil not in _MUAF:
            yield bagil, yol.read_text(encoding="utf-8")


_KAYNAKLAR = sorted(_kaynak_dosyalar())


@pytest.mark.parametrize("bagil,govde", _KAYNAKLAR, ids=[b for b, _ in _KAYNAKLAR])
def test_hicbir_modul_kendi_content_disposition_kuralini_yazmaz(bagil, govde):
    """`app.core.http.content_disposition` DIŞINDA başlık kurulmaz.

    Bu bekçi olmadan yeni bir dışa aktarma ucu sessizce kendi (eksik) kopyasını
    yazabilir ve davranış testleri bunu GÖREMEZ.
    """
    assert not _HAM_BASLIK.search(govde), (
        f"{bagil}: `Content-Disposition` elle kuruluyor. "
        "Tek kaynak `app.core.http.content_disposition`tır."
    )
    assert "def _content_disposition(" not in govde, (
        f"{bagil}: yerel `_content_disposition` kopyası. `app.core.http.content_disposition` çağır."
    )
