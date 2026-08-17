"""Gelir Tablosunun sorgu çekirdeği (MT-2 T5) — mockup `Ekran 11 - Mali Tablo`.

Mockup GT:86-147 tek bir kart çizer ve üç seviyelidir: **bölüm bandı → kalem →
ara toplam**, sonda `DÖNEM KARI`. Toplam **2 bölüm · 6 kalem · 2 ara toplam ·
1 genel toplam** ve bu SAYI bağlayıcıdır (K1) — TDHP'nin `Brüt Satış Kârı` /
`Faaliyet Kârı` basamakları mockup'ta ÇİZİLMEMİŞTİR ve icat edilmezler
(bilanço 13 kalemde durdu, K15). Kalem→grup eşlemesi `statement_map.py`dedir
(TEK KOPYA, Bilanço ve Nakit Akışı ile paylaşılır).

## 🔴 `DÖNEM KARI` bu modülde HESAPLANMAZ — İTHAL EDİLİR

`statement_map.period_profit()` ZATEN VARDIR, canlıdadır ve docstring'i ikinci
bir kopyayı AÇIKÇA YASAKLAR. Bilanço'nun `Dönem Net Kârı` satırı (BL:83) ile bu
tablonun `DÖNEM KARI` satırı (GT:141) birebir aynı olmak ZORUNDADIR; iki kopya
kaçınılmaz olarak ayrışırdı ve hiçbir kolon farkı bunu ele vermezdi.

Bu modülün işi FORMÜL değil **SATIR KIRILIMIDIR**.

## Dönem modeli BİRİKİMLİ ARALIK — mizan/nakit akışıyla AYNI pencere

Mockup GT:90: `Ocak – Temmuz 2026`.

    {year}-01-01 <= entry_date <= month_end(year, month)

🔴 **Bilançonun `as_of` NOKTA-ZAMANI BURADA YANLIŞ OLURDU:** gelir tablosu bir
AKIŞ tablosudur, anlık görüntü değil; kümülatif `<= as_of` penceresi geçmiş
yılların hasılatını bu yılın cirosuna eklerdi. `year_start`/`month_end`
`trial_balance`ten İTHAL EDİLİR — ikinci bir ay sonu aritmetiği yazılsaydı biri
artık yılı kaçırırdı (`calendar.monthrange`).

## İşaret sözleşmesi

    gelir kalemi = Σ(alacak − borç)      (`60` alacak bakiyelidir → +)
    gider kalemi = Σ(borç − alacak)      (`71` borç bakiyelidir  → +)

Doğru işlenmiş bir defterde İKİSİ DE POZİTİFTİR (mockup'ın altı satırı da
pozitif) ve `Toplam Gelir − Toplam Gider` mockup aritmetiğiyle birebir çalışır.
🔴 `61 Satış İndirimleri (-)` borç bakiyelidir ve `İş Hasılatı` kalemine
NEGATİF katkı verir — indirim hasılatı DÜŞÜRÜR (K2), ayrı bir satır İCAT
EDİLMEZ.

🔴 **TÜR ve KONTRA OKUNMAZ** (`period_profit()` kanonu): yön ham borç/alacak
niceliğinden gelir. Yanlış TÜR işaretlenmiş bir hesap kâra yanlış yönde
girmez, yalnız kendi kaleminde görünür kalır.

## 🔴 K7 — gider kalemleri 7/A YANSITMA hesaplarını DIŞLAR

`711 Direkt İlk Madde ve Malzeme Yansıtma Hesabı` `revenue` türündedir (ALACAK
yönlü) ve kendi grubundadır (`71`). Kalem grup olarak toplansaydı `710` (borç)
ile `711` (alacak) BİRBİRİNİ GÖTÜRÜR ve `Malzeme Giderleri` **`0` basardı** —
kullanıcı 12.480.000 beklerken. Sekiz grupta birden olurdu.

🔴 **K7-b — ÇİFTİN BORÇ BACAĞI DA DIŞLANIR** (final review CRITICAL-1).
`700 Maliyet Muhasebesi Bağlantı Hesabı` ve `799 Üretim Maliyet Hesabı`
`expense` TÜRÜNDEDİR (borç yönlü) ve bir gider hesabı gibi GÖRÜNÜR — ama ikisi
de bir aktarım bacağıdır:

* `790` (gerçek gider) + `799` (transfer) **ikisi de grup `79`dadır** →
  `Malzeme Giderleri` aynı parayı **İKİ KAT** basardı;
* `700`/`701` çiftinde **iki bacak da sınıf 7'dedir** → `701` dışlanıp `700`
  sayılınca `Genel Giderler` **hiç var olmayan** bir gider basardı.

Karar: gider kalemleri aktarım çiftinin **HER İKİ** bacağını da dışlar → satır
**BRÜT** gideri gösterir. Netleşme `DÖNEM KARI`da, `period_profit()` içinde
olur ve o formül DEĞİŞMEZ — orada iki bacak zaten birbirini götürür, yani bu
bir **SATIR** kusuruydu, kâr kusuru değil.

🔴 **Sonucu bilinçli bir AYRIŞMADIR:** yansıtma fişi atılmış bir defterde
`total_revenue − total_expense ≠ period_profit`. Uç üçünü de döndürür ki fark
GÖRÜNÜR kalsın; tek bir "kâr" alanı basan bir uç, hangi tarafın doğru olduğunu
kullanıcıya sormadan seçerdi.

## Görünmezlik

`6x`/`7x` her grup açıkça haritalıdır; haritasız kalan `general_expenses`e
düşer, KAYBOLMAZ. `69` tek dışlamadır ve AÇIKTIR (K6) — `period_profit()` de
onu saymaz, yani para tablonun HİÇBİR yerinde iki kez görünmez.

## N+1

Kaç hesap olursa olsun **TEK** sorgu. Ölçüm tahmine değil `before_cursor_execute`
sayacına dayanır. Sayfalama YOKTUR (küme sabit: 6 kalem).

Para her yerde `Decimal`dir; uç **YUVARLAMAZ** (MT-K2 — yuvarlama bir GÖSTERİM
kararıdır, oran/marj/trend kolonları da öyle ve bu uçta YOKTUR).
"""

from collections.abc import Sequence
from decimal import Decimal

from sqlalchemy import ColumnElement, Select, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounting import statement_map
from app.modules.accounting.balance import ZERO, posting_filter
from app.modules.accounting.models import ChartAccount, JournalEntry, JournalLine
from app.modules.accounting.reports_schemas import (
    IncomeStatementLine,
    IncomeStatementResponse,
    IncomeStatementSection,
)
from app.modules.accounting.trial_balance import month_end, year_start

__all__ = ["build_income_statement", "select_income_statement_rows"]


def _sinif(kolon: ColumnElement[str]) -> ColumnElement[str]:
    """Hesap kodunun SINIFI (ilk hane), SQL tarafında.

    `cash_flow_statement._grup`ün kardeşidir. `codes.class_code()` Python
    tarafındadır ve SQL'e inemez.
    """
    return func.substr(kolon, 1, 1)


def select_income_statement_rows(year: int, month: int) -> Select:
    """Hesap başına `Σ(borç − alacak)` — **TEK** sorgu, yalnız SINIF 6/7.

    🔴 Sınıf süzgeci SQL'DEDİR ve bu bir fazlalık DEĞİLDİR: Python katmanı
    (`income_statement_line_for` → `None`) bilanço hesaplarını zaten elerdi ama
    sorgu ~200 hesabın TAMAMINI çekerdi. İki katman birbirini MASKELER (MT-1 T6
    kanonu), bu yüzden SQL katmanının KENDİ bekçisi vardır ve çekirdek `Select`e
    iner — yalnız uçtan ölçen bir test bu sınıfı GÖREMEZ.

    Pencere BİRİKİMLİDİR ve İKİ SINIRI DA KAPALIDIR (`>=` / `<=`): `<` yazılsaydı
    yıl başında ya da ayın son gününde kesilen fiş tablodan sessizce düşerdi
    (MU-2 T6'nın kaçırdığı kusur sınıfı).

    `join` INNER'dır: hiç yevmiye satırı olmayan hesap burada kaybolur ve bu
    DOĞRUDUR — katkısı `0`dır.
    """
    return (
        select(
            ChartAccount.code.label("code"),
            func.coalesce(func.sum(JournalLine.debit - JournalLine.credit), literal(ZERO)).label(
                "net"
            ),
        )
        .select_from(JournalLine)
        .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
        .join(ChartAccount, ChartAccount.id == JournalLine.account_id)
        .where(
            posting_filter(),
            JournalEntry.entry_date >= year_start(year),
            JournalEntry.entry_date <= month_end(year, month),
            _sinif(ChartAccount.code).in_(sorted(statement_map.INCOME_STATEMENT_CLASSES)),
        )
        .group_by(ChartAccount.code)
        .order_by(ChartAccount.code.asc())
    )


def _dagit(
    kayitlar: Sequence,
) -> tuple[dict[str, Decimal], dict[str, list[str]]]:
    """Hesapları kalemlere dağıtır — 🔴 K7 gider kalemlerinde yansıtmayı ELER.

    Katkı DAİMA `−net` (= `alacak − borç`) olarak birikir; işaret çevirimi
    `_bolumler`de, bölümün sözleşmesine göre yapılır. Burada çevrilseydi kalem
    anahtarından bölümü türetmek gerekir ve harita iki yerde okunurdu.
    """
    tutarlar: dict[str, Decimal] = {}
    kodlar: dict[str, list[str]] = {}
    for kayit in kayitlar:
        kod = kayit["code"]
        kalem = statement_map.income_statement_line_for(kod)
        # 🔴 Bu dal bugün yalnız `69` için (K6) çalışır: sorgunun `WHERE`ı
        # sınıf 1-5'i zaten eledi.
        # 🔴 ÖLÇÜLDÜ — iki katman burada ANLAMSAL OLARAK DENKTİR: SQL sınıf
        # süzgeci kaldırıldığında hiçbir test kırmızı olmadı (163/163 yeşil),
        # çünkü `income_statement_line_for` bilanço hesaplarına `None` döner ve
        # sonuç DEĞİŞMEZ. Yani bu dal bir DOĞRULUK bekçisi değildir; SQL
        # süzgecinin değeri PERFORMANSTIR (~200 hesap yerine yalnız 6x/7x).
        # Bekçisi de bu yüzden sonucu değil ÇEKİLEN SATIRLARI ölçer
        # (`test_SQL_katmani_YALNIZ_sinif_6_ve_7yi_CEKER`).
        if kalem is None:
            continue
        # 🔴 K7 + K7-b: maliyet AKTARIM hesabı (çiftin alacak bacağı `711` ya
        # da borç bacağı `700`/`799`) GİDER kaleminde ne tutara ne kod
        # listesine girer — girseydi satır ya `0` basar (`710`+`711`) ya İKİ
        # KAT basardı (`790`+`799`). `period_profit()` onları YİNE sayar ve
        # orada iki bacak birbirini götürür; netleşmenin yeri orasıdır.
        if statement_map.is_cost_reflection(kod):
            continue
        tutarlar[kalem] = tutarlar.get(kalem, ZERO) - kayit["net"]
        kodlar.setdefault(kalem, []).append(kod)
    return tutarlar, kodlar


def _bolumler(
    tutarlar: dict[str, Decimal], kodlar: dict[str, list[str]]
) -> tuple[list[IncomeStatementSection], Decimal, Decimal]:
    """İki bölümün ağacı + `Toplam Gelir` / `Toplam Gider`.

    🔴 İşaret bölümün ANAHTARINDAN okunur (`INCOME_STATEMENT_EXPENSE_SECTION`),
    SIRASINDAN (`sections[1]`) değil: üçüncü bir bölüm eklenirse dizinli bir
    yazım sessizce yanlış işaret basardı.

    Ara toplamlar KALEMLERDEN toplanır, mockup'tan KOPYALANMAZ (K15).
    """
    bolumler: list[IncomeStatementSection] = []
    toplamlar: list[Decimal] = []
    for bolum in statement_map.INCOME_STATEMENT_SECTIONS:
        gider_mi = bolum.key == statement_map.INCOME_STATEMENT_EXPENSE_SECTION
        satirlar: list[IncomeStatementLine] = []
        ara_toplam = ZERO
        for kalem in bolum.lines:
            # 🔴 Hareketsiz kalem `0` basar, `null` DEĞİL ve LİSTEDEN DÜŞMEZ:
            # 6 kalem SABİTTİR (K1), aksi hâlde ekranın satır sayısı veriye
            # göre oynardı. `account_codes` boş kalır ve `0`ın ANLAMINI ayırt
            # eder: kod listesi boşsa hiç hareket yok, doluysa hareketler
            # birbirini götürmüş demektir.
            ham = tutarlar.get(kalem.key, ZERO)
            tutar = -ham if gider_mi else ham
            satirlar.append(
                IncomeStatementLine(
                    key=kalem.key,
                    label=kalem.label,
                    amount=tutar,
                    account_codes=sorted(kodlar.get(kalem.key, [])),
                )
            )
            ara_toplam += tutar
        bolumler.append(
            IncomeStatementSection(
                key=bolum.key,
                title=bolum.title,
                subtotal_label=bolum.subtotal_label,
                subtotal=ara_toplam,
                lines=satirlar,
            )
        )
        toplamlar.append(ara_toplam)
    gelir, gider = toplamlar
    return bolumler, gelir, gider


async def build_income_statement(
    session: AsyncSession, *, year: int, month: int
) -> IncomeStatementResponse:
    """Gelir Tablosunun tamamı — **TEK** sorgu, sayfalama YOK.

    🔴 `period_profit` KALEMLERDEN TOPLANMAZ: `statement_map.period_profit()`
    İTHAL EDİLİR (MT-K3, TEK KOPYA) ve Bilanço'nun `Dönem Net Kârı` kalemi ile
    birebir aynı fonksiyondur. `total_revenue − total_expense` ise kalemlerden
    gelir; ikisi K7 yansıtma dışlaması yüzünden AYRIŞABİLİR ve fark bilinçli
    olarak GÖRÜNÜR bırakılır.

    🔴 `period_profit()` HAM kayıtlardan beslenir, `_dagit`in çıktısından
    DEĞİL: `_dagit` yansıtmaları eler ve o küme kâra girmek ZORUNDADIR.
    """
    kayitlar = (await session.execute(select_income_statement_rows(year, month))).mappings().all()

    tutarlar, kodlar = _dagit(kayitlar)
    bolumler, gelir, gider = _bolumler(tutarlar, kodlar)

    return IncomeStatementResponse(
        year=year,
        month=month,
        sections=bolumler,
        total_revenue=gelir,
        total_expense=gider,
        profit_label=statement_map.INCOME_STATEMENT_PROFIT_LABEL,
        period_profit=statement_map.period_profit(
            {kayit["code"]: kayit["net"] for kayit in kayitlar}
        ),
    )
