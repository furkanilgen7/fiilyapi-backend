"""Denetim metinlerinin PAYLASILAN parcalari — birden cok aileye ait olanlar.

Buradaki uc sembol OLCULEREK secildi: yalnizca bunlar urun modulu sinirini
asiyor (AST ile, yorum ve docstring haric).

* `BILINMIYOR` + `_damga` -> isveren VE taseron hakedis aileleri
* `APPROVAL_ON_BEHALF_MARK` -> onay zinciri VE personel izin ailesi

🔴 Bunlar KOPYALANMAZ. `_damga`nin TR saat dilimi duzeltmesi (TB5 §1 kusur
sinifi) iki kopyadan yalniz birinde kalsaydi bu SESSIZ bir bozulma olurdu:
gunlugun yarisi onay saatini bir gun geride gosterirdi. Tek kopya oldugu
`tests/test_tbaudit_denetim_metni_anlik_goruntu.py` icinde AST ile bekcilenir.
"""

from datetime import datetime

from app.core.timezone import DISPLAY_TIMESTAMP_FORMAT, to_display

BILINMIYOR = "Bilinmiyor"


def _damga(value: datetime | None) -> str:
    """Denetim metnindeki, kullanıcıya görünen tarih-saat damgası.

    `approved_at` bir `timestamptz`tir; ham `strftime` sunucunun UTC saatini
    basar ve TR gecesi 21:00-24:00 arasında BİR ÖNCEKİ GÜNÜ gösterir (TB5 §1
    kusur sınıfı — denetim metni onay saatini yanlış anlatırdı). Çeviri TEK
    kaynaktan (`core.timezone.to_display`) yapılır.
    """
    return to_display(value).strftime(DISPLAY_TIMESTAMP_FORMAT) if value else BILINMIYOR


#: "Kendi evragini onaylama" istisnasinin GORUNUR izi (K1, kullanici karari
#: 2026-08-21). Kolon DEGIL metindir: istisnanin kendisi bir olay niteligidir,
#: kaydin kalici bir ozelligi degil.
APPROVAL_ON_BEHALF_MARK = "admin vekâleten"
