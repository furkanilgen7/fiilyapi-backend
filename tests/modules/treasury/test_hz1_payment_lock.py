"""HZ-1 T4 — 🔴 K7: EŞİK = KİLİT. Ödeme yolu faturayı DENETİMDEN ÖNCE kilitler.

Spec §3/K7: *"K6 bir eşik denetimidir → kilitsiz yapılamaz. Kilit fatura
satırındadır, denetimlerden ÖNCE alınır (TOCTOU), sıra SABİT: fatura → ödemeler
→ hesap. Regresyon İKİ GERÇEK BAĞLANTIYLA yazılır ve kilit kaldırılınca KIRMIZI
olduğu KANITLANIR."*

## Niçin `client`/`seeded_db` KULLANILMAZ

Kök `tests/conftest.py`'deki `db_session` her testi TEK bağlantı üzerinde
SAVEPOINT'e sarar ve dış transaction'ı asla gerçekten COMMIT ETMEZ — o session
üzerinde iki görev AYNI bağlantıyı paylaşır ve gerçek satır kilidi test EDİLEMEZ.
Bu dosya `tests/modules/invoicing/test_invoicing_lock.py` desenini izler:
`test_engine` üzerinden İKİ BAĞIMSIZ bağlantı, gerçek commit, gerçek temizlik.

## 🔴 ÇAKIŞMA PENCERESİ DETERMİNİSTİKTİR — sabit `sleep` YOKTUR

FAT-1'in kilit testi mutasyonlu hâlde **dosya bütün koşulunca** kırmızıydı ama
**TEK BAŞINA koşulunca YEŞİLDİ**: izole koşuda havuz SOĞUKTUR, ilk görev bağlantı
kurulumunu beklerken ikincisi henüz başlamamış olur ve iki görev hiç
çakışmaz — bekçi kırılgandır, kusur testtedir.

Bu dosyadaki iki bekçi de o zaafı devralmaz ve İKİSİ DE sabit `asyncio.sleep`
ile pencere AÇMAZ — ama farklı yollarla:

1. **Uç 7 (`test_K6_ESZAMANLI_iki_tahsilat_BIR_KEZ_gecer`) — BARAJ.** Her görev
   önce kendi bağlantısını kurar ve üzerinde gerçek bir sorgu
   (`session.get(User, …)`) koşturur; ancak ondan SONRA `asyncio.Barrier`a
   varır. Isınma barajdan sonra yapılsaydı izole koşuda bağlantı kurulum
   gecikmesi iki görevi sıraya sokar ve pencere HİÇ AÇILMAZDI. Baraj açıldığında
   iki bağlantı da sıcaktır; kilit kaldırılırsa ikisi de `Σ = 0` okur, ikisi de
   K6'yı geçer ve fatura tutarının **%120'si** tahsil edilmiş görünür (İK-3'te
   iki eşzamanlı ödeme bordroyu İKİ KEZ ödemişti).

2. **Uç 8 (`test_SILME_de_faturayi_DENETIMDEN_ONCE_kilitler`) — TUTULAN KİLİT.**
   🔴 Burada bilinçli olarak bir YARIŞ kurulmaz: "bir ekleme ile bir silmeyi aynı
   anda koştur" biçimindeki bir yarış, hangi görevin önce commit ettiğine göre
   kusuru bazen GİZLER (silme önce commit ederse kilitsiz sonuç da doğru çıkar) —
   bu tam olarak FAT-1'in kırılgan bekçisinin sınıfıdır ve ölçülerek doğrulandı:
   o biçim mutasyonlu hâlde 3/3 YEŞİL geliyordu. Yerine tx0 fatura kilidini
   GERÇEKTEN tutar ve silme görevinin İLERLEYEMEDİĞİ ölçülür; sonuç iki yönde de
   zamanlamadan bağımsızdır.
"""

import asyncio
import contextlib
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import TreasuryValidationError
from app.core.security import hash_password
from app.modules.invoicing.models import (
    Invoice,
    InvoiceDirection,
    InvoiceDocumentType,
    InvoiceStatus,
)
from app.modules.roles.models import Role
from app.modules.treasury import payments_service, repository
from app.modules.treasury.models import BankAccount, BankAccountType, Payment, PaymentMethodKind
from app.modules.treasury.schemas import PaymentCreate
from app.modules.users.models import User
from tests.conftest import test_engine

_SessionFactory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

#: Rol anahtarı ve e-postalar TESTE ÖZELDİR: bu dosya GERÇEKTEN commit ettiği
#: için sızıntı ancak yaratılan satırların tam bilinmesiyle kapanır.
_ROL_ANAHTARI = "hz1_conc_admin"
_EPOSTALAR = ("hz1-kilit1@conc.co", "hz1-kilit2@conc.co")

#: Baraj/görev bekleyişlerinin tavanı. Kilit DOĞRUYKEN görevler saniyenin
#: altında biter; tavan yalnızca BOZUK bir kurulumun testi sonsuza asmasını
#: engeller — pencere açmak için KULLANILMAZ.
_TAVAN_SANIYE = 15

#: "Bloke kalmalı" iddiasının ÜST SINIRI. Bu bir pencere AÇMAZ (çakışma zaten
#: tutulan gerçek bir kilitle garanti altındadır); yalnızca "bitmemeli"yi sonlu
#: sürede karara bağlar. Kilit yerindeyken görev bu süre içinde ASLA bitmez;
#: kaldırılırsa milisaniyeler içinde biter — iki yön de zamanlamadan bağımsız.
_BLOKE_TAVANI = 2


class _Kurulum:
    def __init__(
        self,
        invoice_id: uuid.UUID,
        account_id: uuid.UUID,
        actor_ids: list[uuid.UUID],
        role_id: uuid.UUID,
        payment_id: uuid.UUID | None = None,
    ) -> None:
        self.invoice_id = invoice_id
        self.account_id = account_id
        self.actor_ids = actor_ids
        self.role_id = role_id
        self.payment_id = payment_id


async def _kur(
    *,
    total: str = "1000.00",
    status: InvoiceStatus = InvoiceStatus.sent,
    mevcut_odeme: str | None = None,
) -> _Kurulum:
    """Fatura PROJESİZ açılır (`project_id` NULL, FAT-1 §6 şirket geneli).

    Kurulum böylece proje/şantiye/`user_project_access` satırı YARATMAK ZORUNDA
    KALMAZ — gerçekten commit eden bir testte yaratılan her satır bir sızıntı
    riskidir. İzin satırı da gerekmez: yetki kapısı ROUTER'dadır, bu dosya
    SERVİSİ doğrudan çağırır.
    """
    async with _SessionFactory() as session:
        role = Role(key=_ROL_ANAHTARI, name="Hazine Eşzamanlılık Rolü")
        session.add(role)
        await session.flush()
        aktorler = [
            User(
                email=eposta,
                password_hash=hash_password("parola1234"),
                full_name=f"Kilit Aktörü {sira}",
                role_id=role.id,
            )
            for sira, eposta in enumerate(_EPOSTALAR, start=1)
        ]
        session.add_all(aktorler)
        await session.flush()

        account = BankAccount(
            bank_name="Eşzamanlılık Bank",
            account_type=BankAccountType.checking,
            iban="TR00CONCURRENCY0000000001",
            opening_balance=Decimal("0.00"),
        )
        session.add(account)

        tutar = Decimal(total)
        invoice = Invoice(
            direction=InvoiceDirection.outgoing,
            invoice_no="HZCONC000001",
            document_type=InvoiceDocumentType.einvoice,
            status=status,
            issue_date=date(2026, 8, 1),
            party_name="Eşzamanlılık A.Ş.",
            subtotal=tutar,
            advance_amount=Decimal("0.00"),
            retention_amount=Decimal("0.00"),
            tax_base=tutar,
            vat_amount=Decimal("0.00"),
            withholding_amount=Decimal("0.00"),
            total=tutar,
            created_by_id=aktorler[0].id,
        )
        session.add(invoice)
        await session.flush()

        payment_id: uuid.UUID | None = None
        if mevcut_odeme is not None:
            payment = Payment(
                invoice_id=invoice.id,
                bank_account_id=account.id,
                method=PaymentMethodKind.transfer,
                amount=Decimal(mevcut_odeme),
                paid_on=date(2026, 8, 10),
                created_by_id=aktorler[0].id,
            )
            session.add(payment)
            await session.flush()
            payment_id = payment.id

        await session.commit()
        return _Kurulum(invoice.id, account.id, [a.id for a in aktorler], role.id, payment_id)


async def _gorevleri_bosalt(*gorevler: asyncio.Task | None) -> None:
    """Temizlikten ÖNCE görevleri sonlandırır — MUTASYON DENETİMİ İÇİN ŞART.

    Kilit kaldırıldığında iddia kırmızıya döner ve gövde ORTADA terk edilir; bir
    görev hâlâ commit etmemiş bir transaction içinde kilit tutuyor olabilir. Bu
    boşaltma olmadan `_temizle`nin DELETE'i o kilidi sonsuza dek bekler ve
    kırmızı test SONSUZ ASKIYA dönüşürdü (İK-2 dersi).
    """
    for gorev in gorevler:
        if gorev is None:
            continue
        gorev.cancel()
        with contextlib.suppress(BaseException):
            await gorev


async def _temizle(kurulum: _Kurulum) -> None:
    async with _SessionFactory() as session:
        await session.execute(delete(Payment).where(Payment.invoice_id == kurulum.invoice_id))
        await session.execute(delete(Invoice).where(Invoice.id == kurulum.invoice_id))
        await session.execute(delete(BankAccount).where(BankAccount.id == kurulum.account_id))
        await session.execute(delete(User).where(User.id.in_(kurulum.actor_ids)))
        await session.execute(delete(Role).where(Role.id == kurulum.role_id))
        await session.commit()


async def _guvenli_temizlik(kurulum: _Kurulum, *gorevler: asyncio.Task | None) -> None:
    """Görevleri boşalt, sonra TAVANLI temizle.

    Temizliğin kendi hatası `finally` içinde ASIL iddianın hata metnini
    EZMEMELİDİR: mutasyon koşusunda okunması gereken şey kilit iddiasıdır,
    temizliğin zaman aşımı değil.
    """
    await _gorevleri_bosalt(*gorevler)
    with contextlib.suppress(Exception):
        await asyncio.wait_for(_temizle(kurulum), timeout=_TAVAN_SANIYE)


async def _isin_ve_bekle(
    session: AsyncSession, actor_id: uuid.UUID, baraj: asyncio.Barrier
) -> User:
    """🔴 ISINMA + BARAJ — determinizmin tamamı buradadır.

    `session.get` bağlantıyı havuzdan ÇEKER, transaction'ı başlatır ve gerçek
    bir sorgu koşturur. Baraja ancak ondan sonra varılır; ısınma barajdan SONRA
    yapılsaydı (ya da hiç yapılmasaydı) izole koşuda bağlantı kurulum gecikmesi
    iki görevi sıraya sokar ve çakışma penceresi HİÇ AÇILMAZDI.
    """
    actor = await session.get(User, actor_id)
    await asyncio.wait_for(baraj.wait(), timeout=_TAVAN_SANIYE)
    return actor


async def _tahsilat(
    kurulum: _Kurulum, aktor_sirasi: int, tutar: str, baraj: asyncio.Barrier
) -> str:
    """Bağımsız bir bağlantıda TAM yol: kilit → Σ → hesap → K6 → yazma → damga."""
    async with _SessionFactory() as session:
        actor = await _isin_ve_bekle(session, kurulum.actor_ids[aktor_sirasi], baraj)
        try:
            await payments_service.create_payment(
                session,
                actor,
                kurulum.invoice_id,
                PaymentCreate(
                    bank_account_id=kurulum.account_id,
                    method=PaymentMethodKind.transfer,
                    amount=Decimal(tutar),
                    paid_on=date(2026, 8, 14),
                ),
            )
        except TreasuryValidationError:
            await session.rollback()
            return "rejected"
        await session.commit()
        return "created"


async def _kilidi_al_ve_tut(
    kurulum: _Kurulum, kilit_alindi: asyncio.Event, kilidi_birak: asyncio.Event
) -> str:
    """tx0: fatura satırının kilidini alır (HİÇBİR kolona yazmaz) ve tutar.

    Yazmadığı için `UPDATE`in örtük satır kilidi devrede DEĞİLDİR: karşı tarafı
    bekleten tek şey OKUMADAKİ açık `FOR UPDATE`tir.
    """
    async with _SessionFactory() as session:
        actor = await session.get(User, kurulum.actor_ids[0])
        await payments_service._locked_invoice(session, actor, kurulum.invoice_id)
        kilit_alindi.set()
        await kilidi_birak.wait()
        await session.commit()
        return "locked"


async def _silme(kurulum: _Kurulum, aktor_sirasi: int) -> str:
    async with _SessionFactory() as session:
        actor = await session.get(User, kurulum.actor_ids[aktor_sirasi])
        await payments_service.delete_payment(session, actor, kurulum.payment_id)
        await session.commit()
        return "deleted"


async def _fatura_durumu(invoice_id: uuid.UUID) -> tuple[InvoiceStatus, Decimal]:
    """Son sözü DB söyler: durum + Σ payments TAZE bir bağlantıdan okunur."""
    async with _SessionFactory() as session:
        invoice = await session.get(Invoice, invoice_id)
        toplam = await repository.paid_total_for_invoice(session, invoice_id)
        return invoice.status, toplam


async def test_K6_ESZAMANLI_iki_tahsilat_BIR_KEZ_gecer() -> None:
    """🔴 ASIL MUTASYON REGRESYONU — EŞİK = KİLİT (spec §3 K7).

    İki gerçek bağlantı 1.000,00₺'lik faturaya AYNI ANDA 600,00₺ tahsilat
    yazmaya çalışır. Doğru davranış: BİRİ geçer, ÖTEKİ K6'dan **422** alır.

    `create_payment` içindeki `for_update=True` kaldırılırsa ikisi de `Σ = 0`
    okur, ikisi de kapıdan geçer ve fatura 1.200,00₺ tahsil edilmiş görünür —
    o hâlde aşağıdaki İKİ iddia da kırmızıya döner.
    """
    kurulum = await _kur(total="1000.00")
    baraj = asyncio.Barrier(2)
    gorevler: list[asyncio.Task] = []
    try:
        gorevler = [
            asyncio.create_task(_tahsilat(kurulum, 0, "600.00", baraj)),
            asyncio.create_task(_tahsilat(kurulum, 1, "600.00", baraj)),
        ]
        sonuclar = list(await asyncio.wait_for(asyncio.gather(*gorevler), timeout=_TAVAN_SANIYE))
        assert sonuclar.count("created") == 1, (
            f"iki eşzamanlı tahsilat da geçti ({sonuclar}) — `create_payment` faturayı "
            "K6 EŞİĞİNDEN ÖNCE kilitlemiyor; fatura tutarının üstünde tahsilat yazıldı"
        )
        assert sonuclar.count("rejected") == 1, sonuclar

        _, toplam = await _fatura_durumu(kurulum.invoice_id)
        assert toplam == Decimal("600.00"), f"Σ payments fatura tutarını aştı: {toplam}"
    finally:
        await _guvenli_temizlik(kurulum, *gorevler)


async def test_SILME_de_faturayi_DENETIMDEN_ONCE_kilitler() -> None:
    """🔴 Uç 8 de AYNI kilidi alır (spec §4 md.8) — DETERMİNİSTİK BEKÇİ.

    Silme faturanın durumunu YENİDEN TÜRETİR, yani `Σ payments` üzerinde bir
    oku-değiştir-yaz koşar; kilitsiz hâlde eşzamanlı bir tahsilatla birleşince
    fatura hiç tam tahsil edilmemişken `collected` kalabilir.

    ## Neden ZAMANLAMA YARIŞI DEĞİL, TUTULAN KİLİT ölçülür

    "Bir ekleme ile bir silmeyi aynı anda koştur" biçimindeki bir yarış, hangi
    görevin önce commit ettiğine göre kusuru bazen GİZLER (silme önce commit
    ederse kilitsiz sonuç da doğru çıkar) — tam olarak FAT-1'in kırılgan
    bekçisinin sınıfı. Burada bunun yerine tx0 fatura kilidini GERÇEKTEN tutar
    ve silme görevinin İLERLEYEMEDİĞİ ölçülür:

    * kilit YERİNDEYSE görev `_locked_invoice`ta DB düzeyinde bloke olur ve
      tavan içinde ASLA bitmez — sonuç zamanlamadan bağımsızdır;
    * kilit KALDIRILIRSA görev hiçbir şey beklemez ve milisaniyeler içinde
      biter, `asyncio.wait_for` zaman aşımına DÜŞMEZ → iddia KIRMIZI.

    Kurulum, silmenin durumu DEĞİŞTİRMEYECEĞİ şekilde seçilmiştir (`sent` fatura,
    kısmi ödeme): mutasyonlu koşuda görev `invoices` satırına hiç UPDATE
    atmasın, yoksa tx0'ın kilidine takılır ve testi yanlış sebeple yeşile
    çevirirdi.
    """
    kurulum = await _kur(total="1000.00", status=InvoiceStatus.sent, mevcut_odeme="400.00")
    kilit_alindi = asyncio.Event()
    kilidi_birak = asyncio.Event()
    tx0: asyncio.Task | None = None
    silici: asyncio.Task | None = None
    try:
        tx0 = asyncio.create_task(_kilidi_al_ve_tut(kurulum, kilit_alindi, kilidi_birak))
        await asyncio.wait_for(kilit_alindi.wait(), timeout=_TAVAN_SANIYE)

        silici = asyncio.create_task(_silme(kurulum, 1))
        try:
            sonuc = await asyncio.wait_for(asyncio.shield(silici), timeout=_BLOKE_TAVANI)
        except TimeoutError:
            sonuc = None
        assert sonuc is None, (
            "silme, tx0 fatura kilidini tutarken tamamlandı — `delete_payment` `invoices` "
            "satırını DENETİMDEN ÖNCE KİLİTLEMİYOR (TOCTOU penceresi yeniden açık)"
        )

        # Kilit bırakılınca görev UYANIR ve tamamlanır: bekleyiş bir çakılma
        # değil GERÇEK bir kilit beklemesiydi.
        kilidi_birak.set()
        assert await asyncio.wait_for(tx0, timeout=_TAVAN_SANIYE) == "locked"
        assert await asyncio.wait_for(silici, timeout=_TAVAN_SANIYE) == "deleted"

        durum, toplam = await _fatura_durumu(kurulum.invoice_id)
        assert toplam == Decimal("0.00"), toplam
        assert durum is InvoiceStatus.sent, durum
    finally:
        kilidi_birak.set()
        await _guvenli_temizlik(kurulum, tx0, silici)
