"""🔴 MU-3A — **OTOMATİK FİŞİN TEK GİRİŞ NOKTASI** (`post_document`).

## Neden TEK bir fonksiyon

MU-3A'dan önce `JournalEntry` yalnız İKİ yerde üretiliyordu (ölçüldü):
`accounting.service.create_entry` (elle kayıt) ve
`accounting.state_service._build_reversal` (storno). Fatura, ödeme, bordro,
hakediş — HİÇBİRİ fiş atmıyordu; muhasebe modülü canlıdaydı ama KENDİ KENDİNE
DOLMUYORDU.

Beş belge ailesi kendi fişini kendi servisinde yazsaydı, beş yerde birden:
dönem kapısı · K1 dengesi · yaprak denetimi · numara üretimi · idempotanlık
kurulurdu. Bu deponun tekrar tekrar ölçtüğü ders tam olarak bunun aleyhindedir
(`validation.balance_blockers`ın "üç yolda birden koşar" notu): bir kapı beş
yere kopyalandığında biri onu ATLAR ve delik YALNIZ O YOLDA açılır.

## Adım sırası — SABİTTİR

    0. KAYNAK KİLİDİ  (belge başına danışma kilidi)
    1. İDEMPOTANLIK   (fişlenmişse MEVCUDU döndür, created=False)
    2. DÖNEM KAPISI   (kilitli okuma → kapalıysa 409)
    3. EŞLEME         (rol → hesap; eksikse 422)
    4. K1 KAPISI      (denge + satır sayısı + yaprak; 422)
    5. YAZIM          (numara → başlık → bacaklar)

🔴 **1, 2'DEN ÖNCEDİR** ve bu bilinçlidir: ay kapandıktan sonra çağıran yeniden
denerse yapılacak bir iş YOKTUR. 409 atmak, hiç yazılmayacak bir fiş yüzünden
onay akışını kilitlerdi. Test bunu çakıyor
(`test_ZATEN_fislenmis_belge_KAPALI_donemde_de_MEVCUDU_doner`).

🔴 **0, 1'DEN ÖNCEDİR**: kilitsiz bir "önce oku, sonra yaz" iki eşzamanlı onayda
ikisini de geçirir ve kaybeden `uq_journal_entries_source`a çarpıp kullanıcıya
ayrımsız bir 409 gösterirdi (İK-2 kanonu: EŞİK = KİLİT).

## Yönetimin bağladığı kararların BU DOSYADAKİ karşılığı

* **KARAR-1** (NORMAL TİCARİ REJİM `740`/`600`) ve **KARAR-2** (CARİ ANA HESAP
  `320`, `320.04` AÇILMAZ) — bu dosyada HİÇBİR HESAP KODU YOKTUR. İkisi de
  `posting_rules` SATIRIDIR; MU-4 kararı değiştirdiğinde kod değişmez.
* **KARAR-3** — fiş `posted` DOĞAR (`draft` doğsaydı mizan yine boş kalırdı).
  `transitions.INITIAL_STATUS` BİLEREK kullanılmaz: o, elle kaydın taslak
  aşamasıdır ve otomatik fişin taslağı YOKTUR.
* **KARAR-5** — geri alma STORNODUR: bu dosya fiş SİLMEZ, `draft`a DÖNDÜRMEZ ve
  bir `unpost_document` AÇMAZ. Çağıran `state_service.perform_transition(...,
  reverse)` kullanır; storno kaynak damgasını taşımaz (gerekçe `models.py`).
* **KARAR-6** (geriye dönük fiş yok) — kod ayağı DÖNEM KAPISIDIR. Öteki ayağı
  (eski belgelerin toplu fişlenmesi) bir KOD KURALI DEĞİL, bir yokluktur: bu
  dilim hiçbir backfill/komut açmaz.
* **KARAR-7** (satınalma ve stok fiş atmaz) — `JournalSourceType`ta o üyeler
  YOKTUR; çağrı DB'ye ulaşmadan tip düzeyinde imkânsızdır.

## Bu dilimde HİÇBİR AİLE BAĞLANMAZ

`post_document`in bugün ÜRÜN İÇİNDE çağıranı yoktur ve bu bir eksiklik değil,
kapsam sınırıdır (MU-3B/C/D/E). 🔴 Bunun ölçülmüş bedeli şudur: *çağıran kod
yoksa kapı bekçisizdir* (paralel frontend turunun BFF dersi). Bu yüzden testler
fonksiyonu DOĞRUDAN çağırır ve her fail-closed dalında "hiçbir şey yazılmadı"
İDDİASI ayrıca tutulur.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounting import numbering, periods_service, service as accounting_service
from app.modules.accounting import validation
from app.modules.accounting.models import (
    ChartAccount,
    JournalEntry,
    JournalEntryStatus,
    JournalLine,
    JournalSourceType,
)
from app.modules.posting import guards, repository
from app.modules.users.models import User

__all__ = ["PostingLine", "PostingOutcome", "post_document"]

_ZERO = Decimal("0")


@dataclass(frozen=True)
class PostingLine:
    """Çağıranın tarif ettiği BİR bacak — hesabı DEĞİL, ROLÜNÜ bilir.

    🔴 Hesap kodu taşımaz ve taşımamalıdır: taşısaydı KARAR-2'nin geri alınması
    (MU-4'te `320` → `320.04`) beş belge ailesinin servis kodunu birden
    değiştirirdi. Rol → hesap çevirisi `posting_rules`tadır.

    `debit`/`credit` çifti `JournalLine` ile AYNI şekildedir (tek taraflı satır,
    `ck_journal_lines_single_side`) — tek bir `amount` + `side` seçilseydi K1'in
    DB kısıtı yazılamazdı (`JournalLine` docstring'i).

    `frozen=True`: bacak kümesi çağıranda kurulur ve burada DEĞİŞTİRİLMEZ;
    mutasyona açık olsaydı tutarlar doğrulama ile yazım arasında kayabilirdi.
    """

    role_key: str
    debit: Decimal = _ZERO
    credit: Decimal = _ZERO


@dataclass(frozen=True)
class PostingOutcome:
    """`created` bir NEZAKET ALANI DEĞİLDİR.

    Çağıran (MU-3B/C/D/E) denetim günlüğüne "fiş kesildi" satırını YALNIZ
    `created=True` iken yazmalıdır; yoksa her yeniden deneme mali izde yeni bir
    fiş kesilmiş gibi görünür ve denetim, olmayan bir işi anlatırdı.
    """

    entry: JournalEntry
    created: bool


@dataclass
class _Cozum:
    """Rol → hesap çözümünün sonucu; eksik roller AYRI taşınır."""

    accounts: list[ChartAccount] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)


def _resolve(lines: Sequence[PostingLine], rules: dict[str, ChartAccount]) -> _Cozum:
    """Bacak SIRASINI KORUYARAK hesapları çözer; eksikleri TOPLAR.

    İlk eksikte durulmaz: altı bacaklı bir fişte eksik eşlemeleri birer birer
    keşfettirmek, her denemede ayrı bir veri düzeltmesi anlamına gelirdi.
    """
    cozum = _Cozum()
    for satir in lines:
        account = rules.get(satir.role_key)
        if account is None:
            cozum.missing.append(satir.role_key)
        else:
            cozum.accounts.append(account)
    return cozum


async def post_document(
    session: AsyncSession,
    actor: User,
    *,
    source_type: JournalSourceType,
    source_id: uuid.UUID,
    entry_date: date,
    description: str,
    lines: Sequence[PostingLine],
    detail_note: str | None = None,
) -> PostingOutcome:
    """Belgeyi fişler. İkinci çağrı YENİ FİŞ ÜRETMEZ.

    Adım sırası ve gerekçeleri modül docstring'indedir; burada TEKRARLANMAZ.

    🔴 COMMIT ETMEZ. Çağıranın kendi transaction'ında koşar: belgenin durum
    damgası ile fiş AYNI transaction'da yazılmalıdır, aksi hâlde "onaylı ama
    fişsiz" (ya da tersi) bir belge doğardı. Bu aynı zamanda danışma kilidinin
    (`_xact_`) çağıranın işlemi boyunca tutulmasını sağlar.
    """
    await repository.lock_source(session, source_type, source_id)

    mevcut = await repository.entry_for_source(session, source_type, source_id)
    if mevcut is not None:
        return PostingOutcome(entry=mevcut, created=False)

    await periods_service.assert_periods_open(session, [periods_service.period_of(entry_date)])

    cozum = _resolve(lines, await repository.rules_for(session, source_type))
    # Eksik eşleme K1'in engelleriyle AYNI 422'de toplanır; hesaplar çözülemeden
    # yaprak denetimi de koşamaz, bu yüzden eksik varsa BURADA durulur.
    accounting_service.raise_blockers(
        [guards.rule_missing(cozum.missing)] if cozum.missing else []
    )
    accounting_service.raise_blockers(
        await validation.balance_blockers(session, lines, cozum.accounts)
    )

    entry = JournalEntry(
        entry_date=entry_date,
        period_year=entry_date.year,
        period_month=entry_date.month,
        description=description.strip(),
        detail_note=detail_note,
        # 🔑 KARAR-3.
        status=JournalEntryStatus.posted,
        total_debit=sum((satir.debit for satir in lines), _ZERO),
        total_credit=sum((satir.credit for satir in lines), _ZERO),
        source_type=source_type,
        source_id=source_id,
        created_by_id=actor.id,
    )
    # 🔑 FIS-NO karar 1 — yıl `period_year` KOLONUNDAN okunur, `entry_date`ten
    # DEĞİL (`accounting.service.create_entry` ile AYNI kaynak).
    entry.entry_no = await numbering.generate_entry_no(session, year=entry.period_year)
    session.add(entry)
    await session.flush()

    session.add_all(
        [
            JournalLine(
                entry_id=entry.id,
                sort_order=sira,
                account_id=account.id,
                debit=satir.debit,
                credit=satir.credit,
            )
            for sira, (satir, account) in enumerate(zip(lines, cozum.accounts, strict=True))
        ]
    )
    await session.flush()
    # `updated_at` SUNUCU damgasıdır; `refresh` olmadan async bağlamda okunması
    # `MissingGreenlet` = 500 üretirdi (P11 dersi).
    await session.refresh(entry)
    return PostingOutcome(entry=entry, created=True)
