"""FIS-NO — yevmiye fis numarasi ureticisi: `YEV-{yil}-{sira:04d}` (`YEV-2026-0214`).

Kullanicinin bagladigi UC KARAR (2026-08-21):

1. Sira **YIL bazlidir** ve her 1 Ocak'ta 1'e doner; sayac **SIRKET GENELINDE
   TEKTIR** (santiye/proje kirilimi YOK). Yil, fisin `period_year` kolonundan
   gelir — `ck_journal_entries_period_matches_date` onu `entry_date`in yiliyla
   zaten esitledigi icin tek kaynaktir. `SEQUENCE_WIDTH` bir TAVAN DEGIL EN AZ
   genisliktir: 9999'dan sonra numara **BUDANMAZ**, bes haneye UZAR
   (`YEV-2026-10000`). Basa donmek `uq_journal_entries_entry_no` ihlali demek
   olurdu.
2. **BOSLUK OLABILIR**: sayac GERI ALINMAZ, numaralar YENIDEN DIZILMEZ.
3. Numara **`draft` ACILIRKEN** verilir; `posted` olurken DEGISMEZ.

Dayanak `projedesign/Muhasebe - Donem Kapanisi.dc.html`tir: taslak fisler
`YEV-2026-0214` / `0216` / `0218` ile listelenir — numara taslakta ZATEN vardir
ve sira BOSLUKLU ilerler.

🔴 NEDEN `advisory lock` + `max + 1` DEGIL (depodaki OTEKI IKI URETICI)
----------------------------------------------------------------------
`procurement/numbering.py` ve `invoicing/numbering.py`
`pg_advisory_xact_lock(anahtar, yil)` + `max(cast(sonek AS int)) + 1` kullanir
ve ikisinin docstring'i de `SELECT … FOR UPDATE`yi ACIKCA REDDEDER
("kilitlenecek SATIR henuz yoktur"). Bu modul UCUNCU bir mekanizma acar ve bu
DOGRUDUR — sebebi yazilmazsa gelecekteki okuyucu bunu DRIFT sanar:

`max + 1` numarayi **hayatta kalan satirlardan** yeniden HESAPLAR. **En buyuk
numarali fis silinince numarasi YENIDEN KULLANILIR** — bu, 2. karari ("sayac
geri alinmaz") dogrudan cigner. Yevmiye fisinde bu bir kenar durum DEGILDIR:
`draft` SILINEBILIR ve numara `draft` ACILIRKEN verilir, yani "kullanici taslak
acti sonra vazgecti" **OLAGAN** yoldur. `journal_entry_counters` MONOTONDUR ve
bunu yapisal olarak atlatir. `procurement`/`invoicing`de bu fark ISIRMAZ cunku
oradaki numaralar ayni bicimde silinmez — o iki modul DEGISTIRILMEZ.

Satir VAR OLDUGU icin `FOR UPDATE`in reddedilme gerekcesi de burada gecersizdir;
satirin YOKLUGU sorunu UPSERT-SONRA-KILITLE ile kapanir (asagida).

🔴 UPSERT-SONRA-KILITLE ve `DO NOTHING`in DELIGI (MU-2 kanonu)
--------------------------------------------------------------
Kilitlenecek satirin **VARLIGI da kilidin parcasidir**: yilin ilk fisinde satir
YOKTUR. `periods_service.lock_period` bunu `INSERT … ON CONFLICT DO NOTHING` +
ayri bir `SELECT … FOR UPDATE` ile yapar. Burada **`DO NOTHING` KULLANILMAZ**,
cunku bir DELIGI vardir:

    `ON CONFLICT DO NOTHING` catisan satiri **KILITLEMEZ** ve **DONDURMEZ**.
    Kaybeden islem, kazananin commit'ini bekledikten sonra bos eller doner;
    arkasindan gelen `SELECT … FOR UPDATE` satiri gorur ama arada kilitsiz bir
    an vardir ve kazanan ROLLBACK ederse `scalar_one()` hic satir bulamayip
    `NoResultFound` (= ayrimsiz 500) uretebilir.

Secilen yol **`ON CONFLICT (year) DO UPDATE SET next_no = journal_entry_counters
.next_no RETURNING next_no`**tir. Gerekcesi tek cumledir: **no-op `DO UPDATE`
satiri HER IKI YOLDA da KILITLER ve DONDURUR.**
  * Catisma YOKSA satir INSERT edilir ve zaten bizimdir.
  * Catisma VARSA Postgres catisan satira gercek bir `UPDATE` uygular; bu, satir
    kilidini alir ve `RETURNING` **kilitlenmis, en guncel** degeri dondurur
    (EvalPlanQual yeniden degerlendirmesi). Kayip guncelleme YOKTUR.
  * Kazanan islem HENUZ COMMIT ETMEDIYSE ikinci istek bu ifadede BLOKE olur —
    eszamanlilik bekcisinin `not done` bariyerinin gordugu sey tam olarak budur.
  * Kazanan ROLLBACK ederse ifade kendiliginden INSERT yoluna doner; "SELECT
    bos dondu" hali HIC DOGMAZ, dolayisiyla bir yeniden-deneme dali da gerekmez.

Tek bir ifadeye ("`… DO UPDATE SET next_no = next_no + 1 RETURNING next_no`",
sonra `- 1`) sikistirilabilirdi; SIKISTIRILMADI cunku dagitilan numaranin
"donen deger eksi bir" olmasi sessiz bir okuma tuzagidir. Satir 1. ifadede
KILITLENDIGI icin iki ifade arasinda baska bir islem giremez.

🔴 CEKIRDEK (ORM DEGIL) ifadeler kullanilir: sayac bir `Table` uzerinden
okunup yazilir, `JournalEntryCounter` nesnesi HIC yuklenmez. ORM yuklenseydi
kimlik haritasinda BAYAT bir `next_no` yasar ve ayni oturumda ikinci kez numara
uretmek (storno + fis) eski degeri okuyabilirdi.
"""

from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounting.models import JournalEntryCounter

__all__ = [
    "ENTRY_NO_PREFIX",
    "FIRST_SEQUENCE",
    "SEQUENCE_WIDTH",
    "format_entry_no",
    "generate_entry_no",
]

#: Seri koku. Hicbir ayar ekraninda cizilmedigi icin MODUL SABITIDIR
#: (`invoicing.INVOICE_NUMBER_PREFIX` deseni) — ayar yapilmaz.
ENTRY_NO_PREFIX = "YEV"

#: EN AZ genislik — TAVAN DEGIL (bkz. modul docstring'i, karar 1).
SEQUENCE_WIDTH = 4

#: Yilin ilk fisinin sirasi; sayac her 1 Ocak'ta buraya doner.
FIRST_SEQUENCE = 1

#: 🔴 Cekirdek `Table` — ORM sinifi DEGIL (bkz. modul docstring'i).
_COUNTERS = JournalEntryCounter.__table__


def format_entry_no(year: int, sequence: int) -> str:
    """`(2026, 214) -> "YEV-2026-0214"` · `(2026, 10000) -> "YEV-2026-10000"`.

    Bicim TEK yerde kurulur: migration'in backfill'i de, uretici de, testler de
    ayni kurali okur. Iki yerde yazilsaydi biri `SEQUENCE_WIDTH` degisiminde
    guncellenip oteki kalir ve backfill ile canli uretim AYRISIRDI.

    `:0{SEQUENCE_WIDTH}d` genisligi BUDAMAZ, yalnizca doldurur — 9999'dan sonra
    numara kendiliginden bes haneye uzar.
    """
    return f"{ENTRY_NO_PREFIX}-{year}-{sequence:0{SEQUENCE_WIDTH}d}"


async def generate_entry_no(session: AsyncSession, *, year: int) -> str:
    """Sirada bekleyen numarayi ATOMIK olarak alir ve sayaci TUKETIR.

    `year` ZORUNLU ve ADLIDIR; `today().year`a dusen bir varsayilan YOKTUR.
    Cagiran, yilin fisin **`period_year`** kolonundan geldigini bilmek
    ZORUNDADIR (karar 1): gizli bir varsayilan, gecen yila kesilen bir fise
    sessizce BU yilin numarasini verirdi.

    Iki ifadelik UPSERT-SONRA-KILITLE — gerekcesi modul docstring'indedir.

    🔴 ROLLBACK SAYACI GERI ALIR — bosluk ORADAN GELMEZ (kod duzeyinde
    dogrulandi, 2026-08-21; ampirik olarak OLCULMEDI).
    Her iki ifade de CAGIRANIN kendi `AsyncSession`inda kosar: ayri baglanti,
    otonom transaction ve ic `commit()` YOKTUR. Cagiran rollback ederse sayac
    da geri alinir; dahasi eszamanli bekleyen, satir kilidinde kazananin
    commit'ini VEYA rollback'ini bekler ve rollback halinde ILERLEMEMIS degeri
    okur. Yani rollback edilen bir yaratma numara YAKMAZ.

    Boslugun GERCEK kaynagi DELETE yoludur (karar 2): commit edilmis bir fis
    sonradan silindiginde numarasi bosta kalir ve sayac geri SARILMAZ. Bunu
    `test_EN_BUYUK_numara_silinse_bile_sayac_GERI_ALINMAZ` kilitler — en buyuk
    numarali fis silinse bile sonraki fis onun numarasini YENIDEN KULLANMAZ.
    """
    # 1. KILIT + OKUMA. No-op `DO UPDATE` satiri her iki yolda da KILITLER ve
    #    DONDURUR; `DO NOTHING` catisan satiri ne kilitler ne dondurur.
    sequence = await session.scalar(
        pg_insert(_COUNTERS)
        .values(year=year, next_no=FIRST_SEQUENCE)
        .on_conflict_do_update(
            index_elements=["year"],
            set_={"next_no": _COUNTERS.c.next_no},
        )
        .returning(_COUNTERS.c.next_no)
    )

    # 2. TUKET. Satir 1. adimda KILITLENDI: arada baska bir islem giremez.
    await session.execute(
        update(_COUNTERS).where(_COUNTERS.c.year == year).values(next_no=sequence + 1)
    )

    return format_entry_no(year, sequence)
