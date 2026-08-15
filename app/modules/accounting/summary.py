"""Yevmiye KPI şeridi (MU-1 spec §7) — `GET /journal-entries/summary`, E8:79-88.

`invoicing/summary.py` ve `procurement/summary.py`nin kardeşi ve aynı sebeple
AYRI dosyadadır: bu modül hiçbir kaydı DEĞİŞTİRMEZ, yalnızca sayar.

## Üç kart (E8 etiketleri birebir)

| Kart | Alan | Tanım |
|---|---|---|
| E8:80 "Toplam Borç" | `total_debit` | dönemdeki satırların `Σ debit` |
| E8:84 "Toplam Alacak" | `total_credit` | dönemdeki satırların `Σ credit` |
| E8:88 "Net Bakiye" | `net_balance` | 🔴 **ALACAK − BORÇ** |

🔴 **Yön KANITLIDIR, tercih değildir:** E8:88 `4.120.000 − 3.842.600 = 277.400`
tam tutar ve bu, E8'deki tek göstermelik-olmayan aritmetiktir (koşan bakiye
sütunu hiçbir aritmetiği tutmaz). Ters yazılsaydı ekran her ay işaretini ters
basar ve hiçbir kolon farkı bunu ele vermezdi — üç sayı da TÜREVDİR.

## 🔴 Süzgeç: yalnız DÖNEM

`account_id` ALINMAZ (spec §1b/§7). E8:72'de KPI şeridi tablonun ve filtre
çubuğunun **DIŞINDADIR**, dönem seçiciyle aynı satırdadır — yani hesap seçimi
kartları oynatmaz (FAT-1 `summary.py`de aynı karar, aynı gerekçe).

## 🔴 Hangi fişler sayılır

`balance.POSTING_STATUSES` — TEK KOPYA. `draft` GİRMEZ (yarım bırakılmış bir fiş
KPI'yı kirletmemelidir), `reversed` GİRER: kayıtlaştırılmış fiş defterden ÇIKMAZ,
yalnız ters kaydıyla nötrlenir. Yalnız `posted` sayılsaydı stornolanmış bir ay
KPI'sı `−orijinal` kadar kayardı (R6).

## Ay penceresi

Varsayılan dönem `app/core/timezone.today()`nin ayıdır (🔴 K6 SINIR ÇAĞRISI).
`date.today()` sunucunun yerel saatini (Railway'de UTC) okurdu ve TR gecesi
00:00-03:00 arasında ayın ilk/son günü BİR GÜN kayardı. Sorgu dönem KOLONLARI
üzerinden koşar (`ix_journal_entries_period`), tarih aralığı üzerinden değil:
`ck_journal_entries_period_matches_date` ikisinin ayrışmasını zaten engeller ve
dönem kolonları indekslidir.

Bu modül BAŞKA BİR MODÜLÜ IMPORT ETMEZ.
"""

from decimal import Decimal

from sqlalchemy import func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounting.balance import POSTING_STATUSES, ZERO
from app.modules.accounting.models import JournalEntry, JournalLine
from app.modules.accounting.schemas import JournalSummaryResponse

__all__ = ["build_summary"]


async def build_summary(session: AsyncSession, *, year: int, month: int) -> JournalSummaryResponse:
    """Üç KPI'ı **TEK** sorguyla kurar.

    İki toplam AYNI ifadede okunur; ayrı sorgulara bölünseydi biri süzgeci alır
    öteki almaz ve net, iki farklı kümenin farkı olurdu.

    🔴 `COALESCE` ŞARTTIR: satırı olmayan bir ayda `SUM()` **NULL** döner, `0`
    değil — kart `₺0,00` yerine BOŞ basardı (R12). Ve boş ay, sistemin ilk
    ayında ve her yeni dönemde NORMAL hâldir.
    """
    stmt = (
        select(
            func.coalesce(func.sum(JournalLine.debit), literal(ZERO)).label("total_debit"),
            func.coalesce(func.sum(JournalLine.credit), literal(ZERO)).label("total_credit"),
        )
        .select_from(JournalLine)
        .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
        .where(
            JournalEntry.status.in_(POSTING_STATUSES),
            JournalEntry.period_year == year,
            JournalEntry.period_month == month,
        )
    )
    toplam_borc, toplam_alacak = (await session.execute(stmt)).one()

    return JournalSummaryResponse(
        year=year,
        month=month,
        total_debit=Decimal(toplam_borc),
        total_credit=Decimal(toplam_alacak),
        # 🔴 ALACAK − BORÇ (E8:88 aritmetiğinden birebir). TEK yerde kurulur:
        # istemciye bırakılsaydı her ekran kendi işaretini seçerdi.
        net_balance=Decimal(toplam_alacak) - Decimal(toplam_borc),
    )
