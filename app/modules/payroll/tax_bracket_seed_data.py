"""2026 gelir vergisi tarifesi + asgari ücret — UYGULAMA KATMANI doğruluk kaynağı.

`rate_seed_data.py`nin kardeşidir ve ondan bir farkı vardır: oran tohumu
`c5d6e7f8a9b0` içinde ZATEN basılıydı, bu tohum ise IK3-GV migration'ıyla
BİRLİKTE doğuyor. Yine de aynı desen uygulanır — **bu dosya tohum BASMAZ**,
yalnız migration'ın basması BEKLENEN durumu tek okunur yerde tutar; böylece
migration zincirinin ürettiği DB durumu bir sabite karşı ölçülebilir olur.

## 🔴 Niçin bir bekçiye ihtiyaç var: `tests/conftest.py` alembic KOŞTURMAZ

`tests/conftest.py:59-60` şemayı `Base.metadata.create_all` ile kurar. Normal
suite'te `payroll_tax_brackets` **BOŞTUR** ve migration'ın bastığı tarife hiçbir
testte görünmez. Naif bir "DB'yi oku, sabitle karşılaştır" testi o boş tabloya
bakar ve **sahte yeşil** verir ("aynı yeşil iki anlam taşır" kanonu). Bu yüzden
eşitlik İKİ AYRI şekilde ölçülür ve gerekçesi
`tests/modules/payroll/test_ik3_gv_iki_katman.py` docstring'indedir:

* **(A) SEMBOLİK** — migration modülü dosyadan yüklenir, sabitleri buradaki
  sabitle karşılaştırılır. DB'ye HİÇ dokunmaz → boş tablo yeşile boyayamaz.
* **(B) GERÇEK ZİNCİR** — kendi tek kullanımlık DB'sini açar, gerçek
  `alembic upgrade` koşturur, satır sayısını AÇIKÇA iddia eder.

## KK-6 — 2026 ÜCRET geliri tarifesi (kullanıcı kararı, 2026-08-17)

| # | Üst eşik (TL) | Oran | Kümülatif formül |
|---|---|---|---|
| 1 | 190.000 | %15 | `m × 0,15` |
| 2 | 400.000 | %20 | `28.500 + (m − 190.000) × 0,20` |
| 3 | 1.500.000 | %27 | `70.500 + (m − 400.000) × 0,27` |
| 4 | 5.300.000 | %35 | `367.500 + (m − 1.500.000) × 0,35` |
| 5 | üstü | %40 | `1.697.500 + (m − 5.300.000) × 0,40` |

Kaynak: GV Genel Tebliği **332**, RG 31.12.2025 sayı 33124 (5. mükerrer).

🔴 **ÜCRET tablosudur** (bordro = ücret geliri). Ücret DIŞI tablo 3. dilimden
itibaren AYRIŞIR (1.000.000 / 232.500 / 1.737.500) ve **BASILMAZ** — bordroda
kullanılmıyor, uydurulmaz (WORKFLOW §3). `income_kind` ayrımı yine de ŞİMDİ
modellenir (K5): kolonu sonradan eklemek geçmiş tohumu belirsizleştirirdi
("bu satır hangi tabloydu?").

🔴 **Tarife YDO'dan (%25,49) TÜRETİLMEZ** — ölçüldü: 158.000 → 190.000 = +%20,25,
mekanik bir yeniden değerleme değil. Yayımlanmış değerler SABİTLENİR.

## 2026 asgari ücret (Komisyon Kararı 2025/1, RG 26.12.2025)

Brüt **33.030,00** · net **28.075,50**.

🔴 **Net BURAYA YAZILMAZ, TÜRETİLİR.** `33.030 − %14 SGK (4.624,20) − %1 işsizlik
(330,30) = 28.075,50` ve bu aynı zamanda gelir vergisi MATRAHIDIR; vergi ile
damganın TAMAMI istisnaya girdiği için matrah = net olur. Net sabit olarak
yazılsaydı ikinci bir gerçek kaynak doğar ve oran değişince sessizce çelişirdi.

## İstisna tablosu KASTEN YOKTUR

Oca-Haz 4.211,33 · Tem 4.537,75 · Ağu-Ara 5.615,10 değerleri buraya SABİT
olarak yazılmaz: onlar brüt asgari ücret + oran seti + tarifenin TÜREVİDİR
(MK-2 kanonu — türev para snapshot'lanır, sabitlenmez) ve
`income_tax.minimum_wage_income_tax_credit` tarafından hesaplanır. Sabitlenselerdi
oran ya da tarife değiştiğinde sessizce yanlış kalırlardı.
"""

from decimal import Decimal

#: Tohumun kapsadığı TEK yıl. 2027 KASTEN yoktur: tarife yıllıktır ve mevzuat
#: icat edilmez (K1). Dilim seti olmayan yıl fail-closed'dur (K3) — satır
#: `uncomputed` kalır, 0 vergi YAZILMAZ.
TAX_BRACKET_SEED_YEAR = 2026

#: Tohumlanan TEK gelir türü (K5). `non_wage` modellenir ama BASILMAZ.
WAGE_INCOME_KIND = "wage"

#: `(ordinal, upper_bound, rate_pct)` — `upper_bound is None` yalnız SON dilimde.
#: Sıra ANLAMLIDIR ve `ordinal` ile ayrıca sabitlenmiştir.
TAX_BRACKETS_2026_WAGE: tuple[tuple[int, Decimal | None, Decimal], ...] = (
    (1, Decimal("190000.00"), Decimal("15.000")),
    (2, Decimal("400000.00"), Decimal("20.000")),
    (3, Decimal("1500000.00"), Decimal("27.000")),
    (4, Decimal("5300000.00"), Decimal("35.000")),
    (5, None, Decimal("40.000")),
)

#: Brüt asgari ücret — istisnanın (gelir + damga) TEK girdisi.
MINIMUM_WAGE_GROSS_2026 = Decimal("33030.00")
