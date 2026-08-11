"""Hakediş satırı ↔ şantiye günlüğü köprüsünün YAZMA yolundaki yüzü (TB4 B1).

## Neden ayrı bir modül, neden ikinci bir sorgu YOK

`quantity_source=diary` damgası (SD-2, kullanıcı kararı 2026-08-03) satırın
miktarını "hakedişin dönemine ait **gönderilmiş** günlüklerin poz-bazlı toplamı"
ile karşılaştırır. Bu toplamın TEK kaynağı `repository.employer_suggestion_rows`
/ `repository.subcontractor_suggestion_rows`tır — "günlükten doldur" öneri
uçlarının (`suggestion.py`) okuduğu AYNI sorgular.

İkinci bir toplama açılsaydı ekran ile damga ayrışırdı: kullanıcı "günlükten
doldur" düğmesinin verdiği gövdeyi hiç değiştirmeden kaydettiğinde satır
`manual` damgalanabilirdi. Bu modül yalnız o satırları **arama tablosuna**
çevirir; süzgeç (yalnız `submitted`, dönem, köprü, `HAVING SUM > 0`) sorgunun
kendi gövdesinde KALIR.

`QuantitySource` enum'u burada BİLEREK kullanılmaz: bu modül `progress_payments`
paketine bağlanmaz (import çemberi), yalnız "eşleşiyor mu" sorusunu yanıtlar;
enum'a çevirme işi iki hakediş ailesinin kendi yazma yolundadır.
"""

import uuid
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.site_diary import repository

# İşveren hakediş hücresinin kimliği: (contract_item_id, site_id).
EmployerCellKey = tuple[uuid.UUID, uuid.UUID]


async def employer_period_totals(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    year: int | None,
    month: int | None,
) -> dict[EmployerCellKey, Decimal]:
    """(kalem, şantiye) → dönemin gönderilmiş günlük toplamı.

    `year is None` = hakedişin DÖNEMİ YOK. Bu durumda sözlük BOŞ döner: dönemsiz
    bir evrağı tüm zamanların toplamıyla kıyaslamak "bu miktar günlükten geldi"
    iddiasını uydurmak olurdu (süzgeçsiz çağrı `period_conditions`ta "tüm dönem"
    anlamına gelir — okuma ucunda meşru, damgada DEĞİL).
    """
    if year is None:
        return {}
    rows = await repository.employer_suggestion_rows(session, project_id, year=year, month=month)
    return {(contract_item_id, site_id): total for contract_item_id, site_id, total in rows}


async def subcontractor_period_totals(
    session: AsyncSession,
    contract_id: uuid.UUID,
    site_id: uuid.UUID | None,
    *,
    year: int | None,
    month: int | None,
) -> dict[uuid.UUID, Decimal]:
    """Taşeron sözleşme kalemi → dönemin gönderilmiş günlük toplamı.

    `site_id is None` (proje-geneli sözleşme) = köprü YOK — öneri ucunun spec §7
    S5 kuralının yazma-yolu karşılığı: hangi şantiyenin günlüğüne bakılacağı
    belirsizken damga basmak uydurma olurdu.
    """
    if year is None or site_id is None:
        return {}
    rows = await repository.subcontractor_suggestion_rows(
        session, contract_id, site_id, year=year, month=month
    )
    return {item_id: total for item_id, total in rows}


def is_diary_quantity(total: Decimal | None, quantity: Decimal) -> bool:
    """S1 (ONAYLI): **birebir eşitlik**. Kısmi/yaklaşık/fazla eşleşme `diary`
    DEĞİLDİR — yarım eşleşen miktara "günlükten geldi" rozeti basmak, kaynağı
    doğrulanmış sanılan bir sayı üretirdi.

    Kural tek satırdır ama TEK YERDEDİR: iki hakediş ailesi de bunu çağırır.
    """
    return total is not None and total == quantity
