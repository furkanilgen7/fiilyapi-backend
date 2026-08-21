"""Bilançonun sorgu çekirdeği (MT-1 T4) — `projedesign/Mali Tablo - Bilanço.dc.html`.

Mockup iki kart çizer (BL:42 ızgarası) ve her kart üç seviyelidir: **bölüm bandı
→ kalem → ara toplam**, sonda genel toplam. Toplam 13 kalem (4+2 aktif, 3+1+3
pasif) ve bu SAYI bağlayıcıdır — icat edilmiş bir 14. kalem tasarım otoritesini
aşardı. Kalem→hesap eşlemesi `statement_map.py`dedir (TEK KOPYA).

## 🔴 Dönem modeli NOKTA-ZAMANDIR — mizandan FARKLI

Mockup BL:37 üç ayrı **tek gün** sunuyor (`31 Temmuz 2026` / `30 Haziran 2026` /
`31 Aralık 2025`). Bilanço bir ANLIK GÖRÜNTÜDÜR:

    gövde          : entry_date <= as_of                       → KÜMÜLATİF NET
    Dönem Net Kârı : {as_of.year}-01-01 <= entry_date <= as_of → YILBAŞINDAN BUGÜNE
    Geçmiş Yıl K/Z : entry_date <  {as_of.year}-01-01          → ÖNCEKİ DÖNEMLER

🔴 **ÜÇÜNCÜ PENCERE ZORUNLUDUR ve ilk yazımda YOKTU (T7 final review bulgusu).**
Gövde `6xx`/`7xx`i dışlar, `Dönem Net Kârı` yalnız bu yılı alır; aradaki küme —
önceki yılların gelir/gider bakiyeleri — bir yere konulmazsa **sessizce
buharlaşır**. Üründe kapanış akışı YOKTUR (`models.py` "AÇILMAYANLAR"), yani
`6xx`/`7xx` hiçbir zaman `570`e kapanmaz ve bakiyeleri yıllar boyunca defterde
durur. Kusur bir uç durum değil TAKVİMİN KENDİSİDİR: 2026'da defter tutan bir
şirketin **2027'de çekilen HER bilançosu** geçen yılın kârı kadar dengesiz
çıkardı. Doğru yer `Geçmiş Yıllar Kârları`dır (BL:82) ve `57` grubunun GERÇEK
bakiyesini EZMEZ, ona EKLENİR.

🔴 **ÜÇ PENCERENİN de sınırları AYRI AYRI testlidir.** MU-2'nin T6 dersi
(`<` → `<=` mutasyonunu 31 testin hiçbiri görmemişti, çünkü hiçbiri SINIR
GÜNÜNÜ kullanmıyordu) bu dilimde iki kez ısırabilirdi. Bu yüzden
`trial_balance.py`ye EKLEME YAPILMADI: mizanın penceresi ÜÇLÜdür ve
`year_start`e çakılıdır, bilanço TEK kümülatif pencere ister; ayrıca mizan
`SIGN`/`balance_column()` KULLANMAZ (ham borç/alacak basar), bilanço ise işaret
çevirmek ZORUNDADIR.

## İşaret ve kontra

    etkin yön = (is_contra ? −1 : +1) × SIGN[account_type]
    katkı     = etkin yön × net

`SIGN` `balance.py`den İTHAL EDİLİR, yeniden yazılmaz. Doğru işaretlenmiş bir
defterde etkin yön, kalemin TARAFINA eşittir (aktif `+1`, pasif `−1`) ve sonuç
kalemin kendi tarafında POZİTİF çıkar (mockup'ın 13 satırının hepsi pozitiftir):
`320` Satıcılar `net = −2.184.000` iken `2.184.000` basar.

🔴 **`is_contra`nın kuralı `(-)` SON EKİ DEĞİLDİR** (T7 final review bulgusu):
bayrak, hesabın doğal bakiye yönü düştüğü kalemin tarafının TERSİ olduğunda
işaretlenir. `257 Birikmiş Amortismanlar (-)` `Pasif` türdedir (HP:154 — alacak
bakiyelidir) ama AKTİF tarafta bir kaleme düşer → **işaretlenir** ve
`Maddi Duran Varlıklar (net)` = 2.400.000 + 1.840.000 − 620.000 = **3.620.000**
olur (BL:57). Buna karşılık `501 Ödenmemiş Sermaye (-)` `equity` türdedir ve
PASİF tarafta kalır → **işaretlenmez**; borç bakiyesini `SIGN[equity] = −1`
zaten düşürür, kontra işaretlenirse iki kez çevrilir ve sermayeyi ARTIRIR.

Bayrak `257`de kaldırılırsa kalem **iki katı amortisman** kadar kayar ve
`is_balanced` FALSE olur — kusur GÖRÜNÜR kalır, sessizce yutulmaz.

## 🔴 `is_balanced` ÖLÇÜLÜR, `True` VARSAYILMAZ

🔴 **GEREKÇE TB6 T2'DE DEĞİŞTİ, SONUÇ DEĞİŞMEDİ.** Eskiden
`ck_journal_entries_posted_balanced` yalnız `posted`ı bağlardı ve dengesiz bir
`reversed` fiş DB'ye GİREBİLİYORDU; **o borç KAPANDI** —
`ck_journal_entries_posting_balanced` artık `POSTING_STATUSES`in TAMAMINI bağlar.
Gösterge yine de SÜS DEĞİLDİR: kısıt **BAŞLIK** toplamlarını bağlar, bilanço ise
`journal_lines`ı toplar (`balance.py`) — başlığı dengeli, satırları dengesiz bir
fiş HÂLÂ kurulabilir. Gösterge ayrıca `is_contra` veri hatalarını ve `59` grubu
gibi dışlanmış bakiyeleri de görünür kılar. Sabit `True` basan bir bilanço
sessizce yalan söylerdi.

## Saf takvim

`as_of` uçta ZORUNLUDUR; bu modül sunucunun "bugün"üne HİÇ ihtiyaç duymaz
(TB5'in yerel-takvim kusuru yapısal olarak imkânsız). `trial_balance.year_start`
İTHAL EDİLİR — ikinci bir `date(year, 1, 1)` yazımı, biri düzeltilip öteki
kalınca iki raporu ayrıştırırdı.

## N+1

Kaç hesap olursa olsun **TEK** sorgu: iki pencere koşullu `SUM(CASE WHEN …)`
ifadeleriyle TEK `GROUP BY`da toplanır. Ölçüm tahmine değil
`before_cursor_execute` sayacına dayanır.

Para her yerde `Decimal`dir; kayan nokta hiçbir aşamada devreye girmez ve uç
**YUVARLAMAZ** (MT-K2 — yuvarlama bir GÖSTERİM kararıdır).
"""

from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from sqlalchemy import ColumnElement, Select, case, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounting import statement_map
from app.modules.accounting.balance import SIGN, ZERO, posting_filter
from app.modules.accounting.models import ChartAccount, JournalEntry, JournalLine
from app.modules.accounting.reports_schemas import (
    BalanceSheetLine,
    BalanceSheetResponse,
    BalanceSheetSection,
    BalanceSheetSide,
)
from app.modules.accounting.trial_balance import year_start

__all__ = ["build_balance_sheet", "select_balance_sheet_rows"]


def _net() -> ColumnElement[Decimal]:
    """`SUM(debit − credit)` — dış `WHERE`ın penceresi (kümülatif `<= as_of`).

    `COALESCE` ŞARTTIR: `SUM()` satırsız kümede NULL döner (`balance.py`nin NULL
    yutması tuzağı).
    """
    return func.coalesce(func.sum(JournalLine.debit - JournalLine.credit), literal(ZERO))


def _kosullu_net(kosul: ColumnElement[bool]) -> ColumnElement[Decimal]:
    """`SUM(CASE WHEN kosul THEN debit − credit ELSE 0 END)` — İÇ pencere.

    `else_` AÇIKTIR: bırakılsaydı pencereye hiç satır düşmeyen bir hesapta
    `SUM()` NULL döner ve dıştaki `COALESCE`a bağımlılık artardı. İki katman da
    yerinde durur (`trial_balance._kosullu_toplam` ile aynı gerekçe).
    """
    return func.coalesce(
        func.sum(case((kosul, JournalLine.debit - JournalLine.credit), else_=literal(ZERO))),
        literal(ZERO),
    )


def select_balance_sheet_rows(as_of: date) -> Select:
    """Hesap başına İKİ pencere — **TEK** `GROUP BY`, hesap sayısından bağımsız.

    Dış `WHERE` zaten `entry_date <= as_of` ile sınırlıdır, dolayısıyla `net`
    kümülatif penceredir ve `ytd_net` onun İÇİNDE bir alt penceredir. İki ayrı
    sorgu koşulsaydı biri süzgeci alır öteki almaz ve `Dönem Net Kârı`
    gövdeyle AYRI bir defterden türerdi.

    `join` INNER'dır: hiç yevmiye satırı olmayan hesap burada kaybolur ve bu
    DOĞRUDUR — katkısı `0`dır, kaleme eklenecek bir şeyi yoktur. (Mizanın
    `include_empty` seçeneğinin bilançoda karşılığı YOKTUR: kalemler sabittir,
    hesaplar değil.)

    🔴 `as_of` GÜNÜ DÂHİLDİR (`<=`). `<` yazılsaydı o gün kesilen fiş bilançoda
    ertesi gün belirirdi ve kullanıcı sebebini anlayamazdı.
    """
    yil_basi = year_start(as_of.year)
    return (
        select(
            ChartAccount.code.label("code"),
            ChartAccount.account_type.label("account_type"),
            ChartAccount.is_contra.label("is_contra"),
            _net().label("net"),
            _kosullu_net(JournalEntry.entry_date >= yil_basi).label("ytd_net"),
        )
        .select_from(JournalLine)
        .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
        .join(ChartAccount, ChartAccount.id == JournalLine.account_id)
        .where(posting_filter(), JournalEntry.entry_date <= as_of)
        .group_by(ChartAccount.code, ChartAccount.account_type, ChartAccount.is_contra)
        .order_by(ChartAccount.code.asc())
    )


def _etkin_yon(kayit) -> int:  # noqa: ANN001
    """Hesabın ETKİN yönü: `(is_contra ? −1 : +1) × SIGN[account_type]`.

    🔴 **Kural tek cümledir:** `is_contra = True` ⟺ hesabın doğal bakiye yönü,
    düştüğü **kalemin tarafının TERSİDİR.** `(-)` son ekine bakan bir kural
    YANLIŞTIR ve `257` dışındaki her kontra hesapta işareti ters çevirir:

    | Hesap | Tür | Kalem tarafı | `is_contra` |
    |---|---|---|---|
    | `257 Birikmiş Amortismanlar (-)` | `liability` (alacak) | AKTİF | **True** |
    | `501 Ödenmemiş Sermaye (-)`      | `equity` (alacak)    | PASİF | **False** |
    | `580 Geçmiş Yıllar Zararları (-)`| `equity` (alacak)    | PASİF | **False** |

    `501`/`580` borç bakiyelidir ve `SIGN[equity] = −1` onları ZATEN negatife
    çevirir; kontra işaretlenirlerse iki kez çevrilir ve sermayeyi düşürecek
    yerde ARTIRIRLAR (T7 final review'de ölçüldü: `Sermaye` 6.000 yerine 14.000).

    🔴 `SIGN` `balance.py`den gelir ve orada BEŞ türün hepsi vardır; eksik bir
    tür `KeyError` ile GÜRÜLTÜLÜ patlar (SQL tarafındaki `sign_case()` NULL
    üretmesinin Python karşılığı — ikisi de sessiz `0` varsaymaz).
    """
    return (-1 if kayit["is_contra"] else 1) * SIGN[kayit["account_type"]]


def _katki(kayit) -> Decimal:  # noqa: ANN001
    """Hesabın kalemine yaptığı KATKI = etkin yön × ham `net`.

    Doğru işaretlenmiş bir defterde etkin yön, kalemin TARAFINA eşittir
    (aktif `+1`, pasif `−1`) ve `AKTİF TOPLAM − PASİF TOPLAM = Σ net` olur —
    dengeli defterde SIFIR. Yanlış işaretlenmiş bir hesap dengeyi kaydırır ve
    `is_balanced` bunu GÖRÜNÜR kılar (kusuru gizlemek yerine bildirmek
    bilinçli bir karardır).
    """
    return _etkin_yon(kayit) * kayit["net"]


def _bos_kalem(kalem: statement_map.StatementLine) -> BalanceSheetLine:
    """Hareketi olmayan kalem `0` basar, `null` DEĞİL (MT-K11) ve LİSTEDEN
    DÜŞMEZ: 13 kalem SABİTTİR, aksi hâlde ekranın satır sayısı veriye göre
    oynardı."""
    return BalanceSheetLine(
        key=kalem.key, label=kalem.label, amount=ZERO, account_codes=[], group_codes=[]
    )


def _taraf(
    yapi: statement_map.StatementSide,
    tutarlar: dict[str, Decimal],
    kodlar: dict[str, list[str]],
) -> BalanceSheetSide:
    """Bir tarafın bölüm/kalem/ara toplam ağacını kurar.

    Ara toplamlar ve genel toplam KALEMLERDEN toplanır, mockup'tan
    KOPYALANMAZ (K15: mockup'ın toplamları satırlarıyla çelişebilir ve bu bir
    SUNUM göstermeliğidir). Böylece "ara toplam ≠ bileşenleri" hâli yapısal
    olarak imkânsızdır.
    """
    bolumler: list[BalanceSheetSection] = []
    taraf_toplami = ZERO
    for bolum in yapi.sections:
        satirlar: list[BalanceSheetLine] = []
        ara_toplam = ZERO
        for kalem in bolum.lines:
            if kalem.key not in tutarlar:
                satirlar.append(_bos_kalem(kalem))
                continue
            tutar = tutarlar[kalem.key]
            hesap_kodlari = sorted(kodlar.get(kalem.key, []))
            satirlar.append(
                BalanceSheetLine(
                    key=kalem.key,
                    label=kalem.label,
                    amount=tutar,
                    account_codes=hesap_kodlari,
                    group_codes=sorted({statement_map.group_of(k) for k in hesap_kodlari}),
                )
            )
            ara_toplam += tutar
        bolumler.append(
            BalanceSheetSection(
                key=bolum.key,
                title=bolum.title,
                subtotal_label=bolum.subtotal_label,
                subtotal=ara_toplam,
                lines=satirlar,
            )
        )
        taraf_toplami += ara_toplam
    return BalanceSheetSide(
        key=yapi.key,
        title=yapi.title,
        total_label=yapi.total_label,
        total=taraf_toplami,
        sections=bolumler,
    )


def _dagit(kayitlar: Sequence) -> tuple[dict[str, Decimal], dict[str, list[str]]]:
    """Hesapları kalemlere dağıtır — 🔴 hiçbiri GÖRÜNMEZ olmaz.

    `statement_map` `None` döndüğünde hesap gövdeye girmez ve bu AÇIK bir
    karardır (gelir tablosu sınıfları · `59` kapanış grubu), sessiz bir düşme
    DEĞİL. Onun dışında her hesap bir kaleme düşer; haritada karşılığı olmayan
    gruplar (`8x`/`9x`) doğal bakiye yönlerine göre mevcut `Diğer …`
    kalemlerine gider ve kodları `account_codes`ta GÖRÜNÜR.
    """
    tutarlar: dict[str, Decimal] = {}
    kodlar: dict[str, list[str]] = {}
    for kayit in kayitlar:
        # 🔴 Yedek kalemin TARAFI ETKİN yönden okunur (`is_contra` DÂHİL), ham
        # `SIGN`dan DEĞİL: kontra işaretli bir nazım hesap yalnız `SIGN`a
        # bakılsaydı PASİF kaleme düşer ama katkısı `+net` olurdu ve denge iki
        # katı tutar kayardı — sebebi hiçbir kalemde görünmeden.
        kalem = statement_map.balance_sheet_line_for(
            kayit["code"], credit_natured=_etkin_yon(kayit) < 0
        )
        if kalem is None:
            continue
        tutarlar[kalem] = tutarlar.get(kalem, ZERO) + _katki(kayit)
        kodlar.setdefault(kalem, []).append(kayit["code"])
    return tutarlar, kodlar


async def build_balance_sheet(session: AsyncSession, *, as_of: date) -> BalanceSheetResponse:
    """Bilançonun tamamı — **TEK** sorgu, sayfalama YOK.

    `Dönem Net Kârı` kalemi hiçbir GRUPTAN gelmez: `statement_map.period_profit()`
    ile `6xx`/`7xx`ten TÜRETİLİR (MT-K3, TEK KOPYA — Gelir Tablosu dilimi aynı
    fonksiyonu İTHAL EDER). Pencere `ytd_net`tir, gövdenin kümülatif penceresi
    DEĞİL: geçmiş yılların sonucu `Geçmiş Yıllar Kârları` kalemine aittir.

    🔴 `59` grubu (`590`/`591`) gövdeye HİÇ girmez — çift sayım yasağı: kapanış
    fişi atılmış bir dönemde kâr hem `59` bakiyesinden hem `6xx`/`7xx`ten
    sayılırdı. Üründe kapanış akışı yoktur; `59` bakiyesi varsa `is_balanced`
    FALSE olur ve kullanıcı sebebini kalem kodlarından görebilir.
    """
    kayitlar = (await session.execute(select_balance_sheet_rows(as_of))).mappings().all()

    tutarlar, kodlar = _dagit(kayitlar)

    # 🔴 ÜÇÜNCÜ PENCERE — `entry_date < {as_of.year}-01-01` gelir/gider hareketleri.
    # Gövde `6xx`/`7xx`i dışlar, `Dönem Net Kârı` yalnız BU YILI alır; aradaki
    # küme bir yere KONULMAZSA sessizce buharlaşır ve `AKTİF ≠ PASİF` olur.
    # Kusur bir uç durum DEĞİL takvimin kendisidir: kapanış akışı olmadığı için
    # `6xx`/`7xx` yıllar boyunca defterde durur ve 2027'de çekilen HER bilanço
    # 2026'nın kârı kadar dengesiz çıkardı (T7 final review'de bulundu).
    # Doğru yer `Geçmiş Yıllar Kârları`dır (BL:82) — kapanış fişi atılmış olsaydı
    # `59` üzerinden zaten oraya taşınacaktı. `57` grubunun GERÇEK bakiyesini
    # EZMEZ, ona EKLENİR: kapanış yapan da yapmayan da aynı sayıyı görsün.
    tutarlar[statement_map.RETAINED_EARNINGS_LINE] = tutarlar.get(
        statement_map.RETAINED_EARNINGS_LINE, ZERO
    ) + statement_map.period_profit(
        {kayit["code"]: kayit["net"] - kayit["ytd_net"] for kayit in kayitlar}
    )

    tutarlar[statement_map.PERIOD_PROFIT_LINE] = statement_map.period_profit(
        {kayit["code"]: kayit["ytd_net"] for kayit in kayitlar}
    )

    aktif_yapi, pasif_yapi = statement_map.BALANCE_SHEET_SIDES
    aktif = _taraf(aktif_yapi, tutarlar, kodlar)
    pasif = _taraf(pasif_yapi, tutarlar, kodlar)

    return BalanceSheetResponse(
        as_of=as_of,
        # 🔴 ÖLÇÜLÜR, VARSAYILMAZ (modül docstring'i): dengesiz bir `reversed`
        # fiş DB'ye girebilir ve sabit `True` sessizce yalan söylerdi.
        is_balanced=aktif.total == pasif.total,
        assets=aktif,
        liabilities=pasif,
    )
