"""MU-3A T1 — 🔴 **İDEMPOTANLIK DB DÜZEYİNDE YAŞAR.**

Bu dilimin ASIL sebebi: MU-3A'dan önce `journal_entries` tablosunda belge
kimliği tutan HİÇBİR ALAN YOKTU (ölçüldü — `JournalEntry` yalnız iki yerde
üretiliyordu: `service.create_entry` ve `state_service._build_reversal`).
Sonucu iki katlıydı ve ikincisi daha ağırdır:

1. Aynı fatura iki kez onaylansaydı İKİ FİŞ doğar ve hiçbir kısıt engellemezdi;
2. *"bu belge fişlendi mi?"* sorusu **SORULAMAZDI** — cevabı taşıyan kolon yoktu.

🔴 **SERVİS KAPISI TEK BAŞINA YETMEZ** (bu deponun tekrar tekrar ölçtüğü ders).
`post_document` bir danışma kilidi alır ve önce okur; ama bu dosyadaki testlerin
HİÇBİRİ servisten geçmez — hepsi ORM ile DOĞRUDAN satır yazar. Sebebi tam olarak
şudur: `post_document`i çağırmayı unutan (ya da atlayan) bir yol yarın yazılırsa
tekilliği ayakta tutacak tek şey `uq_journal_entries_source`tur.

## `ck_journal_entries_source_pair` neden ŞART

Postgres'te UNIQUE, NULL'ları BİRBİRİNE EŞİT SAYMAZ (varsayılan
`NULLS DISTINCT`) — bu, elle girilen fişlerin (kaynağı NULL) birbirini
engellememesi için TAM OLARAK İSTENEN davranıştır ve aşağıda VARSAYILMAZ,
ÖLÇÜLÜR. Ama aynı davranış YARIM bir çifti de serbest bırakır: `source_type`
dolu, `source_id` NULL olan İKİ satır UNIQUE'e HİÇ çarpmaz. O hâlde
"bu belge fişlendi mi?" sorusu yine cevapsız kalırdı — kaynak türü bilinir,
belge bilinmez. CHECK bu yüzden çiftin BÜTÜNLÜĞÜNÜ zorlar.
"""

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounting.models import JournalEntry, JournalEntryStatus, JournalSourceType

KAYNAK = JournalSourceType.invoice
BELGE_ID = uuid.UUID("11111111-2222-3333-4444-555555555555")


def _fis(
    *,
    entry_no: str,
    kullanici_id: uuid.UUID,
    source_type: JournalSourceType | None = None,
    source_id: uuid.UUID | None = None,
) -> JournalEntry:
    """Kısıtın ÖLÇÜLDÜĞÜ en küçük geçerli başlık — satırsızdır.

    Satır AÇILMAZ: `uq_journal_entries_source` BAŞLIK kısıtıdır ve bacaklar
    iddiaya hiçbir şey katmaz; eklenselerdi bu dosya `ck_journal_lines_*`
    kırmızılarını da toplar ve kırmızı KURALI DEĞİL KURULUMU gösterirdi.

    Toplamlar 0/0'dır: `ck_journal_entries_posting_balanced` `posted` için
    `total_debit = total_credit` ister, `0 = 0` onu geçer.
    """
    return JournalEntry(
        entry_no=entry_no,
        entry_date=date(2026, 7, 17),
        period_year=2026,
        period_month=7,
        description="Kaynak damgası probu",
        status=JournalEntryStatus.posted,
        total_debit=Decimal("0"),
        total_credit=Decimal("0"),
        source_type=source_type,
        source_id=source_id,
        created_by_id=kullanici_id,
    )


async def _yaz(seeded_db: AsyncSession, entry: JournalEntry) -> None:
    seeded_db.add(entry)
    await seeded_db.flush()


async def _yazmayi_dene(seeded_db: AsyncSession, entry: JournalEntry) -> IntegrityError | None:
    """SAVEPOINT içinde yazar: ihlal, testin kalanını POISON ETMEZ.

    `db_session` zaten bir SAVEPOINT üzerindedir; `begin_nested` bir alt
    savepoint açar ve ihlalde YALNIZ o geri alınır.
    """
    try:
        async with seeded_db.begin_nested():
            seeded_db.add(entry)
            await seeded_db.flush()
    except IntegrityError as hata:
        return hata
    return None


async def _fis_sayisi(seeded_db: AsyncSession) -> int:
    return await seeded_db.scalar(select(func.count()).select_from(JournalEntry)) or 0


async def test_AYNI_belgeye_IKINCI_fis_DB_kisitina_carpar(
    seeded_db: AsyncSession, kullanici_id: uuid.UUID
):
    """🔴 MUTASYON HEDEFİ: `uq_journal_entries_source` kaldırılırsa BU test kırmızı olur.

    İkinci fiş `entry_no`su FARKLIDIR — aynı olsaydı kırmızı
    `uq_journal_entries_entry_no`dan gelir ve bu dosya kaynak tekilliğini
    HİÇ ÖLÇMEMİŞ olurdu (sahte-yeşilin aynası: DOĞRU SEBEPLE kırmızı).
    """
    await _yaz(
        seeded_db,
        _fis(
            entry_no="YEV-2026-0001",
            kullanici_id=kullanici_id,
            source_type=KAYNAK,
            source_id=BELGE_ID,
        ),
    )

    hata = await _yazmayi_dene(
        seeded_db,
        _fis(
            entry_no="YEV-2026-0002",
            kullanici_id=kullanici_id,
            source_type=KAYNAK,
            source_id=BELGE_ID,
        ),
    )

    assert hata is not None, (
        "aynı belgeye ikinci fiş YAZILDI — `uq_journal_entries_source` yok ya da "
        "düşmüş: aynı fatura iki kez onaylandığında iki fiş doğar"
    )
    assert "uq_journal_entries_source" in str(hata.orig), str(hata.orig)
    assert await _fis_sayisi(seeded_db) == 1


async def test_ELLE_fisler_NULL_kaynakla_birbirini_ENGELLEMEZ(
    seeded_db: AsyncSession, kullanici_id: uuid.UUID
):
    """🔴 ÖLÇÜLÜR, VARSAYILMAZ: PG'de UNIQUE NULL'ları birbirine eşit saymaz.

    Bu test olmasaydı kısıt, elle kayıt yolunu (MU-1'in `create_entry`i) İKİNCİ
    FİŞTE kilitler ve muhasebeci hiçbir gerekçe olmadan 409 alırdı. ÜÇ satır
    yazılır: iki satır `NULLS NOT DISTINCT` bir indekste bile şans eseri
    geçebilecek bir sayı değildir, ama üçüncüsü niyeti açık kılar.
    """
    for sira in range(1, 4):
        await _yaz(seeded_db, _fis(entry_no=f"YEV-2026-{sira:04d}", kullanici_id=kullanici_id))

    assert await _fis_sayisi(seeded_db) == 3


async def test_FARKLI_belge_ailesi_AYNI_kimlikle_CAKISMAZ(
    seeded_db: AsyncSession, kullanici_id: uuid.UUID
):
    """Tekillik ÇİFTİNDİR: kimlik tek başına değil, `(tür, kimlik)` tekildir.

    Kısıt yalnız `source_id`de olsaydı iki AYRI ailenin (teorik olarak) aynı
    UUID'yi taşıması ikinciyi engellerdi — kimlikler tablolar arasında paylaşılan
    bir uzayda YAŞAMAZ.
    """
    await _yaz(
        seeded_db,
        _fis(
            entry_no="YEV-2026-0001",
            kullanici_id=kullanici_id,
            source_type=JournalSourceType.invoice,
            source_id=BELGE_ID,
        ),
    )
    await _yaz(
        seeded_db,
        _fis(
            entry_no="YEV-2026-0002",
            kullanici_id=kullanici_id,
            source_type=JournalSourceType.payment,
            source_id=BELGE_ID,
        ),
    )

    assert await _fis_sayisi(seeded_db) == 2


@pytest.mark.parametrize(
    ("source_type", "source_id"),
    [
        (KAYNAK, None),
        (None, BELGE_ID),
    ],
    ids=["tur_dolu_kimlik_bos", "tur_bos_kimlik_dolu"],
)
async def test_YARIM_kaynak_cifti_REDDEDILIR(
    seeded_db: AsyncSession,
    kullanici_id: uuid.UUID,
    source_type: JournalSourceType | None,
    source_id: uuid.UUID | None,
):
    """🔴 MUTASYON HEDEFİ: `ck_journal_entries_source_pair`.

    Yarım çift UNIQUE'e ÇARPMAZ (NULL'lar ayrıktır) — kısıt düşerse
    "türü bilinen, belgesi bilinmeyen" fişler sessizce birikir ve
    "bu belge fişlendi mi?" sorusu yine cevapsız kalır.
    """
    hata = await _yazmayi_dene(
        seeded_db,
        _fis(
            entry_no="YEV-2026-0009",
            kullanici_id=kullanici_id,
            source_type=source_type,
            source_id=source_id,
        ),
    )

    assert hata is not None, "yarım kaynak çifti YAZILDI — `ck_journal_entries_source_pair` yok"
    assert "ck_journal_entries_source_pair" in str(hata.orig), str(hata.orig)
    assert await _fis_sayisi(seeded_db) == 0
