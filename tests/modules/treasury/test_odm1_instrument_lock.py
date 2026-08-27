"""🔴 ODM-1 D-YARIŞ — ödeme yazma yolu enstrüman satırını KİLİTLER.

## Kusuru ODM-1'in KENDİSİ doğurdu

ODM-1'den önce `financial_instrument_id` bağının hiçbir mali sonucu yoktu
(FIN-1 K4: *"etiket ≠ varlık"*), bu yüzden `_instrument_or_none` satırı
kilitsiz okuyordu ve bu DOĞRUYDU. ODM-1 bağa bir mali sonuç yükledi:

* **ödeme yaz** (`payments_service.create_payment`) — enstrümanı okur, D4
  kapısından `portfolio` diye geçer ve nakit bacağını `101`/`103`e yazar;
* **tahsil et** (`instruments.service.change_status`) — satırı `FOR UPDATE` ile
  kilitler, **Σ BAĞLI ÖDEMELERİ** okur (D3) ve fişi o toplamdan yazar.

İkisi eşzamanlı koşarsa tahsil fişi, henüz commit etmemiş yeni ödemeyi
KAÇIRIR. O ödeme `101`i borçlandırmıştır; onu boşaltacak İKİNCİ bir geçiş bir
daha DOĞAMAZ, çünkü `transitions.TERMINAL_STATUSES`ten **çıkış yoktur**. Sonuç:
defterde sonsuza dek "yolda" görünen bir para — D4'ün 422 ile kapattığı kalıcı
`101` kalıntısının eşzamanlılık hâli. 🔴 Bakiye SAKLANMADIĞI için hiçbir kolon
farkı bunu ele vermez; ancak `101`in NETİ ele verir ve o da yalnız bakan olursa.

## Neden `seeded_db` KULLANILMAZ

Kök `tests/conftest.py`'deki `db_session` her testi TEK bağlantı üzerinde
SAVEPOINT'e sarar ve dış transaction'ı asla gerçekten COMMIT ETMEZ — o session
üzerinde iki görev AYNI bağlantıyı paylaşır ve gerçek bir satır kilidi test
EDİLEMEZ. Bu dosya `test_hz1_payment_lock.py` desenini izler: `test_engine`
üzerinden bağımsız bağlantılar, gerçek commit, gerçek temizlik.

## 🔴 BEKÇİ GERÇEK SENARYOYU KOŞAR — "tutulan kilit" YETMEDİ, ÖLÇÜLDÜ

İlk yazım `test_hz1_payment_lock.py`nin TUTULAN KİLİT desenini kopyaladı: tx0
`SELECT … FOR UPDATE` ile çek satırını tutar, ödeme yazımının ilerleyemediği
ölçülürdü. 🔴 **O bekçi mutasyonla ÇÜRÜTÜLDÜ: `for_update` kaldırıldığında test
YEŞİL kaldı** (izole ve dosya-bütün koşuda, 2/2). Sebebi ölçüldü ve bir kanondur:

    `payments.financial_instrument_id` bir YABANCI ANAHTARDIR ve INSERT,
    başvurulan satırda ÖRTÜK bir `FOR KEY SHARE` kilidi alır. `FOR KEY SHARE`
    PostgreSQL'de `FOR UPDATE` ile ÇAKIŞIR — yani kilitsiz kod da bloke olurdu.

Bekçi bu yüzden kilidin kendisini değil, kilidin ÖNLEDİĞİ MALİ SONUCU ölçer ve
ürünün gerçek iki yolunu yarıştırır: tx_A çeki `collected` yapar (kilidi alır,
Σ bağlı ödemeleri okur, fişi yazar) ve HENÜZ COMMIT ETMEZ; tx_B aynı çeke yeni
bir ödeme yazmaya çalışır.

* **KİLİT VARSA:** tx_B `_instrument_or_none`ta bekler, tx_A commit edince
  satırı TAZE okur (`populate_existing`) ve `collected` görüp D4'ten **422**
  alır. `101` net SIFIR kapanır.
* **KİLİT YOKSA:** tx_B çeki commit edilmemiş hâliyle `portfolio` okur, D4'ten
  geçer ve INSERT'te (FK'nin `FOR KEY SHARE`i yüzünden) tx_A'yı bekler; tx_A
  commit edince ödeme YAZILIR. Artık `collected` bir çeke bağlı bir ödeme
  vardır: `101` borçlanmıştır ve onu boşaltacak ikinci bir geçiş bir daha
  DOĞAMAZ → **kalıcı `101` kalıntısı**, iddia KIRMIZI.

Sıra DETERMİNİSTİKTİR: tx_B ancak tx_A kilidini aldıktan SONRA başlar (olay
bayrağı), sabit `asyncio.sleep` YOKTUR.

## 🔴 POZİTİF KONTROL — 422'nin kaynağı YARIŞ, kurulum DEĞİL

Bekçi tek başına yetmez: aynı 422 bozuk bir kurulumdan da gelebilirdi (çek
zaten terminal, yön uyumsuz, eşleme eksik…) ve o hâlde test kilidi değil
kurulumu ölçerdi. İkinci bekçi BİREBİR AYNI kurulumu koşar, tek farkla: tx_A
**BAŞKA** bir çeki tahsil eder. tx_B'nin ödemesi o zaman YAZILMALIDIR. İki
bekçi bir arada, 422'nin yalnız ve yalnız aynı satır üzerindeki yarıştan
geldiğini kanıtlar.
"""

import asyncio
import contextlib
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import TreasuryValidationError
from app.core.security import hash_password
from app.modules.accounting.chart_seed_data import CHART_ACCOUNTS
from app.modules.accounting.models import (
    AccountingPeriod,
    ChartAccount,
    JournalEntry,
    JournalEntryCounter,
    JournalSourceType,
)
from app.modules.invoicing.models import (
    Invoice,
    InvoiceDirection,
    InvoiceDocumentType,
    InvoiceStatus,
)
from app.modules.posting.models import PostingRule
from app.modules.roles.models import Role
from app.modules.treasury import payments_service, posting
from app.modules.treasury.instruments import service as instruments_service
from app.modules.treasury.instruments.posting import INSTRUMENT_POSTING_RULES
from app.modules.treasury.models import (
    BankAccount,
    BankAccountType,
    FinancialInstrument,
    FinancialInstrumentDirection,
    FinancialInstrumentKind,
    FinancialInstrumentStatus,
    Payment,
    PaymentMethodKind,
)
from app.modules.treasury.schemas import PaymentCreate
from app.modules.users.models import User
from tests.conftest import test_engine
from tests.modules.treasury._mu3c import hesap_neti

_SessionFactory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

#: Rol anahtarı ve e-postalar TESTE ÖZELDİR: bu dosya GERÇEKTEN commit ettiği
#: için sızıntı ancak yaratılan satırların tam bilinmesiyle kapanır.
_ROL_ANAHTARI = "odm1_conc_admin"
_EPOSTALAR = ("odm1-kilit1@conc.co", "odm1-kilit2@conc.co")

#: 🔴 İKİ AİLE de kurulur ve kurulmak ZORUNDADIR: `101`e GİREN ödeme fişi
#: (`payment`) ile onu ÇIKARAN tahsil fişi (`financial_instrument`) AYNI veri
#: kümesinde koşar. Biri eksik olsaydı `post_document` eksik eşleme dalından
#: **422** verir, görev kilide HİÇ ULAŞMADAN biter ve bekçi kilidi değil
#: KURULUMU ölçerdi. Demetler ÜRÜNDEN okunur, testte elle yazılmaz.
_AILELER: tuple[tuple[JournalSourceType, tuple[tuple[str, str], ...]], ...] = (
    (JournalSourceType.payment, posting.PAYMENT_POSTING_RULES),
    (JournalSourceType.financial_instrument, INSTRUMENT_POSTING_RULES),
)

#: Kalıntının ele veren hesabı — ÜRÜNDEN okunmaz, iddianın KENDİSİDİR.
_KOD_ALINAN_CEK = "101"

_DONEM = (2026, 8)
_TARIH = date(2026, 8, 14)

#: Görev bekleyişlerinin tavanı — pencere AÇMAZ, yalnız bozuk bir kurulumun
#: testi sonsuza asmasını engeller.
_TAVAN_SANIYE = 15

#: "Bloke kalmalı" iddiasının ÜST SINIRI. Çakışma tutulan GERÇEK bir kilitle
#: garanti altındadır; bu sayı yalnız "bitmemeli"yi sonlu sürede karara bağlar.
#: Kilit yoklamasının aralığı. Pencere AÇMAZ (pencereyi KOŞUL açar); yalnız
#: yoklamanın CPU'yu döndürmesini engeller.
_YOKLAMA_ARALIGI = 0.02


class _Kurulum:
    def __init__(
        self,
        invoice_id: uuid.UUID,
        account_id: uuid.UUID,
        instrument_ids: list[uuid.UUID],
        actor_ids: list[uuid.UUID],
        role_id: uuid.UUID,
        chart_account_ids: list[uuid.UUID],
    ) -> None:
        self.invoice_id = invoice_id
        self.account_id = account_id
        self.instrument_ids = instrument_ids
        self.actor_ids = actor_ids
        self.role_id = role_id
        self.chart_account_ids = chart_account_ids


async def _kur() -> _Kurulum:
    """Fatura PROJESİZ, çekler PROJESİZ (`project_id` NULL) açılır.

    Böylece proje/şantiye/`user_project_access` satırı yaratılmak ZORUNDA
    kalmaz — gerçekten commit eden bir testte yaratılan her satır bir sızıntı
    riskidir. `_visible_project_ids` boş kümeyle de geçer: `project_id` NULL
    kayıt modül izniyle GÖRÜNÜR (`repository.scope_clause`in üçüncü hâli).
    """
    async with _SessionFactory() as session:
        role = Role(key=_ROL_ANAHTARI, name="ODM-1 Eşzamanlılık Rolü")
        session.add(role)
        await session.flush()
        aktorler = [
            User(
                email=eposta,
                password_hash=hash_password("parola1234"),
                full_name=f"Çek Kilit Aktörü {sira}",
                role_id=role.id,
            )
            for sira, eposta in enumerate(_EPOSTALAR, start=1)
        ]
        session.add_all(aktorler)
        await session.flush()

        tohum = {kart.code: kart for kart in CHART_ACCOUNTS}
        hesap_plani: dict[str, ChartAccount] = {}
        for _source_type, kurallar in _AILELER:
            for _rol, kod in kurallar:
                if kod in hesap_plani:
                    continue
                kart = tohum[kod]
                hesap_plani[kod] = ChartAccount(
                    code=kart.code,
                    name=kart.name,
                    account_type=kart.account_type,
                    is_contra=kart.is_contra,
                )
                session.add(hesap_plani[kod])
        await session.flush()
        session.add_all(
            [
                PostingRule(source_type=source_type, role_key=rol, account_id=hesap_plani[kod].id)
                for source_type, kurallar in _AILELER
                for rol, kod in kurallar
            ]
        )
        await session.flush()

        account = BankAccount(
            bank_name="Çek Eşzamanlılık Bank",
            account_type=BankAccountType.checking,
            iban="TR420001000000000000000009",
            opening_balance=Decimal("0.00"),
        )
        session.add(account)

        tutar = Decimal("1000.00")
        invoice = Invoice(
            direction=InvoiceDirection.outgoing,
            invoice_no="ODMCONC00001",
            document_type=InvoiceDocumentType.einvoice,
            status=InvoiceStatus.sent,
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

        # İKİ çek: biri kilitlenir, ÖTEKİ pozitif kontrolün konusudur.
        cekler = [
            FinancialInstrument(
                instrument_kind=FinancialInstrumentKind.cheque,
                direction=FinancialInstrumentDirection.received,
                serial_no=f"ODMCONC{sira:03d}",
                drawer_name="Güneşkent A.Ş.",
                issue_date=date(2026, 8, 1),
                due_date=date(2026, 9, 1),
                amount=Decimal("500.00"),
                status=FinancialInstrumentStatus.portfolio,
            )
            for sira in (1, 2)
        ]
        session.add_all(cekler)
        await session.flush()

        # 🔴 BİRİNCİ çekin BAĞLI bir ödemesi ZATEN vardır ve ÜRÜN yolundan
        #    yazılır: tahsil fişinin tutarı Σ BAĞLI ÖDEMELERDİR (D3) ve bağlı
        #    ödemesi olmayan bir çekin geçişi HİÇ FİŞ YAZMAZ — o hâlde `101`
        #    hiç açılmaz ve kalıntı iddiası ölçülecek bir şey bulamazdı.
        #    ORM ile yazılsaydı fişleme hiç koşmaz ve aynı boşluk doğardı.
        await payments_service.create_payment(
            session,
            aktorler[0],
            invoice.id,
            PaymentCreate(
                bank_account_id=account.id,
                method=PaymentMethodKind.cheque,
                amount=Decimal("300.00"),
                paid_on=_TARIH,
                financial_instrument_id=cekler[0].id,
            ),
        )
        await session.commit()
        return _Kurulum(
            invoice.id,
            account.id,
            [c.id for c in cekler],
            [a.id for a in aktorler],
            role.id,
            [h.id for h in hesap_plani.values()],
        )


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
        # 🔴 SIRA ÖNEMLİ: `journal_lines` başlıktan CASCADE gelir, ama
        # `posting_rules` ve `chart_of_accounts` FİŞ SİLİNMEDEN silinemez
        # (`journal_lines.account_id` RESTRICT'tir).
        for source_type, _kurallar in _AILELER:
            await session.execute(
                delete(JournalEntry).where(JournalEntry.source_type == source_type)
            )
        for source_type, _kurallar in _AILELER:
            await session.execute(delete(PostingRule).where(PostingRule.source_type == source_type))
        await session.execute(
            delete(ChartAccount).where(ChartAccount.id.in_(kurulum.chart_account_ids))
        )
        await session.execute(
            delete(JournalEntryCounter).where(JournalEntryCounter.year == _DONEM[0])
        )
        await session.execute(
            delete(AccountingPeriod)
            .where(AccountingPeriod.year == _DONEM[0])
            .where(AccountingPeriod.month == _DONEM[1])
        )
        await session.execute(
            delete(FinancialInstrument).where(FinancialInstrument.id.in_(kurulum.instrument_ids))
        )
        await session.execute(delete(BankAccount).where(BankAccount.id == kurulum.account_id))
        await session.execute(delete(User).where(User.id.in_(kurulum.actor_ids)))
        await session.execute(delete(Role).where(Role.id == kurulum.role_id))
        await session.commit()


async def _guvenli_temizlik(kurulum: _Kurulum, *gorevler: asyncio.Task | None) -> None:
    """Görevleri boşalt, sonra TAVANLI temizle.

    Temizliğin kendi hatası ASIL iddianın metnini EZMEMELİDİR: mutasyon
    koşusunda okunması gereken şey kilit iddiasıdır, temizliğin zaman aşımı değil.
    """
    await _gorevleri_bosalt(*gorevler)
    with contextlib.suppress(Exception):
        await asyncio.wait_for(_temizle(kurulum), timeout=_TAVAN_SANIYE)


async def _tahsil_et_ve_TUT(
    kurulum: _Kurulum,
    instrument_id: uuid.UUID,
    gecis_yazildi: asyncio.Event,
    birak: asyncio.Event,
) -> str:
    """tx_A — ÜRÜN yolu: `change_status(collected)`. Kilidi alır, COMMIT ETMEZ.

    `change_status` satırı DENETİMLERDEN ÖNCE `FOR UPDATE` ile kilitler, Σ bağlı
    ödemeleri okur (D3) ve tahsil fişini o toplamdan yazar. Bayrak tam bu
    noktada kaldırılır: tx_B ancak Σ OKUNDUKTAN sonra sahneye girer — yarışın
    kaçırılan tarafı budur.
    """
    async with _SessionFactory() as session:
        actor = await session.get(User, kurulum.actor_ids[0])
        await instruments_service.change_status(
            session, actor, instrument_id, FinancialInstrumentStatus.collected
        )
        gecis_yazildi.set()
        await birak.wait()
        await session.commit()
        return "collected"


async def _bagli_odeme(kurulum: _Kurulum, aktor_sirasi: int, instrument_id: uuid.UUID) -> str:
    """tx_B — TAM ürün yolu: fatura kilidi → Σ → hesap → eşik → çek.

    D4'ün **422**si `rejected` olarak döner; başka hiçbir hata YUTULMAZ.
    """
    async with _SessionFactory() as session:
        actor = await session.get(User, kurulum.actor_ids[aktor_sirasi])
        try:
            await payments_service.create_payment(
                session,
                actor,
                kurulum.invoice_id,
                PaymentCreate(
                    bank_account_id=kurulum.account_id,
                    method=PaymentMethodKind.cheque,
                    amount=Decimal("100.00"),
                    paid_on=_TARIH,
                    financial_instrument_id=instrument_id,
                ),
            )
        except TreasuryValidationError:
            await session.rollback()
            return "rejected"
        await session.commit()
        return "created"


async def _bloke_olana_kadar_BEKLE() -> None:
    """🔴 tx_B'nin GERÇEKTEN bir kilide takıldığını ÜÇÜNCÜ bir bağlantıdan ölçer.

    Bu bir `sleep` penceresi DEĞİLDİR, bir KOŞUL yoklamasıdır: tx_A ancak tx_B
    kilide takıldıktan sonra bırakılır. İlk yazımda bu yoklama yoktu ve tx_A,
    tx_B daha ilk sorgusunu koşmadan commit ediyordu — yarış HİÇ açılmıyor,
    ödeme her iki hâlde de `collected` bir çek okuyup 422 alıyordu, yani bekçi
    mutasyonla YEŞİL kalıyordu (ölçüldü). Pencereyi zamana değil DURUMA bağlamak
    kusuru iki yönde de zamanlamadan bağımsız kılar.

    `wait_event_type = 'Lock'` iki mutasyon hâlinde de görülür ve GÖRÜLMELİDİR:
    kilit varken tx_B `FOR UPDATE` okumasında, yokken FK'nin örtük
    `FOR KEY SHARE`i yüzünden INSERT'te bekler. Ayrımı yapan şey bu yoklama
    değil, tx_A bırakıldıktan SONRAKİ sonuçtur (422 mi, yazılmış ödeme mi).
    """
    async with _SessionFactory() as session:
        son = asyncio.get_running_loop().time() + _TAVAN_SANIYE
        while asyncio.get_running_loop().time() < son:
            bekleyen = (
                await session.execute(
                    text(
                        "SELECT count(*) FROM pg_stat_activity "
                        "WHERE datname = current_database() "
                        "AND wait_event_type = 'Lock' AND pid <> pg_backend_pid()"
                    )
                )
            ).scalar_one()
            await session.rollback()
            if bekleyen:
                return
            await asyncio.sleep(_YOKLAMA_ARALIGI)
        raise AssertionError(
            "tx_B hiçbir kilide takılmadı — yarış penceresi AÇILMADI ve bekçi hiçbir şey "
            "ölçmüyor (kurulum bozuk ya da ödeme yolu enstrümana hiç uğramıyor)"
        )


async def _odeme_sayisi(invoice_id: uuid.UUID) -> int:
    """Son sözü DB söyler: sayı TAZE bir bağlantıdan okunur."""
    async with _SessionFactory() as session:
        return (
            await session.execute(
                select(func.count()).select_from(Payment).where(Payment.invoice_id == invoice_id)
            )
        ).scalar_one()


async def _ara_hesap_neti(kod: str) -> Decimal:
    """🔴 `101`in NETİ — kusurun ele veren TEK büyüklüğü.

    Ödeme sayısı da fiş sayısı da yanıltır: her fiş TEK BAŞINA dengelidir ve
    mizan doğru görünür. Kalıntıyı yalnız ara hesabın neti gösterir.

    Sorgu `_mu3c.hesap_neti`den ÇAĞRILIR, kopyalanmaz: ikinci bir yazım bir gün
    `posted`/`reversed` kümesinde ayrışır ve iki dosya aynı deftere farklı
    sayılar okurdu. Yalnız BAĞLANTI bu dosyanın kendisidir — `seeded_db`nin
    SAVEPOINT'i buradan GÖRÜNMEZ.
    """
    async with _SessionFactory() as session:
        return await hesap_neti(session, kod)


async def test_TAHSIL_ile_ODEME_YAZIMI_yarisinda_101_KALINTISI_DOGMAZ() -> None:
    """🔴 ASIL MUTASYON REGRESYONU — D-YARIŞ kapatıldı.

    tx_A çeki tahsil eder (kilidi alır, Σ'yı okur, fişi yazar) ve commit
    ETMEDEN bekler; tx_B AYNI çeke yeni bir ödeme yazmaya çalışır.

    Doğru davranış: tx_B `_instrument_or_none`ta BEKLER, tx_A commit edince
    satırı TAZE okur ve `collected` görüp D4'ten **422** alır — ödeme HİÇ
    yazılmaz, `101` SIFIR kapanır.

    `visible_instrument(..., for_update=True)`daki bayrak KALDIRILIRSA tx_B çeki
    commit edilmemiş hâliyle `portfolio` okur, kapıdan GEÇER ve ödeme yazılır:
    `101` net 100,00₺ kalır ve onu boşaltacak ikinci bir geçiş bir daha
    DOĞAMAZ (terminalden çıkış yoktur) → aşağıdaki İKİ iddia da kırmızıya döner.
    """
    kurulum = await _kur()
    gecis_yazildi = asyncio.Event()
    birak = asyncio.Event()
    tx_a: asyncio.Task | None = None
    tx_b: asyncio.Task | None = None
    try:
        tx_a = asyncio.create_task(
            _tahsil_et_ve_TUT(kurulum, kurulum.instrument_ids[0], gecis_yazildi, birak)
        )
        await asyncio.wait_for(gecis_yazildi.wait(), timeout=_TAVAN_SANIYE)

        tx_b = asyncio.create_task(_bagli_odeme(kurulum, 1, kurulum.instrument_ids[0]))
        # 🔴 tx_A ancak tx_B GERÇEKTEN kilide takıldıktan sonra bırakılır.
        await _bloke_olana_kadar_BEKLE()
        birak.set()
        assert await asyncio.wait_for(tx_a, timeout=_TAVAN_SANIYE) == "collected"
        sonuc = await asyncio.wait_for(tx_b, timeout=_TAVAN_SANIYE)

        assert sonuc == "rejected", (
            "tahsil edilmekte olan çeke eşzamanlı yeni ödeme YAZILDI — "
            "`_instrument_or_none` enstrümanı `for_update` ile OKUMUYOR. Tahsil fişi bu "
            "ödemeyi Σ'ya katmadı ve terminalden çıkış olmadığı için `101` borcunu "
            "boşaltacak ikinci bir geçiş bir daha DOĞAMAZ."
        )
        assert await _odeme_sayisi(kurulum.invoice_id) == 1, "kurulumun ödemesi dışında satır var"
        assert await _ara_hesap_neti(_KOD_ALINAN_CEK) == Decimal("0.00"), (
            "🔴 KALICI `101` KALINTISI: ara hesap kapanmadı"
        )
    finally:
        birak.set()
        await _guvenli_temizlik(kurulum, tx_a, tx_b)


async def test_POZITIF_KONTROL_tahsil_BASKA_cekteyse_odeme_YAZILIR() -> None:
    """🔴 422'nin kaynağı YARIŞ, kurulum DEĞİL.

    Aynı 422 bozuk bir kurulumdan da gelebilirdi (yön uyumsuz çek, zaten
    terminal kayıt, eksik eşleme…) ve o hâlde üstteki bekçi kilidi değil
    kurulumu ölçerdi. Burada kurulum BİREBİR AYNIDIR; tek fark tx_A'nın BAŞKA
    bir çeki tahsil etmesidir — tx_B'nin ödemesi YAZILMALIDIR.
    """
    kurulum = await _kur()
    gecis_yazildi = asyncio.Event()
    birak = asyncio.Event()
    tx_a: asyncio.Task | None = None
    tx_b: asyncio.Task | None = None
    try:
        tx_a = asyncio.create_task(
            _tahsil_et_ve_TUT(kurulum, kurulum.instrument_ids[1], gecis_yazildi, birak)
        )
        await asyncio.wait_for(gecis_yazildi.wait(), timeout=_TAVAN_SANIYE)

        tx_b = asyncio.create_task(_bagli_odeme(kurulum, 1, kurulum.instrument_ids[0]))
        # Pozitif kontrolde çakışma YOKTUR: tx_B beklemeden ilerler, tx_A hemen
        # bırakılır. Yoklama burada koşulsaydı asla dönmezdi.
        birak.set()
        assert await asyncio.wait_for(tx_a, timeout=_TAVAN_SANIYE) == "collected"
        sonuc = await asyncio.wait_for(tx_b, timeout=_TAVAN_SANIYE)

        assert sonuc == "created", (
            f"BAŞKA bir çek tahsil edilirken ödeme reddedildi ({sonuc}) — üstteki 422 "
            "yarıştan değil KURULUMDAN geliyor olabilir; bekçi yanlış sebeple yeşil"
        )
        assert await _odeme_sayisi(kurulum.invoice_id) == 2
    finally:
        birak.set()
        await _guvenli_temizlik(kurulum, tx_a, tx_b)
