"""Gosterge paneli ozeti + BES KARTIN YER TUTUCU DENETIMI (P-YT2).

🔴 `pending_module` ARTIK "MODUL YOK" DEMEK DEGIL (P-YT1 bulgusu). Bu dosyadaki
BES anahtarin BESI de CANLI bir modulu adlandirir; zarfin ilk anlami tek bir
kart icin bile dogru degildir. Denetim bu yuzden UC SINIF uretti:

| Kart | anahtar | sinif | ozet gerekce |
|---|---|---|---|
| `pending_approvals` | `approvals` | **(A) BAYAT** | motor canli, kapsam ayni — **BAGLANDI** |
| `portfolio` | `progress_payments` | **(C) TUZAK** | "Toplam Hakedis" iki canli |
| | | | yuzeyde FARKLI kume sayiyor |
| `receivables` | `invoicing` | **(C) TUZAK** | veri hazir ama IZIN MATRISI |
| | | | bu kapidan gecirmiyor |
| `average_margin` | `progress_payments` | **(C) TUZAK** | ortalama TANIMSIZ + anahtar |
| | | | YANLIS modulu gosteriyor |
| `risks` | `inventory` | **(C) TUZAK** | zarf `list[str]`, kart uc kaynakli |
| | | | ve UC OLGU tasiyan satir istiyor |

Gerekceler kartlarin YANINDA durur, burada degil: bir kart baglandiginda ya da
kaldirilinca gerekcesi de onunla birlikte tasinsin.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.approvals import service as approvals_service
from app.modules.dashboard.schemas import (
    DashboardProjectCard,
    DashboardSummaryResponse,
    ListPlaceholder,
    MetricPlaceholder,
    PendingApprovalsPlaceholder,
)
from app.modules.projects.models import ProjectStatus
from app.modules.projects.repository import list_projects_for_user
from app.modules.roles.models import Role
from app.modules.users.models import User

# Kart -> BESLEYEN modul anahtari. Ad "bekleyen" demeye devam etse de artik
# yalnizca KAYNAGI isaret eder (P-YT1 `_worker_count` emsali): bagli bir kart da
# anahtarini tasir, cunku ekran "bu sayi nereden geliyor" sorusunu sormaya devam
# eder. Anahtar STRING DEGERLERI DEGISTIRILMEDI — frontend bunlara dallanabilir
# ve deger degisimi sozlesme kirilmasi olurdu (bkz. `_MARGIN_MODULE` notu).
_PORTFOLIO_MODULE = "progress_payments"
_RECEIVABLES_MODULE = "invoicing"
_MARGIN_MODULE = "progress_payments"
_APPROVALS_MODULE = "approvals"
_RISKS_MODULE = "inventory"

#: 🔴 YALNIZ SAYIM ISTIYORUZ. `pending_for_user` sayfayi ve TOPLAMI ayri
#: sorgulardan uretir; `limit=0` sayfayi bos birakir ve satir zenginlestirmesini
#: (adimlar · kullanici adlari · UC EVRAK AILESI) HIC calistirmaz.
#: OLCULDU: `limit=0` -> 13 sorgu, `limit=1` -> 19, `limit=50` -> 19.
#: Rozet icin alti sorgu bosuna odenmez; `total` ayni suzgecten gelir.
_ONLY_TOTAL = 0


async def _pending_approvals(session: AsyncSession, user: User) -> PendingApprovalsPlaceholder:
    """(A) — "Onay Bekleyenler" rozeti. Repodaki EN TAZE bayat yer tutucuydu:
    bekledigi motor OK-1A ile canliya cikti, OK-1C ile fiilen isletilebilir oldu.

    🔴 SUZGEC KOPYALANMADI, SERVIS CAGRILDI (K3). Kutunun kurali
    `approvals/repository.py:_pending_filter`ta DORT kosuldur (adim rolu · kendi
    evraki · gorevler ayriligi · proje kapsami). Ikinci bir kopya bugun ayni
    sayiyi verse bile ilk kural degisikliginde sessizce ayrisirdi: panelde
    gorunen sayi ile kutuda gorunen SATIR SAYISI birbirini tutmazdi.

    🔴 KAPSAM AYNEN KORUNUR ve BEDAVA DEGILDIR. Motor kapsami
    `projects.service.visible_projects` uzerinden KENDI cozer; panelin elindeki
    `projects` listesi ONA VERILEMEZ, cunku iki kume AYNI DEGILDIR: panel
    `list_projects_for_user`i cagirir (admin atlamasi YOK), motor ise
    `projects: admin` rolu icin TUM projelere gecer. Kapsami disaridan
    beslemek, admin bir aktorun rozetini sessizce daraltirdi.

    ⚠️ OLCULMUS MALIYET (bu dilimde eklenen):
      * onay rolu OLMAYAN aktor (cogunluk): **+1 sorgu** — motor rol kumesi
        bosken erkenden doner.
      * onay rolu TASIYAN aktor: **+13 sorgu**; bunun **7'si** panelin zaten
        kostugu proje okumasinin (`visible_projects`) tekrarididir. Tekrari
        silmek motorun IMZASINI degistirmeyi gerektirir (kapsami disaridan
        almak) — o `approvals/` dilimidir, burada YAPILMADI.
      Ikisi de SATIR SAYISINDAN BAGIMSIZDIR (bekcisi:
      `test_panelin_sorgu_sayisi_SATIR_SAYISINDAN_BAGIMSIZ`).

    🔴 `available=True` HER ZAMAN, `count=0` olsa bile (K2). Kaynak canli
    oldugu icin sifir artik OTORITER bir olgudur ("sizden bekleyen imza yok"),
    "bilinmiyor" degil. `CountPlaceholder` notundaki emsal aynen gecerlidir:
    dolu zarf `pending_module` tasimaya DEVAM eder.

    🔴 `items` BOS KALIR ve bu bir SONUCTUR. Mockup satiri
    (`Ekran 1 - Gosterge Paneli.dc.html:310-330`) DORT olgu basar: baslik ·
    tutar · goreli zaman · aciliyet cipi. `items: list[str]` bunlardan BIRINI
    tasir; ucunu bir metne yapistirmak, ekranin ayristirmak zorunda kalacagi
    bir sunum kararini sunucuda uretmek olurdu (K10). Ustelik "Acil" cipi bir
    KARAR metnidir ve motor bilincli olarak karar alani dondurmez (kanon E).
    Satiri tasiyabilecek bir zarf ADDITIVE bir sema isidir ve F-OK'undur.

    ⚠️ KAPSAM SINIRI (yalan degil, EKSIKLIK): motor bugun UC evrak ailesi
    tanir (taseron hakedisi · isveren hakedisi · satin alma talebi); mockup'in
    bes kartindan BORDRO ve GUNLUK KAYIT OK-1B'nindir. Rozet bu yuzden kutunun
    gosterdigi kumeyle BIREBIR ayni eksigi tasir — ve tam da servisi CAGIRDIGI
    icin OK-1B geldiginde IKISI BIRDEN buyur. Bir kopya buyumezdi.
    """
    _sayfa, toplam, _roller = await approvals_service.pending_for_user(
        session, user, limit=_ONLY_TOTAL, offset=0
    )
    return PendingApprovalsPlaceholder(
        available=True, count=toplam, pending_module=_APPROVALS_MODULE
    )


def _portfolio() -> MetricPlaceholder:
    """(C) TUZAK — "Portfoy · Toplam Hakedis" (mockup `:196`).

    Modul CANLI ve toplu okuyucu VAR (`progress_payments/summary.py:98`
    `cumulative_gross_by_projects`, 2 sorgu). Baglanmadi, cunku "Toplam Hakedis"
    ADI REPODA ZATEN IKI FARKLI KUMEYI ANLATIYOR:

    * `cumulative_gross_by_projects` TASLAKLARI ELER (`COMPLETED_STATUSES =
      (approved, paid)`);
    * ayni Turkce basligi tasiyan canli ekran
      (`subcontractor_progress_payments/summary.py:129` `total_gross`) taslak
      DAHIL sayar — o dosya bu farki kendi icinde uyari olarak yaziyor.

    Ustelik hangi hakedis oldugu da secilmemistir: isveren hakedisi ALACAK,
    taseron hakedisi BORCTUR (`projects/costs.py:220` onu MALIYET sayar).
    Burada bir sayi uretmek, ayni ada sahip UCUNCU bir kume yaratirdi.
    ⛔ Once URUN KARARI: hangi aile, taslak dahil mi, brut mu?
    """
    return MetricPlaceholder(pending_module=_PORTFOLIO_MODULE)


def _receivables() -> MetricPlaceholder:
    """(C) TUZAK — "Tahsil Edilecek" (mockup `:234`). 🔴 IZIN KAPISI ENGELI.

    Veri tarafi HAZIR ve tam eslesir: `invoicing/summary.py:80` hem tutari hem
    "3 fatura beklemede" sayacini TEK sorgulu bir okumadan uretir.

    BAGLANMADI, cunku iki ucun KAPISI FARKLIDIR ve baglamak yetki genislemesi
    olurdu:
      * `GET /dashboard/summary` -> `require_permission("dashboard", view)`
      * `GET /invoices/summary`  -> `require_permission("invoicing", view)`
    Tohumlanmis matriste (`roles/seed_data.py:175,195`) `hr_manager` icin
    `dashboard = _LIM` ama `invoicing = _N`; `site_chief` ve `field_engineer`
    icin de `invoicing = _N`. Yani bu kart baglanirsa fatura goremeyen UC ROL
    sirketin alacak toplamini gosterge panelinde OKUR.

    🔑 KARSITI `pending_approvals`tir ve fark YAPISALDIR: onay kutusunun AYRI
    bir yetki kapisi YOKTUR ve olmamalidir (`approvals/router.py:57`), cunku
    donen kume zaten "bu adim SANA dustu" olgusuyla sinirlidir.

    ⚠️ IKINCI kusur (kapi acilsa bile kalir): `receivable.amount` BRUT
    `Invoice.total`dir, kismi tahsilatin NETI DEGIL — %90'i tahsil edilmis bir
    fatura tutarinin tamamiyla katilir. "Tahsil EDILECEK" basligi altinda bu
    sayi sistematik olarak fazla gosterir.
    """
    return MetricPlaceholder(pending_module=_RECEIVABLES_MODULE)


def _average_margin() -> MetricPlaceholder:
    """(C) TUZAK — "Ortalama Marj" (mockup `:246`). 🔴 ANAHTAR DA YANLIS.

    ANAHTAR HATASI: `_MARGIN_MODULE = "progress_payments"` ama marjin gercek
    kaynagi `projects/costs.py:112` `_margin_pct`tir ve toplu okuyucusu
    `projects/cost_cards.py:174` `by_projects` (en fazla 3 sorgu) — yani anahtar
    HIC ILGISI OLMAYAN bir modulu isaret ediyor. String DEGISTIRILMEDI: deger
    yanitin govdesindedir ve frontend ona dallanabilir; duzeltmesi F-OK ile
    birlikte gitmelidir (kirici olabilir).

    ORTALAMA TANIMSIZ, ve bu bir isim tartismasi degil: `margin_pct` **taahhut
    projelerinde YAPISAL OLARAK `None`**dur — `card_projection`
    (`projects/costs.py:413-426`) taahhut dali TASIMAZ, cunku E4 taahhut
    kartinda marj alani hic BASILMAZ. Butcesi girilmemis ya da geliri 0 olan
    projeler de `None` doner. Taahhut agirlikli bir portfoyde "ortalama",
    projelerin SESSIZ BIR AZINLIGI uzerinden hesaplanirdi.
    🔴 K2 tam burada isirir: `None`lari 0 saymak uydurma bir sifirdir
    (`cost_summary.py:106-108` bunu ayrica yasaklar), elemek ise "hicbir
    projenin marji yok" hâli ile "ortalama %0" hâlini AYNI sayiya cevirir.
    ⛔ Once URUN KARARI: agirliksiz ortalama mi, `Σkâr / Σgelir` mi; `None`
    projeler paydada mi?
    """
    return MetricPlaceholder(pending_module=_MARGIN_MODULE)


def _risks() -> ListPlaceholder:
    """(C) TUZAK — "Risk & Uyarilar" (mockup `:334-351`). UC AYRI kusur.

    1. 🔴 ZARF YETERSIZ. Mockup'in UC satiri ikiser metin + bir SIDDET rengi
       tasir ("Stok kritik seviyede" / "Liman Altyapi – Demir eksikligi");
       `items: list[str]` bir metin tasir. Ustelik ucuncu satir
       ("Hedef asildi", yesil) bir risk DEGIL, iyi haberdir — kart aslinda
       siddet etiketli bir UYARI AKISIDIR.
    2. 🔴 ANAHTAR KARTIN UCTE BIRINI KAPSAR. `inventory` yalnizca ilk satiri
       besler; digerleri hakedis gecikmesi ve takvimdir. Stogu tek basina
       baglamak kartin ADINI kismen yalan yapardi.
    3. 🔴 IZIN KAPISI — `_receivables` ile AYNI engel: matriste `hr_manager`
       ve `accounting` icin `inventory = _N` (`roles/seed_data.py:191`) ama
       ikisi de gosterge panelini acabiliyor.

    ⚠️ K2 AYRICA ISIRIR: stok durumu `min_stock`tan turer ve o kolon
    NULLABLE'dir (`inventory/models.py:119`) — esigi girilmemis kalem HICBIR
    kovaya dusmez. Yani `items=[]` hem "risk yok" hem "risk BILINMIYOR"
    demeye devam ederdi; kart baglanmis gorunur, gercek risk gorunmezdi.
    """
    return ListPlaceholder(pending_module=_RISKS_MODULE)


async def build_summary(session: AsyncSession, user: User) -> DashboardSummaryResponse:
    """Gosterge paneli ozeti. Projeler + ONAY ROZETI gercek, dort kart bos durum."""
    projects = await list_projects_for_user(session, user.id)
    role = await session.get(Role, user.role_id)

    return DashboardSummaryResponse(
        role_name=role.name if role is not None else "",
        # Spec §5.5: taslaklar aktif proje sayacına GİRMEZ — status active AND NOT is_draft.
        active_project_count=sum(
            1 for p in projects if p.status is ProjectStatus.active and not p.is_draft
        ),
        projects=[DashboardProjectCard.model_validate(p) for p in projects],
        portfolio=_portfolio(),
        receivables=_receivables(),
        average_margin=_average_margin(),
        pending_approvals=await _pending_approvals(session, user),
        risks=_risks(),
    )
