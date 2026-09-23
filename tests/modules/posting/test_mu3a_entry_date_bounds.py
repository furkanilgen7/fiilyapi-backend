"""MU-3A — `post_document`'ta `entry_date` GELECEK SINIRI.

Kusur (envanter kayıt #5, AÇIK bacak): `accounting.service.assert_entry_date_
not_future` yalnız MANUEL yevmiye yolunda (`create_entry`/`update_entry`)
koşuyordu. `post_document` — OTOMATİK fişin TEK giriş noktası (modül
docstring'i) — bu kapıyı hiç çağırmıyordu: yalnız `assert_periods_open` vardı.

Zincir (kaydın `etki` satırı, kapatılmadan önce UÇTAN UCA üretilebiliyordu):

1. İleri `issue_date`li bir belge (fatura vb.) `post_document`e geçer.
2. `entry_date` sınırsız kabul edilir, fiş DOĞRUDAN `posted` doğar (KARAR-3).
3. `assert_periods_open`tan ÖNCE kapı yoksa `lock_period` gelecek dönemi
   `open` olarak DOĞURUR (UPSERT), yani reddedilmeyen istek dönem satırını da
   üretir.
4. Storno `timezone.today()` tarihlidir (K6): storno ayında −tutar, ileri
   ayda +tutar — mizan iki tarih arasında hiç tutmaz.

Bu dosya manuel yoldaki bekçinin (`tests/modules/accounting/
test_mu1_entry_date_bounds.py`) BİREBİR aynı dört iddiasını otomatik fişleme
yoluna taşır. `post_document` bir router değil bir servis giriş noktasıdır
(MU-3A conftest dersi), bu yüzden HTTP değil DOĞRUDAN ÇAĞRI kullanılır.
"""

from datetime import timedelta

from sqlalchemy import select

from app.core.errors import AccountingValidationError
from app.core.timezone import today
from app.modules.accounting import guards
from app.modules.accounting.models import AccountingPeriod, JournalEntryStatus
from app.modules.posting import service as posting_service

from .conftest import KAYNAK, yeni_kaynak_id
from .conftest import satirlar as _satirlar
from .test_mu3a_post_document import _aktor

#: Gelecek AYA düşen bir gün — dönem satırı iddiası için aynı ay yetmez.
_GELECEK_AY = timedelta(days=400)


async def test_GELECEK_tarihli_belge_fislenemez(seeded_db, kullanici_id, temsili_esleme):  # noqa: ANN001
    aktor = await _aktor(seeded_db, kullanici_id)
    yarin = today() + timedelta(days=1)

    try:
        await posting_service.post_document(
            seeded_db,
            aktor,
            source_type=KAYNAK,
            source_id=yeni_kaynak_id(),
            entry_date=yarin,
            description="İleri tarihli belge",
            lines=_satirlar(),
        )
        raise AssertionError("gelecek tarihli belge fişlenmemeliydi")
    except AccountingValidationError as exc:
        assert guards.ENTRY_DATE_IN_FUTURE in str(exc)


async def test_BUGUN_sinir_gunu_fislenir(seeded_db, kullanici_id, temsili_esleme):  # noqa: ANN001
    """🔴 Sınır günü: `<` yerine `<=` yazılsaydı bugünün fişi de reddedilir ve
    kapı kuralı değil KULLANIMI engellerdi."""
    aktor = await _aktor(seeded_db, kullanici_id)
    bugun = today()

    sonuc = await posting_service.post_document(
        seeded_db,
        aktor,
        source_type=KAYNAK,
        source_id=yeni_kaynak_id(),
        entry_date=bugun,
        description="Bugünkü belge",
        lines=_satirlar(),
    )

    assert sonuc.created is True
    assert sonuc.entry.status is JournalEntryStatus.posted
    assert sonuc.entry.entry_date == bugun


async def test_gelecek_donem_SATIRI_dogmaz(seeded_db, kullanici_id, temsili_esleme):  # noqa: ANN001
    """🔴 SIRA iddiası: kapı `assert_periods_open`tan ÖNCE koşmalıdır, yoksa
    reddedilen istek gelecek bir dönemi `open` olarak DOĞURUR."""
    aktor = await _aktor(seeded_db, kullanici_id)
    uzak = today() + _GELECEK_AY

    try:
        await posting_service.post_document(
            seeded_db,
            aktor,
            source_type=KAYNAK,
            source_id=yeni_kaynak_id(),
            entry_date=uzak,
            description="Uzak gelecek belge",
            lines=_satirlar(),
        )
        raise AssertionError("uzak gelecek tarihli belge fişlenmemeliydi")
    except AccountingValidationError:
        pass

    satir = (
        await seeded_db.execute(
            select(AccountingPeriod).where(
                AccountingPeriod.year == uzak.year, AccountingPeriod.month == uzak.month
            )
        )
    ).scalar_one_or_none()
    assert satir is None, "reddedilen istek gelecek dönem satırını DOĞURDU"
