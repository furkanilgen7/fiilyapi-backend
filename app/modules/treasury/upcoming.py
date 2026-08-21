"""Yaklaşan Ödemeler (HZ-1 T5) — spec §4 uç 9, E9:109-125.

`GET /treasury/upcoming-payments`: önümüzdeki `days` gün içinde ÖDEYECEĞİMİZ
paranın satır satır dökümü. Kart beş şey basar — karşı taraf · evrak atfı ·
vade · kalan gün · tutar — ve bunların yalnız biri (kalan gün) TÜREVDİR.

## 🔴 K9 — üç kaynak çizili, bugün İKİSİ var

E9:113/117/121 üç satır gösterir ve üçü üç ayrı kaynaktır:

| Mockup satırı | Kaynak | Durum |
|---|---|---|
| `Akın İnşaat – Hakediş #47` | `subcontractor_progress_payments` | ✅ |
| `Bordro – Temmuz` | `payroll_periods` | ⛔ **YOK** |
| `Yılmaz Elektrik – Fatura` | `invoices` | ✅ |

**Bordro kaynağı UYDURULMAZ.** `payroll_periods` bir ödeme VADESİ taşımaz —
İK-3'te vade kolonu açılmadı; ay/yıl vardır ama "ne zaman ödeneceği" yoktur.
Bir vade uydurmak (ör. "ayın 15'i", "dönem sonu + 5 gün") kanunî/şirket
politikası hakkında sunucuda saklanmayan bir kural icat etmek olurdu ve o gün
geldiğinde ekran gerçek olmayan bir aciliyet gösterirdi. Bu yüzden bordro
kaynağı bugün **HİÇ SATIR ÜRETMEZ** ve `UpcomingSourceType`ta ÜYESİ BİLE
YOKTUR (schemas.py). `payroll_periods`a vade kolonu açıldığında burada bir
`select` ve orada bir enum üyesi eklenir — ROADMAP'e açık borç olarak yazılır.

## Vade nereden gelir

* **Fatura:** `invoices.due_date` — gerçek bir kolon. NULL ise vade
  BİLİNMİYOR demektir ve satır listeye GİRMEZ (bugün varsayılsaydı vadesiz her
  fatura en acil sırada görünürdü — NULL-EŞİK kanonunun fail-closed yüzü).
* **Hakediş:** `approved_at` (TR gününe çevrilmiş) + sözleşmenin
  `payment_term_days`ı. Bu bir TÜRETİMDİR, icat değil: ödeme vadesi (gün)
  sözleşmede SAKLIDIR ve onay damgası da vardır — bordroda ikisi de yoktur.
  `approved_at` NULL ise satır düşer (faturadaki NULL vade ile aynı kural).

## Pencere: `[bugün, bugün + days]`, VADESİ GEÇMİŞ DIŞARIDA

Karar DAR olanıdır ve bilinçlidir: kartın adı "Yaklaşan Ödemeler"dir, mockup
negatif bir "kalan gün" ÇİZMEZ ve geçmişi içeri almak pencerenin alt sınırını
SINIRSIZ yapardı (bir yıl önce vadesi dolmuş bir fatura da "yaklaşan" sayılır,
liste ödenmemiş her eski borçla dolardı). Gecikmiş borç takibi ayrı bir
yüzeydir ve hiçbir mockup'ta çizilmemiştir. Sonuç: `days_remaining` asla
negatif olmaz.

## 🔴 ÇİFT SAYIM KAPISI

Onaylı bir hakediş FATURALANDIYSA (`invoices.subcontractor_progress_payment_id`)
ödenecek olan FATURADIR: vadesi, tutarı ve ödeme kaydı onun üzerindedir. İkisi
de listelenseydi aynı borç iki satır üretir ve nakit ihtiyacı sessizce iki
katına çıkardı. Süzgeç `NOT EXISTS`tir — hakediş başına sorgu değil.

## 🔴 K10 — aciliyet SUNUCUDA üretilmez

E9 renk kodlaması kendi içinde tutarsızdır (2 gün→turuncu, 3 gün→**kırmızı**,
7 gün→yeşil). Sunucu `days_remaining` (sayı) + `source_type` döner; eşik/renk
kararı istemcinindir (SA'nın "EN HIZLI rozeti sunucuda üretilmez" kanonu).

## 🔴 Kapsam (IDOR) — K3'ün SINIRI burada biter

Banka HESABI şirket genelidir (K3) ama bu ucun KAYNAKLARI proje kapsamı taşır
ve her satır karşı taraf + evrak + tutar SIZDIRIR. Süzgeç düşseydi
`treasury=_V` olan bir proje müdürü, göremediği projenin taşeronunu ve borç
tutarını okurdu. Bu yüzden iki kaynak da KENDİ modülünün süzgecinden geçer:
`invoicing.repository.scope_clause` (proje NULL = şirket geneli, modül izniyle
görünür) ve hakediş için `project_id IN visible` (hakedişte NULL proje YOKTUR).
İkinci bir görünürlük tanımı yazılmaz — liste uçlarıyla ayrışırdı.

## N+1

Sorgu sayısı SATIR SAYISINDAN bağımsızdır: iki `select` (fatura · hakediş) +
hakediş tutarları için `amounts.bulk_calculations`ın iki toplu sorgusu. Tutarı
hakediş başına `calculation_for` ile çeken bir uygulama `test_N_ARTI_1_YAPMAZ`ı
geçemez.
"""

import uuid
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import Date, Integer, cast, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import AccessLevel, satisfies
from app.core.config import settings
from app.core.timezone import today
from app.modules.contracts.models import SubcontractorContract
from app.modules.invoicing import repository as invoicing_repository
from app.modules.invoicing.models import Invoice, InvoiceDirection, InvoiceStatus
from app.modules.payroll import payable
from app.modules.payroll.guards import PERMISSION_MODULE as PAYROLL_PERMISSION_MODULE
from app.modules.payroll.models import PayrollPeriod, PayrollPeriodStatus
from app.modules.projects.service import visible_projects
from app.modules.roles.repository import get_permission
from app.modules.subcontractor_progress_payments import amounts
from app.modules.subcontractor_progress_payments.models import (
    SubcontractorPaymentStatus,
    SubcontractorProgressPayment,
)
from app.modules.treasury import repository
from app.modules.treasury.schemas import (
    UpcomingPaymentItem,
    UpcomingPaymentsResponse,
    UpcomingSourceType,
)
from app.modules.users.models import User

__all__ = [
    "DEFAULT_DAYS",
    "MAX_DAYS",
    "MIN_DAYS",
    "build_upcoming_payments",
    "progress_payment_due_expression",
]

#: E9:110 `Yaklaşan Ödemeler (7 Gün)` — mockup'tan OKUNUR, seçilmez.
DEFAULT_DAYS = 7
#: Router'ın `Query(ge=…, le=…)` sınırları buradan gelir; tavan aşımı **422**
#: (kırpma DEĞİL — TB3 kanonu). 90 gün bir çeyrektir: daha uzun bir pencere
#: "yaklaşan" kelimesini anlamsızlaştırır ve kartı bir borç listesine çevirirdi.
MIN_DAYS = 1
MAX_DAYS = 90


def progress_payment_due_expression():
    """`approved_at` (TR gününe çevrilmiş) + `payment_term_days` → `date`.

    Çevrim SQL'de yapılır çünkü pencere süzgeci de SQL'dedir: Python'da
    hesaplansaydı pencereye girmeyecek TÜM onaylı hakedişler önce çekilirdi.
    Saat dilimi adı `settings.display_timezone`dan gelir — `app/core/timezone`
    ile AYNI kaynak, gömülü string YOKTUR.

    🔴 `timezone(...)` ŞART ve DIŞA AÇIK: `approved_at` `timestamptz`tir;
    doğrudan `date`e çevrilirse PostgreSQL OTURUMUN `TimeZone` ayarını kullanır.
    Yerel geliştirme makinesinde bu ayar TR olduğu için kusur GÖRÜNMEZ, CI ve
    Railway'de (UTC) ise TR gecesi 00:00-03:00 arasında onaylanan hakedişin
    vadesi bir gün geri kayar ve satır listeden düşer. Yani bu kusur KARA KUTU
    testiyle yakalanamaz (ölçüldü: mutasyon yerelde hayatta kalıyor) — bu yüzden
    ifade dışarı açıktır ve `test_vade_ifadesi_SAAT_DILIMI_cevirir` derlenmiş
    SQL'i denetler.
    """
    tr_gunu = cast(
        func.timezone(settings.display_timezone, SubcontractorProgressPayment.approved_at), Date
    )
    return tr_gunu + cast(SubcontractorContract.payment_term_days, Integer)


async def _invoice_rows(
    session: AsyncSession, project_ids: list[uuid.UUID], ilk: date, son: date
) -> list[UpcomingPaymentItem]:
    """Gelen · onaylı · vadesi pencerede · TAM ÖDENMEMİŞ faturalar.

    "Tam ödenmemiş" ölçütü `Σ payments < total`dır ve toplam T2/T4'ün TEK
    kaynağından (`repository.paid_sum`) gelir; ikinci bir formül yazılsaydı bu
    uç ile fatura detayının "kalan"ı ayrışır ve kart, ödenmiş bir borcu
    ödenecek gösterirdi.

    `outerjoin` ŞART: hiç ödemesi olmayan fatura (asıl kitle) INNER join'de
    listeden tamamen DÜŞERDİ.

    ⚠️ `due_date.is_not(None)` KANITLANMIŞ BİÇİMDE GEREKSİZDİR (mutasyon
    denetiminde hayatta kaldı): SQL'de `NULL >= tarih` sonucu NULL'dır ve
    `WHERE` onu zaten eler. Satır BELGELEME amacıyla durur — "vadesiz fatura
    listeye girmez" kuralı okuyucuya üç değerli mantığı çıkarttırmadan
    görünsün diye. Silinirse davranış DEĞİŞMEZ; aynı şey
    `_progress_payment_rows`taki `approved_at.is_not(None)` için de geçerlidir.
    """
    odenen = repository.paid_totals_by_invoice()
    kalan = Invoice.total - func.coalesce(odenen.c.paid, 0)
    stmt = (
        select(Invoice.id, Invoice.invoice_no, Invoice.party_name, Invoice.due_date, kalan)
        .outerjoin(odenen, odenen.c.invoice_id == Invoice.id)
        .where(
            Invoice.direction == InvoiceDirection.incoming,
            Invoice.status == InvoiceStatus.approved,
            Invoice.due_date.is_not(None),
            Invoice.due_date >= ilk,
            Invoice.due_date <= son,
            kalan > 0,
            invoicing_repository.scope_clause(project_ids),
        )
    )
    return [
        UpcomingPaymentItem(
            source_type=UpcomingSourceType.invoice,
            source_id=invoice_id,
            counterparty=party_name,
            document_no=invoice_no,
            due_date=due_date,
            days_remaining=(due_date - ilk).days,
            amount=Decimal(kalan_tutar),
        )
        for invoice_id, invoice_no, party_name, due_date, kalan_tutar in (
            await session.execute(stmt)
        ).all()
    ]


async def _progress_payment_rows(
    session: AsyncSession, project_ids: list[uuid.UUID], ilk: date, son: date
) -> list[UpcomingPaymentItem]:
    """Onaylı · henüz FATURALANMAMIŞ · vadesi pencerede taşeron hakedişleri.

    Tutar **NET**tir (brüt + KDV − avans − teminat) ve
    `amounts.bulk_calculations`tan gelir: brüt basılsaydı kesintili her hakediş
    fazla, KDV'li her hakediş eksik görünürdü. Hesabın kendisi burada İKİNCİ
    KEZ YAZILMAZ — E15 tfoot'unun tek kaynağı o modüldür.
    """
    if not project_ids:
        return []
    vade = progress_payment_due_expression()
    faturalanmis = exists().where(
        Invoice.subcontractor_progress_payment_id == SubcontractorProgressPayment.id
    )
    stmt = (
        select(SubcontractorProgressPayment, SubcontractorContract.subcontractor_name, vade)
        .join(
            SubcontractorContract,
            SubcontractorContract.id == SubcontractorProgressPayment.contract_id,
        )
        .where(
            SubcontractorProgressPayment.status == SubcontractorPaymentStatus.approved,
            SubcontractorProgressPayment.approved_at.is_not(None),
            SubcontractorProgressPayment.project_id.in_(project_ids),
            vade >= ilk,
            vade <= son,
            ~faturalanmis,
        )
    )
    rows = (await session.execute(stmt)).all()
    bloklar = await amounts.bulk_calculations(session, [payment for payment, _, _ in rows])
    return [
        UpcomingPaymentItem(
            source_type=UpcomingSourceType.subcontractor_progress_payment,
            source_id=payment.id,
            counterparty=taseron_adi,
            document_no=str(payment.sequence_no),
            due_date=vade_gunu,
            days_remaining=(vade_gunu - ilk).days,
            amount=bloklar[payment.id].net,
        )
        for payment, taseron_adi, vade_gunu in rows
    ]


async def _payroll_visible(session: AsyncSession, actor: User) -> bool:
    """Aktörün `payroll` modülünde en az `view` seviyesi var mı — TEK sorgu.

    🔴 Bu ucun kapsam süzgeci burada İKİYE AYRILIR ve sebebi ölçülmüştür:
    `PayrollPeriod`da `project_id` KOLONU YOKTUR. Dönem şirket genelindedir,
    yani fatura/hakediş satırlarının proje süzgeci bordroya UYGULANAMAZ ve
    bordronun görünürlük tanımı saf MODÜL iznidir.

    Süzgeç yazılmasaydı matris tam burada ayrışırdı:

        `"treasury": [_A, _F, _N, _N, _N, _F, _V, _N]`
        `"payroll":  [_A, _F, _N, _N, _F, _F, _N, _N]`

    `project_manager` bu ucu OKUR (`treasury=_V`) ama bordroya HİÇ erişimi
    yoktur (`payroll=_N`) — süzgeç düşerse şirketin AYLIK TOPLAM PERSONEL
    MALİYETİNİ okurdu.

    İkinci bir görünürlük tanımı YAZILMAZ: seviye `roles/repository`den okunur
    ve `core/access.satisfies` ile karşılaştırılır — `site_diary`, `sales` ve
    `contracts` servislerindeki emsalin aynısı. Kapı YALNIZ bordroyu susturur;
    ucun tamamına uygulansaydı (403 ya da boş liste) `treasury=_V` olan bir rol
    çalışan iki kaynağı da kaybederdi.
    """
    permission = await get_permission(session, actor.role_id, PAYROLL_PERMISSION_MODULE)
    level = permission.access_level if permission is not None else AccessLevel.none
    return satisfies(level, AccessLevel.view)


async def _payroll_rows(
    session: AsyncSession, actor: User, ilk: date, son: date
) -> list[UpcomingPaymentItem]:
    """ONAYLI · vadesi pencerede · ödenebilir toplamı 0'dan büyük bordro dönemleri.

    Üç süzgecin üçü de mevcut iki kaynağın kuralının kardeşidir, bordro için
    icat edilmiş DEĞİLDİR:

    * **`approved` ŞART.** `payroll/router.py` → `service.update_period` vadeyi
      `draft`/`pending_approval`da serbestçe değiştirir ve `approved`/`paid`de
      **409** verir; yani `payment_due_date` ancak onaydan sonra bir
      TAAHHÜTTÜR. Onay öncesi tutar da taahhüt değildir: satırlar `uncomputed`
      olabilir ve `compute` netleri baştan yazabilir. `paid` dönem ise DIŞARIDA
      kalır çünkü borcu kapanmıştır (`paid` hakedişin kuralı).
    * **NULL vade DÜŞER** (fail-closed, NULL-EŞİK kanonu). Bugün varsayılsaydı
      vadesi hiç girilmemiş her dönem listenin en acil sırasında görünürdü —
      vadesiz faturanın kuralıyla birebir aynı. Vade UYDURULMAZ.
    * **Ödenebilir toplam > 0.** Faturanın `kalan > 0` süzgecinin kardeşi:
      "₺0 · 3 gün kaldı" satırı ödenecek bir para varmış gibi görünür,
      tıklanır, hiçbir şey bulunmaz.

    Tutar bir KOLON DEĞİL TÜREVDİR ve formülü burada İKİNCİ KEZ YAZILMAZ:
    `payroll.payable` alt sorgusu hangi satırın sayıldığını (durum kümesi +
    `net_amount IS NOT NULL`) bordro modülünde tutar. INNER JOIN'dir — ödenebilir
    satırı hiç olmayan dönem alt sorguda grup açmaz ve kendiliğinden düşer.

    Sorgu dönem sayısından BAĞIMSIZ olarak TEKTİR (`GROUP BY` + JOIN);
    `summary.build_period_summary`i dönem başına çağırmak N+1 olurdu.

    `document_no` `"YYYY-MM"`dir: sunucu E9:117'nin "Temmuz"unu ÜRETMEZ, çeviri
    kararı istemciye aittir. `counterparty` `None`dur — mockup bordro satırında
    bir karşı taraf adı ÇİZMEZ.
    """
    if not await _payroll_visible(session, actor):
        return []
    odenebilir = payable.payable_net_totals_by_period()
    stmt = (
        select(
            PayrollPeriod.id,
            PayrollPeriod.year,
            PayrollPeriod.month,
            PayrollPeriod.payment_due_date,
            odenebilir.c.payable_net,
        )
        .join(odenebilir, odenebilir.c.payroll_period_id == PayrollPeriod.id)
        .where(
            PayrollPeriod.status == PayrollPeriodStatus.approved,
            PayrollPeriod.payment_due_date.is_not(None),
            PayrollPeriod.payment_due_date >= ilk,
            PayrollPeriod.payment_due_date <= son,
            odenebilir.c.payable_net > 0,
        )
    )
    return [
        UpcomingPaymentItem(
            source_type=UpcomingSourceType.payroll,
            source_id=donem_id,
            counterparty=None,
            document_no=f"{yil:04d}-{ay:02d}",
            due_date=vade,
            days_remaining=(vade - ilk).days,
            amount=Decimal(tutar),
        )
        for donem_id, yil, ay, vade, tutar in (await session.execute(stmt)).all()
    ]


async def build_upcoming_payments(
    session: AsyncSession, actor: User, *, days: int
) -> UpcomingPaymentsResponse:
    """ÜÇ kaynağı birleştirir, VADEYE göre artan sıralar.

    Sıralama Python'dadır ve olmalıdır: ayrı `select`lerin birleşimi tek bir
    `ORDER BY` ile sıralanamaz (UNION yazmak, üç farklı sütun kümesini yapay
    olarak aynı şekle sokmak demekti). Küme pencere ile zaten küçüktür.

    İkincil ölçüt `document_no`dur: aynı güne düşen iki satır her istekte aynı
    sırada gelmelidir, yoksa ekran sebepsiz oynardı.
    """
    bugun = today()
    son = bugun + timedelta(days=days)
    project_ids = [p.id for p in await visible_projects(session, actor)]

    satirlar = await _invoice_rows(session, project_ids, bugun, son)
    satirlar += await _progress_payment_rows(session, project_ids, bugun, son)
    satirlar += await _payroll_rows(session, actor, bugun, son)
    satirlar.sort(key=lambda satir: (satir.due_date, satir.document_no))
    return UpcomingPaymentsResponse(items=satirlar, days=days, as_of=bugun)
