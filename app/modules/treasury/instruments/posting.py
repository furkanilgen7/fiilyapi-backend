"""🔴 ODM-1 — ÇEK/SENET AİLESİNİN FİŞİ: rol/hesap eşlemesi (T1 kapsamı).

Bu dosya bugün YALNIZ **veri**dir: `source_type` üyesi + `posting_rules`
tohumunun ürün kaynağı. Fişi ÜRETEN kod (`lines_for` · `post_instrument` ·
storno) bir sonraki adımda buraya gelir; şu an yazılsaydı çağıranı olmayan bir
dal doğar ve hiçbir bekçi onu ölçemezdi (*"çağıran kod yoksa kök bekçisizdir"*
kanonu).

## NE DEĞİŞTİ — MU-3C'nin kararı ODM-1'de TERSİNE DÖNDÜ

MU-3C *"çek/senet durum geçişleri fiş ATMAZ"* demişti ve gerekçesini ÜÇ ölçüme
dayandırmıştı: (1) nakdin tek tanımı `Σ payments`tı, (2) bağlı çekte çift sayım
kesindi, (3) `JournalSourceType`ta üye YOKTU. Aynı bölüm son paragrafında
doğrusunun `101`/`103` ara hesapları olduğunu ve bunun **bir ÜRÜN KARARI**
olduğunu da yazıyordu. ODM-1 o kararı verir ve üç dayanağı da kaldırır:

* nakit tanımı `balance.py`de SÜZGEÇ kazanır — bağlı bir ödeme nakde ancak
  enstrüman `collected`/`paid` iken girer;
* dolayısıyla çift sayım **yapısal olarak** imkânsızdır: portföydeki çekin
  ödemesi nakitten DÜŞÜLMÜŞTÜR, tahsil fişi onu geri KOYAR — toplam bir kez
  sayılır, iki kez değil;
* üye `f5a6b7c8d9e0` migration'ıyla açılmıştır.

## ÜYE = TABLO

`source_type = financial_instrument`, `source_id = financial_instruments.id`.
`uq_journal_entries_source` bu çift üzerinde tekildir: bir enstrümanın CANLI
fişi EN FAZLA BİR TANEDİR ve terminalden çıkış olmadığı için ikinci bir geçiş
zaten doğamaz.

## 🔴 DÖRT ROL — ve neden bu dördü

    B 102/100 Banka/Kasa       A 101 Alınan Çekler        (alınan çek TAHSİL)
    B 103 Verilen Çekler (-)   A 102/100 Banka/Kasa       (verilen çek ÖDENDİ)

* `instrument_receivable` (**101**) / `instrument_payable` (**103**) — ödeme
  fişinin nakit bacağının kaydığı ara hesaplar. Burada TERS yönde kapanırlar.
* `bank` (**102**) / `cash` (**100**) — paranın gerçekten indiği yer. İKİ ayrı
  roldür ve `treasury.posting.cash_role_for` ile ÖDEME BAŞINA seçilir: bir
  çeke kasadan ve bankadan ayrı ayrı bağlanmış ödemeler karışıksa tek bir
  nakit rolü hepsini bankaya yazar, mizanda ikisi de "Hazır Değerler" altında
  toplandığı için TOPLAM tutmaya devam eder ve kusur GÖRÜNMEZDİ.

## 🔴 `expense`/`revenue` BU AİLEDE YOKTUR ve OLAMAZ

Gider/hasılat faturanın fişindedir (MU-3B), cari kapanışı ödemenin fişindedir
(MU-3C). Çek tahsili yalnızca paranın YERİNİ değiştirir — sonuç hesaplarına
DOKUNMAZ. Bir sonuç rolü burada tanımlı olsaydı bir bacak ona düşebilir, fiş
yine dengeli kalır ve mizan DOĞRU görünürdü. Fail-closed olan taraf
tanımsızlıktır: `post_document` çözemediği rolde **422** verir ve fişi YARIM
YAZMAZ. Bekçisi `test_mu3c_posting_rules.py` içindedir (MU-3C'nin aynı
iddiasının kardeşi).

## 🔴 `120`/`320` DE YOKTUR

Cari hesap ödeme fişinde ZATEN kapanmıştır. Burada yeniden kapatılsaydı alacak
İKİ KEZ kapanır ve müşteri borcu negatife düşerdi. `returned`/`cancelled`
hâlinde cariyi yeniden AÇAN şey de bu aile değil, ödeme fişinin STORNOSUDUR
(D6 — `treasury.posting.reverse_payment` ÇAĞRILIR, KOPYALANMAZ).

## KARAR-2 · ALT HESAP AÇILMAZ (MU-4 mayını)

`101`/`103` ANA hesaplardır. Alt hesap açıldığı an ana hesaba bakan kural
`validation.leaf_blockers`tan **422** alır; MU-4 o gün `posting_rules`ın
SATIRINI günceller, bu dosya değişmez.
"""

from app.modules.accounting.models import JournalSourceType
from app.modules.treasury.posting import (
    ROLE_BANK,
    ROLE_CASH,
    ROLE_INSTRUMENT_PAYABLE,
    ROLE_INSTRUMENT_RECEIVABLE,
)

__all__ = ["INSTRUMENT_POSTING_RULES", "SOURCE_TYPE"]

#: `journal_entries.source_type` üyesi — üye = TABLO (`financial_instruments`).
SOURCE_TYPE = JournalSourceType.financial_instrument

#: 🔴 TOHUMUN KAYNAĞI — `(role_key, hesap kodu)`. ÇALIŞMA ZAMANI EŞLEMESİ
#: DEĞİLDİR: `post_document` hesabı DAİMA `posting_rules` tablosundan okur.
#: Buradaki kodlar yalnızca migration'ın tohumladığı satırların kaynağıdır ve
#: iki katmanın birebir aynı olduğunu bir test AST ile iddia eder (MU-3B deseni).
#:
#: 🔴 Rol adları `treasury.posting`ten IMPORT EDİLİR, yeniden YAZILMAZ: iki
#: ailenin `instrument_receivable` rolü AYNI `101` hesabını gösterir ve iki ayrı
#: metin sabiti, birinde yapılan bir yazım düzeltmesini ötekine taşımazdı —
#: `posting_rules`ın anahtarı `(source_type, role_key)` olduğu için sessizce
#: ÇÖZÜLEMEYEN bir rol doğar ve fişleme **422**ye düşerdi.
#:
#: Sıra rol adına göre alfabetiktir (`PAYMENT_POSTING_RULES` deseni).
INSTRUMENT_POSTING_RULES: tuple[tuple[str, str], ...] = (
    (ROLE_BANK, "102"),
    (ROLE_CASH, "100"),
    (ROLE_INSTRUMENT_PAYABLE, "103"),
    (ROLE_INSTRUMENT_RECEIVABLE, "101"),
)
