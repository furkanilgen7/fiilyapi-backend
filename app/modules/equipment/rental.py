"""Kira hakedişinin PARA çekirdeği — saf, yan etkisiz fonksiyonlar (MK-2 T2).

Spec: `docs/superpowers/specs/2026-08-14-mk2-kira-hakedisi-design.md`
(K1 · K3 · K4 · K6 · K10). `cost.py` ve `consumption.py` kardeşidir: DB'ye
DOKUNMAZ, kapsam/durum kararı VERMEZ (onu T3'ün `service.py`si verir), yalnız
verilen satırlardan parayı ve toplamları üretir.

## Zincir

    satır (saat + bedel) → BİZİM HESABIMIZ → tür bazlı toplamlar
    firmanın faturası (matrah) → KDV → ÖDENECEK TOPLAM

İki taraf AYRI yürür ve BİRBİRİNE KARIŞMAZ: sol taraf bizim çalışma
kaydımızdan, sağ taraf firmanın kestiği faturadan gelir. Karıştırılsalardı
doğrulamanın kendisi anlamsızlaşırdı — M5'in tüm amacı bu iki bağımsız sayıyı
YAN YANA koymaktır.

## Bu dosyanın taşıdığı bağlanmış kararlar

* **🔴 K4 — saatlik bedel `cost.py`den İTHAL EDİLİR**, burada YENİDEN
  TANIMLANMAZ. `rate_period` dönüşümü ve `DAILY_HOURS = 10` orada, TEK yerde
  yaşar; kopyalansaydı M3'ün satır maliyeti ile M5'in hakedişi aynı makine için
  farklı bir sayı gösterebilirdi. Satırın `rate_amount`ı ekipmanınkini EZER
  (M5:93 düzenlenebilir input); ikisi de yoksa sonuç **`None`** (MK-1 K16
  fail-closed), **0 DEĞİL** — 0 "bedava çalıştı" derdi.
* **🔴 K1 — KDV oranı KOLONDAN gelir** (`vat_rate`), koda gömülü bir sabitten
  DEĞİL (İK-3 `payroll_rates` dersi): oran mevzuatla değişir ve geçmiş fatura
  KENDİ oranıyla okunabilir kalmalıdır. `invoice_amount` KDV **HARİÇ**
  matrahtır; NULL ise (taslak) KDV de ödenecek toplam da **`None`**tur.
  Yuvarlama TEK NOKTADADIR: KDV yuvarlanır, **ödenecek toplam onların
  TOPLAMIDIR** ve ikinci kez yuvarlanmaz — yoksa `payable − vat` matrahtan
  kuruş kayardı (İK-3'ün "net FARKTIR" dersi).
* **🔴 K3 — ödenecek toplama katılım `line_kind`ten okunur ve ÇİFT ÖDEME
  YAPISAL OLARAK İMKÂNSIZDIR:** `our_total` YALNIZ `rented` satırlardan türer;
  `owned` ve `breakdown` KENDİ raporlama alanlarına yazılır ve hiçbir ödenecek
  toplamın kaynağı DEĞİLDİR (İK-3 K2 `excluded` deseni). Tek bir "hariç"
  bayrağıyla birleştirilselerdi kendi makinemizin amortismanı ile firmanın
  arıza indirimi aynı kovaya düşerdi.
* **MK-1 K15 — toplamlar SATIRLARDAN türer**, mockup tfoot'undan değil.
* **🔴 Hesaplanamayan satır UYDURMA 0 ile toplama GİRMEZ ama SESSİZ de
  KALMAZ:** atlanır ve `*_unknown_count` ile ADETÇE bildirilir (MK-1
  `summarize` kanonu). Toplamın kendisi `None` yapılmadı: tek bedelsiz satır
  yüzünden bütün hakedişi gizlemek kullanıcıyı ekranın tamamından ederdi.
* **K6 — fark bir DURUM değil TÜREVDİR** ve rozet SUNUCUDAN gelir
  (F-P10 kanonu). `invoiced_hours` yoksa rozet `unknown`dır — `match` basmak
  girilmemiş bir faturayı "doğrulandı" diye damgalamak olurdu. **Fark ödemeyi
  BLOKE ETMEZ**; yalnız görünür kılınır.
* **K10 — `Decimal`, asla `float`;** para tam sayıya `ROUND_HALF_UP`
  (`cost.quantize_money` üzerinden, ikinci bir yuvarlama kuralı doğmasın diye).
"""

import enum
import uuid
from dataclasses import dataclass
from decimal import Decimal

from app.modules.equipment.cost import compute_cost, quantize_money
from app.modules.equipment.models import EquipmentRatePeriod, RentalLineKind

#: KDV oranı YÜZDEDİR (`20.00` = %20), katsayı değil — kolonun kendi ölçeği.
PERCENT_DIVISOR = Decimal("100")

ZERO = Decimal("0")


class VarianceStatus(str, enum.Enum):
    """K6 rozeti — M5:110/122'nin `✓ Eşleşiyor` / `⚠ 6 saat fark` damgası.

    DB'de KOLON DEĞİLDİR: her okumada farktan türer. Saklansaydı satır
    düzenlendiğinde rozet eski farkta donup kalırdı.

    `over` firmanın BİZDEN ÇOK saat faturaladığı (bizim aleyhimize), `under`
    ise AZ faturaladığı durumdur. Tek bir "fark var" değeri bu iki yönü
    birleştirir ve ekranda hangi tarafın lehine olduğunu kaybederdi.
    """

    match = "match"
    over = "over"
    under = "under"
    unknown = "unknown"


@dataclass(frozen=True)
class RentalLineInput:
    """Bir hakediş satırının hesap için gereken TÜM girdisi — DONMUŞTUR.

    Bilerek DB nesnesi değil, düz bir taşıyıcıdır: çekirdek `AsyncSession`
    tanımaz ve girdinin NEREDEN geldiğini de bilmez.

    🔴 Çağıran taraf (`rental_service.invoice_detail`) tutarı etkileyen HER
    girdiyi satırın KENDİ kolonundan doldurur: `equipment_rate_amount` artık
    `None` geçilir (MK-2 T5) ve `monthly_capacity_hours` satırın
    `capacity_hours` snapshot'ından gelir (MK-3 K1). `equipment_rate_amount`
    alanı yalnız K4'ün yedek kuralını ifade edebilmek için durur.
    """

    line_id: uuid.UUID
    equipment_id: uuid.UUID
    site_id: uuid.UUID | None
    line_kind: RentalLineKind
    worked_hours: Decimal
    breakdown_hours: Decimal
    line_rate_amount: Decimal | None
    equipment_rate_amount: Decimal | None
    invoiced_hours: Decimal | None = None
    monthly_capacity_hours: int | None = None


@dataclass(frozen=True)
class RentalLineResult:
    """Bir satırın TÜREV alanları — hiçbiri kolon değildir (K4/K6)."""

    line_id: uuid.UUID
    equipment_id: uuid.UUID
    site_id: uuid.UUID | None
    line_kind: RentalLineKind
    worked_hours: Decimal
    breakdown_hours: Decimal
    #: Satırda dolu değilse ekipmandan düşülen bedel; ikisi de yoksa `None`.
    effective_rate_amount: Decimal | None
    #: 🔴 K4 — `worked_hours × saatlik bedel`. Fail-closed `None`.
    our_amount: Decimal | None
    #: Arıza saatinin PARA karşılığı (M5'in üstü çizili tutarı). Ödenecek hiçbir
    #: toplamın kaynağı DEĞİLDİR; yalnız hariç tutulanı görünür kılar.
    breakdown_amount: Decimal | None
    hours_variance: Decimal | None
    variance_status: VarianceStatus


@dataclass(frozen=True)
class SiteDistributionEntry:
    """Proje bazlı maliyet dağılımının bir kovası (M5:177-193).

    `site_id` `None` ise kova "Atanmamış"tır: uydurma bir proje adı BASILMAZ
    (ad zaten burada değil, T3'te çözülür — çekirdek isim bilmez).
    """

    site_id: uuid.UUID | None
    hours: Decimal
    amount: Decimal
    #: Kovadaki bedeli bilinmeyen satır adedi — para eksik toplandıysa sessiz
    #: kalmaz.
    unknown_count: int
    #: Kovaya katkı veren ekipmanlar, ilk görülme sırasında (M5 kovanın altına
    #: "Tower Crane TC-48 · 186 saat" yazıyor; adı T3 çözer).
    equipment_ids: tuple[uuid.UUID, ...]


@dataclass(frozen=True)
class RentalInvoiceResult:
    """M5'in TÜM türev yüzeyi — spec §4 "Yanıt toplamları".

    Üç toplam ÜÇ AYRI alandır ve yalnız `our_total` ödeme tarafındadır; tek
    alana indirgenselerdi K3'ün çift ödeme güvencesi hesapta kaybolurdu.
    """

    lines: tuple[RentalLineResult, ...]
    #: 🔴 K3 — YALNIZ `rented` satırlardan.
    our_total: Decimal
    our_total_unknown_count: int
    #: `owned` satırların maliyeti: görünür, ödenmez.
    owned_total: Decimal
    owned_total_unknown_count: int
    #: `breakdown` satırların hariç tutulan tutarı: görünür, ödenmez.
    excluded_breakdown_amount: Decimal
    excluded_breakdown_unknown_count: int
    #: Firmanın kestiği matrah (KDV HARİÇ) — girdinin aynısı, ekranın sağ tarafı.
    invoice_amount: Decimal | None
    vat_rate: Decimal
    vat_amount: Decimal | None
    payable_total: Decimal | None
    site_distribution: tuple[SiteDistributionEntry, ...]


def effective_rate_amount(
    *, line_rate_amount: Decimal | None, equipment_rate_amount: Decimal | None
) -> Decimal | None:
    """K4 — satırın bedeli ekipmanınkini EZER; ikisi de yoksa `None`.

    `is None` ile bakılır, doğruluk değeriyle DEĞİL: `0` bilinen bir bedeldir
    (bedelsiz tahsis) ve ekipman bedeline düşmek onu sessizce ezerdi.
    """
    if line_rate_amount is not None:
        return line_rate_amount
    return equipment_rate_amount


def compute_our_amount(
    *,
    worked_hours: Decimal,
    line_rate_amount: Decimal | None,
    equipment_rate_amount: Decimal | None,
    rate_period: EquipmentRatePeriod,
    monthly_capacity_hours: int | None = None,
) -> Decimal | None:
    """🔴 K4 — `worked_hours × saatlik bedel`; formül `cost.py`den GELİR.

    Dönem FATURANINDIR (M5:74): aynı fatura içindeki satırlar tek bir kira
    döneminden okunur, yoksa aynı tablodaki iki satır farklı gün tanımıyla
    çarpılabilirdi.
    """
    return compute_cost(
        hours=worked_hours,
        rate_amount=effective_rate_amount(
            line_rate_amount=line_rate_amount, equipment_rate_amount=equipment_rate_amount
        ),
        rate_period=rate_period,
        monthly_capacity_hours=monthly_capacity_hours,
    )


def compute_hours_variance(
    *, invoiced_hours: Decimal | None, worked_hours: Decimal | None
) -> Decimal | None:
    """K6 — `invoiced_hours − worked_hours`; biri yoksa `None`.

    Pozitif = firma bizden ÇOK saat faturaladı.
    """
    if invoiced_hours is None or worked_hours is None:
        return None
    return invoiced_hours - worked_hours


def variance_status(variance: Decimal | None) -> VarianceStatus:
    """K6 rozeti — fark `None` ise `unknown`.

    Rozet `None` DEĞİL bir enum döner (`consumption.py`nin `None` rozetinden
    bilerek farklı): M5 her satırın Fark/Onay sütununa bir damga basar ve
    "fatura saati henüz girilmedi" ekranda GÖRÜNMESİ gereken bir durumdur.
    """
    if variance is None:
        return VarianceStatus.unknown
    if variance == ZERO:
        return VarianceStatus.match
    return VarianceStatus.over if variance > ZERO else VarianceStatus.under


def compute_vat_amount(*, invoice_amount: Decimal | None, vat_rate: Decimal) -> Decimal | None:
    """🔴 K1 — `invoice_amount × vat_rate / 100`; oran KOLONDAN gelir.

    Matrah yoksa (taslak fatura) sonuç **`None`**tur: 0 basmak "vergisiz
    fatura" demek olurdu.
    """
    if invoice_amount is None:
        return None
    return quantize_money(invoice_amount * vat_rate / PERCENT_DIVISOR)


def compute_payable_total(
    *, invoice_amount: Decimal | None, vat_amount: Decimal | None
) -> Decimal | None:
    """K1 — `invoice_amount + vat_amount`, İKİNCİ bir yuvarlama YOK.

    Toplam bağımsız yuvarlansaydı `payable − vat` matrahtan kuruş kayar ve
    ekrandaki üç satır kendi içinde tutmazdı (İK-3 "net FARKTIR" dersi).
    """
    if invoice_amount is None or vat_amount is None:
        return None
    return invoice_amount + vat_amount


def compute_line(line: RentalLineInput, *, rate_period: EquipmentRatePeriod) -> RentalLineResult:
    """Bir satırın tüm türevleri — saf: aynı girdiye her zaman aynı çıktı."""
    saatlik_kaynak = {
        "line_rate_amount": line.line_rate_amount,
        "equipment_rate_amount": line.equipment_rate_amount,
        "rate_period": rate_period,
        "monthly_capacity_hours": line.monthly_capacity_hours,
    }
    fark = compute_hours_variance(
        invoiced_hours=line.invoiced_hours, worked_hours=line.worked_hours
    )
    return RentalLineResult(
        line_id=line.line_id,
        equipment_id=line.equipment_id,
        site_id=line.site_id,
        line_kind=line.line_kind,
        worked_hours=line.worked_hours,
        breakdown_hours=line.breakdown_hours,
        effective_rate_amount=effective_rate_amount(
            line_rate_amount=line.line_rate_amount,
            equipment_rate_amount=line.equipment_rate_amount,
        ),
        our_amount=compute_our_amount(worked_hours=line.worked_hours, **saatlik_kaynak),
        # 🔴 Arıza tutarı ARIZA saatinden türer, çalışma saatinden DEĞİL: M5'in
        # arıza satırında çalışma sütunu "—", arıza sütunu 38'dir ve üstü çizili
        # tutar o 38 saatin karşılığıdır. `worked_hours`tan türetilseydi hariç
        # tutulan tutar sessizce 0 görünür, "neyi ödemediğimiz" kaybolurdu.
        breakdown_amount=compute_our_amount(worked_hours=line.breakdown_hours, **saatlik_kaynak),
        hours_variance=fark,
        variance_status=variance_status(fark),
    )


def _line_contribution(line: RentalLineResult) -> Decimal | None:
    """Satırın KENDİ türüne ait toplama yazacağı tutar.

    🔴 `rented` ve `owned` çalışma saatinin, `breakdown` arıza saatinin
    karşılığını taşır. Bu eşleme TEK yerdedir; iki kez yazılsaydı toplam ile
    dağılım birbirinden ayrışabilirdi.
    """
    if line.line_kind is RentalLineKind.breakdown:
        return line.breakdown_amount
    return line.our_amount


@dataclass
class _SiteBucket:
    """Dağılım kovasının BİRİKTİRİCİSİ — yalnız bu modülün içinde yaşar.

    Dışarı verilen `SiteDistributionEntry` DONMUŞTUR; birikimin kendisi
    yerel ve kısa ömürlüdür (fonksiyondan hiç çıkmaz).
    """

    first_seen: int
    hours: Decimal = ZERO
    amount: Decimal = ZERO
    unknown_count: int = 0
    equipment_ids: tuple[uuid.UUID, ...] = ()

    def add(self, line: RentalLineResult) -> None:
        # Saat BİLİNEN bir olgudur: bedel bilinmese de kaybolmaz.
        self.hours += line.worked_hours
        if line.our_amount is None:
            self.unknown_count += 1
        else:
            self.amount += line.our_amount
        if line.equipment_id not in self.equipment_ids:
            self.equipment_ids = (*self.equipment_ids, line.equipment_id)

    def to_entry(self, site_id: uuid.UUID | None) -> SiteDistributionEntry:
        return SiteDistributionEntry(
            site_id=site_id,
            hours=self.hours,
            amount=self.amount,
            unknown_count=self.unknown_count,
            equipment_ids=self.equipment_ids,
        )


def _site_distribution(
    lines: tuple[RentalLineResult, ...],
) -> tuple[SiteDistributionEntry, ...]:
    """M5:177-193 — proje bazlı dağılım, satırların KENDİ `site_id`sinden.

    🔴 YALNIZ `rented` satırlar girer: M5'in dağılım kartı da yalnız ödenecek
    toplama giren iki satırı basar (`owned` araç ve arıza satırı kartta YOKTUR)
    ve dağılımın anlamı "her projenin ilgili hakediş dönemine yansıyacak
    KİRA maliyeti"dir (M5:190-192). `owned` maliyeti ayrıca `owned_total`da
    zaten görünür.

    Sıra: adlı projeler tutara göre AZALAN, "Atanmamış" (NULL) EN SONDA. Eşit
    tutarda ilk görülme sırası korunur — böylece aynı fatura her okumada aynı
    sırayı verir (ekranın oynamaması bir doğruluk meselesidir).
    """
    kovalar: dict[uuid.UUID | None, _SiteBucket] = {}
    for sira, line in enumerate(lines):
        if line.line_kind is not RentalLineKind.rented:
            continue
        kova = kovalar.setdefault(line.site_id, _SiteBucket(first_seen=sira))
        kova.add(line)

    sirali = sorted(
        kovalar.items(), key=lambda oge: (oge[0] is None, -oge[1].amount, oge[1].first_seen)
    )
    return tuple(kova.to_entry(site_id) for site_id, kova in sirali)


def compute_invoice(
    *,
    invoice_amount: Decimal | None,
    vat_rate: Decimal,
    rate_period: EquipmentRatePeriod,
    lines: tuple[RentalLineInput, ...],
) -> RentalInvoiceResult:
    """M5'in tamamı: satırlar + üç tür toplamı + KDV zinciri + proje dağılımı.

    🔴 **MK-1 K15** — toplamlar SATIRLARDAN türer. 🔴 **K3** — `our_total` yalnız
    `rented`tan beslenir; `owned`/`breakdown` KENDİ alanlarına yazılır ve
    ödenecek hiçbir toplama sızmaz (çift ödeme yapısal olarak imkânsız).
    """
    hesaplanmis = tuple(compute_line(line, rate_period=rate_period) for line in lines)

    toplamlar: dict[RentalLineKind, Decimal] = dict.fromkeys(RentalLineKind, ZERO)
    bilinmeyen: dict[RentalLineKind, int] = dict.fromkeys(RentalLineKind, 0)
    for line in hesaplanmis:
        tutar = _line_contribution(line)
        if tutar is None:
            # Hesaplanamayan satır UYDURMA 0 ile toplama girmez; ATLANIR ama
            # adetçe bildirilir (MK-1 `summarize` kanonu).
            bilinmeyen[line.line_kind] += 1
        else:
            toplamlar[line.line_kind] += tutar

    kdv = compute_vat_amount(invoice_amount=invoice_amount, vat_rate=vat_rate)
    return RentalInvoiceResult(
        lines=hesaplanmis,
        our_total=toplamlar[RentalLineKind.rented],
        our_total_unknown_count=bilinmeyen[RentalLineKind.rented],
        owned_total=toplamlar[RentalLineKind.owned],
        owned_total_unknown_count=bilinmeyen[RentalLineKind.owned],
        excluded_breakdown_amount=toplamlar[RentalLineKind.breakdown],
        excluded_breakdown_unknown_count=bilinmeyen[RentalLineKind.breakdown],
        invoice_amount=invoice_amount,
        vat_rate=vat_rate,
        vat_amount=kdv,
        payable_total=compute_payable_total(invoice_amount=invoice_amount, vat_amount=kdv),
        site_distribution=_site_distribution(hesaplanmis),
    )
