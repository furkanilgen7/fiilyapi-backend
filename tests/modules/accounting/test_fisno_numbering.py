"""FIS-NO T2 — `numbering.generate_entry_no` birim bekcileri.

T1'in uc bekcileri (`test_fisno_entry_no.py`) numarayi HTTP uzerinden olcer.
Bu dosya ureticinin KENDISINI olcer: T1'in ucundan ulasilamayan iki hâl vardir
ve ikisi de bir KARARI kilitler.

1. **9999 -> bes hane** (karar 1: dort hane TAVAN degil EN AZ genisliktir).
   Uctan olculemez: 9999 fis kesmek gerekirdi. Sayac satiri DOGRUDAN kurulur.
2. **Sayac fislerden BAGIMSIZ yasar** (karar 2): tabloda hic fis olmadan da
   ilerler. `max + 1` tabanli bir uretici burada 1'e donerdi.

⚠️ `EN AZ genislik` bir suslemedir sanilmasin: `SEQUENCE_WIDTH` bir TAVAN
sayilsaydi 9999'dan sonra numara ya BUDANIR (`10000` -> `1000`) ya da basa
donerdi; ikisi de `uq_journal_entries_entry_no` ihlalidir ve mali izde AYNI
numarayi tasiyan iki fis birakirdi.
"""

import re

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounting import numbering
from app.modules.accounting.models import JournalEntryCounter

YIL = 2026

#: T1'in bicim bekcisiyle AYNI ifade (`test_fisno_entry_no.BICIM`): `YEV-` +
#: dort haneli yil + EN AZ dort haneli sira. UST SINIR YOKTUR.
BICIM = re.compile(r"^YEV-\d{4}-\d{4,}$")


async def _sayaci_kur(session: AsyncSession, yil: int, next_no: int) -> None:
    """Sayac satirini DOGRUDAN kurar — 9999 fis kesmenin tek alternatifi."""
    await session.execute(
        pg_insert(JournalEntryCounter)
        .values(year=yil, next_no=next_no)
        .on_conflict_do_update(index_elements=["year"], set_={"next_no": next_no})
    )


async def test_9999dan_sonra_numara_BES_HANEYE_uzar_BUDANMAZ(seeded_db: AsyncSession) -> None:
    """🔴 Karar 1'in ikinci yarisi: dort hane EN AZ genisliktir, TAVAN DEGIL.

    `9999` -> `10000` -> `10001`. Budama (`'1000'`) ya da basa donme (`'0001'`)
    ikisi de tekillik kisitini ihlal ederdi ve kusur ancak 9999. fis kesildikten
    SONRA, canlida gorunurdu.
    """
    await _sayaci_kur(seeded_db, YIL, 9999)

    numaralar = [await numbering.generate_entry_no(seeded_db, year=YIL) for _ in range(3)]

    assert numaralar == ["YEV-2026-9999", "YEV-2026-10000", "YEV-2026-10001"]
    for numara in numaralar:
        assert BICIM.match(numara), numara
    # Sifir dolgusu SOLA yapilir, sag BUDANMAZ: `10000` dort haneye sigmaz.
    assert numaralar[1][-5:] == "10000"


async def test_format_entry_no_yalnizca_DOLDURUR_asla_BUDAMAZ() -> None:
    """Bicim kurali TEK yerdedir; migration'in SQL karsiligi
    `test_fisno_migration` icinde bununla KARSILASTIRILIR."""
    assert numbering.format_entry_no(2026, 1) == "YEV-2026-0001"
    assert numbering.format_entry_no(2026, 214) == "YEV-2026-0214"
    assert numbering.format_entry_no(2026, 9999) == "YEV-2026-9999"
    assert numbering.format_entry_no(2026, 10000) == "YEV-2026-10000"
    assert numbering.format_entry_no(2027, 123456) == "YEV-2027-123456"


async def test_sayac_HIC_FIS_YOKKEN_de_ilerler(seeded_db: AsyncSession) -> None:
    """🔴 Karar 2: sayac fislerden BAGIMSIZ yasar.

    `journal_entries` bu testte BOSTUR. `max(entry_no) + 1` (ya da
    `count(*) + 1`) tabanli bir uretici her cagrida `0001` dondururdu; sayac
    tablosu tek basina ilerler ve numaralar TEKIL kalir.
    """
    ilk = await numbering.generate_entry_no(seeded_db, year=YIL)
    ikinci = await numbering.generate_entry_no(seeded_db, year=YIL)
    ucuncu = await numbering.generate_entry_no(seeded_db, year=YIL)

    assert [ilk, ikinci, ucuncu] == ["YEV-2026-0001", "YEV-2026-0002", "YEV-2026-0003"]

    sayac = (
        await seeded_db.execute(select(JournalEntryCounter).where(JournalEntryCounter.year == YIL))
    ).scalar_one()
    assert sayac.next_no == 4, "sayac TUKETILMEMIS — numara ikinci kez dagitilabilirdi"


async def test_YIL_sayaclari_BIRBIRINI_sifirlamaz(seeded_db: AsyncSession) -> None:
    """Her yil KENDI hattinda ilerler: 2027 acilinca 2026'nin sayaci geri
    sarmaz (T1'in uc bekcisinin birim karsiligi)."""
    assert await numbering.generate_entry_no(seeded_db, year=2026) == "YEV-2026-0001"
    assert await numbering.generate_entry_no(seeded_db, year=2027) == "YEV-2027-0001"
    assert await numbering.generate_entry_no(seeded_db, year=2026) == "YEV-2026-0002"
    assert await numbering.generate_entry_no(seeded_db, year=2027) == "YEV-2027-0002"

    sayaclar = {
        satir.year: satir.next_no
        for satir in (await seeded_db.execute(select(JournalEntryCounter))).scalars()
    }
    assert sayaclar == {2026: 3, 2027: 3}
