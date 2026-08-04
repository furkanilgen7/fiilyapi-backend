"""Dosya adı / uzantı / MIME saf yardımcıları — yüklemenin İLK savunması (T3).

Buradaki fonksiyonlar oturum, HTTP ya da model TANIMAZ: girdi bir dizedir, çıktı
bir dizedir ya da `DocumentValidationError`dır (422). Bu yüzden bypass denemeleri
(çift uzantı, büyük harf, gizli boşluk, yol enjeksiyonu) HTTP'ye çıkmadan tek tek
sınanabilir — `tests/documents/test_files.py`.

## DONDURULAN KARAR — OTORİTE UZANTIDIR, İSTEMCİNİN `Content-Type`I DEĞİL

Config'teki beyaz liste (`allowed_document_extensions`) bir UZANTI listesidir ve
gerekçesi orada yazılıdır: mockup tip ikonunu dosya ADINDAN seçer, `dwg`/`heic`
gibi tiplerin güvenilir tek bir MIME'i yoktur. Bu yüzden:

* **İzin kararı** yalnız adın SON uzantısına bakar (`rapor.pdf.exe` → `exe` → red).
* **Künyeye yazılan `mime_type`** istemcinin beyanından DEĞİL, uzantıdan türetilir.

"İkisi de kontrol edilirse çelişkide ne olur" sorusu böylece ORTADAN KALKAR:
istemcinin beyanı hiç kullanılmaz. Çelişkide reddetmek iki kırılma üretirdi:
(a) tarayıcılar `dwg`/`heic` için tutarsız MIME gönderir, meşru yüklemeler
reddedilirdi; (b) `Content-Type: text/html` ile yüklenen bir `.pdf` künyeye o
tiple yazılsaydı indirme ucu saldırgan HTML'i tarayıcıya `text/html` olarak
sunardı — depolanmış XSS. Türetme bu yüzden aynı zamanda bir güvenlik kararıdır
(ikinci katman: indirme ucundaki `attachment` + `nosniff`).

Beyaz listenin KENDİSİ config'ten gelir; buradaki harita yalnız "izinli uzantının
MIME karşılığı nedir" sorusunu cevaplar. İkisinin senkron kalması testle
korunur (`test_beyaz_listedeki_her_uzantinin_mime_karsiligi_var`).
"""

import re
import unicodedata
from urllib.parse import quote

from app.core.config import settings
from app.core.errors import DocumentValidationError
from app.modules.documents import guards

MAX_FILENAME_LENGTH = 255
"""`Document.filename` sütunuyla AYNI (String(255)).

Aşan ad KIRPILMAZ, REDDEDİLİR: kırpma son uzantıyı yok edip beyaz liste
kararını anlamsızlaştırır ve kullanıcıya sebebi anlaşılmaz bir hata verirdi.
"""

_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
"""CR/LF dahil kontrol karakterleri — `Content-Disposition` enjeksiyon yüzeyi."""

_INVISIBLE_CHARS = re.compile(
    "[\u00ad\u200b-\u200f\u2028\u2029\u202a-\u202e\u2060-\u2064\u2066-\u2069\ufeff]"
)
"""GÖRÜNMEZ biçim karakterleri: bidi gömme/override/izolat, sıfır genişlikliler,
yumuşak tire, BOM, satır/paragraf ayracı.

Beyaz listeyi ATLATMAZLAR — uzantı kararı adın gerçek son uzantısına bakar ve
`rapor‮exe.fdp` gibi bir ad `fdp` uzantısıyla zaten reddedilir (kapı KAPALI
başarısız olur). Temizliğin sebebi GÖRÜNTÜ SAHTECİLİĞİDİR: U+202E taşıyan bir ad
arşiv listesinde ve indirme diyaloğunda gerçek uzantısından BAŞKA bir uzantıyla
görünür, yani kullanıcı ne indirdiğini yanlış okur. Sıfır genişlikliler ise aynı
görünen iki ayrı klasör/belge adı üretip tekillik kontrolünü anlamsızlaştırır."""

_EDGE_NOISE = re.compile(r"^[\s.]+|[\s.]+$")
"""Baştaki/sondaki boşluk ve noktalar. `rapor.exe .` gibi adlarda gerçek uzantıyı
gizlemeye çalışan girişimler bu temizlikten SONRA sınanır."""

_ASCII_UNSAFE = re.compile(r"[^A-Za-z0-9 ._\-()]")
"""`Content-Disposition`ın ASCII yedeğinde bırakılan karakter kümesi dışı her şey."""

MIME_BY_EXTENSION = {
    "pdf": "application/pdf",
    "doc": "application/msword",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xls": "application/vnd.ms-excel",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "csv": "text/csv",
    "dwg": "image/vnd.dwg",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "heic": "image/heic",
    "zip": "application/zip",
}
"""Config'teki VARSAYILAN beyaz listenin tamamını kapsar (test dondurur)."""

FALLBACK_MIME = "application/octet-stream"
FALLBACK_ASCII_FILENAME = "belge"


def normalize_filename(raw: str | None) -> str:
    """Görünen adı KORUYARAK yol/başlık enjeksiyonunu temizler.

    Türkçe karakterler, boşluklar ve büyük/küçük harf AYNEN kalır — kullanıcı
    arşivde kendi verdiği adı görmelidir. Temizlenen şeyler:

    * kontrol karakterleri (CR/LF ile başlık bölme),
    * GÖRÜNMEZ biçim karakterleri (bidi override, sıfır genişlikliler, BOM) —
      gerekçe `_INVISIBLE_CHARS`ta: uzantı SAHTECİLİĞİ ve aynı görünen ikiz adlar,
    * dizin bileşenleri — yalnız SON bileşen kalır, böylece `../../etc/x.pdf`
      `x.pdf` olur (hem `/` hem `\\` ayracı; Windows istemcileri tam yol gönderir),
    * baştaki/sondaki boşluk ve noktalar.

    Geriye bir şey kalmazsa 422 (404 DEĞİL: düzeltilebilir bir ALAN değeridir).
    """
    if not raw:
        raise DocumentValidationError(guards.FILENAME_INVALID)
    temiz = _CONTROL_CHARS.sub("", raw)
    temiz = _INVISIBLE_CHARS.sub("", temiz)
    temiz = temiz.replace("\\", "/").rsplit("/", 1)[-1]
    temiz = _EDGE_NOISE.sub("", temiz)
    if not temiz:
        raise DocumentValidationError(guards.FILENAME_INVALID)
    if len(temiz) > MAX_FILENAME_LENGTH:
        raise DocumentValidationError(guards.FILENAME_TOO_LONG)
    return temiz


def extension_of(filename: str) -> str | None:
    """SON uzantı, küçük harfe indirgenmiş. Uzantı yoksa `None`.

    SON uzantı: `rapor.pdf.exe` çalıştırılabilir bir dosyadır, PDF değil.
    """
    ad = filename.strip().rstrip(".")
    if "." not in ad:
        return None
    uzanti = ad.rsplit(".", 1)[1].strip().lower()
    return uzanti or None


def assert_allowed_extension(filename: str) -> str:
    """Beyaz liste kapısı (spec §4). Geçerse uzantıyı döndürür, geçmezse 422."""
    uzanti = extension_of(filename)
    if uzanti is None or uzanti not in settings.allowed_document_extension_set:
        raise DocumentValidationError(guards.EXTENSION_NOT_ALLOWED)
    return uzanti


def mime_for_filename(filename: str) -> str:
    """Künyeye yazılacak tip — UZANTIDAN türetilir (istemci beyanı kullanılmaz)."""
    uzanti = extension_of(filename)
    if uzanti is None:
        return FALLBACK_MIME
    return MIME_BY_EXTENSION.get(uzanti, FALLBACK_MIME)


def _ascii_fallback(filename: str) -> str:
    """Latin-1 dışı karakterleri düşürerek eski istemciler için yedek ad üretir.

    NFKD ayrıştırması "ü"yü "u" + birleşen aksana böler, `ascii/ignore` aksanı
    atar; böylece "Günlük" tamamen kaybolmak yerine "Gunluk" olur. Kalanların da
    tırnak/kontrol karakteri taşımaması gerekir — aksi hâlde ad başlığı bölerdi.
    """
    duz = unicodedata.normalize("NFKD", filename).encode("ascii", "ignore").decode("ascii")
    guvenli = _ASCII_UNSAFE.sub("_", duz).strip()
    return guvenli or FALLBACK_ASCII_FILENAME


def content_disposition(filename: str) -> str:
    """`attachment` + ASCII yedeği + RFC 5987 UTF-8 adı.

    İki ad birlikte verilir: `filename*`i anlayan tarayıcı onu, anlamayan ASCII
    yedeğini kullanır. `attachment` zorunludur — `inline` olsaydı tarayıcı
    arşivdeki bir HTML/SVG'yi uygulamanın kaynağında ÇALIŞTIRIRDI.
    """
    return (
        f'attachment; filename="{_ascii_fallback(filename)}"; '
        f"filename*=UTF-8''{quote(filename, safe='')}"
    )
