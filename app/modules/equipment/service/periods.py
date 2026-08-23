"""Dönem aritmetiği — ay ve hafta sınırlarının TEK tanımı.

`service.py` bölünürken ayrı dosyaya alındı: bu üç yardımcıyı `core` (cari ay
KPI'ı), `work_summary` (aylık tablo + haftalık kovalar) ve `fuel_summary`
(aylık yakıt) AYRI AYRI çağırıyor. Herhangi birinin içine konsaydı öteki iki
parça ona bağımlı olur, ya da — çok daha kötüsü — ikinci bir kopya yazılırdı;
`month_bounds` bu depoda zaten BEŞ modülde ayrı ayrı tanımlı (accounting,
treasury, payroll…) ve o kopyaların birbirinden habersizliği bilinen bir borç.

Bu dosya DB'ye dokunmaz, hiçbir modülden içe aktarım yapmaz: bağımlılık
grafiğinin yaprağıdır.
"""

from datetime import date, timedelta


def _month_bounds(bugun: date) -> tuple[date, date]:
    """Cari ayın ilk ve son günü. "Aylık maliyet" cari aydır: geçmiş aylar
    eklenseydi KPI her ay birikerek büyür, hiçbir zaman düşmezdi."""
    ilk = bugun.replace(day=1)
    sonraki_ay = (
        ilk.replace(year=ilk.year + 1, month=1)
        if ilk.month == 12
        else ilk.replace(month=ilk.month + 1)
    )
    return ilk, sonraki_ay - timedelta(days=1)


def month_bounds(year: int, month: int) -> tuple[date, date]:
    """Verilen ayın ilk ve son günü. `_month_bounds` (cari ay) ile aynı
    aritmetiği paylaşır ama dönemi PARAMETREDİR."""
    ilk = date(year, month, 1)
    sonraki = ilk.replace(year=year + 1, month=1) if month == 12 else ilk.replace(month=month + 1)
    return ilk, sonraki - timedelta(days=1)


def _monday(gun: date) -> date:
    """Haftanın PAZARTESİSİ. Hafta sınırının TEK tanımı."""
    return gun - timedelta(days=gun.weekday())
