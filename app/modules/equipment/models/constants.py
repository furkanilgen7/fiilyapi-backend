"""Ekipman kolonlarının ÖLÇEK sabitleri (para · miktar · saat · KDV).

`models.py` bölünürken ayrı dosyaya alındı: bu sabitleri hem `core` (ekipman
kartı, çalışma/yakıt kaydı) hem `rental` (kira hakedişi başlığı ve satırı)
kullanıyor. Herhangi birinin içine konsaydı öteki ona bağımlı olur ya da —
çok daha kötüsü — ikinci bir kopya yazılır ve iki tablonun `Numeric` ölçeği
zamanla ayrışırdı (para invariantlarının klasik kaçağı).
"""

from decimal import Decimal

# Para kolonlarının kuruş hassasiyeti (alış bedeli / rayiç / birim bedel).
MONEY_PRECISION = 18
MONEY_SCALE = 2

# Yakıt birim fiyatı DÖRT ondalıklıdır: litre fiyatı kuruşun altında kotalanır
# (M4:111) ve iki ondalık, litre × fiyat çarpımını sistematik olarak kaydırırdı.
UNIT_PRICE_PRECISION = 10
UNIT_PRICE_SCALE = 4

# Litre ve norm tüketim ölçeği.
QUANTITY_PRECISION = 10
QUANTITY_SCALE = 2

# Saat: 24 saatlik tavan (K12) iki ondalıkla rahat sığar.
HOURS_PRECISION = 6
HOURS_SCALE = 2

# K7: kullanım yüzdesinin PAYDASI. Mockup'tan tersine mühendislikle doğrulandı
# (186/200 = %93 · 152/200 = %76 · 42/200 = %21 · 168/200 = %84 · 144/200 = %72
# — beşi de M3 rozetleriyle birebir). Ekipman başına DEĞİŞTİRİLEBİLİR.
DEFAULT_MONTHLY_CAPACITY_HOURS = 200

# MK-2 K1: KDV oranının VARSAYILANIDIR, SABİTİ DEĞİL. Oran `vat_rate`
# kolonunda satır satır yaşar; koda gömülseydi mevzuat değişiminde GEÇMİŞ
# faturaların tutarı geriye dönük oynardı (İK-3 `payroll_rates` dersi).
DEFAULT_VAT_RATE = Decimal("20.00")

# Oran ölçeği: yüzde iki ondalıkla ifade edilir (%20,00 · %8,00 · %1,00).
VAT_RATE_PRECISION = 5
VAT_RATE_SCALE = 2

# MK-2 saat ölçeği. MK-1'in `HOURS_PRECISION`ı (6) TEK GÜNÜN saatidir; kira
# hakedişi satırı bir AYIN toplamını taşır (M5: 186 saat) ve dönem birikimi
# altı hanenin altında sıkışmamalıdır.
RENTAL_HOURS_PRECISION = 8
RENTAL_HOURS_SCALE = 2
