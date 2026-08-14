"""FAT-1 T3/T4 — 🔴 EŞİK = KİLİT: yazan uçlar faturayı DENETİMDEN ÖNCE kilitler.

Spec §8/2: *"fatura satırı `with_for_update` + `populate_existing` ile kilitlenir,
kilit denetimlerden ÖNCE alınır (TOCTOU)"* ve §8/3: *"regresyon İKİ GERÇEK
BAĞLANTIYLA yazılır ve kilit kaldırılınca KIRMIZI olduğu kanıtlanır."*

## Niçin `client`/`seeded_db` KULLANILMAZ

`tests/conftest.py`'deki `db_session` her testi TEK bağlantı üzerinde SAVEPOINT'e
sarar ve dış transaction'ı asla gerçekten COMMIT ETMEZ — o session üzerinde iki
`asyncio.gather` görevi AYNI bağlantıyı paylaşır ve gerçek satır kilidi test
EDİLEMEZ. Bu dosya `tests/modules/equipment/test_mk1_work_log_concurrency.py`
desenini birebir izler: `test_engine` üzerinden İKİ BAĞIMSIZ bağlantı, gerçek
commit, sonunda gerçek temizlik.

## Neyi kanıtlar

tx1 `visible_invoice(..., for_update=True)` ile YALNIZCA kilidi alır ve tutar
(hiçbir kolon yazmaz). tx2 bir `PUT lines` koşar. Kilit varken tx2 BLOKE OLUR;
`with_for_update` kaldırılırsa tx1 hiçbir satır kilidi almaz, tx2 anında biter
ve `not task2.done()` iddiası KIRMIZI'ya döner — mutasyon denetimi budur.

Bu ayrım önemlidir: `UPDATE`in kendi örtük satır kilidi yazma ANINDA alınır,
denetimlerden SONRA. TOCTOU penceresini kapatan şey OKUMADAKİ açık kilittir.

## T4 — DURUM GEÇİŞİ eş zamanlı İKİ `send`te BİR KEZ koşar

`test_send_ESZAMANLI_iki_istekte_BIR_KEZ_gecer` ikinci bir şey daha kanıtlar:
kilit yalnız BEKLETMEZ, bekleyen istek uyandığında kararı YENİDEN verir. tx1
`draft → sent` yazıp commit ettikten sonra tx2 uyanır ve `populate_existing`
sayesinde BAYAT değil TAZE satırı okur — matris `(sent, send)` çiftini
tanımadığı için **409** alır. Kilit kaldırılsaydı ikisi de `draft` okur, ikisi
de geçer ve fatura İKİ KEZ gönderilmiş olurdu (İK-2 "eşik = kilit" kanonu).

## 🔴 ÇAKIŞMA PENCERESİ DETERMİNİSTİKTİR — sabit `sleep` YOKTUR (T4b)

O bekçi ilk hâlinde ÇIPLAK `asyncio.gather` ile yazılmıştı ve KIRILGANDI:
kilit kaldırıldığında **dosya bütün koşulunca** kırmızı oluyor, ama **tek başına
koşulunca 3/3 YEŞİL** kalıyordu. Sebep ölçüldü: izole koşuda bağlantı havuzu
SOĞUKTUR — ilk görev bağlantı kurulumunu beklerken ikincisi henüz başlamamış
olur, iki görev kritik anda hiç KESİŞMEZ ve kilitsiz kod da doğru sonucu verir.
*"Test var" ≠ "test bekçilik ediyor".*

Düzeltme `tests/modules/treasury/test_hz1_payment_lock.py` desenidir ve pencereyi
sabit `asyncio.sleep` ile AÇMAZ: her görev önce kendi bağlantısını ısıtır
(`session.get(User, …)` — bağlantıyı havuzdan çeker, transaction'ı başlatır),
ANCAK ONDAN SONRA `asyncio.Barrier`a varır. Isınma barajdan sonra yapılsaydı
kurulum gecikmesi görevleri yine sıraya sokardı. Baraj açıldığında iki bağlantı
da sıcaktır ve çakışma GARANTİDİR. İddialar DEĞİŞMEDİ — yalnız pencere
deterministikleşti.
"""

import asyncio
import contextlib
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import ConflictError
from app.core.security import hash_password
from app.modules.invoicing import service, state_service
from app.modules.invoicing.models import (
    Invoice,
    InvoiceDirection,
    InvoiceDocumentType,
    InvoiceLine,
    InvoiceStatus,
)
from app.modules.invoicing.schemas import InvoiceLineCreate, InvoiceLinesReplace
from app.modules.invoicing.transitions import InvoiceAction
from app.modules.roles.models import Role
from app.modules.users.models import User
from tests.conftest import test_engine

_SessionFactory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

#: Rol anahtarı TESTE ÖZELDİR: bu dosya GERÇEKTEN commit ettiği için sızıntı
#: ancak yaratılan satırların tam bilinmesiyle kapanır.
_ROL_ANAHTARI = "fat1_conc_admin"
_EPOSTALAR = ("fat1-kilit1@conc.co", "fat1-kilit2@conc.co")

#: Baraj/görev bekleyişlerinin tavanı. Kilit DOĞRUYKEN görevler saniyenin
#: altında biter; tavan yalnızca BOZUK bir kurulumun testi sonsuza asmasını
#: engeller — pencere AÇMAK için KULLANILMAZ.
_TAVAN_SANIYE = 15


class _Kurulum:
    def __init__(
        self, invoice_id: uuid.UUID, actor_ids: list[uuid.UUID], role_id: uuid.UUID
    ) -> None:
        self.invoice_id = invoice_id
        self.actor_ids = actor_ids
        self.role_id = role_id


async def _kur() -> _Kurulum:
    """Fatura PROJESİZ açılır (`project_id` NULL, §6 şirket geneli): kurulum
    proje/şantiye/`user_project_access` satırı YARATMAK ZORUNDA KALMAZ —
    gerçekten commit eden bir testte yaratılan her satır bir sızıntı riskidir."""
    async with _SessionFactory() as session:
        role = Role(key=_ROL_ANAHTARI, name="Fatura Eşzamanlılık Rolü")
        session.add(role)
        await session.flush()
        # İZİN SATIRI GEREKMEZ: yetki kapısı ROUTER'dadır (`require_permission`),
        # bu test SERVİSİ doğrudan çağırır. `visible_projects` izin satırı
        # bulamayınca `user_project_access`e düşer ve o da boştur — fatura
        # PROJESİZ açıldığı için (§6) kapsam süzgecine hiç takılmaz.
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

        invoice = Invoice(
            direction=InvoiceDirection.outgoing,
            invoice_no="FILCONC000001",
            document_type=InvoiceDocumentType.einvoice,
            status=InvoiceStatus.draft,
            issue_date=date(2026, 7, 18),
            party_name="Eşzamanlılık A.Ş.",
            subtotal=Decimal("0.00"),
            advance_amount=Decimal("0.00"),
            retention_amount=Decimal("0.00"),
            tax_base=Decimal("0.00"),
            vat_amount=Decimal("0.00"),
            withholding_amount=Decimal("0.00"),
            total=Decimal("0.00"),
            created_by_id=aktorler[0].id,
        )
        session.add(invoice)
        await session.flush()
        # T4: K6 kapısı kalemsiz faturayı 422 ile reddeder — eşzamanlılık testi
        # KİLİDİ ölçer, kapıyı değil, bu yüzden fatura KALEMLİ kurulur. Kalem
        # olmasaydı iki `send` de 422'de buluşur ve kilit hiç sınanmazdı.
        session.add(
            InvoiceLine(
                invoice_id=invoice.id,
                sort_order=0,
                description="Kurulum kalemi",
                unit="m³",
                quantity=Decimal("1.000"),
                unit_price=Decimal("1000.00"),
                vat_rate=Decimal("20.00"),
                line_total=Decimal("1000.00"),
            )
        )
        await session.flush()
        await session.commit()
        return _Kurulum(invoice.id, [a.id for a in aktorler], role.id)


async def _gorevleri_bosalt(*gorevler: asyncio.Task | None) -> None:
    """Temizlikten ÖNCE görevleri sonlandırır — MUTASYON DENETİMİ İÇİN ŞART.

    Kilit kaldırıldığında iddia kırmızıya döner ve gövde ORTADA terk edilir;
    tx1 hâlâ commit etmemiş bir transaction içinde kilit tutuyor olabilir. Bu
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
        await session.execute(
            delete(InvoiceLine).where(InvoiceLine.invoice_id == kurulum.invoice_id)
        )
        await session.execute(delete(Invoice).where(Invoice.id == kurulum.invoice_id))
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


async def _kilidi_al_ve_tut(
    kurulum: _Kurulum, kilit_alindi: asyncio.Event, kilidi_birak: asyncio.Event
) -> str:
    """tx1: YALNIZCA kilidi alır (hiçbir kolona yazmaz) ve sinyale kadar tutar."""
    async with _SessionFactory() as session:
        actor = await session.get(User, kurulum.actor_ids[0])
        await service.visible_invoice(session, actor, kurulum.invoice_id, for_update=True)
        kilit_alindi.set()
        await kilidi_birak.wait()
        await session.commit()
        return "locked"


async def _kalemleri_yaz(kurulum: _Kurulum) -> str:
    async with _SessionFactory() as session:
        actor = await session.get(User, kurulum.actor_ids[1])
        invoice = await service.visible_invoice(session, actor, kurulum.invoice_id, for_update=True)
        await service.replace_lines(
            session,
            invoice,
            InvoiceLinesReplace(
                lines=[
                    InvoiceLineCreate(
                        description="Eşzamanlı kalem",
                        quantity=Decimal("1.000"),
                        unit_price=Decimal("100.00"),
                        vat_rate=Decimal("20.00"),
                    )
                ]
            ),
        )
        await session.commit()
        return "written"


async def test_put_lines_faturayi_denetimden_ONCE_kilitler() -> None:
    """🔴 ASIL REGRESYON: kilit kalkarsa tx2 beklemeden ilerler.

    tx1 hiçbir kolona YAZMADIĞI için `UPDATE`in örtük satır kilidi devrede
    değildir; tx2'yi bekleten tek şey OKUMADAKİ açık `FOR UPDATE`tir.
    """
    kurulum = await _kur()
    kilit_alindi = asyncio.Event()
    kilidi_birak = asyncio.Event()
    task1: asyncio.Task | None = None
    task2: asyncio.Task | None = None
    try:
        task1 = asyncio.create_task(_kilidi_al_ve_tut(kurulum, kilit_alindi, kilidi_birak))
        await asyncio.wait_for(kilit_alindi.wait(), timeout=5)

        task2 = asyncio.create_task(_kalemleri_yaz(kurulum))
        await asyncio.sleep(0.3)
        assert not task2.done(), (
            "tx2, tx1 kilidi bırakmadan ilerleyebildi — `visible_invoice(for_update=True)` "
            "artık `invoices` satırını KİLİTLEMİYOR (TOCTOU penceresi yeniden açık)"
        )

        kilidi_birak.set()
        assert await asyncio.wait_for(task1, timeout=5) == "locked"
        assert await asyncio.wait_for(task2, timeout=5) == "written"
    finally:
        await _gorevleri_bosalt(task1, task2)
        await _temizle(kurulum)


async def _gonder(kurulum: _Kurulum, aktor_sirasi: int, baraj: asyncio.Barrier) -> str:
    """Bağımsız bir bağlantıda TAM `send` yolu: kilit → matris → K6 → damga.

    🔴 ISINMA + BARAJ — determinizmin tamamı buradadır (modül docstring'i T4b).
    `session.get` bağlantıyı havuzdan ÇEKER, transaction'ı başlatır ve gerçek bir
    sorgu koşturur; baraja ANCAK ONDAN SONRA varılır. Isınma barajdan sonra
    yapılsaydı (ya da hiç yapılmasaydı) izole koşuda bağlantı kurulum gecikmesi
    iki görevi sıraya sokar ve çakışma penceresi HİÇ AÇILMAZDI.
    """
    async with _SessionFactory() as session:
        actor = await session.get(User, kurulum.actor_ids[aktor_sirasi])
        await asyncio.wait_for(baraj.wait(), timeout=_TAVAN_SANIYE)
        try:
            await state_service.perform_transition(
                session, actor, kurulum.invoice_id, InvoiceAction.send
            )
        except ConflictError:
            await session.rollback()
            return "conflict"
        await session.commit()
        return "sent"


async def test_send_ESZAMANLI_iki_istekte_BIR_KEZ_gecer() -> None:
    """🔴 EŞİK = KİLİT (spec §8) — ASIL MUTASYON REGRESYONU.

    İki gerçek bağlantı aynı `draft` faturaya AYNI ANDA `send` atar. Doğru
    davranış: BİRİ `sent` yazar, ÖTEKİ 409 alır.

    Fatura satırındaki `with_for_update` kaldırılırsa ikisi de `draft` okur,
    ikisi de matrisi geçer ve fatura İKİ KEZ gönderilmiş olur — o hâlde
    `sonuclar.count("sent") == 1` iddiası KIRMIZI'ya döner. Bu KANIT İZOLE
    KOŞUDA alınmıştır (T4b): pencereyi açan şey `asyncio.Barrier`dır, dosyadaki
    önceki testlerin ısıttığı havuz DEĞİL.
    """
    kurulum = await _kur()
    baraj = asyncio.Barrier(2)
    gorevler: list[asyncio.Task] = []
    try:
        gorevler = [
            asyncio.create_task(_gonder(kurulum, 0, baraj)),
            asyncio.create_task(_gonder(kurulum, 1, baraj)),
        ]
        sonuclar = list(await asyncio.wait_for(asyncio.gather(*gorevler), timeout=_TAVAN_SANIYE))
        assert sonuclar.count("sent") == 1, (
            f"iki eşzamanlı `send` de geçti ({sonuclar}) — `perform_transition` faturayı "
            "DENETİMDEN ÖNCE kilitlemiyor; fatura iki kez gönderilmiş sayılır"
        )
        assert sonuclar.count("conflict") == 1, sonuclar

        async with _SessionFactory() as session:
            invoice = await session.get(Invoice, kurulum.invoice_id)
            assert invoice.status is InvoiceStatus.sent
    finally:
        await _guvenli_temizlik(kurulum, *gorevler)
