"""Fiş DURUM GEÇİŞLERİ + STORNO (MU-1 T3b) — spec §5, §7 yolları 13-14.

`service.py`den AYRI bir dosyadır ve bu bilinçlidir (FAT-1 emsali): o dosya
fişin İÇERİĞİNİ yazar, bu dosya yalnızca `status` damgalar ve ters kaydı üretir.
Tek dosyada toplansalardı 800 satır tavanına doğru itilirdi.

## 🔴 EŞİK = KİLİT — SIRA DEĞİŞMEZ (spec §5, İK-2 kanonu)

    1. KİLİT    — `entry_or_404(..., for_update=True)`
                  (`with_for_update` + **`populate_existing`**)
    2. MATRİS   — `transitions.next_status` → **409**
    3. STORNO KAPILARI — zaten terslenmiş · stornonun stornosu → **409**
    4. K1       — `validation.balance_blockers` → **422** (yalnız `post`)
    5. DAMGA    — `status` yazılır, `reverse` ise storno fişi + bacakları
    6. REFRESH  — `session.refresh(entry)`

**Kilit 2. adımdan SONRA alınsaydı** iki eşzamanlı `post` da `draft` okur, ikisi
de matrisi geçer ve fiş **İKİ KEZ** kayıtlaştırılırdı; iki eşzamanlı `reverse`
ise **İKİ storno** üretirdi ve hesabın bakiyesi (K3) `−orijinal` kadar kayardı —
kaydığını hiçbir kolon farkı ele vermezdi, çünkü bakiye SAKLANMAZ.

`UPDATE`in örtük satır kilidi yazma ANINDA alınır, yani kararın çok geç bir
noktasında. TOCTOU penceresini kapatan tek şey OKUMADAKİ açık `FOR UPDATE`tir ve
`populate_existing` onun ayrılmaz parçasıdır (kimlik haritasındaki bayat nesne
`session.get`i sorgusuz döndürür, kilit HİÇ ALINMAZ).

Bekleyen istek uyandığında kararı YENİDEN verir: taze satırda durum artık
`posted` olduğu için matris `(posted, post)` çiftini tanımaz ve **409** döner.

🔴 **Kilit sırası uçtan uca SABİT: fiş → satırlar → hesap.** Ters sırada
kilitleyen bir yol eklenirse karşılıklı kilitlenme (deadlock) doğar.

## 🔴 Adım 6 neden var

`updated_at` SUNUCU damgasıdır (`onupdate=func.now()`); UPDATE'ten sonra ORM'deki
değer BAYATTIR ve SQLAlchemy onu "expired" işaretler. Yanıt şeması onu okuduğunda
tembel yükleme tetiklenir ve async bağlamda bu **`MissingGreenlet` = 500**
demektir (P11'de birebir yaşandı).

## 🔴 STORNO — YENİ BİR FİŞ (alan değil, bayrak değil)

| Alan | Değer | Gerekçe |
|---|---|---|
| `status` | **`posted`** doğrudan | storno taslak değildir |
| `entry_date` | 🔴 **`timezone.today()`** | **K6 SINIR ÇAĞRISI** (aşağıda) |
| `period_*` | `entry_date`ten | CHECK zorlar |
| `description` | `REVERSAL_PREFIX` + orijinal | önek `guards.py`de TEK kopya |
| `detail_note` | kopya | dayanak aynıdır |
| `reversal_of_id` | orijinalin `id`si | `uq_…_reversal_of` çift stornoyu engeller |
| bacaklar | `debit ↔ credit` TAKAS, `sort_order` KORUNUR | ters kaydın tanımı |
| orijinal | `posted → reversed` | matris |

🔴 **K6:** bu dosya `timezone.today()`yi çağıran TEK sınırdır; `date.today()` /
`datetime.utcnow()` YASAKTIR ve AST bekçisi (`tests/test_local_calendar_guard.py`)
onları anında kırmızıya çevirir. Saf çekirdek (`transitions`, `validation`,
`codes`) `today` bilmez.

## Yeni `AuditAction` üyesi AÇILMADI (TB3/T3 kanonu)

`action` gerçek bir Postgres enum tipidir ve yeni üye MIGRATION ister. İki geçiş
mevcut üyelere oturur: `post → approve` (kayıtlaştırma bir ONAYDIR ve fişi mali
ize sokar), `reverse → update`. Ayrım `messages.*` METNİNDEDİR.
🔴 **TUTAR metne GİRMEZ** (HZ-1 kanonu).
"""

import uuid
from typing import NamedTuple

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError
from app.core.timezone import today
from app.modules.accounting import guards, repository, service, transitions, validation
from app.modules.accounting.models import JournalEntry, JournalEntryStatus, JournalLine
from app.modules.accounting.transitions import JournalAction
from app.modules.audit import messages
from app.modules.audit.models import AuditAction
from app.modules.users.models import User

__all__ = ["TransitionOutcome", "perform_transition"]


class TransitionOutcome(NamedTuple):
    """Geçişin çıktısı — router yalnız bunu denetime yazar ve yanıta çevirir.

    🔴 `entry` YANITA GİDEN fiştir ve `reverse`de bu **STORNO**dur (uç 201 döner
    ve istemcinin görmesi gereken yeni kayıttır), `post`ta ise fişin kendisidir.
    Router'ın bunu ayırt etmesi gerekseydi `if action == …` uca sızardı.

    `audit_action` de burada durur: hangi işlemin hangi `AuditAction`a düştüğü
    bir GEÇİŞ bilgisidir; uçlara dağıtılsaydı iki uç iki farklı karar verebilirdi.
    """

    entry: JournalEntry
    audit_action: AuditAction
    detail: str


#: İşlem → denetim eylemi. **Yeni enum üyesi AÇILMAZ** (modül docstring'i).
_AUDIT_ACTIONS: dict[JournalAction, AuditAction] = {
    JournalAction.post: AuditAction.approve,
    JournalAction.reverse: AuditAction.update,
}


def _assert_reversible(entry: JournalEntry) -> None:
    """Stornonun İKİ ek 409'u (spec §5) — matristen SONRA, damgadan ÖNCE.

    * `reversal_of_id IS NOT NULL` → fiş zaten bir STORNODUR ve terslenemez:
      matris bunu göremez çünkü storno `posted`tır ve `(posted, reverse)` çifti
      GEÇERLİDİR. Zincir açılsaydı sonsuza kadar sürerdi ve mali anlamı yoktur.
    * fişin stornosu zaten var → `uq_journal_entries_reversal_of`un servis
      karşılığı; UNIQUE'e düşseydi kullanıcı ayrımsız bir "Veri bütünlüğü
      hatası" alırdı. UQ emniyet ağı olarak KALIR.

    Sıra bilinçlidir: önce "bu bir stornodur" sorulur, çünkü kullanıcının
    öğrenmesi gereken ilk şey odur.
    """
    if entry.reversal_of_id is not None:
        raise ConflictError(guards.REVERSAL_NOT_REVERSIBLE)


async def _build_reversal(session: AsyncSession, actor: User, entry: JournalEntry) -> JournalEntry:
    """Ters kayıt fişini ve TAKASLI bacaklarını üretir.

    🔴 Tarih **`timezone.today()`**tir (K6 sınır çağrısı): orijinalin tarihi
    kullanılsaydı storno kapalı bir döneme düşerdi. `date.today()` ise sunucunun
    yerel saatini (Railway'de UTC) okur ve TR gecesi 00:00-03:00 arasında bir
    gün geriye kayardı.

    Toplamlar TAKASLA birlikte yer değiştirir: `total_debit ↔ total_credit`.
    Bacaklardan yeniden toplansaydı `apply_totals` ikinci bir çağrı noktası
    kazanır ve takasın doğruluğu iki yerden okunurdu — burada tek kaynak
    ORİJİNALİN toplamlarıdır ve o toplamlar zaten K1'den geçmiştir.
    """
    bugun = today()
    storno = JournalEntry(
        entry_date=bugun,
        period_year=bugun.year,
        period_month=bugun.month,
        description=f"{guards.REVERSAL_PREFIX}{entry.description}",
        detail_note=entry.detail_note,
        status=JournalEntryStatus.posted,
        total_debit=entry.total_credit,
        total_credit=entry.total_debit,
        reversal_of_id=entry.id,
        created_by_id=actor.id,
    )
    session.add(storno)
    await session.flush()

    session.add_all(
        [
            JournalLine(
                entry_id=storno.id,
                sort_order=satir.sort_order,
                account_id=satir.account_id,
                debit=satir.credit,
                credit=satir.debit,
            )
            for satir in await repository.load_lines(session, entry.id)
        ]
    )
    await session.flush()
    await session.refresh(storno)
    return storno


async def perform_transition(
    session: AsyncSession, actor: User, entry_id: uuid.UUID, action: JournalAction
) -> TransitionOutcome:
    """İki geçiş ucunun TEK gövdesi — sıra modül docstring'indedir.

    İki uç için iki fonksiyon yazılsaydı kilidi ya da K1 kapısını birinde
    unutmak mümkün olurdu; işlemler arasındaki tek fark `action` PARAMETRESİDİR
    ve geçerliliği matristen okunur — burada hiçbir `if status == …` yoktur.
    """
    # 1. KİLİT — her şeyden ÖNCE (EŞİK = KİLİT).
    entry = await service.entry_or_404(session, entry_id, for_update=True)

    # 2. MATRİS → 409.
    yeni_durum = transitions.next_status(entry.status, action)

    # 3. Stornoya özel 409'lar (yalnız `reverse` için anlamlı).
    if action is JournalAction.reverse:
        _assert_reversible(entry)
        if await repository.reversal_exists(session, entry.id):
            raise ConflictError(guards.ENTRY_ALREADY_REVERSED)

    # 4. K1 kapısı → 422. Kayıtlaştırma anında YENİDEN koşar: fiş taslakken
    #    yaprak olan bir hesabın altına sonradan çocuk açılmış olabilir ve o fiş
    #    artık deftere girmemelidir (yoksa MU-2 mizanı ÇİFT SAYARDI).
    if action in validation.GATE_ACTIONS:
        satirlar = await repository.load_lines_with_accounts(session, entry.id)
        service.raise_blockers(
            await validation.balance_blockers(
                session,
                [satir for satir, _ in satirlar],
                [hesap for _, hesap in satirlar],
            )
        )

    # 5. DAMGA (+ storno yazımı).
    entry.status = yeni_durum
    yanit = entry
    if action is JournalAction.reverse:
        yanit = await _build_reversal(session, actor, entry)
    await session.flush()

    # 6. REFRESH — `updated_at` sunucu damgasıdır (P11 dersi).
    await session.refresh(entry)

    return TransitionOutcome(
        entry=yanit,
        audit_action=_AUDIT_ACTIONS[action],
        detail=_detail(action, entry),
    )


def _detail(action: JournalAction, entry: JournalEntry) -> str:
    """Denetim metni — ayrım `AuditAction`da DEĞİL burada.

    Metin ORİJİNAL fişin kimliğinden kurulur (storno değil): denetim satırı
    "hangi fişe ne oldu" sorusuna yanıt vermelidir; stornonun kendi doğuşu
    orijinalin `reversed` olmasıyla zaten anlatılır.
    """
    if action is JournalAction.post:
        return messages.journal_entry_posted(entry.entry_date, entry.description)
    return messages.journal_entry_reversed(entry.entry_date, entry.description)
