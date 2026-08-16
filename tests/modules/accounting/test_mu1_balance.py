"""MU-1 T3a — türetilmiş bakiyenin (K3) TEK KAYNAK davranışı.

Spec: `docs/superpowers/specs/2026-08-15-mu1-muhasebe-cekirdegi-design.md` §6.

    net(hesap) = COALESCE(Σ debit − Σ credit, 0)   [status ∈ POSTING_STATUSES]
    bakiye     = SIGN[account_type] * net           [aktif/gider +1, pasif/gelir −1]

NEDEN BU TESTLER: bakiye SAKLANMADIĞI için hiçbir kolon onu doğrulamaz —
formülün doğruluğunun tek kanıtı buradaki iddialardır. Dört sınıf kusur ölçülür:

1. 🔴 **NULL YUTMASI** — satırı olmayan hesapta `SUM()` **NULL** döner, `0`
   değil. `COALESCE` düşerse kart bakiye yerine BOŞ basar. Ayrı testi vardır
   (`test_satirsiz_hesapta_bakiye_SIFIRDIR_null_degil`).
2. 🔴 **`POSTING_STATUSES` = (`posted`, `reversed`)** — `draft` GİRMEZ ama
   `reversed` GİRER. Yalnız `posted` sayılsaydı stornolanmış bir fiş defterden
   düşer, storno ters bacaklarıyla eklenir ve net **−orijinal** çıkardı (çift
   ters kayıt). Bekçi: `test_storno_ile_orijinal_birlikte_NET_SIFIR_verir` +
   `test_reversed_fis_TEK_BASINA_bakiyeye_GIRER`.
3. 🔴 **İŞARET** — `SIGN` takas edilirse bakiye sessizce ters döner; kart yine
   bir sayı basar. Testler DÖRT türü de ayrı ayrı ve AYNI ham `net` üzerinde
   sınar, yani takas iki iddiayı birden kırar.
4. 🔴 **N+1** — 1 hesap ile 20 hesabın SORGU SAYISI `before_cursor_execute`
   sayacıyla KARŞILAŞTIRILIR; tahmine dayanmaz.

Kuruş hassasiyeti ayrıca sınanır: `Decimal` toplamları TAM çıkmalıdır.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounting import balance
from app.modules.accounting.models import ChartAccountType, JournalEntryStatus
from tests.conftest import test_engine


@contextmanager
def _sorgu_sayaci() -> Iterator[list[str]]:
    """Sürücüye giden HER ifadeyi toplar — N+1 iddiasının ÖLÇÜM aracı.

    `tests/modules/treasury/test_hz1_balance.py`deki `before_cursor_execute`
    deseninin birebir aynısı.
    """
    ifadeler: list[str] = []

    def kaydet(conn, cursor, statement, parameters, context, executemany) -> None:  # noqa: ANN001
        ifadeler.append(" ".join(statement.split()))

    event.listen(test_engine.sync_engine, "before_cursor_execute", kaydet)
    try:
        yield ifadeler
    finally:
        event.remove(test_engine.sync_engine, "before_cursor_execute", kaydet)


# --------------------------------------------------------------------------- #
# 1. 🔴 NULL yutması — `COALESCE` bekçisi
# --------------------------------------------------------------------------- #


async def test_satirsiz_hesapta_bakiye_SIFIRDIR_null_degil(
    seeded_db: AsyncSession, hesap_fabrikasi
) -> None:
    """🔴 Yevmiye satırı olmayan hesapta `SUM()` **NULL** döner, 0 DEĞİL.

    `COALESCE` düşürülürse bu iddia `None == Decimal("0")` olur ve kırmızıya
    döner. Yeni açılan HER hesap bu hâldedir, yani kusur ekranın tamamını
    boşaltırdı.
    """
    hesap = await hesap_fabrikasi("100", account_type=ChartAccountType.asset)

    bakiyeler = await balance.balances_for(seeded_db, [hesap.id])

    assert bakiyeler[hesap.id] is not None
    assert bakiyeler[hesap.id] == Decimal("0")


async def test_satirsiz_hesap_toplu_selectte_de_sifir_doner(
    seeded_db: AsyncSession, hesap_fabrikasi
) -> None:
    """İkinci yol (`select_accounts_with_balance`) da `COALESCE` taşımalıdır —
    biri unutulsaydı liste ucu boş, detay ucu 0 basardı."""
    hesap = await hesap_fabrikasi("101")

    satirlar = (await seeded_db.execute(balance.select_accounts_with_balance())).all()

    bakiyeler = {satir[0].id: satir[1] for satir in satirlar}
    assert bakiyeler[hesap.id] == Decimal("0")


# --------------------------------------------------------------------------- #
# 2. 🔴 `POSTING_STATUSES` — draft GİRMEZ, reversed GİRER
# --------------------------------------------------------------------------- #


def test_posting_statuses_posted_ve_reversed_tasir_draft_tasimaz() -> None:
    """Kümenin KENDİSİ bir bekçidir: `reversed` çıkarılırsa burada ölür."""
    assert set(balance.POSTING_STATUSES) == {
        JournalEntryStatus.posted,
        JournalEntryStatus.reversed,
    }
    assert JournalEntryStatus.draft not in balance.POSTING_STATUSES


async def test_taslak_fis_bakiyeye_GIRMEZ(
    seeded_db: AsyncSession, hesap_fabrikasi, fis_fabrikasi
) -> None:
    """`draft` sayılsaydı yarım bırakılmış her fiş mizanı kirletirdi."""
    kasa = await hesap_fabrikasi("100", account_type=ChartAccountType.asset)
    satici = await hesap_fabrikasi("320", account_type=ChartAccountType.liability)
    await fis_fabrikasi(
        [(kasa, "1000.00", "0.00"), (satici, "0.00", "1000.00")],
        status=JournalEntryStatus.draft,
    )

    bakiyeler = await balance.balances_for(seeded_db, [kasa.id, satici.id])

    assert bakiyeler[kasa.id] == Decimal("0")
    assert bakiyeler[satici.id] == Decimal("0")


async def test_reversed_fis_TEK_BASINA_bakiyeye_GIRER(
    seeded_db: AsyncSession, hesap_fabrikasi, fis_fabrikasi
) -> None:
    """🔴 `reversed` DÜŞMEZ: kayıtlaştırılmış fiş defterden ÇIKMAZ.

    Yalnız `posted` sayılsaydı bu iddia `0` görür ve kırmızıya dönerdi.
    """
    kasa = await hesap_fabrikasi("100", account_type=ChartAccountType.asset)
    satici = await hesap_fabrikasi("320", account_type=ChartAccountType.liability)
    await fis_fabrikasi(
        [(kasa, "1000.00", "0.00"), (satici, "0.00", "1000.00")],
        status=JournalEntryStatus.reversed,
    )

    bakiyeler = await balance.balances_for(seeded_db, [kasa.id, satici.id])

    assert bakiyeler[kasa.id] == Decimal("1000.00")


async def test_storno_ile_orijinal_birlikte_NET_SIFIR_verir(
    seeded_db: AsyncSession, hesap_fabrikasi, fis_fabrikasi
) -> None:
    """🔴 SPEC §6a TABLOSUNUN BEKÇİSİ — bu dilimin en sinsi tuzağı.

    Orijinal `posted → reversed` damgalanır ve bacakları TAKAS edilmiş yeni bir
    storno fişi doğrudan `posted` doğar. İki fiş de sayılınca net TAM SIFIRDIR.

    | | Orijinal | Storno | Net |
    |---|---|---|---|
    | yalnız `posted` sayılsaydı | düşer | −X eklenir | **−X** ❌ |
    | `posted + reversed` sayılınca | +X kalır | −X eklenir | **0** ✅ |

    `POSTING_STATUSES`ten `reversed` çıkarılırsa iddia `-1000.00` görür.
    """
    kasa = await hesap_fabrikasi("100", account_type=ChartAccountType.asset)
    satici = await hesap_fabrikasi("320", account_type=ChartAccountType.liability)
    orijinal = await fis_fabrikasi(
        [(kasa, "1000.00", "0.00"), (satici, "0.00", "1000.00")],
        status=JournalEntryStatus.reversed,
    )
    await fis_fabrikasi(
        [(kasa, "0.00", "1000.00"), (satici, "1000.00", "0.00")],
        status=JournalEntryStatus.posted,
        reversal_of=orijinal,
    )

    bakiyeler = await balance.balances_for(seeded_db, [kasa.id, satici.id])

    assert bakiyeler[kasa.id] == Decimal("0")
    assert bakiyeler[satici.id] == Decimal("0")


# --------------------------------------------------------------------------- #
# 3. 🔴 İŞARET (K3) — dört tür, aynı ham `net`
# --------------------------------------------------------------------------- #


def test_sign_dort_turu_de_kapsar_ve_isaretleri_ayrisir() -> None:
    """`SIGN` bir SÖZLÜK bekçisidir: yeni bir üye açılırsa ya da bir işaret takas
    edilirse burada ölür.

    🔑 MT-1/KK-1 (kullanıcı kararı, 2026-08-16) beşinci üyeyi (`equity: -1`)
    ekledi — özkaynak ALACAK bakiyelidir, `liability`/`revenue` ile aynı işaret.
    🔴 Sözlüğün enum'la BİREBİR olması ayrıca zorunludur: `sign_case()`in
    `else_` dalı yoktur ve eksik üye **NULL** üretir
    (`test_mt1_ozkaynak_kontra_migration.py` bunu fiilen kurar)."""
    assert balance.SIGN == {
        ChartAccountType.asset: 1,
        ChartAccountType.expense: 1,
        ChartAccountType.liability: -1,
        ChartAccountType.revenue: -1,
        ChartAccountType.equity: -1,
    }


@pytest.mark.parametrize(
    ("account_type", "beklenen"),
    [
        (ChartAccountType.asset, Decimal("2184000.00")),
        (ChartAccountType.expense, Decimal("2184000.00")),
        (ChartAccountType.liability, Decimal("-2184000.00")),
        (ChartAccountType.revenue, Decimal("-2184000.00")),
    ],
)
async def test_borc_bakiyesinin_isareti_TURDEN_okunur(
    seeded_db: AsyncSession,
    hesap_fabrikasi,
    fis_fabrikasi,
    account_type: ChartAccountType,
    beklenen: Decimal,
) -> None:
    """AYNI ham `net` (+2.184.000) dört türde iki farklı işaret üretir.

    İşaretler takas edilirse dört iddianın DÖRDÜ birden kırmızıya döner; tek
    türle kurulmuş bir test takası göremezdi.
    """
    hesap = await hesap_fabrikasi("100", account_type=account_type)
    karsi = await hesap_fabrikasi("320", account_type=ChartAccountType.liability)
    await fis_fabrikasi([(hesap, "2184000.00", "0.00"), (karsi, "0.00", "2184000.00")])

    bakiyeler = await balance.balances_for(seeded_db, [hesap.id])

    assert bakiyeler[hesap.id] == beklenen


async def test_pasif_hesap_alacak_bakiyesini_POZITIF_gosterir(
    seeded_db: AsyncSession, hesap_fabrikasi, fis_fabrikasi
) -> None:
    """HP:164 `320 Satıcılar` → ekranda `2.184.000` (parantezsiz, POZİTİF).

    Ham `net` **−2.184.000**dır; işaret dönüşümü olmasaydı ekran eksi basardı.
    """
    satici = await hesap_fabrikasi("320", account_type=ChartAccountType.liability)
    kasa = await hesap_fabrikasi("100", account_type=ChartAccountType.asset)
    await fis_fabrikasi([(kasa, "2184000.00", "0.00"), (satici, "0.00", "2184000.00")])

    bakiyeler = await balance.balances_for(seeded_db, [satici.id, kasa.id])

    assert bakiyeler[satici.id] == Decimal("2184000.00")
    assert bakiyeler[kasa.id] == Decimal("2184000.00")


async def test_baska_hesabin_satiri_bakiyeye_KARISMAZ(
    seeded_db: AsyncSession, hesap_fabrikasi, fis_fabrikasi
) -> None:
    """Gruplama `account_id` üzerindedir; kaldırılsaydı tek toplam tüm hesaplara
    dağılır ve her kart aynı sayıyı basardı."""
    a = await hesap_fabrikasi("100")
    b = await hesap_fabrikasi("101")
    karsi = await hesap_fabrikasi("320", account_type=ChartAccountType.liability)
    await fis_fabrikasi([(a, "999.00", "0.00"), (karsi, "0.00", "999.00")])

    bakiyeler = await balance.balances_for(seeded_db, [a.id, b.id])

    assert bakiyeler[a.id] == Decimal("999.00")
    assert bakiyeler[b.id] == Decimal("0")


async def test_ayni_hesabin_borc_ve_alacagi_NETLESIR(
    seeded_db: AsyncSession, hesap_fabrikasi, fis_fabrikasi
) -> None:
    """`Σdebit − Σcredit` tek ifadedir; iki taraf ayrı okunsaydı biri unutulurdu."""
    kasa = await hesap_fabrikasi("100", account_type=ChartAccountType.asset)
    karsi = await hesap_fabrikasi("320", account_type=ChartAccountType.liability)
    await fis_fabrikasi([(kasa, "1000.00", "0.00"), (karsi, "0.00", "1000.00")])
    await fis_fabrikasi([(karsi, "300.00", "0.00"), (kasa, "0.00", "300.00")])

    bakiyeler = await balance.balances_for(seeded_db, [kasa.id, karsi.id])

    assert bakiyeler[kasa.id] == Decimal("700.00")
    assert bakiyeler[karsi.id] == Decimal("700.00")


async def test_kurus_toplamlari_TAM_cikar(
    seeded_db: AsyncSession, hesap_fabrikasi, fis_fabrikasi
) -> None:
    """`0.01` üç kez toplanınca TAM `0.03` olmalıdır.

    Kayan noktaya düşen bir uygulama `0.030000000000000002` üretir.
    """
    kasa = await hesap_fabrikasi("100")
    karsi = await hesap_fabrikasi("320", account_type=ChartAccountType.liability)
    for _ in range(3):
        await fis_fabrikasi([(kasa, "0.01", "0.00"), (karsi, "0.00", "0.01")])

    bakiyeler = await balance.balances_for(seeded_db, [kasa.id])

    assert bakiyeler[kasa.id] == Decimal("0.03")
    assert isinstance(bakiyeler[kasa.id], Decimal)


# --------------------------------------------------------------------------- #
# 4. 🔴 N+1 ÖLÇÜMÜ
# --------------------------------------------------------------------------- #


async def test_bir_hesap_ile_yirmi_hesabin_sorgu_sayisi_esittir(
    seeded_db: AsyncSession, hesap_fabrikasi, fis_fabrikasi
) -> None:
    """1 hesap X sorgu / 20 hesap X sorgu — SAYI EŞİT OLMALI.

    Hesap başına döngü kuran bir uygulama 20 hesapta 20 kat sorgu üretir;
    tahminle değil `before_cursor_execute` sayacıyla ölçülür.
    """
    karsi = await hesap_fabrikasi("320", account_type=ChartAccountType.liability)
    tek = await hesap_fabrikasi("100")
    await fis_fabrikasi([(tek, "5.00", "0.00"), (karsi, "0.00", "5.00")])

    with _sorgu_sayaci() as ifadeler:
        await balance.balances_for(seeded_db, [tek.id])
    tek_sorgu = len(ifadeler)

    coklu = [await hesap_fabrikasi(f"1{n:02d}.01") for n in range(20)]
    for hesap in coklu:
        await fis_fabrikasi([(hesap, "5.00", "0.00"), (karsi, "0.00", "5.00")])

    with _sorgu_sayaci() as ifadeler:
        bakiyeler = await balance.balances_for(seeded_db, [h.id for h in coklu])
    coklu_sorgu = len(ifadeler)

    assert tek_sorgu == coklu_sorgu, f"N+1: 1 hesap {tek_sorgu}, 20 hesap {coklu_sorgu} sorgu"
    assert tek_sorgu == 1, f"tek sorguluk API bekleniyordu, {tek_sorgu} ifade koştu"
    assert len(bakiyeler) == 20
    assert all(v == Decimal("5.00") for v in bakiyeler.values())


async def test_bos_hesap_listesi_HIC_sorgu_kosmaz(seeded_db: AsyncSession) -> None:
    """Boş liste `IN ()` üretmez; erken döner."""
    with _sorgu_sayaci() as ifadeler:
        bakiyeler = await balance.balances_for(seeded_db, [])

    assert bakiyeler == {}
    assert ifadeler == []


async def test_select_accounts_with_balance_TEK_sorguda_satir_ve_bakiye_doner(
    seeded_db: AsyncSession, hesap_fabrikasi, fis_fabrikasi
) -> None:
    """Liste ucu satırı ve bakiyeyi TEK `Select`te alır.

    Ayrı bir bakiye sorgusu koşulsaydı liste ucu N+1'e döner ve ikinci bir
    formül yazma baskısı doğardı.
    """
    kasa = await hesap_fabrikasi("100", account_type=ChartAccountType.asset)
    satici = await hesap_fabrikasi("320", account_type=ChartAccountType.liability)
    await fis_fabrikasi([(kasa, "40.00", "0.00"), (satici, "0.00", "40.00")])
    satirsiz = await hesap_fabrikasi("191")

    with _sorgu_sayaci() as ifadeler:
        sonuc = (await seeded_db.execute(balance.select_accounts_with_balance())).all()

    assert len(ifadeler) == 1, f"tek sorgu bekleniyordu, {len(ifadeler)} ifade koştu"
    bakiyeler = {satir[0].id: satir[1] for satir in sonuc}
    assert bakiyeler[kasa.id] == Decimal("40.00")
    assert bakiyeler[satici.id] == Decimal("40.00")
    assert bakiyeler[satirsiz.id] == Decimal("0")
