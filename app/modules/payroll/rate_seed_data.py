"""Bordro oran setinin UYGULAMA KATMANI doğruluk kaynağı — 2026 (IK3-RATE-FIX).

🔴 **BU DOSYA TOHUM BASMAZ.** MU-SEED'in `chart_seed_data.py`sinden farkı budur
ve kasıtlıdır: 2026 oran tohumu `c5d6e7f8a9b0` (İK-3 çekirdeği) içinde ZATEN
basılıyor ve canlıda uygulanmış durumda. İkinci bir tohum yazmak `ON CONFLICT
DO NOTHING` altında hiçbir şey yapmayan ölü kod olurdu.

Bu modülün TEK işi, oran setinin **KK-5 sonrası nihai** hâlini tek bir okunur
yerde tutmaktır — böylece migration zincirinin ürettiği DB durumu bir sabite
karşı ölçülebilir hâle gelir.

## 🔴 Niçin bir bekçiye ihtiyaç var: `tests/conftest.py` alembic KOŞTURMAZ

`tests/conftest.py:59-60` şemayı `Base.metadata.create_all` ile kurar. Yani
normal test suite'inde `payroll_rates` tablosu **BOŞTUR** ve migration
zincirinin bastığı oranlar hiçbir testte görünmez. Bu, iki katmanın sessizce
ayrışmasına izin verir: canlıda (`Dockerfile:22` `alembic upgrade head`) bir
değer, testlerde bambaşka bir değer.

🔴 Bu boşluğu naif bir "DB'yi oku, sabitle karşılaştır" testi KAPATAMAZ —
normal suite'te boş tabloya bakar ve **sahte yeşil** verir ("aynı yeşil iki
anlam taşır" kanonu). `tests/modules/payroll/test_ik3_rate_fix_iki_katman.py`
bu yüzden iki AYRI şekilde ölçer; gerekçesi orada yazılıdır.

## Oranların durumu

| Oran | Değer | Kaynak |
|---|---|---|
| `sgk_employee_pct` | 14 | 5510 s.K. — işçi payı %14 (SGK 70) |
| `unemployment_employee_pct` | 1 | 4447 s.K. m.49 — işçi %1 (SGK 71) |
| `income_tax_pct` | 10 | 🔴 **AÇIK BORÇ**, aşağı bak (SGK 72) |
| `stamp_tax_pct` | 0.759 | 488 s.K. — ücrette binde 7,59 (SGK 73) |
| `sgk_employer_pct` | 20.5 | 5510 s.K. — işveren payı %20,5, teşvik öncesi (SGK 79) |
| `unemployment_employer_pct` | 2 | 4447 s.K. m.49 — işveren %2 (SGK 80) |
| `short_work_pct` | **0** | 🔑 **KK-5**, aşağı bak (SGK 81 %1 yazar → REDDEDİLDİ) |

🔑 **KK-5 (kullanıcı kararı, 2026-08-16): "SGK %1 kısa çalışma ödeneği YOK,
hesaplanmaz."** `c5d6e7f8a9b0:102` bu oranı mockup etiketine (SGK 81) bakarak
`1` basmıştı; mevzuatta ayrı bir "%1 kısa çalışma primi" YOKTUR. Kararın
YALNIZ satırı basmamakla uygulanamayacağı ölçüldü: `short_work_total`,
`sgk.py`de `_RATE_FIELDS[4:]` üzerinden `employer_burden_total`ın İÇİNDE
taşınıyor ve `summary.py`nin maliyet tabanını brütün %1'i kadar şişiriyor.
Doğru çözüm oranın **`0`** olmasıdır; `models.py:276` `short_work_pct >= 0`
CHECK'i `0`ı açıkça yasal kılar.
🔴 **BURAYA 1 YAZMA.** "Eksik veri" değildir, karardır.

🔴 **AÇIK BORÇ — `income_tax_pct` = 10 mevzuata DAYANMIYOR.** Tek kaynağı
mockup etiketidir (SGK 72 "Gelir Vergisi Stopajı (%10)"). Türkiye'de ücret
geliri vergisi GVK m.103 uyarınca **artan oranlıdır** (ilk dilim %15, sonra
20/27/35/40) ve %10 hiçbir dilime karşılık gelmez; model tek `Decimal` taşır
(`models.py:293`) ve `compute.deduction_and_net` bunu DÜZ oran olarak kullanır
(`models.py:9`: "Dilimli/kümülatif gelir vergisi motoru YOK"). Karar
KULLANICIDA, cevap beklemektedir → bu turda **DEĞİŞTİRİLMEDİ**. Değer
geldiğinde burası ve `c5d6e7f8a9b0`in düzeltmesi AYRI bir dilimde ele alınır.

`freelance` = 20 doğrudur (GVK m.94 serbest meslek stopajı %20).
`general` ("genel işçi") KASTEN yoktur — bordro tipi değildir (şef kararı 2,
`site_diary/models.py:66` + `tests/modules/payroll/conftest.py:61`).
2027 ve sonrası KASTEN yoktur — oran tablosu yıllıktır ve mevzuat icat
edilmez; oran giren ekranın yokluğu ayrı bir dilimdir.
"""

from decimal import Decimal

#: Tohumun kapsadığı TEK yıl. `c5d6e7f8a9b0:123` `RATE_SEED_YEAR` ile aynıdır.
RATE_SEED_YEAR = 2026

#: Oran sütunlarının KANONİK sırası — `models.py`deki tanım sırası.
RATE_COLUMNS: tuple[str, ...] = (
    "sgk_employee_pct",
    "unemployment_employee_pct",
    "income_tax_pct",
    "stamp_tax_pct",
    "sgk_employer_pct",
    "unemployment_employer_pct",
    "short_work_pct",
)

#: SGK 4a rejimi — `company` ve `subcontractor`. `short_work_pct` KK-5 gereği 0.
_SGK_4A: dict[str, Decimal] = {
    "sgk_employee_pct": Decimal("14.000"),
    "unemployment_employee_pct": Decimal("1.000"),
    "income_tax_pct": Decimal("10.000"),
    "stamp_tax_pct": Decimal("0.759"),
    "sgk_employer_pct": Decimal("20.500"),
    "unemployment_employer_pct": Decimal("2.000"),
    "short_work_pct": Decimal("0.000"),
}

_ZERO: dict[str, Decimal] = dict.fromkeys(RATE_COLUMNS, Decimal("0.000"))

#: 🔴 Migration zincirinin (`c5d6e7f8a9b0` tohumu + `f6a7b8c9d0e1` KK-5
#: düzeltmesi) SONUNDA `payroll_rates` tablosunda durması BEKLENEN tam durum.
PAYROLL_RATES_2026: dict[str, dict[str, Decimal]] = {
    # BY 127 "ŞİRKET KADROSU — SGK 4a".
    "company": _SGK_4A,
    # BY 175 "TAŞERON İŞÇİSİ": kesinti sütunu "—" DEĞİLDİR (BY 186), yani
    # taşeron işçisi de kesintiye tabidir → 4a oranlarının aynısı. Ödemeye
    # girmemesi K2'dir ve SERVİS katmanındadır, oranla ilgisi yoktur.
    "subcontractor": _SGK_4A,
    # BY 243 "SERBEST MESLEK · %20 Stopaj" (GVK m.94). SGK payı YOK.
    "freelance": {**_ZERO, "income_tax_pct": Decimal("20.000")},
    # BY 285: stajyer satırında kesinti sütunu "—" → TÜM oranlar 0.
    "intern": _ZERO,
}
