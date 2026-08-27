import uuid
from decimal import ROUND_HALF_UP, Decimal

from pydantic import BaseModel, Field, computed_field

# Serbest metin tavani (TB4 S3) `contracts` ailesiyle PAYLASILIR — tek kaynak.
from app.core.text import FREE_TEXT_MAX_LENGTH

# Yer tutucu sozlesmesi TEK yerde tanimlidir (B6/P1, spec §3/§5.1): kopyalanmaz,
# projects modulunden import edilir (plan T2 notu).
from app.modules.projects.schemas import MetricPlaceholder

__all__ = [
    "MetricPlaceholder",
    "quantize_money",
    "BoqGroupCreate",
    "BoqGroupResponse",
    "BoqGroupUpdate",
    "BoqItemAllocation",
    "BoqItemAllocationInput",
    "BoqItemAllocationsReplace",
    "BoqItemAllocationsResponse",
    "BoqItemCreate",
    "BoqItemResponse",
    "BoqItemUpdate",
    "BoqListResponse",
    "BoqTotals",
]

_MONEY = Decimal("0.01")

#: Miktar hassasiyeti — `boq_items.quantity` / `boq_item_section_allocations.quantity`
#: kolonlarinin `Numeric(14, 3)` olcegiyle BIREBIR. Govdeden gelen miktar YAZILMADAN
#: ONCE bu olcege cekilir: kontrol edilen sayi ile SAKLANAN sayi ayrisirsa toplam
#: invarianti (K3) DB'nin yuvarlamasi kadar kacak verir.
_QUANTITY = Decimal("0.001")


def quantize_money(value: Decimal) -> Decimal:
    """Paranin `boq/` icindeki TEK yuvarlamasi (K3, P-YT3 T2).

    🔴 Ad basindaki alt cizgi KALDIRILDI cunku ikinci bir kopya vardi:
    `service.py` ayni `_MONEY`/`_quantize_money` ikilisini kendi icinde
    yeniden tanimliyordu. Iki kopya bugun ayni sonucu veriyordu, ama
    `boq`nun kalem basina yuvarlayan para formulu `sites.Section.budget`in
    (C) gerekcesinin TAM MERKEZINDEDIR (P-YT2): o alani ileride baglayacak
    dilim "tek kopyayi cagir" derken IKI aday bulurdu.
    """
    return value.quantize(_MONEY, rounding=ROUND_HALF_UP)


def quantize_quantity(value: Decimal) -> Decimal:
    return value.quantize(_QUANTITY, rounding=ROUND_HALF_UP)


# --- Okuma semalari ---


class BoqItemResponse(BaseModel):
    """Spec §5.1 poz kalemi satiri. `amount` turevdir, saklanmaz — quantity *
    unit_price, para hassasiyetine (0.01) yuvarlanir.

    ✅ `progress_pct` — **ILR-1'DE BAGLANDI (2026-08-27). KAYNAK GUNLUKTUR.**

    P-YT3 (2026-08-23) bu alani (C) TUZAK diye BOS birakmisti ve gerekcesi
    **IZIN KAPISIYDI (K4)**: `procurement` `boq=view/limited` ama
    `progress_payments=none`; zarfi doldurmak isverene kesilen hakedisin
    gerceklesme oranini satinalmaya BOQ ekranindan acardi.

    🔴 **O GEREKCE CURUMEDI — KARSILANDI.** Iki sey degisti:
      1. **Kaynak degisti.** Kullanici karari (2026-08-27): FIZIKSEL ilerleme
         hakedisten DEGIL, **gonderilmis santiye gunlugunden** turer
         (`boq/progress.py`). Hakedisten turemis MALI ilerleme AYRI bir
         kavramdir ve BU alanda DEGILDIR.
      2. **Kapi kalkmadi, ALANA TASINDI.** Kaynak degisince sizinti kumesi de
         degisti (olculdu: `boq` okuyup `site_diary` okuyamayan roller =
         `accounting`, `procurement`) — yani kapi HALA GEREKLI. Bu yuzden zarf
         **IZNE DUYARLIDIR**: izinsiz rolde `restricted()` doner
         (`available=False` + `pending_module is None`), izinli rolde DOLAR.

    🔴 Formul **PARA AGIRLIKLI**: `Σ(gerceklesen × fiyat) / Σ(taban × fiyat)`.
    PAYDA = SUNULAN miktar — bolum suzgecinde o bolumun TAHSISI, aksi hâlde
    pozun santiye kotasi (asagidaki "iki anlam" notuyla birebir tutarli).

    Bekciler: `tests/modules/test_ilr_ilerleme.py` (cift yonlu izin + para
    agirligi mutanti) ve `test_boq_pyt3_yer_tutucu_denetimi.py` (`test_K4_*`
    kumeyi hâlâ cakar — matris ayrismasi kapanirsa haber verir).
    """

    id: uuid.UUID
    code: str
    description: str
    unit: str
    quantity: Decimal
    unit_price: Decimal
    progress_pct: MetricPlaceholder
    sort_order: int
    # --- BOQ-SEC (K6) — MEVCUT alanlarin hicbiri degismedi, ikisi EKLENDI ---
    #
    # 🔴 IKI ANLAM TUZAGI: `section_id` suzgeciyle okundugunda `quantity` O BOLUME
    # tahsis edilen miktardir (poz toplami DEGIL, K5) — ama asagidaki iki alan HER
    # ZAMAN pozun GERCEK santiye kotasi uzerinden turer. Yani suzulmus yanitta
    # `unallocated_quantity != quantity - allocated_quantity`'dir ve bu bir kusur
    # degil tanimdir. Mockup'in "Santiye Kotasi" sutunu (BoqAssignmentCard.tsx:17)
    # suzulmus yanitta `allocated_quantity + unallocated_quantity`den okunur.
    allocated_quantity: Decimal
    unallocated_quantity: Decimal

    @computed_field  # type: ignore[prop-decorator]
    @property
    def amount(self) -> Decimal:
        return quantize_money(self.quantity * self.unit_price)


class BoqGroupResponse(BaseModel):
    """Spec §5.1 grup satiri. `group_total` turevdir: kalem tutarlarinin toplami."""

    id: uuid.UUID
    name: str
    sort_order: int
    items: list[BoqItemResponse]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def group_total(self) -> Decimal:
        return quantize_money(sum((item.amount for item in self.items), Decimal("0")))


class BoqTotals(BaseModel):
    """Spec §5.1 ust KPI seridi. `grand_total` GERCEK deger (gruplarin toplami).

    ⚠️ **ILR-1 (2026-08-27): `grand_progress_pct` BAGLANDI** — kaynagi hakedis
    DEGIL **gunluktur** ve `boq/progress.py`den TEK kaynaktan gelir (grup
    satirlarindan yeniden toplanmaz). Kalan DORT zarfin gerekcesi AYNEN
    gecerlidir. Asagidaki tablo o dort satir icin okunur.

    🔴 **P-YT3 DENETIMI (2026-08-23) — BES ZARFIN DE SINIFI VE SEBEBI.** Eski
    yorum *"sozlesme/hakediş bu dilimde yazilmiyor"* diyordu ve BAYATTI: iki
    modul de aylardir canli. Bugunku olgu:

    | alan | sinif | bagli olmama SEBEBI |
    |---|---|---|
    | `contract_total` | (C) TUZAK | **K4** — `site_chief`+`procurement`: boq=view, contracts=none |
    | `realized_total` | (C) TUZAK | **K4** — `procurement` `progress_payments`ta `none` |
    | `remaining_total` | (C) TUZAK | `contract_total − realized_total`; iki ucu da K4 kapali |
    | `revision_total` | (B) GECERLI | 🔑 **repoda REVIZYON KAVRAMI YOK** — kaynak yok |
    | `grand_progress_pct` | ✅ **BAGLANDI** | ILR-1: kaynak GUNLUK, izne duyarli |

    🔑 `contract_total`in formulu ZATEN YAZILI ve TEK KOPYA:
    `contracts/distribution.py::_site_summaries` santiye basina
    `Σ (BOQ satiri miktari × SOZLESME kaleminin birim fiyati)` hesaplar (spec
    §3.3: otorite sozlesmedir). Baglanacagi gun o cagrilir, KOPYALANMAZ (K3) —
    burada ikinci bir carpim yazmak kurus farkli bir "Sozlesme Bedeli" uretirdi.

    🔴 `revision_total` icin arama YAPILDI: `revision`/`revizyon` gecen tek yer
    `subcontractor_progress_payments`taki `is_revision_required` BAYRAGIDIR
    (hakedisin "duzeltilmeli" durumu) — sozlesme revizyonu ile ilgisi yoktur.
    Sozlesme revizyonu ne modelde ne migration'da vardir; anahtar `contracts`
    dogru kalir ama bekleyen sey MODUL degil **KAVRAMDIR**.
    """

    contract_total: MetricPlaceholder
    realized_total: MetricPlaceholder
    remaining_total: MetricPlaceholder
    revision_total: MetricPlaceholder
    grand_total: Decimal
    grand_progress_pct: MetricPlaceholder


class BoqListResponse(BaseModel):
    totals: BoqTotals
    groups: list[BoqGroupResponse]


# --- Yazma semalari ---


class BoqGroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=FREE_TEXT_MAX_LENGTH)
    sort_order: int = Field(default=0, ge=0)


class BoqGroupUpdate(BaseModel):
    """`site_id` YOK — grup baska santiyeye tasinamaz (spec §3.3 invariant 4)."""

    name: str | None = Field(default=None, min_length=1, max_length=FREE_TEXT_MAX_LENGTH)
    sort_order: int | None = Field(default=None, ge=0)


class BoqItemCreate(BaseModel):
    group_id: uuid.UUID
    code: str = Field(min_length=1, max_length=50)
    description: str = Field(min_length=1, max_length=FREE_TEXT_MAX_LENGTH)
    unit: str = Field(min_length=1, max_length=50)
    quantity: Decimal = Field(gt=0)
    unit_price: Decimal = Field(ge=0)
    sort_order: int = Field(default=0, ge=0)


class BoqItemAllocationInput(BaseModel):
    """Tek tahsis satiri (BOQ-SEC K4).

    `quantity` STRICT pozitiftir: sifir tahsis bir satir olarak TUTULMAZ (K1
    `CHECK`i ile ayni kural) — "bu bolumden cikar" demenin yolu satiri govdeden
    DUSURMEKTIR, sifir yazmak degil.
    """

    section_id: uuid.UUID
    quantity: Decimal = Field(gt=0)


class BoqItemAllocationsReplace(BaseModel):
    """`PUT /boq/items/{item_id}/allocations` govdesi — TAM KUME DEGISTIRME.

    🔴 `allocations` ZORUNLUDUR (varsayilani YOKTUR): alan hic gonderilmezse ya
    da `null` gecilirse istek 422 alir. Bu ucta "dokunma" anlami YOKTUR; bos
    dizi `[]` "hepsini kaldir" demektir ve eksik alani sessizce ona ya da
    "degistirme"ye yorumlamak, kullanicinin niyetini SUNUCUNUN uydurmasi olurdu.
    """

    allocations: list[BoqItemAllocationInput]


class BoqItemAllocation(BaseModel):
    """Yaziladan SONRAKI tahsis satiri. `section_name` UI icindir (mockup F131-211).

    Bu sema santiye BOQ listesinde BASILMAZ (K6): her kalem icin tahsis listesi
    donmek N+1 acar ve liste ekraninin ihtiyaci olan sey zaten `allocated_quantity`
    ozetidir.
    """

    section_id: uuid.UUID
    section_name: str
    quantity: Decimal


class BoqItemAllocationsResponse(BaseModel):
    item: BoqItemResponse
    allocations: list[BoqItemAllocation]


class BoqItemUpdate(BaseModel):
    """`site_id` YOK (spec §3.3 invariant 4). `group_id` verilirse ayni santiye
    kontrolu servis katmaninda tekrarlanir (spec §3.3 invariant 1)."""

    group_id: uuid.UUID | None = None
    code: str | None = Field(default=None, min_length=1, max_length=50)
    description: str | None = Field(default=None, min_length=1, max_length=FREE_TEXT_MAX_LENGTH)
    unit: str | None = Field(default=None, min_length=1, max_length=50)
    quantity: Decimal | None = Field(default=None, gt=0)
    unit_price: Decimal | None = Field(default=None, ge=0)
    sort_order: int | None = Field(default=None, ge=0)
