"""TDHP grubu → mali tablo kalemi haritası (MT-1 T3) — 🔴 **SAF** modül.

`codes.py` emsali: bu dosya **DB bilmez, Pydantic bilmez, `today` bilmez**.
Girdisi bir hesap KODU, çıktısı bir kalem ANAHTARIDIR. Böyle olması bilinçlidir
— Bilanço (`balance_sheet.py`), Nakit Akış Tablosu (`cash_flow_statement.py`)
**ve ileride Gelir Tablosu** aynı eşlemeyi okur; üç yerde ayrı ayrı yazılsaydı
biri `19`u aktifte, öteki pasifte sayar ve **`AKTİF ≠ PASİF`** çıkardı.

Ölçülen gerçek: repoda kod-aralığı eşleme tablosu **HİÇ YOKTU**. `codes.py`
yalnız `class_code()` (ilk hane) ve `level()` verir. 🔄 (MU-SEED T5) Hesap planı
artık `e5f6a7b8c9d0` migration'ıyla tohumlanır — 56 grup (`NN`) + 260 ana hesap
(`NNN`), 316 satır — ama bu tohum bir HARİTA YAZMAZ, yalnız kod/ad/tür/kontra
taşır. Harita hâlâ hiçbir kayıttan türetilemez — TDHP'den YAZILMAK zorundadır.

## 🔴 Anahtar İKİ HANELİ GRUPTUR, ilk hane DEĞİL

Mockup'ın kalemleri (`Kasa ve Bankalar` · `Ticari Alacaklar` · `Stoklar`) tek
haneyle ayrılamaz: üçü de SINIF 1'dedir (HP:69). `codes.class_code()` bu iş için
yetersizdir ve **DEĞİŞTİRİLMEZ** (mizan/hesap planı onu kendi anlamıyla
kullanıyor); burada kendi türeticisi vardır. Üç kod biçimi de (`NN` · `NNN` ·
`NNN.NN`) `code[:2]` ile aynı grubu verir.

## Üç bağlayıcı kural (MT-K1)

1. 🔴 **KDV NETLEŞTİRİLMEZ.** `19x` (İndirilecek) **aktifte**
   (`Diğer Dönen Varlıklar`), `39x` (Hesaplanan) **pasifte** (`Vergi Borçları`)
   kalır. Netleştirme bir mali tablo kararıdır ve mockup söylemiyor.
2. 🔴 **`59` grubu (Dönem Net Kârı) bilanço GÖVDESİNE girmez.** `Dönem Net Kârı`
   kalemi DAİMA `6xx`/`7xx`ten türer (`period_profit()`). `59` bir KAPANIŞ
   hesabıdır ve üründe kapanış akışı yoktur; ikisi birden sayılsaydı kapanış
   fişi atılmış bir dönemde kâr İKİ KEZ görünürdü.
3. 🔴 **`101 Alınan Çekler` ölçülmüş bir mockup tutarsızlığıdır.** TDHP'de grup
   `10`dadır ama mockup'ın `Kasa ve Bankalar` rakamı (4.249.500 = `100`+`102`)
   onu içermez ve `Diğer Dönen Varlıklar` (768.520 = `191`) de içermez — yani
   mockup'ta HİÇBİR satıra girmiyor. **TDHP grubu KAZANIR** (rakam
   göstermeliktir, KURALLAR §9): `101` → `Kasa ve Bankalar`.
   ⚠️ Açık borç: etiket çeki kapsamıyor, `Hazır Değerler` daha doğru olurdu.

## Görünmezlik yasağı

Haritaya girmeyen bir hesap **sessizce düşemez**: düşseydi `AKTİF ≠ PASİF` olur
ve kullanıcı sebebini GÖREMEZDİ. `10`–`58` arasındaki her grup AÇIKÇA
haritalıdır; TDHP dışı gruplar (`8x` serbest, `9x` nazım) doğal bakiye
yönlerine göre mockup'ın mevcut `Diğer …` kalemlerine düşer. Kalem SAYISI
(4+2 / 3+1+3 = 13) mockup'tan gelir ve **artırılmaz** — icat edilmiş bir 14.
kalem tasarım otoritesini aşardı.

## Kaynak notları

`GROUP_SOURCE_NOTES` her grubun TDHP adını ve bağlandığı mockup satırını taşır.
Notsuz girdi yasaktır: "bu neden burada?" sorusu cevapsız kalırsa harita gözden
geçirilemez ve bir sonraki dilim onu tahminle büyütür.

## 🔴 Paket yapısı (TB-REFACTOR) — davranış DEĞİŞMEDİ

Dosya 796 satıra ulaşmıştı (tavan 800). COHESION'a göre dörde bölündü; hiçbir
uç, hiçbir SQL, hiçbir kalem anahtarı değişmedi. Dış imza KORUNDU: her isim
`app.modules.accounting.statement_map`ten aynen ithal edilmeye devam eder.

* `core.py` — paylaşılan çekirdek: `group_of` · üç yapı taşı ·
  `INCOME_STATEMENT_CLASSES` / `EXCLUDED_INCOME_STATEMENT_GROUPS` ·
  `period_profit()` (Bilanço ve Gelir Tablosu AYNI formülü okur, TEK KOPYA);
* `balance_sheet_map.py` · `cash_flow_map.py` · `income_statement_map.py` —
  üç tablonun kendine özgü iskeleti + haritası. Üçü YALNIZ `core`a bağlıdır,
  birbirlerini ithal ETMEZLER.

🔴 **Paket içi ithaller GÖRELİDİR** (`from .core import …`) ve bu, deponun
mutlak-ithal alışkanlığından BİLİNÇLİ bir sapmadır: modülün SAFLIK bekçisi
(`test_modul_SAFTIR_db_pydantic_takvim_bilmez`) kaynakta `app` adının
geçmemesini şart koşar. Göreli ithal, paketin dört dosyasının da o yasağı
sürdürmesini sağlar.
"""

# 🔴 `X as X` biçimi BİLİNÇLİDİR: açık yeniden-ihraç (PEP 484) — hem ruff'un
# F401'ini `noqa` olmadan susturur hem de `_INCOME_STATEMENT_FALLBACK` gibi
# `__all__`e girmeyen (ama testin okuduğu) adı da kapsar.
from .balance_sheet_map import (
    BALANCE_SHEET_GROUPS as BALANCE_SHEET_GROUPS,
)
from .balance_sheet_map import (
    BALANCE_SHEET_SIDES as BALANCE_SHEET_SIDES,
)
from .balance_sheet_map import (
    EXCLUDED_BALANCE_SHEET_GROUPS as EXCLUDED_BALANCE_SHEET_GROUPS,
)
from .balance_sheet_map import (
    GROUP_SOURCE_NOTES as GROUP_SOURCE_NOTES,
)
from .balance_sheet_map import (
    PERIOD_PROFIT_LINE as PERIOD_PROFIT_LINE,
)
from .balance_sheet_map import (
    RETAINED_EARNINGS_LINE as RETAINED_EARNINGS_LINE,
)
from .balance_sheet_map import (
    balance_sheet_line_for as balance_sheet_line_for,
)
from .cash_flow_map import (
    CASH_FLOW_GROUPS as CASH_FLOW_GROUPS,
)
from .cash_flow_map import (
    CASH_FLOW_SECTIONS as CASH_FLOW_SECTIONS,
)
from .cash_flow_map import (
    CASH_GROUP as CASH_GROUP,
)
from .cash_flow_map import (
    cash_flow_line_for as cash_flow_line_for,
)
from .core import (
    EXCLUDED_INCOME_STATEMENT_GROUPS as EXCLUDED_INCOME_STATEMENT_GROUPS,
)
from .core import (
    INCOME_STATEMENT_CLASSES as INCOME_STATEMENT_CLASSES,
)
from .core import (
    StatementLine as StatementLine,
)
from .core import (
    StatementSection as StatementSection,
)
from .core import (
    StatementSide as StatementSide,
)
from .core import (
    group_of as group_of,
)
from .core import (
    period_profit as period_profit,
)
from .income_statement_map import (
    _INCOME_STATEMENT_FALLBACK as _INCOME_STATEMENT_FALLBACK,
)
from .income_statement_map import (
    COST_REFLECTION_ACCOUNTS as COST_REFLECTION_ACCOUNTS,
)
from .income_statement_map import (
    COST_TRANSFER_ACCOUNTS as COST_TRANSFER_ACCOUNTS,
)
from .income_statement_map import (
    INCOME_STATEMENT_EXPENSE_SECTION as INCOME_STATEMENT_EXPENSE_SECTION,
)
from .income_statement_map import (
    INCOME_STATEMENT_GROUPS as INCOME_STATEMENT_GROUPS,
)
from .income_statement_map import (
    INCOME_STATEMENT_PROFIT_LABEL as INCOME_STATEMENT_PROFIT_LABEL,
)
from .income_statement_map import (
    INCOME_STATEMENT_SECTIONS as INCOME_STATEMENT_SECTIONS,
)
from .income_statement_map import (
    INCOME_STATEMENT_SOURCE_NOTES as INCOME_STATEMENT_SOURCE_NOTES,
)
from .income_statement_map import (
    income_statement_line_for as income_statement_line_for,
)
from .income_statement_map import (
    is_cost_reflection as is_cost_reflection,
)

__all__ = [
    "BALANCE_SHEET_GROUPS",
    "BALANCE_SHEET_SIDES",
    "CASH_FLOW_GROUPS",
    "CASH_FLOW_SECTIONS",
    "CASH_GROUP",
    "COST_REFLECTION_ACCOUNTS",
    "COST_TRANSFER_ACCOUNTS",
    "EXCLUDED_BALANCE_SHEET_GROUPS",
    "EXCLUDED_INCOME_STATEMENT_GROUPS",
    "GROUP_SOURCE_NOTES",
    "INCOME_STATEMENT_CLASSES",
    "INCOME_STATEMENT_EXPENSE_SECTION",
    "INCOME_STATEMENT_GROUPS",
    "INCOME_STATEMENT_PROFIT_LABEL",
    "INCOME_STATEMENT_SECTIONS",
    "INCOME_STATEMENT_SOURCE_NOTES",
    "PERIOD_PROFIT_LINE",
    "RETAINED_EARNINGS_LINE",
    "StatementLine",
    "StatementSection",
    "StatementSide",
    "balance_sheet_line_for",
    "cash_flow_line_for",
    "group_of",
    "income_statement_line_for",
    "is_cost_reflection",
    "period_profit",
]
