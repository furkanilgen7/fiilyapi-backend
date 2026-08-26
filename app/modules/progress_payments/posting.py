"""🔴 MU-3D — İŞVEREN HAKEDİŞİNİN FİŞİ (KDV'SİZ).

## 🔴 BU AİLE ÖTEKİ İKİSİNİN AYNASIDIR — ölçülmüş sapma

Kullanıcı kararının metni *"gider + cari borç"* der. Bu, taşeron ve kira
hakedişi için doğrudur; **işveren hakedişi için TERSİDİR** ve kod ölçülerek
yazılmıştır: `progress_payments` bizim işverene KESTİĞİMİZ hakediştir, yani
bir ALACAK ve bir HASILAT doğurur, bir gider değil.

    B 120 Alıcılar          = taban
    A 600 Yurt İçi Satışlar = taban

Aynı yön `invoicing.posting._outgoing_lines` ile birebir uyumludur (GİDEN
fatura da `120`ye borç, `600`e alacak yazar) ve uyumlu olması ZORUNLUDUR:
bu hakedişten kesilen fatura GİDEN faturadır ve İŞ 2 bu fişi STORNO edip
onunkini yazar. Roller ters yazılsaydı hakediş ile faturası mizanı iki KAT
tutar kadar oynatır ve storno hiçbir şeyi netlemezdi.

## 🔴 FİŞ NE ZAMAN DOĞAR — `transitions.py`den ÖLÇÜLDÜ

    draft ──submit──▶ pending_approval ──approve──▶ approved ──mark-paid──▶ paid
                              ▲                         │
                              └────── unapprove ────────┘
                      pending_approval ──reject──▶ draft

Mali olarak BAĞLAYICI olan geçiş **BİRDİR**: `pending_approval ──approve──▶
approved`. Ötekiler bilinçli olarak dışarıdadır:

* **`submit`** para taşımaz — onaya gönderme bir iş akışı adımıdır.
* **`reject`** kaydı `draft`a geri atar; hiç fişlenmemiştir.
* **`mark-paid`** bir TAHSİLATTIR, bir hakediş olayı değil. Nakit bacağı
  (`102`/`100`) Hazine diliminindir (MU-3C) ve oradan yazılır. Buradan fiş
  atılsaydı aynı hakediş İKİ KEZ hasılat yazardı.

🔴 **KANCA GEÇİŞE DEĞİL BELGEYE BAĞLIDIR** (MU-3C dersi: yanlış kancanın bedeli
bir hata değil bir SESSİZLİKTİR). `approve` eylemi TEK BAŞINA yetmez: onay
zinciri (OK-1A) tamamlanmadıysa `perform` erken döner ve **durum
`pending_approval` KALIR**. Fiş bu yüzden eylemden değil, kaydın `approved`
durumuna FİİLEN geçmesinden doğar — `transitions.perform` fişlemeyi
`payment.status = new_status` damgasından SONRA çağırır.

## 🔴 GERİ ALMA = STORNO (KARAR-5)

`unapprove` (`approved → pending_approval`) kaydı kümülatif kümeden ÇIKARIR.
Fişi ayakta bırakmak, onaylı olmayan bir hakedişin hasılatını mizanda
tutmak olurdu. `reverse_progress_payment` bu yüzden `unapprove` dalında
koşar. Yeniden onay SERBESTTİR: tekillik `WHERE status <> 'reversed'` ile
CANLI fişlere daraltılmıştır (MU-3B), yani stornolanan belge yeniden fişlenir.

## 🔴 TUTAR YAZILDIĞI ANDA DONAR — FİŞİN KENDİSİ SNAPSHOT'TIR

Bu ailede para SAKLANMAZ (K3 türev ilkesi: `progress_payments`ta tutar kolonu
YOKTUR). Çarpanların bir kısmı satırda donmuştur (`contract_unit_price` ·
`coefficient` · `quantity`) ve oranlar başlıkta (`vat_pct` · `advance_pct` ·
`retainage_pct`) — ama **avans mahsubu BAYATLAR** ve bu ölçülmüştür:

* `contract_amount` = `project_contracts.amount`, her okumada **CANLI** okunur;
* `advance_recovered` = önceki hakedişlerin **zincirleme** kümülatifi
  (`calculations.cumulative_state`, `sequence_no` sırasına bağlı).

İkisi de fiş yazıldıktan SONRA değişebilir. MK-2 kanonu (*"türev para N
çarpandan oluşuyorsa snapshot N'in HEPSİNİ kapsar"*) bir snapshot ister ve
deponun bu aile için MEVCUT bir snapshot deseni **YOKTUR** (ölçüldü: `net`,
`gross`, `advance_recovered` — hiçbirinin kolonu yok).

👉 **Bu dilimde snapshot FİŞİN KENDİSİDİR ve bu AÇIKÇA seçilmiştir.**
`journal_lines.debit`/`credit` yazıldığı anda donar ve bir daha ASLA yeniden
hesaplanmaz. Sözleşme bedeli sonradan düzeltilirse hakediş EKRANI yeni bir net
gösterir ama MİZAN onayın alındığı andaki gerçeği gösterir — ve doğru olan
budur: mali iz, kararın alındığı andaki büyüklüktür. Bu ayrışma bir kusur
değil, iki yüzeyin FARKLI sorulara cevap vermesidir (MU-3C'nin `cash_flow`
ayrımıyla aynı cins). Bir tutar kolonu AÇMAK bu dilimde YAPILMAZ: şema kararı
ayrı bir dilimin işidir.

## KARAR-1 / KARAR-2

Hesap kodları BU DOSYADA DEĞİL `posting_rules` tablosundadır; aşağıdaki
`PROGRESS_PAYMENT_POSTING_RULES` yalnız TOHUMUN kaynağıdır.
"""

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounting import state_service as accounting_state_service
from app.modules.accounting.models import JournalSourceType
from app.modules.accounting.transitions import JournalAction
from app.modules.posting import repository as posting_repository
from app.modules.posting import service as posting_service
from app.modules.posting.service import PostingLine, PostingOutcome
from app.modules.progress_payments import calculations
from app.modules.progress_payments.models import ProgressPayment
from app.modules.users.models import User

__all__ = [
    "PROGRESS_PAYMENT_POSTING_RULES",
    "ROLE_RECEIVABLE",
    "ROLE_REVENUE",
    "SOURCE_TYPE",
    "description_for",
    "lines_for",
    "post_progress_payment",
    "reverse_progress_payment",
]

#: `journal_entries.source_type` üyesi — üye = TABLO (`progress_payments`).
SOURCE_TYPE = JournalSourceType.progress_payment

#: 🔴 Roller `invoicing.posting`in GİDEN rolleriyle AYNI ADI taşır ve bu
#: ÇAKIŞMA DEĞİLDİR: `posting_rules`ın anahtarı `(source_type, role_key)`dir.
#: Aynı adı taşımaları bilinçlidir — ikisi de AYNI hesabı gösterir ve farklı
#: adlandırmak, iki ailenin aynı hesaba yazdığını okuyucudan gizlerdi.
ROLE_RECEIVABLE = "receivable"
ROLE_REVENUE = "revenue"

#: 🔴 TOHUMUN KAYNAĞI — `(role_key, hesap kodu)`. ÇALIŞMA ZAMANI EŞLEMESİ
#: DEĞİLDİR: `post_document` hesabı DAİMA `posting_rules` tablosundan okur.
#: İki katmanın birebir aynı olduğunu bir test AST ile iddia eder.
PROGRESS_PAYMENT_POSTING_RULES: tuple[tuple[str, str], ...] = (
    (ROLE_RECEIVABLE, "120"),
    (ROLE_REVENUE, "600"),
)

_ZERO = Decimal("0")


def description_for(payment: ProgressPayment, employer_name: str | None) -> str:
    """`3. Hakediş — Güneşkent İnşaat A.Ş.`

    🔴 TUTAR metne GİRMEZ (HZ-1 kanonu): metin donmuş bir kopyadır ve fişin
    kendi kolonlarıyla çelişebilirdi. İşveren adı `projects.employer_name`
    SNAPSHOT'undan okunur (cari kartından DEĞİL): kart sonradan düzeltilse bile
    fişin metni hakedişi anlatmalıdır.
    """
    taraf = (employer_name or "").strip()
    baslik = f"{payment.sequence_no}. Hakediş"
    return f"{baslik} — {taraf}" if taraf else baslik


def lines_for(base: Decimal) -> list[PostingLine]:
    """İKİ bacak — sıra SABİTTİR (borç önce, alacak sonra).

    🔴 Süzgeç YOKTUR (`invoicing.posting.lines_for`in aksine) ve gerekmez:
    çağıran sıfır/negatif tabanı zaten FİŞLEMEZ, yani `(0, 0)` bacağı buraya
    HİÇ ULAŞMAZ. Bir süzgeç yazılsaydı hiçbir zaman koşmayan bir dal, okuyucuya
    var olmayan bir hâli varmış gibi gösterirdi.
    """
    return [
        PostingLine(role_key=ROLE_RECEIVABLE, debit=base),
        PostingLine(role_key=ROLE_REVENUE, credit=base),
    ]


def posting_base_for(
    payment: ProgressPayment, contract_amount: Decimal | None, advance_recovered: Decimal
) -> Decimal:
    """Fişin KDV'siz tabanı — `calculations.posting_base`in ÇAĞRISI.

    Aritmetik BURADA TEKRARLANMAZ: ikinci bir kopya bir gün ayrışır ve mizan
    ile hakediş ekranı sessizce farklı iki büyüklük gösterirdi.
    """
    gross = calculations.gross_total(payment.lines)
    advance = calculations.advance_or_uncapped(
        gross, payment.advance_pct, contract_amount, advance_recovered
    )
    retention = calculations.retention_amount(gross, payment.retainage_pct)
    return calculations.posting_base(gross, advance, retention)


async def post_progress_payment(
    session: AsyncSession,
    actor: User,
    payment: ProgressPayment,
    *,
    base: Decimal,
    entry_date: date,
    employer_name: str | None,
) -> PostingOutcome | None:
    """Hakedişi fişler. `None` = *"fişlenecek para yok"*.

    🔴 COMMIT ETMEZ: çağıranın (`transitions.perform`) kendi transaction'ında
    koşar. Durum damgası ile fiş AYNI transaction'da yazılmalıdır, aksi hâlde
    "onaylı ama fişsiz" (ya da tersi) bir hakediş doğardı.

    🔴 `base <= 0` FİŞLENMEZ: `ck_journal_lines_single_side` `(0, 0)` bacağını
    reddeder ve K1'in ikinci engeli (`MIN_LINES_REQUIRED`) satırsız fişe **422**
    verirdi — o 422 kullanıcının ONAYINI bloklardı. Satırı olmayan (henüz
    doldurulmamış) bir hakediş normal hâldir.
    """
    if base <= _ZERO:
        return None
    return await posting_service.post_document(
        session,
        actor,
        source_type=SOURCE_TYPE,
        source_id=payment.id,
        entry_date=entry_date,
        description=description_for(payment, employer_name),
        lines=lines_for(base),
    )


async def reverse_progress_payment(
    session: AsyncSession, actor: User, payment_id: uuid.UUID
) -> bool:
    """🔴 KARAR-5 — hakedişin CANLI fişini STORNO eder. `True` = storno YAZILDI.

    `treasury.posting.reverse_payment`in kardeşidir; gerekçeler oradadır. Fiş
    SİLİNMEZ ve `draft`a DÖNDÜRÜLMEZ: orijinal `posted → reversed` olur, ters
    bacaklı YENİ bir fiş doğar ve net TAM sıfırlanır
    (`balance.POSTING_STATUSES` ikisini de sayar).

    `False` iki meşru hâli birden taşır ve ikisi de sessiz bir `pass` olmamalıdır:
    MU-3D ÖNCESİ onaylanmış hakedişlerin fişi hiç doğmadı, ve tabanı sıfır olan
    bir hakediş de hiç fişlenmedi.

    🔴 Storno fişi **BUGÜNE** yazılır (`state_service._build_reversal`) ve o ayın
    dönemi kapalıysa **409** alır — geri alma GERÇEKLEŞMEZ. İstenen budur:
    kapalı bir ayın mali izini sessizce oynatan bir geri alma KARAR-6'yı delerdi.
    """
    entry = await posting_repository.entry_for_source(session, SOURCE_TYPE, payment_id)
    if entry is None:
        return False
    await accounting_state_service.perform_transition(
        session, actor, entry.id, JournalAction.reverse
    )
    return True
