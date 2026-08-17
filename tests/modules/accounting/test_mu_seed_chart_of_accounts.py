"""MU-SEED T2 — `chart_seed_data`: TDHP tohum listesi + `seed_chart_of_accounts()`.

İki katman vardır ve bu dosya **ÖLÇÜLEBİLİR** olanı bekçiler:

* **Migration** (T3) canlıdaki gerçek mekanizmadır (`Dockerfile:22` açılışta
  `alembic upgrade head` koşar).
* **Servis tohumu** (`seed_chart_of_accounts`) o verinin ikizidir ve
  `tests/conftest.py:57-61` şemayı `Base.metadata.create_all` ile kurup
  `alembic upgrade` KOŞMADIĞI için, tek katmanlı bir migration normal suite'te
  tamamen bekçisiz kalırdı.

🔴 Tohum `lifespan`a BAĞLANMAZ: `lifespan` testlerde hiç koşmaz
(`conftest.py:106` `ASGITransport(app=app)`) ve hataları yutulur
(`main.py:61-66`) → tohum sessizce hiç yazılmamış olabilirdi.

Ölçülen kusur sınıfları:

1. **Üstüne yazma** — kullanıcı `100`ü kendi adıyla açtıysa tohum onu ezerse
   kullanıcı emeği yok olur (K6: `ON CONFLICT DO NOTHING`).
2. **Yedeğe düşme** — `statement_map`in `_UNMAPPED_LINES` / `_CASH_FLOW_FALLBACK`
   yedeğine düşen bir tohum hesabı, parasını "bir yere" koyar ama hangi kurala
   göre koyduğu YAZILI DEĞİLDİR (K3).
3. **Kontra işaretinin ters çevrilmesi** — `(-)` son ekinden türetilen bir kural
   `501`i kontra yapar ve `Sermaye` 6.000 yerine 14.000 basar (K4).
4. **Türü sınıftan türetme** — `621` gelir sayılır, kâr şişer (K5).
5. **Çift sayım** — kapanış hesabı `690`/`692` tohumlanırsa `period_profit()`
   dönem kârını İKİ KEZ sayar (İş A).
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounting.chart_seed_data import (
    CHART_ACCOUNTS,
    seed_chart_of_accounts,
)
from app.modules.accounting.models import ChartAccount, ChartAccountType
from app.modules.accounting.statement_map import (
    BALANCE_SHEET_GROUPS,
    CASH_FLOW_GROUPS,
    EXCLUDED_BALANCE_SHEET_GROUPS,
    INCOME_STATEMENT_CLASSES,
    group_of,
)

_BY_CODE = {row.code: row for row in CHART_ACCOUNTS}


async def _count(session: AsyncSession) -> int:
    return (await session.execute(select(func.count()).select_from(ChartAccount))).scalar_one()


# --------------------------------------------------------------------------- #
# K6 — İDEMPOTENS
# --------------------------------------------------------------------------- #


async def test_tohum_iki_kez_kosunca_satir_sayisi_degismez(db_session: AsyncSession) -> None:
    """K6: ikinci koşu `uq_chart_of_accounts_code`u ihlal edip patlamamalı.

    Bekçilik ettiği kusur: düz `INSERT` yazılsaydı migration'ı ikinci kez koşan
    ya da tohumu elle çağıran her yol `IntegrityError` ile ölürdü.
    """
    assert await _count(db_session) == 0

    await seed_chart_of_accounts(db_session)
    ilk = await _count(db_session)
    assert ilk == len(CHART_ACCOUNTS)

    await seed_chart_of_accounts(db_session)
    assert await _count(db_session) == ilk


async def test_tohum_kullanicinin_actigi_hesabin_uzerine_YAZMAZ(db_session: AsyncSession) -> None:
    """🔴 K6: `DO NOTHING` — `DO UPDATE` DEĞİL.

    Bekçilik ettiği kusur: upsert `DO UPDATE` olsaydı, kullanıcının `100`
    kartına verdiği ad/tür/kontra her açılışta (Dockerfile `alembic upgrade
    head`) sessizce TDHP varsayılanına geri dönerdi.
    """
    kullanicinin = ChartAccount(
        code="100",
        name="Benim Kasam",
        account_type=ChartAccountType.liability,
        is_contra=True,
    )
    db_session.add(kullanicinin)
    await db_session.flush()

    await seed_chart_of_accounts(db_session)

    korunan = (
        await db_session.execute(select(ChartAccount).where(ChartAccount.code == "100"))
    ).scalar_one()
    assert korunan.name == "Benim Kasam"
    assert korunan.account_type is ChartAccountType.liability
    assert korunan.is_contra is True

    # Diğer her satır yine de eklenmiş olmalı — çakışma tüm toplu INSERT'i
    # iptal etseydi tohum tek bir kullanıcı kaydı yüzünden hiç yazılmazdı.
    assert await _count(db_session) == len(CHART_ACCOUNTS)
    kasa_bankalar = (
        await db_session.execute(select(ChartAccount).where(ChartAccount.code == "102"))
    ).scalar_one()
    assert kasa_bankalar.name == "Bankalar"


# --------------------------------------------------------------------------- #
# K3 — HİÇBİR TOHUM HESABI `statement_map` YEDEĞİNE DÜŞMEZ
# --------------------------------------------------------------------------- #


def test_her_tohum_kodu_haritada_ACIK_anahtardir() -> None:
    """🔴 K3: `_UNMAPPED_LINES` / `_CASH_FLOW_FALLBACK` HİÇ devreye girmemeli.

    ⚠️ İddia ETİKET metnine göre yazılmaz: `other_current_assets`
    ("Diğer Dönen Varlıklar") kalemine düşmek MEŞRUDUR — mockup'ın kendi
    `191 İndirilecek KDV`i oraya düşer (`GROUP_SOURCE_NOTES:319`). Yasak olan
    haritada anahtarı OLMAYAN bir gruba düşmektir; o hâlde para "bir yere"
    konur ama hangi kurala göre konduğu hiçbir yerde YAZILI DEĞİLDİR.
    """
    yedege_dusenler = [
        row.code
        for row in CHART_ACCOUNTS
        if not (
            group_of(row.code) in BALANCE_SHEET_GROUPS
            or (
                group_of(row.code)[0] in INCOME_STATEMENT_CLASSES
                and group_of(row.code) in CASH_FLOW_GROUPS
            )
        )
    ]
    assert yedege_dusenler == []


def test_tohumda_dislanan_grup_ve_sinif_8_9_yoktur() -> None:
    """`59` (kapanış) ve sınıf `8`/`9` (serbest/nazım) tohumlanmaz."""
    assert [
        r.code for r in CHART_ACCOUNTS if group_of(r.code) in EXCLUDED_BALANCE_SHEET_GROUPS
    ] == []
    assert [r.code for r in CHART_ACCOUNTS if r.code[0] in {"8", "9"}] == []


def test_grup_69_tohumdan_CIKARILDI() -> None:
    """🔴 İş A bekçisi — kapanış aktarım hesabı çift sayım üretir.

    `period_profit()` sınıf 6/7'yi `Σ(alacak − borç)` ile sayar. `690`/`692` bir
    KAPANIŞ aktarım hesabıdır; fiş atılırsa dönem kârı İKİ KEZ sayılır.
    Üründe kapanış akışı YOKTUR (`statement_map.py:222`), dolayısıyla bu
    hesaplar zaten kullanılamaz — dâhil etmenin kazancı yok, sessiz para hatası
    riski var. `EXCLUDED_BALANCE_SHEET_GROUPS = {"59"}` ile aynı ailedendir.
    """
    for kod in ("69", "690", "691", "692"):
        assert kod not in _BY_CODE


def test_tohum_sayilari() -> None:
    """56 grup + 260 ana hesap = 316; kontra 34 (`691` kontra DEĞİLDİ)."""
    gruplar = [r for r in CHART_ACCOUNTS if len(r.code) == 2]
    ana_hesaplar = [r for r in CHART_ACCOUNTS if len(r.code) == 3]
    assert len(gruplar) == 56
    assert len(ana_hesaplar) == 260
    assert len(CHART_ACCOUNTS) == 316
    assert len([r for r in CHART_ACCOUNTS if r.is_contra]) == 34


# --------------------------------------------------------------------------- #
# K4 — KONTRA
# --------------------------------------------------------------------------- #


def test_k4_iki_kanonik_ornek() -> None:
    """🔴 İKİSİ DE ZORUNLU — kural `(-)` son ekinden TÜRETİLEMEZ.

    * `257 Birikmiş Amortismanlar (-)` → `liability` (alacak yönlü) ama AKTİF
      taraftaki `Maddi Duran Varlıklar (net)` kalemine düşer → taraf TERS →
      `is_contra=True`.
    * `501 Ödenmemiş Sermaye (-)` → `equity` + `is_contra=False`. PASİF tarafta
      kalır; borç bakiyesi `SIGN[equity] = −1` ile zaten DÜŞER.
      🔴 Ölçülmüş gerekçe: `501` kontra işaretlenirse `Sermaye` kalemi 6.000
      yerine **14.000** çıkıyor (T7 final review).

    Tek örnekle yazılsaydı test, "`(-)` varsa kontra" kuralını da geçirirdi.
    """
    assert _BY_CODE["257"].account_type is ChartAccountType.liability
    assert _BY_CODE["257"].is_contra is True

    assert _BY_CODE["501"].account_type is ChartAccountType.equity
    assert _BY_CODE["501"].is_contra is False


def test_k4_yapisal_kontra_bekcisi() -> None:
    """Her kontra satırı, doğal yönü düştüğü kalemin tarafının TERSİ olmalı.

    * kontra-AKTİF (sınıf 1-2, aktif tarafta alacak bakiyeli) → `liability`
    * kontra-PASİF (sınıf 3-4, pasif tarafta borç bakiyeli) → `asset`

    Sınıf 5/6/7'de kontra YOKTUR: 5'te `501`/`580` kanonik karşı örnektir,
    6/7 bilanço gövdesine hiç girmez ve `period_profit()` kontrayı okumaz.
    """
    for row in CHART_ACCOUNTS:
        if not row.is_contra:
            continue
        sinif = row.code[0]
        if sinif in {"1", "2"}:
            assert row.account_type is ChartAccountType.liability, row.code
        elif sinif in {"3", "4"}:
            assert row.account_type is ChartAccountType.asset, row.code
        else:
            raise AssertionError(f"sinif {sinif} kontra tasiyamaz: {row.code}")

    assert [r.code for r in CHART_ACCOUNTS if r.is_contra and r.code[0] in {"5", "6", "7"}] == []


# --------------------------------------------------------------------------- #
# K5 — SINIF 6'DA TÜR SINIFTAN TÜRETİLEMEZ
# --------------------------------------------------------------------------- #


def test_k5_tur_siniftan_turetilmez() -> None:
    """🔴 SINIF 6 hem geliri hem gideri taşır.

    `621 Satılan Ticari Mallar Maliyeti (-)` bir GİDERDİR; türü sınıftan
    türetilseydi gelir sayılır ve `period_profit()` kârı şişirirdi.
    Tür = DOĞAL BAKİYE YÖNÜ: borç yönlü → `expense`, alacak yönlü → `revenue`.
    """
    assert _BY_CODE["621"].account_type is ChartAccountType.expense
    assert _BY_CODE["600"].account_type is ChartAccountType.revenue
    assert _BY_CODE["730"].account_type is ChartAccountType.expense
    assert _BY_CODE["500"].account_type is ChartAccountType.equity


# --------------------------------------------------------------------------- #
# K2 — KAPSAM
# --------------------------------------------------------------------------- #


def test_k2_alt_hesap_yok_kodlar_tekil_ve_sirali() -> None:
    """Yalnız `NN` ve `NNN`; alt hesabı kullanıcı açar.

    Bekçilik ettiği kusur: migration ham SQL'dir ve servis kapısını atlar; bir
    alt hesap tohumlansaydı `_assert_parent_has_no_lines` kuralı delinir,
    üstündeki ana hesap sessizce fiş satırı kabul eder hâle gelirdi.
    """
    kodlar = [row.code for row in CHART_ACCOUNTS]
    assert all("." not in kod for kod in kodlar)
    assert all(kod.isdigit() and len(kod) in {2, 3} for kod in kodlar)
    assert len(set(kodlar)) == len(kodlar)
    assert kodlar == sorted(kodlar)
