"""E4 proje kartlarinin ZARF katmani — hangi alan gercek, hangisi yer tutucu.

## Neden `service.py`dan ayri (2026-08-22, P-YT1 denetimi)

`service.py` oturum/yetki/yazma tasir; buradaki is ise TEK bir soruya bakar:
*"kart bu alani gercek deger olarak mi, yoksa durust bir bos durum olarak mi
basar?"* Denetim turu her yer tutucunun **gerekcesini** koda yazinca `service.py`
**808 satira** cikti ve depo tavani **800**dur (`KURALLAR-BACKEND-SEFI.md §8`;
SA'nin 973 satirlik `service.py`si acik borctur ve TEKRARLANMAZ). Ayrim
`cost_cards.py` / `cost_summary.py` / `land_share_schemas.py` bolunmelerinin
aynisidir: gerekceler kisalmasin diye **dosya** bolundu, yorumlar degil.

## Bu dosyanin sinirlari

* **Hesap YOK.** Rakamlar `cost_cards.ProjectCardCosts` icinde HAZIR gelir;
  burasi yalnizca onlari zarfa koyar. Yeni bir `SELECT` ya da yeni bir para
  formulu buraya YAZILMAZ.
* **Yer tutucu gerekceleri BURADA yasar.** Her bos alanin yaninda, o alanin
  bugun neden bos oldugunu **olculmus** olarak anlatan not durur — modulun
  yoklugu DEGIL (13 anahtarin hepsi canli bir kaynagi adlandirir), gercek engel.
* Zarf sozlesmesinin kendisi `schemas.py`dedir (`MetricPlaceholder` /
  `CountPlaceholder` ve `metric` fabrikasi).
"""

from decimal import Decimal

from app.modules.projects.cost_cards import ProjectCardCosts
from app.modules.projects.models import Project
from app.modules.projects.schemas import (
    ContractingCard,
    CountPlaceholder,
    InvestmentCard,
    LandShareCard,
    MetricPlaceholder,
    ShareholderResponse,
    metric,
)

# Spec §2: bos durum alanlari ve bagli olduklari dilim anahtarlari.
_PROGRESS_PAYMENTS = "progress_payments"
_TIMESHEET = "timesheet"
_SUBCONTRACTS = "subcontracts"
_UNITS = "units"
_PROJECT_COSTS = "project_costs"

_LAND_COST_FIXED = Decimal("0")  # kat karsiliginda tanim geregi 0 (spec §3.3)


def _metric(pending_module: str) -> MetricPlaceholder:
    """Bos metrik zarfi. ⚠️ `pending_module` ARTIK "MODUL YOK" DEMEK DEGILDIR.

    Zarfin ilk anlami *"bu degeri verecek modul henuz yazilmadi"* idi. Bu anlam
    2026-08-22 denetiminde OLCULDU ve ARTIK YANLIS: backend'de `pending_module`
    olarak sahaya CIKABILEN 13 anahtarin (accounting · approvals · boq ·
    contracts · inventory · invoicing · progress_payments · project_costs ·
    site_planning · subcontracts · timesheet · treasury · units) HEPSI CANLI bir
    kaynagi adlandirir — onunun router'i `app/main.py`de kayitlidir, kalan
    ikisi (`project_costs` = `projects/costs.py`, `subcontracts` =
    `contracts/subcontracts.py`) canli DOSYADIR. Tek istisna gorunumundeki
    `purchasing` (`inventory/service.py:309`) sahaya HIC cikmaz: cagrisi
    `metric()`e daima dolu deger gecer, dolayisiyla anahtar `None`a duser.

    Anahtarin BUGUNKU anlami: **veri hangi modulun mulkiyetinde**. Alanin hâlâ
    bos olmasinin gercek sebebi ise ZARFTA DEGIL, her CAGRI YERINDE yazilidir —
    cunku sebepler ayni degildir: kimi alanda mockup kendi etiketiyle celisir,
    kimi alan zarfin SEKLINE sigmaz, kimi de yalnizca toplu okuyucusunu bekler.

    Yer tutucunun KALMASI mesru bir sonuctur (kullanici karari, `schemas.py`
    `TimelineSection` notu: kaynagi olmayan sayiyi bos zarfla dondurmek ekranda
    doldurulmayi bekleyen sahte bir sozlesme birakir) — ama bildirdigi SEBEP
    dogru olmak zorundadir. Sebepler `tests/modules/test_projects_cost_bindings.py`
    icindeki denetim bekcileriyle cakilidir.

    Ayni zarfin BAGLANMIS hâli: `_worker_count` / `_side_unit_count` — zarf tipi
    DEGISMEZ, yalnizca ici dolar.
    """
    return MetricPlaceholder(pending_module=pending_module)


def _count(pending_module: str) -> CountPlaceholder:
    """Bos sayac zarfi — `_metric`in sayac ikizi, ayni anahtar sozlesmesi gecerli.

    `pending_module` burada da "modul yok" DEMEZ, veriyi kimin sahiplendigini
    soyler (gerekce `_metric` docstring'inde). Fark: dolu `CountPlaceholder`
    `pending_module` TASIMAYA DEVAM EDER (`CountPlaceholder` sinif notu), bu
    yuzden `_worker_count`/`_side_unit_count` baglandiktan sonra bile ayni
    seritteki kardes sayaclar kaynagini okumaya devam eder.
    """
    return CountPlaceholder(pending_module=pending_module)


def _worker_count(value: int) -> CountPlaceholder:
    """T4 — `_TIMESHEET` yer tutucusunun BAGLANMIS hali (puantaj spec §4).

    Zarf KORUNUR, yalnizca doldurulur (`available=True` + gercek `count`):
    taahhut kartinin diger sayaclari hâlâ yer tutucudur ve ayni serit iki farkli
    sozlesme tasimamalidir. Sayim `timesheet.counts`tadir — bu modul kendi
    `SELECT`ini yazmaz.
    """
    return CountPlaceholder(available=True, count=value, pending_module=_TIMESHEET)


def _side_unit_count(value: int | None) -> CountPlaceholder:
    """E4 148-149 paylasim seridinin iki sayaci — `_worker_count` emsalinin AYNISI.

    Zarf SEKLI degismez: dolu `CountPlaceholder` `pending_module` TASIMAYA DEVAM
    EDER (`MetricPlaceholder`in "dolu zarf modul tasimaz" kurali `CountPlaceholder`a
    UYGULANMAZ — bkz. o sinifin notu). Ayni serit uzerindeki diger ünite alanlari
    (`unit_summary`, `sold_amount`) hâlâ yer tutucudur ve ekran seridin kaynagini
    oradan okur.

    `None` yalnizca kart maliyetleri HIC OKUNMADAN kurulan saf donusturucu
    yolunda (`to_detail`in varsayilan `cost_cards.EMPTY`i) gelir; o hâl "sayi
    bilinmiyor"dur ve bos zarf doner. Kat karsiligi projede sayac ASLA `None`
    olmaz — ünitesi olmayan projede `0` GERCEK cevaptir.
    """
    if value is None:
        return _count(_UNITS)
    return CountPlaceholder(available=True, count=value, pending_module=_UNITS)


def _contracting_card(worker_count: int, card_costs: ProjectCardCosts) -> ContractingCard:
    """E4 181/206/231/256 "Harcanan" P10 T4'te ZARFIN ICINDE gercege baglandi.

    Kaynak TASERON hakedisidir (spec §2), isveren hakedisi DEGIL: taahhut
    projesinde isveren hakedisi GELIRDIR — alanin eski `_PROGRESS_PAYMENTS`
    etiketi P1'den kalan yanlis etiketti ve etiket de `_PROJECT_COSTS`a dondu.
    Serit uzerindeki kalan uc alan hâlâ BOS; ama 2026-08-22 denetiminden sonra
    "modulu bekliyor" DEMEZ (bkz. `_metric`) — her birinin gercek engeli
    asagida, kendi cagri yerinde yazilidir.
    """
    return ContractingCard(
        spent=metric(card_costs.spent, _PROJECT_COSTS),
        # 🔴 SINIF (C) TUZAK — E4 185/210/235/260/279 "Fiziksel İlerleme"
        # (%75/%58/%42/%88/%100). MOCKUP KENDI KENDIYLE CELISIYOR: bes karonun
        # BESINDE de basilan yuzde tam olarak `Harcanan / Sözleşme Bedeli`dir
        # (8,4/11,2 · 6,2/10,7 · 5,8/13,8 · 4,5/5,1 · 9,4/9,4) — yani sayi MALI,
        # etiket FIZIKSEL. `progress_payments` modulu CANLI ve GERCEK bir fiziksel
        # ilerleme HESAPLIYOR (`progress_payments/service.py` `_progress_block`,
        # `physical_numerator / get_contract_items_total_value`) — ama YALNIZ TEK
        # HAKEDIS icin ve yalniz `get_detail(payment_id)` uzerinden; PROJE
        # duzeyinde fiziksel ilerleme fonksiyonu YOKTUR.
        # ⚠️ Kolay olani (harcama orani) baglamak, FIZIKSEL etiketin altina MALI
        # bir sayi basar: makul gorunur ve YANLISTIR. Baglayacak kisi ONCE alanin
        # bu ikisinden HANGISI oldugunu karara baglamak zorundadir.
        physical_progress=_metric(_PROGRESS_PAYMENTS),
        # 🔴 SINIF (C) TUZAK — engel VERI degil, KART SOZLESMESI.
        # Mockup etiketi "Final Hakediş"tir (E4 277), "Son Hakediş" DEGIL: o dize
        # hicbir mockup'ta ALAN ETIKETI olarak gecmez (yalnizca superseded
        # `projedesign/uploads/...` kopyalarinda "Son Hakedişler" liste basligi
        # olarak vardir — baska bir sey).
        # Alan TEK bir karoda gorunur: `Tamamlandı` olani. Orada `Harcanan`in
        # YERINI alir (E4 275-278: izgara 4 hucreden 2'ye duser). Yani daimi bir
        # alan degil, KOSULLU bir yuvadir; `ContractingCard` ise `spent` ile
        # `final_progress_payment`i KOSULSUZ iki alan olarak tasir ve bu yuvayi
        # ifade EDEMEZ. Baglamadan once kart sozlesmesi karara baglanmalidir.
        final_progress_payment=_metric(_PROGRESS_PAYMENTS),
        worker_count=_worker_count(worker_count),
        # SINIF (A) BAYAT — kaynak CANLI, alan yalnizca henuz BAGLANMADI.
        # E4 188/213/238 → `12 taşeron` / `9 taşeron` / `7 taşeron`: tek bir int,
        # yani `CountPlaceholder` zarfi SIGAR. `_SUBCONTRACTS = "subcontracts"`
        # bekleyen bir modul ima eder ama `app/modules/subcontracts/` YOKTUR:
        # gercek kaynak CANLI `contracts/subcontracts.py`dir ve
        # `contracts/repository.py:166` `count_subcontractor_contract_rows(...)`
        # zaten `project_id` kabul eder. Baglamayi bekleten IKI ACIK KARAR:
        #   (a) TOPLU sayac YOK — o fonksiyon TEK projelidir; naif baglama proje
        #       basina bir sorgu acar ve `cost_cards.py` modul docstring'indeki
        #       N+1 kuralini (kart turevleri proje basina sorgu ACMAZ) kirar.
        #   (b) HANGI sozlesmeler sayilir? `SubcontractorContract.status`
        #       `ContractStatus{active, completed, on_hold}` (contracts/models.py:246)
        #       ve ayrica `is_draft` bayragi var (a.g.e. 252) — TASLAK sozlesme
        #       calisan bir taseron DEGILDIR.
        # Ev emsali: `subcontractor_progress_payments/summary.py:132`
        # (`active_subcontractor_count`) SOZLESME sayar, FIRMA degil — cunku
        # `subcontractor_name` serbest metin ve nullable'dir (contracts/models.py:203).
        subcontractor_count=_count(_SUBCONTRACTS),
    )


def _investment_card(project: Project, card_costs: ProjectCardCosts) -> InvestmentCard:
    """KY 182/187-188 üç alanı P10 T3'te ZARFIN İÇİNDE gerçeğe baglandi.

    `total_cost` E4 122'dir ve KULLANICI KARARI 2026-08-09 ile **HARCANAN**dir
    (arsa + taşeron hakedişi; `costs.total_spent`) — kanıt KY hero ikilisi
    ("₺20,3M / ₺29,8M bütçe"). `estimated_profit`/`margin` ise BÜTÇE tabanlı
    KALIR (`costs.card_projection`): kartın bu karışımı mockup'ın kendi
    okumasidir, backend iki tabani da tasir.

    Bagli olmayan alanlar (satis/ünite tarafi) yer tutucu KALIR: bu dilim yalniz
    maliyet/kâr türevlerini baglar (`_worker_count`un P-T4'teki kismi baglama
    deseninin aynisi). Uc alanin da engeli `units` modulunun YOKLUGU DEGILDIR
    (modul CANLI, 2026-08-22 denetimi) — her biri asagida ayri ayri yazilidir.
    """
    investment = project.investment
    return InvestmentCard(
        sales_target=investment.sales_target if investment else None,
        land_cost=investment.land_cost if investment else None,
        # SINIF (A) BAYAT — kaynak CANLI, engel yalnizca TOPLU YUKLEYICI eksikligi.
        # E4 121 "Satılan ₺31,4M"; tam hassasiyeti KY detayinda
        # (`Proje - Kendi Yatırım.dc.html:172` `₺31.420.000` + "34 ünite satıldı").
        # FORMUL ZATEN VAR: `projects/costs.py::realized_sales_total`
        # (`REALIZED_SALE_STATUSES` uzerinden `UnitSale.sale_price` toplami) ve
        # tek bir `Decimal` uretir, yani zarf SIGAR.
        # Engel: satis satirlari KART YOLUNDA HIC YUKLENMIYOR. `cost_cards.by_projects`
        # uniteleri TOPLU okur (`units.repository.list_units_for_projects`) ama
        # `UnitSale`i okumaz; mevcut satis okuyucularinin IKISI DE tek projeliktir
        # (`sales.repository.list_sale_rows(project_id)` — `cost_summary.py:181`;
        # `units.repository.list_open_sales_for_project` — `land_share.py:266`).
        # Kalan is TAM OLARAK BUDUR: TOPLU bir satis yukleyicisi (N+1 kurali,
        # `cost_cards.py` modul docstring'i).
        sold_amount=_metric(_UNITS),
        # 🔴 SINIF (C) TUZAK — engel VERI degil, ZARFIN SEKLI.
        # E4 125'te etiket birebir `Satış Oranı (34/52 ünite)`, deger `%65`.
        # Oran UNITE tabanlidir, PARA tabanli DEGIL: KY hero ikizi bunu
        # dogruluyor (`Proje - Kendi Yatırım.dc.html:87-91` → "Satılan Ünite" /
        # "34 / 52" / "%65 satıldı"), ayrica tasarimci para ikilisini AYRI bir
        # karoda tutmus ve oraya hic yuzde koymamis.
        # TUZAK: ETIKETIN KENDISI iki sayac (34 ve 52) iddia ediyor, `MetricPlaceholder`
        # ise TEK bir `Decimal` tasir. Yalnizca `%65`i baglamak, frontend'in KENDI
        # ETIKETINI basamayacagi bir kart gonderir. Once zarf sekli karara baglanmali.
        sales_ratio=_metric(_UNITS),
        # 🔴 SINIF (C) TUZAK — engel VERI degil, ZARFIN SEKLI.
        # E4 127 cipi: `48 daire + 4 dükkan` — bu bir TUR KIRILIMIDIR, tek sayi degil.
        # `CountPlaceholder.count` ise tek bir `int | None`dir ve bunu IFADE EDEMEZ:
        # `count=52` baglamak, mockup'in tarif ettiginden BASKA bir alani sessizce
        # gondermek olurdu.
        # Dogrulama: 48+4 = 52 = kardes `sales_ratio` etiketindeki `/52` paydasi.
        # Alanin gercekten ihtiyac duydugu SEKIL zaten yazili:
        # `units/schemas.py:143` `UnitKindBreakdown` (apartment/shop/office/
        # warehouse/parking + turev `total`).
        unit_summary=_count(_UNITS),
        total_cost=metric(card_costs.total_cost, _PROJECT_COSTS),
        estimated_profit=metric(card_costs.profit, _PROJECT_COSTS),
        margin=metric(card_costs.margin_pct, _PROJECT_COSTS),
    )


def _land_share_card(project: Project, card_costs: ProjectCardCosts) -> LandShareCard | None:
    """KK karti — E4 148-149 paylasim seridinin iki ünite sayaci ARTIK GERCEKTIR.

    `units` modülü CANLIDIR: `our_unit_count`/`owner_unit_count` duz `owner_side`
    sayimidir ve `GET /projects/{id}/land-share/summary` ucunun
    `our_side.unit_count` / `owner_side.unit_count` alanlariyla AYNI SAYILARDIR —
    ayrimi yapan yüklem artik TEK dosyada (`projects.unit_sides`) yasar, bu üc
    yüzey birbirinden kayamaz. Sayaclar ek sorgu ACMAZ: üniteler kart okumasinda
    zaten yüklüdür ve `ProjectCardCosts` üzerinden gelir.

    Atanmamis (`owner_side IS NULL`) ünite iki sayacin HICBIRINE girmez; onun
    görünürlügü `land-share/summary` ucunun `unassigned` bölümündedir.
    """
    land_share = project.land_share
    if land_share is None:
        return None
    return LandShareCard(
        landowner_name=land_share.landowner_name,
        our_share_pct=land_share.our_share_pct,
        owner_share_pct=land_share.owner_share_pct,
        land_cost=_LAND_COST_FIXED,
        contract_no=land_share.contract_no,
        notary_date=land_share.notary_date,
        land_area_m2=land_share.land_area_m2,
        construction_area_m2=land_share.construction_area_m2,
        delivery_date=land_share.delivery_date,
        daily_penalty=land_share.daily_penalty,
        guarantee_amount=land_share.guarantee_amount,
        shareholder_count=len(project.shareholders),
        shareholders=[ShareholderResponse.model_validate(s) for s in project.shareholders],
        our_unit_count=_side_unit_count(card_costs.our_unit_count),
        owner_unit_count=_side_unit_count(card_costs.owner_unit_count),
        # KK 121 "BİZİM PAY": kaynak modül (`units`) CANLI olduğu için değer
        # daima bilinir — ünitesi olmayan projede 0,00 gerçek cevaptır.
        our_share_value=metric(card_costs.our_share_value, _UNITS),
        # KK 135 BÜTÇEDIR (kâr projeksiyonunun tabani, spec §2) — kendi yatirim
        # kartinin HARCANAN `total_cost`u ile ayni sayi DEGILDIR (kullanici karari
        # 2026-08-09); iki alanin bagi `ProjectCardCosts`ta KOPARILDI.
        construction_cost=metric(card_costs.construction_cost, _PROJECT_COSTS),
        estimated_profit=metric(card_costs.profit, _PROJECT_COSTS),
        margin=metric(card_costs.margin_pct, _PROJECT_COSTS),
        # 🔴🔴 SINIF (C) TUZAK — bu dosyadaki EN TEHLIKELI yer tutucu (E4 157
        # "İnşaat İlerlemesi", %42). IKI ayri tuzak var, ikisi de baglamayi yasakliyor.
        #
        # TUZAK A — `pending_module` YAPISAL OLARAK KARSILANAMAZ.
        # Bu alan KAT KARSILIGI kartindadir. `progress_payments` ise ISVEREN
        # hakedisini modeller (`progress_payments/models.py:41-42`) ve kat karsiligi
        # projesinde ISVEREN YOKTUR. Yani `pending_module="progress_payments"`,
        # bu degeri ASLA veremeyecek bir modulu adlandiriyor. Ayni yanlis etiket
        # kardes alanda BIR KEZ YAKALANIP DUZELTILDI — yukaridaki `_contracting_card`
        # notu ("P1'den kalan yanlis etiket") — burada HALA DUZELTILMEDI.
        #
        # TUZAK B — CEKICI SUTUN BIR FOSIL. (Denetimin bas bulgusu.)
        # `projects.progress_pct` (`projects/models.py:143`, `Numeric(5,2)`,
        # `nullable=False, default=0`) apacik kaynak gibi gorunuyor. OLCULDU:
        #   * HICBIR uygulama kodu ONA YAZMIYOR. `ProjectCreate` (schemas.py:554)
        #     ve `ProjectUpdate` (schemas.py:576) alanlarinda YOK — yani HICBIR HTTP
        #     istegi onu set EDEMEZ; `create_project` (bu dosya, `Project(...)`
        #     kurulumu) alani atlar; `update_project` `model_dump(exclude_unset=True)`
        #     ile boyle bir alani OLMAYAN semayi gezer. `update(Project)` yok, toplu
        #     guncelleme yok, ham SQL yok.
        #   * AMA DAIMA 0 DEGIL. Canli zincirdeki tohum migration'i
        #     `alembic/versions/795d6498e4da_projects_seed.py:37-65` uc demo projeye
        #     (`GK-A`, `MERKEZ-1`, `SAHIL-2`) `42.50` / `15.00` / `100.00` YAZAR ve
        #     bu revizyon head'in atasidir — `alembic upgrade head` her dagitilan
        #     veritabaninda onu KOSAR.
        #   * USTELIK ZATEN HAM SERVIS EDILIYOR: `ProjectListItem.progress_pct`
        #     (schemas.py:429) zarf DEGIL duz bir `Decimal`dir, `_to_item` icinde
        #     doldurulur ve liste/detay/create/update uclarinin HEPSI onu doner —
        #     `DashboardProjectCard.progress_pct` (dashboard/schemas.py:43) de oyle.
        # SONUC: sutun YAZIMI OLU bir fosildir — kullanicinin actigi her projede
        # kalici olarak 0, uc tohum satirinda ise HICBIR EKRANIN duzeltemeyecegi
        # donmus bir sifir-disi deger. `construction_progress`i buna baglamak yer
        # tutucudan DAHA KOTU olurdu: yetkili gorunen ("insaat %42") ve hicbir
        # formdan duzeltilemeyen YANLIS bir olgu iddiasi basardi.
        # Bekcisi: `tests/modules/test_projects_cost_bindings.py`
        # `test_projects_progress_pct_sutununun_YAZMA_YOLU_YOKTUR`.
        construction_progress=_metric(_PROGRESS_PAYMENTS),
    )
