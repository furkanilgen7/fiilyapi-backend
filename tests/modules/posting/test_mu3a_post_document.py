"""MU-3A T2 — `post_document()`: otomatik fişin TEK GİRİŞ NOKTASI.

Bu dosya SÖZLEŞMEYİ ölçer, bir belge ailesini DEĞİL: MU-3A hiçbir aileyi
bağlamaz (bağlama işi MU-3B/C/D/E'dir). Temsilî eşleme `740` borç / `320`
alacaktır — yönetimin KARAR-1'i (NORMAL TİCARİ REJİM, `170`/`350` DEĞİL) ve
KARAR-2'si (CARİ ANA HESAP, `320.04` AÇILMAZ) burada çakılır.

🔴 Testler eşlemeyi FABRİKAYLA kurar, seed'den OKUMAZ: bu dilim ürün verisi
tohumlamaz (gerekçe `posting/models.py` docstring'i — hiçbir kodun okumadığı
ölü veri).
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AccountingValidationError, ConflictError
from app.modules.accounting.models import (
    JournalEntry,
    JournalEntryStatus,
    JournalLine,
    JournalSourceType,
)
from app.modules.posting import service as posting_service
from app.modules.posting.service import PostingLine

from .conftest import CARI_ROL, GIDER_ROL, KAYNAK, satirlar, yeni_kaynak_id

TARIH = date(2026, 7, 17)
ACIKLAMA = "Alınan hizmet faturası"


async def _aktor(seeded_db: AsyncSession, kullanici_id):  # noqa: ANN001, ANN202
    from app.modules.users.models import User

    return await seeded_db.get(User, kullanici_id)


async def _fisle(seeded_db, kullanici_id, *, source_id=None, lines=None, entry_date=TARIH):  # noqa: ANN001, ANN202
    return await posting_service.post_document(
        seeded_db,
        await _aktor(seeded_db, kullanici_id),
        source_type=KAYNAK,
        source_id=source_id if source_id is not None else yeni_kaynak_id(),
        entry_date=entry_date,
        description=ACIKLAMA,
        lines=lines if lines is not None else satirlar(),
    )


async def _donemi_kapat(seeded_db: AsyncSession, kullanici_id, year: int, month: int) -> None:  # noqa: ANN001
    """Var olan dönem satırını KAPATIR (damga BÜTÜN yazılır)."""
    from datetime import UTC, datetime

    from app.modules.accounting.models import AccountingPeriod, AccountingPeriodStatus

    period = (
        await seeded_db.execute(
            select(AccountingPeriod).where(
                AccountingPeriod.year == year, AccountingPeriod.month == month
            )
        )
    ).scalar_one()
    period.status = AccountingPeriodStatus.closed
    period.closed_at = datetime(2026, 8, 1, tzinfo=UTC)
    period.closed_by_id = kullanici_id
    await seeded_db.flush()


async def _fis_sayisi(seeded_db: AsyncSession) -> int:
    return await seeded_db.scalar(select(func.count()).select_from(JournalEntry)) or 0


async def _satir_sayisi(seeded_db: AsyncSession) -> int:
    return await seeded_db.scalar(select(func.count()).select_from(JournalLine)) or 0


# --------------------------------------------------------------------------- #
# Mutlu yol
# --------------------------------------------------------------------------- #


async def test_belge_fislenince_fis_POSTED_dogar(seeded_db, kullanici_id, temsili_esleme):  # noqa: ANN001
    """🔴 KARAR-3: otomatik fiş `posted` DOĞAR, `draft` DEĞİL.

    `draft` doğsaydı mizan YİNE BOŞ KALIRDI (`balance.POSTING_STATUSES` yalnız
    `posted`+`reversed` sayar) — yani bütün MU-3 ailesi hiçbir şey değiştirmezdi.
    """
    sonuc = await _fisle(seeded_db, kullanici_id)

    assert sonuc.created is True
    assert sonuc.entry.status is JournalEntryStatus.posted


async def test_fis_KAYNAK_damgasini_ve_NUMARASINI_tasir(seeded_db, kullanici_id, temsili_esleme):  # noqa: ANN001
    """Damga + `entry_no`. Numara `period_year`den üretilir (FIS-NO karar 1)."""
    belge_id = yeni_kaynak_id()

    sonuc = await _fisle(seeded_db, kullanici_id, source_id=belge_id)

    assert sonuc.entry.source_type is KAYNAK
    assert sonuc.entry.source_id == belge_id
    assert sonuc.entry.entry_no.startswith("YEV-2026-")
    assert (sonuc.entry.period_year, sonuc.entry.period_month) == (2026, 7)


async def test_bacaklar_ESLEMEDEN_cozulur_ve_SIRALIDIR(seeded_db, kullanici_id, temsili_esleme):  # noqa: ANN001
    """🔴 Hesap kodu KODUN İÇİNDE YAZILI DEĞİLDİR — kuraldan okunur.

    `sort_order` çağıranın verdiği DİZİ İNDEKSİDİR: sunucu varsayılanı yoktur ve
    doldurulmazsa koşan bakiye satırları rastgele sıralardı (`JournalLine`
    docstring'i).
    """
    gider, cari = temsili_esleme

    sonuc = await _fisle(seeded_db, kullanici_id)

    satir_kayitlari = (
        (
            await seeded_db.execute(
                select(JournalLine)
                .where(JournalLine.entry_id == sonuc.entry.id)
                .order_by(JournalLine.sort_order)
            )
        )
        .scalars()
        .all()
    )
    assert [(s.account_id, s.debit, s.credit) for s in satir_kayitlari] == [
        (gider.id, Decimal("1000.00"), Decimal("0")),
        (cari.id, Decimal("0"), Decimal("1000.00")),
    ]
    assert [s.sort_order for s in satir_kayitlari] == [0, 1]


async def test_baslik_toplamlari_BACAKLARDAN_turetilir(seeded_db, kullanici_id, temsili_esleme):  # noqa: ANN001
    sonuc = await _fisle(seeded_db, kullanici_id)

    assert sonuc.entry.total_debit == Decimal("1000.00")
    assert sonuc.entry.total_credit == Decimal("1000.00")


# --------------------------------------------------------------------------- #
# İdempotanlık
# --------------------------------------------------------------------------- #


async def test_AYNI_belge_IKINCI_kez_fislenmez_MEVCUT_fis_doner(
    seeded_db,
    kullanici_id,
    temsili_esleme,  # noqa: ANN001
):
    """🔴 Bu dilimin ASIL sebebi: iki kez onaylanan fatura İKİ FİŞ DOĞURMAZ.

    İkinci çağrı bir HATA DEĞİL, `created=False` ile MEVCUT fişi döndürür:
    çağıran (MU-3B/C/D/E) yeniden deneme yapabilen bir onay akışıdır ve
    "zaten yapılmış" bir işin istisnaya dönüşmesi, onayı yeniden denenemez
    kılardı.
    """
    belge_id = yeni_kaynak_id()

    ilk = await _fisle(seeded_db, kullanici_id, source_id=belge_id)
    ikinci = await _fisle(seeded_db, kullanici_id, source_id=belge_id)

    assert ikinci.created is False
    assert ikinci.entry.id == ilk.entry.id
    assert await _fis_sayisi(seeded_db) == 1
    assert await _satir_sayisi(seeded_db) == 2


async def test_FARKLI_belgeler_AYRI_fis_alir(seeded_db, kullanici_id, temsili_esleme):  # noqa: ANN001
    ilk = await _fisle(seeded_db, kullanici_id)
    ikinci = await _fisle(seeded_db, kullanici_id)

    assert ilk.entry.id != ikinci.entry.id
    assert ilk.entry.entry_no != ikinci.entry.entry_no
    assert await _fis_sayisi(seeded_db) == 2


# --------------------------------------------------------------------------- #
# Fail-closed kapıları — HİÇBİRİ YARIM FİŞ BIRAKMAZ
# --------------------------------------------------------------------------- #


async def test_ESLEMESI_OLMAYAN_rol_422_ve_HICBIR_SEY_yazilmaz(
    seeded_db,
    kullanici_id,
    temsili_esleme,  # noqa: ANN001
):
    """🔴 FAIL-CLOSED: eşlemesi olmayan rol çözülemez, fiş YARIM YAZILMAZ.

    `role_key`in enum OLMAMASININ bedeli burada ödenir ve ödenebilir olduğu
    burada kanıtlanır: yazım hatası (`payble`) bir kural satırı bulamaz ve
    422'ye düşer — sessizce boş bir hesaba yazmaz.
    """
    with pytest.raises(AccountingValidationError):
        await _fisle(
            seeded_db,
            kullanici_id,
            lines=[
                PostingLine(role_key=GIDER_ROL, debit=Decimal("1000.00")),
                PostingLine(role_key="payble", credit=Decimal("1000.00")),
            ],
        )

    assert await _fis_sayisi(seeded_db) == 0
    assert await _satir_sayisi(seeded_db) == 0


async def test_BASKA_ailenin_kurali_KULLANILMAZ(
    seeded_db,
    kullanici_id,
    hesap_fabrikasi,
    kural_fabrikasi,  # noqa: ANN001
):
    """Eşleme anahtarı `(source_type, role_key)`dir — rol tek başına DEĞİL.

    Kural yalnız `role_key`e bakılarak çözülseydi bir ailenin cari hesabı
    ötekinin fişine sızardı.
    """
    gider = await hesap_fabrikasi("740")
    cari = await hesap_fabrikasi("320")
    await kural_fabrikasi(GIDER_ROL, gider)
    await kural_fabrikasi(CARI_ROL, cari, source_type=JournalSourceType.payment)

    with pytest.raises(AccountingValidationError):
        await _fisle(seeded_db, kullanici_id)

    assert await _fis_sayisi(seeded_db) == 0


async def test_DENGESIZ_bacaklar_422(seeded_db, kullanici_id, temsili_esleme):  # noqa: ANN001
    """K1 kapısı `post_document`te de koşar — YENİDEN YAZILMAZ, ÇAĞRILIR."""
    with pytest.raises(AccountingValidationError):
        await _fisle(
            seeded_db,
            kullanici_id,
            lines=[
                PostingLine(role_key=GIDER_ROL, debit=Decimal("1000.00")),
                PostingLine(role_key=CARI_ROL, credit=Decimal("999.99")),
            ],
        )

    assert await _fis_sayisi(seeded_db) == 0


async def test_TEK_bacak_422(seeded_db, kullanici_id, temsili_esleme):  # noqa: ANN001
    """Tek bacak `Σ` olarak dengeli GÖRÜNMEZ ama çift taraflı kayıt DEĞİLDİR."""
    with pytest.raises(AccountingValidationError):
        await _fisle(
            seeded_db,
            kullanici_id,
            lines=[PostingLine(role_key=GIDER_ROL, debit=Decimal("1000.00"))],
        )

    assert await _fis_sayisi(seeded_db) == 0


async def test_YAPRAK_OLMAYAN_hesaba_eslenmis_kural_422(
    seeded_db,
    kullanici_id,
    temsili_esleme,
    hesap_fabrikasi,  # noqa: ANN001
):
    """🔴 MU-4 UYARISI CANLI: `320.04` açıldığı an `320`e bakan kural 422 verir.

    İstenen budur — sessizce ÇİFT SAYAN bir mizan yerine gürültülü bir durma.
    Kapı `accounting.validation.leaf_blockers`tir ve `posting` onu YENİDEN
    YAZMAZ; iki yerde yazılsaydı biri torunları kapsamayı unuturdu.
    """
    await hesap_fabrikasi("320.04", name="Yurt İçi Satıcılar")

    with pytest.raises(AccountingValidationError):
        await _fisle(seeded_db, kullanici_id)

    assert await _fis_sayisi(seeded_db) == 0


async def test_KAPALI_doneme_otomatik_fis_409(
    seeded_db,
    kullanici_id,
    temsili_esleme,
    donem_fabrikasi,  # noqa: ANN001
):
    """🔴 KARAR-6'nın KOD AYAĞI: kapalı dönem otomatik fişe de KAPALIDIR.

    Dönem kapısı elle yolla (`service.create_entry`) ORTAKTIR
    (`periods_service.assert_periods_open`) ve burada YENİDEN YAZILMAZ: iki
    kapı olsaydı biri kilitli okuma yapmayı unutur ve kapanışla yarışırdı.
    """
    await donem_fabrikasi(2026, 7)

    with pytest.raises(ConflictError):
        await _fisle(seeded_db, kullanici_id)

    assert await _fis_sayisi(seeded_db) == 0


async def test_ZATEN_fislenmis_belge_KAPALI_donemde_de_MEVCUDU_doner(
    seeded_db,
    kullanici_id,
    temsili_esleme,
    donem_fabrikasi,  # noqa: ANN001
):
    """İdempotan dönüş dönem kapısından ÖNCEDİR ve bu bilinçlidir.

    Ay kapandıktan sonra çağıran yeniden denerse yapılacak bir iş YOKTUR;
    409 atmak, hiç yazılmayacak bir fiş için onay akışını kilitlerdi.
    """
    belge_id = yeni_kaynak_id()
    ilk = await _fisle(seeded_db, kullanici_id, source_id=belge_id)
    # 🔴 `donem_fabrikasi` BURADA KULLANILAMAZ: ilk fişleme
    # `periods_service.lock_period`ın UPSERT'i ile 2026/07 satırını ZATEN
    # AÇMIŞTIR ve fabrika `uq_accounting_periods_year_month`e çarpardı. Dönem
    # KAPATILIR — kurulum, ölçülen davranışın kendisini taklit etmelidir.
    await _donemi_kapat(seeded_db, kullanici_id, 2026, 7)

    ikinci = await _fisle(seeded_db, kullanici_id, source_id=belge_id)

    assert ikinci.created is False
    assert ikinci.entry.id == ilk.entry.id


# --------------------------------------------------------------------------- #
# KARAR-5 uyumu
# --------------------------------------------------------------------------- #


async def test_STORNO_kaynak_damgasini_TASIMAZ(seeded_db, kullanici_id, temsili_esleme):  # noqa: ANN001
    """🔴 KARAR-5 ile `uq_journal_entries_source` ancak BÖYLE bir arada durur.

    Storno damgayı TAŞISAYDI orijinal fişle çakışır ve "belge geri alınırsa
    storno" kararı HİÇ UYGULANAMAZDI. Stornonun belgesi TÜRETİLİR:
    `reversal_of_id` → orijinal → `source_type`/`source_id`.
    """
    from app.modules.accounting import state_service
    from app.modules.accounting.transitions import JournalAction

    belge_id = yeni_kaynak_id()
    sonuc = await _fisle(seeded_db, kullanici_id, source_id=belge_id)

    cikti = await state_service.perform_transition(
        seeded_db, await _aktor(seeded_db, kullanici_id), sonuc.entry.id, JournalAction.reverse
    )

    assert cikti.entry.reversal_of_id == sonuc.entry.id
    assert cikti.entry.source_type is None
    assert cikti.entry.source_id is None
    await seeded_db.refresh(sonuc.entry)
    assert sonuc.entry.source_id == belge_id
    assert sonuc.entry.status is JournalEntryStatus.reversed


async def test_STORNOLANMIS_belge_YENIDEN_fislenemez_MEVCUDU_doner(
    seeded_db,
    kullanici_id,
    temsili_esleme,  # noqa: ANN001
):
    """🔴 **MU-3B'YE AÇIK KARAR** — davranış burada ÇAKILIR, sürpriz olmasın.

    Bir belge fişlenip sonra STORNOLANIRSA (`KARAR-5`), orijinal fiş
    `reversed` durumunda AYAKTA KALIR ve `uq_journal_entries_source` slotunu
    HÂLÂ TUTAR. Dolayısıyla belge yeniden onaylanırsa `post_document`
    `created=False` ile o `reversed` fişi döndürür — YENİ FİŞ KESMEZ.

    Bu, kısıtın DOĞRUDAN sonucudur ve bugün için FAIL-CLOSED olan taraftır:
    alternatifi (durumu süzen bir tekillik) aynı belgeye N tane fiş açardı.
    Ama çağıran `created=False` gördüğünde "zaten fişli" sanır; oysa mali iz
    NETLENMİŞTİR (`posted` + `reversed` toplamı sıfır).

    🔴 Çağıran (MU-3B/C/D/E) bu yüzden `outcome.entry.status`u OKUMAK
    ZORUNDADIR: `reversed` ise belge FİŞSİZ sayılmalıdır. Karar netleşene
    kadar davranış BUDUR ve bu test onun bekçisidir — sessizce değişirse
    kırmızı verir.
    """
    from app.modules.accounting import state_service
    from app.modules.accounting.transitions import JournalAction

    belge_id = yeni_kaynak_id()
    ilk = await _fisle(seeded_db, kullanici_id, source_id=belge_id)
    await state_service.perform_transition(
        seeded_db, await _aktor(seeded_db, kullanici_id), ilk.entry.id, JournalAction.reverse
    )

    yeniden = await _fisle(seeded_db, kullanici_id, source_id=belge_id)

    assert yeniden.created is False
    assert yeniden.entry.id == ilk.entry.id
    assert yeniden.entry.status is JournalEntryStatus.reversed
    # Storno + orijinal = İKİ fiş; belgenin damgası YALNIZ orijinaldedir.
    assert await _fis_sayisi(seeded_db) == 2
