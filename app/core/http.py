"""`Content-Disposition` üretiminin TEK KAYNAĞI.

## Neden `app.core`da

Bu başlık bir GÜVENLİK YÜZEYİDİR: dosya adı kullanıcı verisinden türer (şantiye
kodu, proje kodu, talep numarası, personel adı) ve doğrudan bir HTTP başlığına
girer. İki kırılma sınıfı vardır:

* **Başlık enjeksiyonu** — addaki CR/LF başlığı bölüp yeni başlık uydurabilir;
  addaki `"` ASCII yedeğinin tırnaklı dizesini erken kapatır.
* **Görüntü sahteciliği** — bidi override taşıyan bir ad indirme diyaloğunda
  gerçek uzantısından başka bir uzantıyla görünür.

EXPORT-XLSX ölçümü: aynı kural depoda **altı yerde** ayrı ayrı yazılmıştı ve
üç FARKLI davranış üretiyordu (aşağıda). Altısı da buraya bağlandı; yeni bir
dışa aktarma ucu KENDİ kopyasını yazmaz, bu fonksiyonu çağırır.

## Ölçülen üç davranış (birleştirmeden önce)

1. `boq` / `units` / `timesheet` / `payroll` — `ascii/ignore`, NFKD YOK:
   "Çankaya" → "ankaya" (Ç sessizce DÜŞER). Yalnız `"` temizlenir; **CR/LF
   temizlenmez**. `quote()` varsayılan `safe="/"` ile çağrıldığından addaki
   `/` `filename*` içinde kaçışsız kalır.
2. `audit` / `procurement` — `filename*` HİÇ YOK ve ad ham interpolasyondur
   (`procurement` adı `request_no`dan kurar, yani kullanıcı verisinden).
3. `documents.files.content_disposition` — NFKD ("Çankaya" → "Cankaya"),
   güvensiz karakterler `_` olur, `quote(safe="")`. **Doğru olan budur** ve
   tek kaynak bunun davranışıdır; 1 ve 2 ona yükseltildi.
"""

import re
import unicodedata
from urllib.parse import quote

_ASCII_UNSAFE = re.compile(r"[^A-Za-z0-9 ._\-()]")
"""ASCII yedeğinde bırakılan küme dışı her şey — CR/LF ve `"` dahil."""

FALLBACK_ASCII_FILENAME = "dosya"
"""Ad ASCII'ye indirgendiğinde tamamen boşalırsa kullanılır (ör. salt Kiril ad)."""


def ascii_fallback(filename: str, fallback: str = FALLBACK_ASCII_FILENAME) -> str:
    """Latin-1 dışı karakterleri düşürerek eski istemciler için yedek ad üretir.

    NFKD ayrıştırması "ü"yü "u" + birleşen aksana böler, `ascii/ignore` aksanı
    atar; böylece "Günlük" tamamen kaybolmak yerine "Gunluk" olur. Kalanların da
    tırnak/kontrol karakteri taşımaması gerekir — aksi hâlde ad başlığı bölerdi.
    """
    duz = unicodedata.normalize("NFKD", filename).encode("ascii", "ignore").decode("ascii")
    guvenli = _ASCII_UNSAFE.sub("_", duz).strip()
    return guvenli or fallback


def content_disposition(filename: str, fallback: str = FALLBACK_ASCII_FILENAME) -> str:
    """`attachment` + ASCII yedeği + RFC 5987 UTF-8 adı.

    İki ad birlikte verilir: `filename*`i anlayan tarayıcı onu, anlamayan ASCII
    yedeğini kullanır. `attachment` zorunludur — `inline` olsaydı tarayıcı
    arşivdeki bir HTML/SVG'yi uygulamanın kaynağında ÇALIŞTIRIRDI.

    `quote(safe="")` şarttır: varsayılan `safe="/"` addaki bir `/`i kaçışsız
    bırakır ve `filename*` değerini yol gibi okutur.
    """
    return (
        f'attachment; filename="{ascii_fallback(filename, fallback)}"; '
        f"filename*=UTF-8''{quote(filename, safe='')}"
    )
