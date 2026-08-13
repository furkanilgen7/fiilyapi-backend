"""🔴 İK-3 T4 — EŞİK = KİLİT (WORKFLOW §4, İK-2 dersi) para çıkışı yolunda.

Bordroda "eşik" bir kota değil bir DURUM KAPISIDIR: `pending → approved → paid`
zincirinde her adım YALNIZ BİR KEZ atılabilir. Kilit olmadan iki eşzamanlı
istek AYNI durumu okur ve İKİSİ DE kapıdan geçer — bir dönem iki kez "ödendi"
damgası alır, bir satır iki kez onaylanır. Bu, para çıkışının kapısında
gerçekleşen bir çift ödemedir.

Neden `client`/`seeded_db` KULLANILMAZ: `tests/conftest.py`'deki `db_session`
her testi TEK bağlantı üzerinde SAVEPOINT'e sarar ve dış transaction'ı asla
gerçekten COMMIT ETMEZ — o session üzerindeki iki `asyncio` görevi AYNI
bağlantıyı paylaşır ve gerçek satır kilidi test EDİLEMEZ. Bu dosya
`tests/personnel/test_ik2_leave_concurrency.py` desenini birebir izler: İKİ
BAĞIMSIZ bağlantı, gerçek commit, sonunda gerçek temizlik.

Bariyer (`asyncio.Event`) BİLİNÇLİDİR: çıplak `asyncio.gather` iki görevi kritik
anda KESİŞTİRMEZ — yarış penceresi hiç açılmayabilir. Burada tx1 kilidi ALIP
TUTARKEN tx2'nin bloke olduğu DOĞRUDAN kanıtlanır; bu yüzden kilit kaldırılınca
testler KIRMIZI olur (mutasyon denetimi raporda).
"""

import asyncio
import contextlib
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import delete, event, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import ConflictError
from app.core.security import hash_password
from app.modules.payroll import service
from app.modules.payroll.models import (
    PayrollLine,
    PayrollLineStatus,
    PayrollPeriod,
    PayrollPeriodStatus,
    PayrollRate,
)
from app.modules.personnel.models import Personnel
from app.modules.roles.models import Role
from app.modules.site_diary.models import WorkerSource
from app.modules.users.models import User
from tests.conftest import test_engine

pytestmark = pytest.mark.asyncio

_SessionFactory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

#: Rol anahtarı ve e-postalar TESTE ÖZELDİR: bu dosya GERÇEKTEN commit ettiği
#: için sızıntı ancak yaratılan satırların tam bilinmesiyle kapanır.
_ROL_ANAHTARI = "ik3_conc_admin"
_EPOSTALAR = ("ik3-onay1@conc.co", "ik3-onay2@conc.co")

#: Üretim verisiyle çakışmayan uzak bir yıl (UQ `(year, month)`); her senaryo
#: KENDİ AYINI kullanır ki testler birbirinin dönemini görmesin.
_YIL = 2099

SIRKET_NET = Decimal("6681.69")
TASERON_NET = Decimal("5000.00")


class _Kurulum:
    def __init__(
        self,
        period_id: uuid.UUID,
        payable_line_id: uuid.UUID,
        excluded_line_id: uuid.UUID,
        personnel_ids: list[uuid.UUID],
        actor_ids: list[uuid.UUID],
        role_id: uuid.UUID,
    ) -> None:
        self.period_id = period_id
        self.payable_line_id = payable_line_id
        self.excluded_line_id = excluded_line_id
        self.personnel_ids = personnel_ids
        self.actor_ids = actor_ids
        self.role_id = role_id


async def _kur(
    *,
    ay: int,
    period_status: PayrollPeriodStatus,
    payable_status: PayrollLineStatus,
) -> _Kurulum:
    """Reel commit'li kurulum: bir dönem + ödenebilir bir satır + bir taşeron satırı.

    Taşeron satırı HER senaryoda vardır: K2'nin yarış altında da tuttuğu
    (`excluded` kalır, toplama girmez) böyle doğrulanabilir.
    """
    async with _SessionFactory() as session:
        role = Role(key=_ROL_ANAHTARI, name="Bordro Eşzamanlılık Rolü")
        session.add(role)
        await session.flush()

        aktorler = [
            User(
                email=eposta,
                password_hash=hash_password("parola1234"),
                full_name=f"Bordro Aktörü {sira}",
                role_id=role.id,
            )
            for sira, eposta in enumerate(_EPOSTALAR, start=1)
        ]
        kisiler = [
            Personnel(full_name="Eşzamanlılık Şirket", source=WorkerSource.company),
            Personnel(full_name="Eşzamanlılık Taşeron", source=WorkerSource.subcontractor),
        ]
        session.add_all([*aktorler, *kisiler])
        await session.flush()

        period = PayrollPeriod(year=_YIL, month=ay, status=period_status)
        session.add(period)
        await session.flush()

        odenebilir = PayrollLine(
            payroll_period_id=period.id,
            personnel_id=kisiler[0].id,
            personnel_source=WorkerSource.company,
            days=5,
            gross_amount=Decimal("9000.00"),
            deduction_amount=Decimal("2318.31"),
            net_amount=SIRKET_NET,
            bank_amount=SIRKET_NET,
            cash_amount=Decimal("0.00"),
            status=payable_status,
        )
        taseron = PayrollLine(
            payroll_period_id=period.id,
            personnel_id=kisiler[1].id,
            personnel_source=WorkerSource.subcontractor,
            days=5,
            gross_amount=Decimal("6730.00"),
            deduction_amount=Decimal("1730.00"),
            net_amount=TASERON_NET,
            status=PayrollLineStatus.excluded,
            excluded_reason="Taşeron işçisi bordrodan ödenmez",
        )
        session.add_all([odenebilir, taseron])
        await session.flush()
        await session.commit()
        return _Kurulum(
            period_id=period.id,
            payable_line_id=odenebilir.id,
            excluded_line_id=taseron.id,
            personnel_ids=[k.id for k in kisiler],
            actor_ids=[a.id for a in aktorler],
            role_id=role.id,
        )


async def _gorevleri_bosalt(*gorevler: asyncio.Task | None) -> None:
    """Temizlikten ÖNCE görevleri sonlandırır — MUTASYON DENETİMİ İÇİN ŞART.

    Kilit kaldırıldığında `not task2.done()` iddiası kırmızıya döner ve test
    gövdesi ORTADA terk edilir; `task1` hâlâ commit etmemiş bir transaction
    içinde satır kilidi TUTUYOR olur. Bu boşaltma olmadan `_temizle`nin DELETE'i
    o kilidi SONSUZA DEK bekler ve kırmızı test SONSUZ ASKIYA dönüşürdü —
    mutasyon kanıtı okunamaz hâle gelirdi.
    """
    for gorev in gorevler:
        if gorev is None:
            continue
        gorev.cancel()
        with contextlib.suppress(BaseException):
            await gorev


async def _temizle(kurulum: _Kurulum) -> None:
    """`_kur`un yarattığı HER satırı geri alır (satırlar dönemle CASCADE gitse de
    `personnel` RESTRICT olduğu için ÖNCE satırlar silinir)."""
    async with _SessionFactory() as session:
        await session.execute(
            delete(PayrollLine).where(PayrollLine.payroll_period_id == kurulum.period_id)
        )
        await session.execute(delete(PayrollPeriod).where(PayrollPeriod.id == kurulum.period_id))
        # T5: oran yarışı senaryosu bu yıl için satır YARATABİLİR (upsert).
        await session.execute(delete(PayrollRate).where(PayrollRate.year == _YIL))
        await session.execute(delete(Personnel).where(Personnel.id.in_(kurulum.personnel_ids)))
        await session.execute(delete(User).where(User.id.in_(kurulum.actor_ids)))
        await session.execute(delete(Role).where(Role.id == kurulum.role_id))
        await session.commit()


# --- Senaryo 1: aynı satıra iki eşzamanlı onay ------------------------------


async def _satiri_onayla_ve_tut(
    line_id: uuid.UUID,
    kilit_alindi: asyncio.Event,
    kilidi_birak: asyncio.Event,
) -> str:
    """tx1: onayı tamamlar (kilit + denetimler + flush) ama sinyal gelene kadar
    COMMIT ETMEZ — `SELECT … FOR UPDATE` kilidi bu süre boyunca AÇIK kalır
    (`flush` kilidi BIRAKMAZ, yalnız commit/rollback bırakır)."""
    async with _SessionFactory() as session:
        await service.approve_line(session, line_id)
        kilit_alindi.set()
        await kilidi_birak.wait()
        await session.commit()
        return "approved"


async def _satiri_onayla(line_id: uuid.UUID) -> str:
    async with _SessionFactory() as session:
        try:
            await service.approve_line(session, line_id)
            await session.commit()
            return "approved"
        except ConflictError:
            await session.rollback()
            return "conflict"


async def test_ayni_satira_iki_esZamanli_onay_TEK_onay_birakir() -> None:
    """🔴 Kilit YOKKEN ikisi de `pending` okur, ikisi de onaylar — satır İKİ KEZ
    onaylanmış olur ve ikinci onay birincinin damgasını ezer.

    Kilit VARKEN tx2 sıraya girer, tx1'in commit'ini görür (`approved`) ve geçiş
    tablosunda `approved → approved` OLMADIĞI için 409 alır.
    """
    kurulum = await _kur(
        ay=1,
        period_status=PayrollPeriodStatus.draft,
        payable_status=PayrollLineStatus.pending,
    )
    kilit_alindi = asyncio.Event()
    kilidi_birak = asyncio.Event()
    task1: asyncio.Task | None = None
    task2: asyncio.Task | None = None
    try:
        task1 = asyncio.create_task(
            _satiri_onayla_ve_tut(kurulum.payable_line_id, kilit_alindi, kilidi_birak)
        )
        await asyncio.wait_for(kilit_alindi.wait(), timeout=5)

        task2 = asyncio.create_task(_satiri_onayla(kurulum.payable_line_id))
        await asyncio.sleep(0.3)
        assert not task2.done(), (
            "tx2, tx1 kilidi serbest bırakmadan ilerleyebildi — satır onayı artık "
            "dönem/satır satırını KİLİTLEMİYOR olabilir (çift onay yarışı yeniden açık)"
        )

        kilidi_birak.set()
        sonuc1 = await asyncio.wait_for(task1, timeout=5)
        sonuc2 = await asyncio.wait_for(task2, timeout=5)
        assert sorted([sonuc1, sonuc2]) == ["approved", "conflict"]

        async with _SessionFactory() as dogrula:
            satir = await dogrula.get(PayrollLine, kurulum.payable_line_id)
            assert satir.status is PayrollLineStatus.approved
    finally:
        await _gorevleri_bosalt(task1, task2)
        await _temizle(kurulum)


# --- Senaryo 2: aynı döneme iki eşzamanlı ödeme -----------------------------


async def _odeme_yap_ve_tut(
    period_id: uuid.UUID,
    kilit_alindi: asyncio.Event,
    kilidi_birak: asyncio.Event,
) -> Decimal:
    async with _SessionFactory() as session:
        sonuc, _ = await service.pay_period(session, period_id)
        kilit_alindi.set()
        await kilidi_birak.wait()
        await session.commit()
        return sonuc.paid_net_total


async def _odeme_yap(period_id: uuid.UUID) -> Decimal | str:
    async with _SessionFactory() as session:
        try:
            sonuc, _ = await service.pay_period(session, period_id)
            await session.commit()
            return sonuc.paid_net_total
        except ConflictError:
            await session.rollback()
            return "conflict"


async def test_ayni_doneme_iki_esZamanli_ODEME_toplami_iki_kez_saymaz() -> None:
    """🔴 ASIL BULGU — iki eşzamanlı `pay` = İKİ PARA ÇIKIŞI.

    Kilitsiz hâlde ikisi de dönemi `approved` okur, ikisi de `paid_at` damgasını
    basar ve ikisi de AYNI 6.681,69 ₺'yi ödenecek toplam olarak raporlar; ödeme
    talimatı iki kez üretilir. Kilit VARKEN tx2 sıraya girer, `paid` durumu
    tazelenmiş olarak okur ve geçiş tablosunda `paid → paid` OLMADIĞI için 409
    alır: toplam BİR KEZ sayılır, dönem TEK bir tutarlı duruma oturur.
    """
    kurulum = await _kur(
        ay=2,
        period_status=PayrollPeriodStatus.approved,
        payable_status=PayrollLineStatus.approved,
    )
    kilit_alindi = asyncio.Event()
    kilidi_birak = asyncio.Event()
    task1: asyncio.Task | None = None
    task2: asyncio.Task | None = None
    try:
        task1 = asyncio.create_task(
            _odeme_yap_ve_tut(kurulum.period_id, kilit_alindi, kilidi_birak)
        )
        await asyncio.wait_for(kilit_alindi.wait(), timeout=5)

        task2 = asyncio.create_task(_odeme_yap(kurulum.period_id))
        await asyncio.sleep(0.3)
        assert not task2.done(), (
            "ikinci ödeme, birincinin kilidi serbest bırakılmadan ilerleyebildi — "
            "`pay` dönem satırını KİLİTLEMİYOR olabilir (ÇİFT ÖDEME penceresi açık)"
        )

        kilidi_birak.set()
        sonuc1 = await asyncio.wait_for(task1, timeout=5)
        sonuc2 = await asyncio.wait_for(task2, timeout=5)
        assert sonuc1 == SIRKET_NET
        assert sonuc2 == "conflict", "ikinci ödeme de geçti — aynı bordro İKİ KEZ ödendi"

        async with _SessionFactory() as dogrula:
            period = await dogrula.get(PayrollPeriod, kurulum.period_id)
            assert period.status is PayrollPeriodStatus.paid
            assert period.paid_at is not None
            odenebilir = await dogrula.get(PayrollLine, kurulum.payable_line_id)
            assert odenebilir.status is PayrollLineStatus.paid
            # K2 yarış altında da tutar: taşeron satırı ÖDENMEDİ.
            taseron = await dogrula.get(PayrollLine, kurulum.excluded_line_id)
            assert taseron.status is PayrollLineStatus.excluded
    finally:
        await _gorevleri_bosalt(task1, task2)
        await _temizle(kurulum)


# --- Senaryo 3: aynı döneme iki eşzamanlı TOPLU onay ------------------------


async def _toplu_onayla_ve_tut(
    period_id: uuid.UUID,
    actor_id: uuid.UUID,
    kilit_alindi: asyncio.Event,
    kilidi_birak: asyncio.Event,
) -> tuple[int, str]:
    async with _SessionFactory() as session:
        sonuc, _ = await service.approve_period(session, actor_id, period_id)
        kilit_alindi.set()
        await kilidi_birak.wait()
        await session.commit()
        return sonuc.approved, sonuc.period_status.value


async def _toplu_onayla(period_id: uuid.UUID, actor_id: uuid.UUID) -> tuple[int, str]:
    async with _SessionFactory() as session:
        sonuc, _ = await service.approve_period(session, actor_id, period_id)
        await session.commit()
        return sonuc.approved, sonuc.period_status.value


async def test_iki_esZamanli_TOPLU_onay_satiri_iki_kez_onaylamaz() -> None:
    """BY 303 "Tümünü Onayla" iki kez tıklanırsa: satır BİR KEZ onaylanır.

    Kilitsiz hâlde iki istek de satırı `pending` okur, ikisi de "1 satır
    onaylandı" raporlar ve dönemi AYNI adıma iki kez iter (`draft →
    pending_approval` iki kez) — kullanıcı ekranda iki farklı sayı görür.
    Kilitle tx2 sıraya girer, tazelenmiş durumu okur ve dönemi BİR SONRAKİ
    adıma taşır, onaylanacak satır bulamaz.
    """
    kurulum = await _kur(
        ay=3,
        period_status=PayrollPeriodStatus.draft,
        payable_status=PayrollLineStatus.pending,
    )
    kilit_alindi = asyncio.Event()
    kilidi_birak = asyncio.Event()
    task1: asyncio.Task | None = None
    task2: asyncio.Task | None = None
    try:
        task1 = asyncio.create_task(
            _toplu_onayla_ve_tut(
                kurulum.period_id, kurulum.actor_ids[0], kilit_alindi, kilidi_birak
            )
        )
        await asyncio.wait_for(kilit_alindi.wait(), timeout=5)

        task2 = asyncio.create_task(_toplu_onayla(kurulum.period_id, kurulum.actor_ids[1]))
        await asyncio.sleep(0.3)
        assert not task2.done(), (
            "ikinci toplu onay beklemedi — `approve_period` dönem satırını "
            "KİLİTLEMİYOR olabilir (çift onay/çift toplam penceresi açık)"
        )

        kilidi_birak.set()
        sayi1, durum1 = await asyncio.wait_for(task1, timeout=5)
        sayi2, durum2 = await asyncio.wait_for(task2, timeout=5)
        assert (sayi1, sayi2) == (1, 0), "satır iki kez onaylandı"
        assert durum1 == PayrollPeriodStatus.pending_approval.value
        assert durum2 == PayrollPeriodStatus.approved.value, (
            "ikinci onay dönemi İLERLETMEDİ — tazelenmiş durumu görmemiş olabilir"
        )
    finally:
        await _gorevleri_bosalt(task1, task2)
        await _temizle(kurulum)


# --- Kilidin VARLIĞI, SIRASI ve YERİ (SQL düzeyinde) -----------------------


async def test_onay_denetimlerden_ONCE_donem_ve_satir_satirini_kilitler() -> None:
    """Kilit SQL'de görünür: dönem `FOR UPDATE` → satır `FOR UPDATE` → durum okuması.

    Üç şeyi çiviler:

    1. `payroll_periods` satırı `FOR UPDATE` ile okunur (serileştirme SAHİP
       satırdadır — satırların ana kaydı dönemdir);
    2. `payroll_lines` satırı da `FOR UPDATE` ile okunur;
    3. **dönem kilidi satır kilidinden ÖNCE gelir** — sıra TÜM uçlarda sabittir,
       ters sırada kilitleyen bir yol eklenirse karşılıklı kilitlenme doğar;
    4. satırın DURUMU yalnız kilit ALTINDA okunur: kilitsiz bir `status`
       okuması kilitten önce gelseydi TOCTOU penceresi açık kalırdı.
    """
    kurulum = await _kur(
        ay=4,
        period_status=PayrollPeriodStatus.draft,
        payable_status=PayrollLineStatus.pending,
    )
    ifadeler: list[str] = []

    def kaydet(conn, cursor, statement, parameters, context, executemany) -> None:  # noqa: ANN001
        ifadeler.append(" ".join(statement.split()))

    event.listen(test_engine.sync_engine, "before_cursor_execute", kaydet)
    try:
        async with _SessionFactory() as session:
            await service.approve_line(session, kurulum.payable_line_id)
            await session.commit()
    finally:
        event.remove(test_engine.sync_engine, "before_cursor_execute", kaydet)
        await _temizle(kurulum)

    kilitli = [i for i, ifade in enumerate(ifadeler) if "FOR UPDATE" in ifade]
    donem_kilidi = [i for i in kilitli if "FROM payroll_periods" in ifadeler[i]]
    satir_kilidi = [i for i in kilitli if "FROM payroll_lines" in ifadeler[i]]
    durum_okumasi = [i for i, ifade in enumerate(ifadeler) if "payroll_lines.status" in ifade]

    assert donem_kilidi, f"dönem satırı FOR UPDATE ile okunmadı: {ifadeler}"
    assert satir_kilidi, f"bordro satırı FOR UPDATE ile okunmadı: {ifadeler}"
    assert donem_kilidi[0] < satir_kilidi[0], f"kilit sırası ters (dönem → satır): {ifadeler}"
    assert durum_okumasi, f"satır durumu hiç okunmadı: {ifadeler}"
    assert donem_kilidi[0] < durum_okumasi[0], (
        "satır durumu kilitten ÖNCE okunmuş — TOCTOU penceresi açık"
    )


async def test_odeme_de_AYNI_sirayla_kilitler() -> None:
    """`pay` da dönem → satır sırasını korur (deadlock önlemi, tüm uçlarda SABİT)."""
    kurulum = await _kur(
        ay=5,
        period_status=PayrollPeriodStatus.approved,
        payable_status=PayrollLineStatus.approved,
    )
    ifadeler: list[str] = []

    def kaydet(conn, cursor, statement, parameters, context, executemany) -> None:  # noqa: ANN001
        ifadeler.append(" ".join(statement.split()))

    event.listen(test_engine.sync_engine, "before_cursor_execute", kaydet)
    try:
        async with _SessionFactory() as session:
            await service.pay_period(session, kurulum.period_id)
            await session.commit()
    finally:
        event.remove(test_engine.sync_engine, "before_cursor_execute", kaydet)
        async with _SessionFactory() as dogrula:
            odenen = (
                (
                    await dogrula.execute(
                        select(PayrollLine.status).where(
                            PayrollLine.payroll_period_id == kurulum.period_id
                        )
                    )
                )
                .scalars()
                .all()
            )
        await _temizle(kurulum)

    kilitli = [i for i, ifade in enumerate(ifadeler) if "FOR UPDATE" in ifade]
    donem_kilidi = [i for i in kilitli if "FROM payroll_periods" in ifadeler[i]]
    satir_kilidi = [i for i in kilitli if "FROM payroll_lines" in ifadeler[i]]

    assert donem_kilidi, f"dönem satırı FOR UPDATE ile okunmadı: {ifadeler}"
    assert satir_kilidi, f"bordro satırları FOR UPDATE ile okunmadı: {ifadeler}"
    assert donem_kilidi[0] < satir_kilidi[0], f"kilit sırası ters (dönem → satır): {ifadeler}"
    assert sorted(d.value for d in odenen) == ["excluded", "paid"]


# --- Senaryo 4: dönem onayı ile ORAN YAZIMI yarışı (T5) --------------------
#
# 🔴 Bu senaryonun ölçtüğü şey bir çift onay değil, GEÇMİŞİN DEĞİŞMESİDİR.
# `upsert_rate` "bu yılda onaylanmış/ödenmiş dönem var mı?" diye sorar; kilitsiz
# hâlde bu soru ile cevabın kullanılması arasında bir `approve_period` commit
# edebilir ve oran yazısı ONAYLANMIŞ bir dönemin raporlanmış işveren maliyetini
# geriye dönük değiştirir (mutasyon kanıtı: 42.230,00 → 43.085,00).


async def _yaz_orani(year: int) -> str:
    from app.modules.payroll.schemas import PayrollRateUpdate

    govde = PayrollRateUpdate(
        sgk_employee_pct=Decimal("14.000"),
        unemployment_employee_pct=Decimal("1.000"),
        income_tax_pct=Decimal("10.000"),
        stamp_tax_pct=Decimal("0.759"),
        sgk_employer_pct=Decimal("30.000"),
        unemployment_employer_pct=Decimal("2.000"),
        short_work_pct=Decimal("1.000"),
    )
    async with _SessionFactory() as session:
        try:
            await service.upsert_rate(session, year, WorkerSource.company, govde)
            await session.commit()
            return "written"
        except ConflictError:
            await session.rollback()
            return "conflict"


async def test_oran_yazimi_esZamanli_DONEM_ONAYINI_bekler() -> None:
    """🔴 T5 — oran kapısı dönem satırında SERİLEŞİR (EŞİK = KİLİT).

    tx1 dönemi `approved`e taşır ve kilidi TUTAR; tx2 oran yazmaya çalışır ve
    BEKLER. Serbest bırakılınca tx2 tazelenmiş durumu okur ve **409** alır —
    onaylanmış dönemin hesabı geriye dönük değişmez.

    Kilit `WHERE status IN (...)` süzgeciyle alınsaydı bu test KIRMIZI olurdu:
    tx1 henüz commit etmediği için tx2 hiçbir "onaylı" satır bulamaz, hiçbir
    şey kilitlemez ve oranı YAZARDI (TOCTOU).
    """
    kurulum = await _kur(
        ay=4,
        period_status=PayrollPeriodStatus.pending_approval,
        payable_status=PayrollLineStatus.pending,
    )
    kilit_alindi = asyncio.Event()
    kilidi_birak = asyncio.Event()
    task1: asyncio.Task | None = None
    task2: asyncio.Task | None = None
    try:
        task1 = asyncio.create_task(
            _toplu_onayla_ve_tut(
                kurulum.period_id, kurulum.actor_ids[0], kilit_alindi, kilidi_birak
            )
        )
        await asyncio.wait_for(kilit_alindi.wait(), timeout=5)

        task2 = asyncio.create_task(_yaz_orani(_YIL))
        await asyncio.sleep(0.3)
        assert not task2.done(), (
            "oran yazımı, dönem onayının kilidi serbest bırakılmadan ilerledi — "
            "`upsert_rate` yılın dönem satırlarını KİLİTLEMİYOR olabilir "
            "(onaylanmış dönemin hesabı geriye dönük değişebilir)"
        )

        kilidi_birak.set()
        _, durum1 = await asyncio.wait_for(task1, timeout=5)
        sonuc2 = await asyncio.wait_for(task2, timeout=5)
        assert durum1 == PayrollPeriodStatus.approved.value
        assert sonuc2 == "conflict", "oran yazıldı — onaylanmış dönemin hesabı değişti"
    finally:
        await _gorevleri_bosalt(task1, task2)
        await _temizle(kurulum)
