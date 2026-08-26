"""MU-3B İŞ 1 — 🔴 **STORNOLANAN BELGE YENİDEN FİŞLENİR** (kullanıcı kararı 2026-08-26).

MU-3A `uq_journal_entries_source`u `(source_type, source_id)` üzerinde TAM
tekillik olarak kurmuştu. Ölçülen sonucu şuydu: bir belge fişlenip
STORNOLANIRSA orijinal fiş `reversed` durumda AYAKTA KALIR ve kaynak damgasını
HÂLÂ taşır → belge bir daha HİÇ fişlenemez. Mali iz netlenmiştir
(`posted` + `reversed` = 0), yani belge FİİLEN FİŞSİZDİR; ama sistem onu fişli
sayar ve bunu kullanıcıya söyleyen HİÇBİR mekanizma yoktur — **sessiz kayıp**.

🔑 **KARAR:** tekillik *"iptal edilmemiş fişler arasında"* daraltılır. Böylece

* aynı belge için aynı anda EN FAZLA BİR CANLI fiş olur → idempotanlık KORUNUR;
* stornolanmış fiş yeni fişi ENGELLEMEZ → belge yeniden onaylanınca muhasebeye
  tekrar girer.

🔴 **"İPTAL EDİLMİŞ" = `reversed` ve bu KODDAN OKUNUR**, varsayılmaz:
`transitions.JOURNAL_TRANSITIONS` matrisinde `reversed` TERMİNALDİR (hiçbir
çiftte kaynak değildir) ve `balance.POSTING_STATUSES` onu bakiyeye ALIR — yani
`reversed` bir fiş defterden çıkmaz, yalnız stornosuyla NÖTRLENİR. Kısmi
tekilliğin süzdüğü küme bu yüzden tam olarak `{reversed}`tir: `draft` bir
otomatik fiş YOKTUR (KARAR-3) ama olsaydı bile o CANLIdır ve slotu tutmalıdır.

## Bu dosya İKİ KATMANI da ölçer

Servis kapısı (`post_document`) ve DB kısıtı AYRI AYRI kırmızıya çevrilebilir
olmalıdır; biri ötekini maskelemez. DB katmanı ORM ile DOĞRUDAN yazar
(`test_mu3a_source_stamp.py` deseni) — `post_document`i atlayan bir yol yarın
yazılırsa tekilliği ayakta tutacak tek şey odur.
"""

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounting import state_service
from app.modules.accounting.models import (
    JournalEntry,
    JournalEntryStatus,
)
from app.modules.accounting.transitions import JournalAction
from app.modules.posting import service as posting_service
from app.modules.users.models import User

from .conftest import KAYNAK, satirlar, yeni_kaynak_id

TARIH = date(2026, 7, 17)
ACIKLAMA = "Alınan hizmet faturası"


async def _aktor(seeded_db: AsyncSession, kullanici_id: uuid.UUID) -> User:
    return await seeded_db.get(User, kullanici_id)


async def _fisle(seeded_db, kullanici_id, *, source_id):  # noqa: ANN001, ANN202
    return await posting_service.post_document(
        seeded_db,
        await _aktor(seeded_db, kullanici_id),
        source_type=KAYNAK,
        source_id=source_id,
        entry_date=TARIH,
        description=ACIKLAMA,
        lines=satirlar(),
    )


async def _storno(seeded_db, kullanici_id, entry_id: uuid.UUID):  # noqa: ANN001, ANN202
    return await state_service.perform_transition(
        seeded_db, await _aktor(seeded_db, kullanici_id), entry_id, JournalAction.reverse
    )


async def _fis_sayisi(seeded_db: AsyncSession) -> int:
    return await seeded_db.scalar(select(func.count()).select_from(JournalEntry)) or 0


# --------------------------------------------------------------------------- #
# SERVİS KATMANI
# --------------------------------------------------------------------------- #


async def test_STORNOLANAN_belge_YENIDEN_fislenir_YENI_fis_dogar(
    seeded_db,
    kullanici_id,
    temsili_esleme,  # noqa: ANN001
):
    """🔴 KULLANICI KARARI: storno bir belgeyi mali olarak SİLER.

    Yeniden onaylanınca muhasebeye TEKRAR girmelidir. Aksi hâlde bir kez
    stornolanan fatura mizanda BİR DAHA HİÇ görünmez ve eksiklik hiçbir kolon
    farkıyla ele vermez.
    """
    belge_id = yeni_kaynak_id()
    ilk = await _fisle(seeded_db, kullanici_id, source_id=belge_id)
    await _storno(seeded_db, kullanici_id, ilk.entry.id)

    yeniden = await _fisle(seeded_db, kullanici_id, source_id=belge_id)

    assert yeniden.created is True, (
        "stornolanmış belge yeniden fişlenemedi — kısmi tekillik `reversed` fişleri süzmüyor"
    )
    assert yeniden.entry.id != ilk.entry.id
    assert yeniden.entry.status is JournalEntryStatus.posted
    assert yeniden.entry.source_id == belge_id
    # orijinal (reversed) + storno + yeni fiş = ÜÇ.
    assert await _fis_sayisi(seeded_db) == 3


async def test_CANLI_fis_varken_IKINCI_fis_YAZILMAZ_idempotanlik_KORUNUR(
    seeded_db,
    kullanici_id,
    temsili_esleme,  # noqa: ANN001
):
    """Daraltma idempotanlığı BOZMAZ: canlı fiş hâlâ TEK slottur."""
    belge_id = yeni_kaynak_id()

    ilk = await _fisle(seeded_db, kullanici_id, source_id=belge_id)
    ikinci = await _fisle(seeded_db, kullanici_id, source_id=belge_id)

    assert ikinci.created is False
    assert ikinci.entry.id == ilk.entry.id
    assert await _fis_sayisi(seeded_db) == 1


async def test_created_FALSE_donen_fis_HER_ZAMAN_CANLIDIR(
    seeded_db,
    kullanici_id,
    temsili_esleme,  # noqa: ANN001
):
    """🔴 DÖNÜŞ SÖZLEŞMESİ: `created=False` artık *"belge FİŞLİ"* DEMEKTİR.

    MU-3A'da değildi (`reversed` bir fiş de `created=False` ile dönüyordu) ve
    çağıranın `entry.status`u ayrıca okuması gerekiyordu. Kısmi tekillik o
    yükümlülüğü KALDIRIR; bu test onun bekçisidir.
    """
    belge_id = yeni_kaynak_id()
    await _fisle(seeded_db, kullanici_id, source_id=belge_id)

    ikinci = await _fisle(seeded_db, kullanici_id, source_id=belge_id)

    assert ikinci.created is False
    assert ikinci.entry.status is not JournalEntryStatus.reversed


async def test_IKI_KEZ_stornolanan_belge_UCUNCU_kez_fislenir(
    seeded_db,
    kullanici_id,
    temsili_esleme,  # noqa: ANN001
):
    """Kısmi tekillik BİRİKİMLİDİR: N tane `reversed` fiş yan yana durabilir.

    Tam tekillikte ikinci storno turu yine tıkanırdı; kural "en fazla bir
    CANLI" olduğu için ölü fişlerin SAYISI hiçbir şeyi engellemez.
    """
    belge_id = yeni_kaynak_id()
    ilk = await _fisle(seeded_db, kullanici_id, source_id=belge_id)
    await _storno(seeded_db, kullanici_id, ilk.entry.id)
    ikinci = await _fisle(seeded_db, kullanici_id, source_id=belge_id)
    await _storno(seeded_db, kullanici_id, ikinci.entry.id)

    ucuncu = await _fisle(seeded_db, kullanici_id, source_id=belge_id)

    assert ucuncu.created is True
    assert ucuncu.entry.id not in {ilk.entry.id, ikinci.entry.id}


# --------------------------------------------------------------------------- #
# DB KATMANI — servis ATLANIR (`test_mu3a_source_stamp.py` deseni)
# --------------------------------------------------------------------------- #


def _ham_fis(
    *,
    entry_no: str,
    kullanici_id: uuid.UUID,
    source_id: uuid.UUID,
    status: JournalEntryStatus,
) -> JournalEntry:
    """Kısıtın ölçüldüğü en küçük geçerli başlık — satırsız, toplamlar 0/0."""
    return JournalEntry(
        entry_no=entry_no,
        entry_date=TARIH,
        period_year=2026,
        period_month=7,
        description="Kısmi tekillik probu",
        status=status,
        total_debit=Decimal("0"),
        total_credit=Decimal("0"),
        source_type=KAYNAK,
        source_id=source_id,
        created_by_id=kullanici_id,
    )


async def _yazmayi_dene(seeded_db: AsyncSession, entry: JournalEntry) -> IntegrityError | None:
    try:
        async with seeded_db.begin_nested():
            seeded_db.add(entry)
            await seeded_db.flush()
    except IntegrityError as hata:
        return hata
    return None


async def test_DB_reversed_fis_YENI_fisi_ENGELLEMEZ(seeded_db, kullanici_id):  # noqa: ANN001
    """🔴 MUTASYON HEDEFİ: kısmi süzgeç (`WHERE status <> 'reversed'`) sökülürse
    BU test kırmızı olur — tam tekillik ikinci satırı reddederdi."""
    belge_id = uuid.uuid4()
    seeded_db.add(
        _ham_fis(
            entry_no="YEV-2026-9001",
            kullanici_id=kullanici_id,
            source_id=belge_id,
            status=JournalEntryStatus.reversed,
        )
    )
    await seeded_db.flush()

    hata = await _yazmayi_dene(
        seeded_db,
        _ham_fis(
            entry_no="YEV-2026-9002",
            kullanici_id=kullanici_id,
            source_id=belge_id,
            status=JournalEntryStatus.posted,
        ),
    )

    assert hata is None, f"stornolanmış fiş yeni fişi engelledi: {hata}"
    assert await _fis_sayisi(seeded_db) == 2


async def test_DB_IKI_CANLI_fis_HALA_REDDEDILIR(seeded_db, kullanici_id):  # noqa: ANN001
    """🔴 MUTASYON HEDEFİ: tekilliğin KENDİSİ sökülürse BU test kırmızı olur.

    `entry_no`lar FARKLIDIR — aynı olsaydı kırmızı `uq_journal_entries_entry_no`
    üzerinden gelir ve bu test kaynak tekilliğini HİÇ ÖLÇMEMİŞ olurdu
    (DOĞRU SEBEPLE kırmızı).
    """
    belge_id = uuid.uuid4()
    seeded_db.add(
        _ham_fis(
            entry_no="YEV-2026-9101",
            kullanici_id=kullanici_id,
            source_id=belge_id,
            status=JournalEntryStatus.posted,
        )
    )
    await seeded_db.flush()

    hata = await _yazmayi_dene(
        seeded_db,
        _ham_fis(
            entry_no="YEV-2026-9102",
            kullanici_id=kullanici_id,
            source_id=belge_id,
            status=JournalEntryStatus.posted,
        ),
    )

    assert hata is not None, (
        "aynı belgeye İKİNCİ CANLI fiş yazıldı — kısmi tekillik yok ya da düşmüş"
    )
    assert "uq_journal_entries_source" in str(hata.orig), str(hata.orig)


async def test_DB_IKI_REVERSED_fis_yan_yana_DURABILIR(seeded_db, kullanici_id):  # noqa: ANN001
    """Süzülen küme kısıtın DIŞINDADIR: ölü fişlerin sayısı sınırsızdır."""
    belge_id = uuid.uuid4()
    seeded_db.add(
        _ham_fis(
            entry_no="YEV-2026-9201",
            kullanici_id=kullanici_id,
            source_id=belge_id,
            status=JournalEntryStatus.reversed,
        )
    )
    await seeded_db.flush()

    hata = await _yazmayi_dene(
        seeded_db,
        _ham_fis(
            entry_no="YEV-2026-9202",
            kullanici_id=kullanici_id,
            source_id=belge_id,
            status=JournalEntryStatus.reversed,
        ),
    )

    assert hata is None, f"iki ölü fiş çakıştı: {hata}"
