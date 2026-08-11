"""Bakiye ve durum TÜREVİNİN TEK KAYNAĞI (ST T3 — spec §3, §7 S1, §7 S4).

`GET /stock/summary`, `GET /sites/{id}/stock` ve her iki ekranın KPI şeridi
bakiyeyi BURADAN türetir. İkinci bir formül yazılsaydı iki ekran aynı kalem için
farklı sayı gösterir ve hangisinin doğru olduğu anlaşılamazdı.

## ÇİFT BACAK — bu dilimin bir numaralı tuzağı (§7 S4)

`transfer` hareketinde miktar HEDEF depoya artı, KAYNAK depodan eksi yansır.
Tek bacaklı bir transfer YOKTAN STOK YARATIR ve şirket toplamını şişirir.

Türetme **AYNA SATIR YAZMAZ**: kaynak bacağı `legs()` içinde
`source_warehouse_id` üzerinden NEGATİF işaretli ikinci bir SELECT olarak
üretilir ve iki dal `UNION ALL` ile birleşir. Ayna satır yazılsaydı

* hareket başlığı ikiye çıkar (audit "giriş başına tek olay" kuralı kırılır),
* hareket listesi her transferi iki kez basar,
* iki kayıt zamanla birbirinden sapabilirdi (klasik iki-kaynak problemi).

`purchase`/`adjustment` hareketlerinde `source_warehouse_id` NULL'dur, bu yüzden
ikinci dal onları hiç üretmez ve tek bacaklı kalırlar.

## Durum formülü (§7 S1 — kullanıcı onaylı, E3 verisinden türetilmiş)

Eşikler ORAN sabitleridir ve TEK YERDE durur; SQL ifadesi de o sabitlerden
kurulur, sihirli sayı serpilmez. `min_stock` yoksa durum `None`dur (uydurma yok).
"""

import enum
from decimal import Decimal

from sqlalchemy import ColumnElement, Select, case, null, select, union_all

from app.modules.inventory.models import StockEntry, StockEntryLine

# E3'ün yedi örnek satırı bu iki orana BİREBİR oturur (spec §7 S1):
# demir 0,24 · PP-R 0,375 → kritik · NYY 0,8 → düşük · alçı 5,6 → fazla ·
# çimento 4,2 · tuğla 2,48 · beton 4,25 → normal.
CRITICAL_RATIO = Decimal("0.5")
"""`bakiye < CRITICAL_RATIO × min_stock` → kritik."""

EXCESS_RATIO = Decimal("5")
"""`bakiye > EXCESS_RATIO × min_stock` → fazla."""


class StockStatus(str, enum.Enum):
    """Kalemin eşiğe göre durumu — **DB kolonu DEĞİL**, türevdir (spec §3).

    E3 rozetleri Kritik/Düşük/Normal/Fazla; ŞS'de "Normal" karşılığı
    **"Yeterli"** diye yazılır (aynı değer, farklı etiket) — iki ekran için ayrı
    değer üretilmez, etiket frontend'in işidir.
    """

    critical = "critical"
    low = "low"
    normal = "normal"
    excess = "excess"


def legs(warehouse_ids: Select):
    """KANONİK bakiye kaynağı: `(warehouse_id, item_id, quantity)` üçlüleri.

    İki dal:
      1. HEDEF bacak — `stock_entries.warehouse_id`, miktar OLDUĞU GİBİ;
      2. KAYNAK bacak — `stock_entries.source_warehouse_id`, miktar NEGATİFİYLE
         (yalnız `source_warehouse_id IS NOT NULL` olan transferler).

    `warehouse_ids` görünürlük süzgecidir (IDOR): kapsam dışı deponun hareketi
    ne bakiyeye ne kırılıma girer. Süzgeç dışarıdan gelir çünkü genel özet
    GÖRÜNEN TÜM depoları, şantiye özeti ise YALNIZ o şantiyenin depolarını
    kapsar (spec §3: merkez depo hiçbir şantiyenin bakiyesine girmez).
    """
    hedef = select(
        StockEntry.warehouse_id.label("warehouse_id"),
        StockEntryLine.item_id.label("item_id"),
        StockEntryLine.quantity.label("quantity"),
    ).join(StockEntryLine, StockEntryLine.entry_id == StockEntry.id)
    kaynak = (
        select(
            StockEntry.source_warehouse_id.label("warehouse_id"),
            StockEntryLine.item_id.label("item_id"),
            (-StockEntryLine.quantity).label("quantity"),
        )
        .join(StockEntryLine, StockEntryLine.entry_id == StockEntry.id)
        .where(StockEntry.source_warehouse_id.is_not(None))
    )
    birlesik = union_all(hedef, kaynak).subquery()
    return (
        select(birlesik.c.warehouse_id, birlesik.c.item_id, birlesik.c.quantity)
        .where(birlesik.c.warehouse_id.in_(warehouse_ids))
        .subquery()
    )


def status_case(balance: ColumnElement, min_stock: ColumnElement) -> ColumnElement:
    """Durum ifadesi — sabitler yukarıdaki İKİ ORANDAN gelir.

    Sıra ANLAMLIDIR ve sınırlar AÇIKTIR (`<` / `>`, `<=` DEĞİL): eşiği TAM
    tutturan kalem bir üst kademededir. `<=` yazılsaydı `bakiye == min_stock`
    olan kalem "düşük" görünür ve satınalma boşuna tetiklenirdi.

    `min_stock` NULL ise üç karşılaştırma da NULL (yani yanlış) döner ve dördüncü
    dal da tutmaz → `else_` ile durum `NULL` olur: eşik yokken durum UYDURULMAZ
    (spec §3). Metin tipini NULL olmayan dallar belirler.
    """
    return case(
        (balance < CRITICAL_RATIO * min_stock, StockStatus.critical.value),
        (balance < min_stock, StockStatus.low.value),
        (balance > EXCESS_RATIO * min_stock, StockStatus.excess.value),
        (min_stock.is_not(None), StockStatus.normal.value),
        else_=null(),
    )
