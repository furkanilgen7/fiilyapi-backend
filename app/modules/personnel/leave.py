"""İzin türev hesapları — İK-2 spec §2, §5 K2.

`status.py`nin kardeşi: KOLON OLMAYAN her değer TEK KAYNAKTAN hesaplanır. Bu
modül saf (I/O'suz) fonksiyonlar tutar; DB'ye dokunan çakışma sorgusu
`repository.py`de, kural `service.py`dedir.

**`days` neden burada?** `LeaveRequest.days` bir KOLONdur ama SUNUCU hesabıdır
(spec §5 K2): istemci gönderemez. POST ve PATCH aynı fonksiyonu ÇAĞIRIR, formülü
KOPYALAMAZ — aksi hâlde tarih düzeltmesinde iki yol ayrışırdı.
"""

from datetime import date


def calculate_leave_days(start_date: date, end_date: date) -> int:
    """İzin gün sayısı: **TAKVİM günü, başlangıç ve bitiş DAHİL** (spec §5 K2).

    Mockup (İZ) 04-08 Ağustos satırını "5 gün" gösterir; takvim hesabı bunu
    doğrular (08-04=4, +1 = 5). Hafta sonu/resmî tatil ÇIKARILMAZ — iş günü
    hesabı İK-3'ün işidir ve buraya sessizce eklenirse mevcut kayıtların `days`
    değeri geriye dönük anlamını değiştirirdi.

    Tek günlük izin 1'dir (0 DEĞİL) — `ck_leave_requests_days_positive` de bunu
    zorlar. Ters tarih ÇAĞIRANIN işidir (servis 422 verir): burada negatif dönmek
    yerine sessizce düzeltmek, hatalı gövdeyi geçirirdi.
    """
    return (end_date - start_date).days + 1
