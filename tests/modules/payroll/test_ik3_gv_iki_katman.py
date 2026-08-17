"""IK3-GV — İKİ KATMAN EŞİTLİĞİ (A): migration sabitleri ↔ `tax_bracket_seed_data`.

`test_ik3_rate_fix_iki_katman.py`nin doğrudan emsalidir ve aynı ölçülmüş
gerekçeyi taşır.

## 🔴🔴 SAHTE YEŞİLE BAĞIŞIKLIK — bu dosyanın asıl tasarım kararı

Bu boşluğu kapatmanın en akla yatkın şekli **YANLIŞTIR**: "DB'yi oku,
`TAX_BRACKETS_2026_WAGE` ile karşılaştır" diyen bir test normal suite'te
`tests/conftest.py:59-60`in `Base.metadata.create_all` ile kurduğu şemaya
bakar — orada alembic HİÇ KOŞMAZ, `payroll_tax_brackets` tablosu **BOŞTUR**
(dilimleri oraya `conftest.dilimler` fixture'ı koyar, migration DEĞİL). Satır
üzerinde dönen bir döngü sıfır kez döner ve test **vacuous** olarak yeşil
yanar: *"aynı yeşil iki anlam taşır"*.

Bu yüzden eşitlik İKİ AYRI şekilde ölçülür:

* **(A) SEMBOLİK** (bu dosya) — migration modülü dosyadan yüklenir, SABİTLERİ
  uygulama katmanının sabitleriyle karşılaştırılır. DB'ye HİÇ dokunmaz →
  boş tablo onu yeşile boyayamaz.
* **(B) GERÇEK ZİNCİR** (`test_ik3_gv_migration.py`) — kendi TEK KULLANIMLIK
  veritabanını açar, gerçek `alembic upgrade` koşturur, satır sayısını
  AÇIKÇA iddia eder.

🔴 **Birini "öteki zaten kapsıyor" diye SİLME.** IK3-RATE-FIX turunda ölçüldü:
(A) migration'ın SABİTLERİNİ okur, SQL'ini DEĞİL — `INSERT`/`UPDATE` gövdesi
tamamen silinse (A) YEŞİL kalır, (B) kırmızı verir. İki katman FARKLI kusur
sınıflarını yakalar: (A) "biri şunu, öteki bunu diyor", (B) "diyor ama
yazmıyor".

## Migration modülü nasıl yüklenir

`alembic/versions/` bir PAKET DEĞİLDİR; dosyadan `importlib` ile elle yüklenir.
Yükleme DB'ye BAĞLANMAZ: modül düzeyinde yalnız sabit ve `sa.Enum(...)` tanımı
vardır, `op.get_bind()` yalnız `upgrade()` GÖVDESİNDE çağrılır ve bu dosya o
fonksiyonu hiç ÇAĞIRMAZ.
"""

import importlib.util
from decimal import Decimal
from pathlib import Path
from types import ModuleType

from app.modules.payroll import income_tax
from app.modules.payroll.tax_bracket_seed_data import (
    MINIMUM_WAGE_GROSS_2026,
    TAX_BRACKET_SEED_YEAR,
    TAX_BRACKETS_2026_WAGE,
    WAGE_INCOME_KIND,
)

_VERSIONS_DIR = Path(__file__).parents[3] / "alembic" / "versions"
_GV_MIGRATION = _VERSIONS_DIR / "b3c4d5e6f7a8_ik3gv_dilimli_gelir_vergisi.py"


def _load(path: Path, adi: str) -> ModuleType:
    assert path.is_file(), f"migration dosyası yok: {path}"
    spec = importlib.util.spec_from_file_location(adi, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _migration() -> ModuleType:
    return _load(_GV_MIGRATION, "ik3gv_migration")


def test_A_tarife_iki_katmanda_AYNIDIR():
    """🔴 (A) Migration'ın tarife sabiti = uygulama katmanının sabiti.

    DB'ye HİÇ dokunmaz → normal suite'in boş tablosu bu testi yeşile boyayamaz.
    """
    mig = _migration()

    assert mig.TARGET_YEAR == TAX_BRACKET_SEED_YEAR
    assert mig.WAGE_INCOME_KIND == WAGE_INCOME_KIND
    assert Decimal(mig.MINIMUM_WAGE_GROSS_2026) == MINIMUM_WAGE_GROSS_2026

    zincir = tuple(
        (ordinal, Decimal(ub) if ub is not None else None, Decimal(rate))
        for ordinal, ub, rate in mig.TAX_BRACKETS_2026_WAGE
    )
    assert zincir == TAX_BRACKETS_2026_WAGE, (
        f"migration {zincir} basıyor, `tax_bracket_seed_data` {TAX_BRACKETS_2026_WAGE} "
        "diyor — İKİ KATMAN AYRIŞTI"
    )


def test_KK6_tarifesi_KULLANICI_KARARINDAKI_kumulatif_formulle_ORTUSUR():
    """🔴 KK-6'nın sabit terimleri BAĞIMSIZ bir doğrulamadır.

    Kullanıcı kararı dilimleri hem `(eşik, oran)` çifti hem KÜMÜLATİF FORMÜL
    olarak yazıyor (28.500 / 70.500 / 367.500 / 1.697.500). İkisi aynı sayıdan
    türemez: eşik/oran listesi yanlış girilseydi sabit terimler TUTMAZDI.
    Tablonun kendi içindeki bu artıklık burada kullanılır.
    """
    dilimler = tuple(
        income_tax.TaxBracket(ordinal=o, upper_bound=u, rate_pct=r)
        for o, u, r in TAX_BRACKETS_2026_WAGE
    )
    beklenen_sabitler = {
        Decimal("190000"): Decimal("28500"),
        Decimal("400000"): Decimal("70500"),
        Decimal("1500000"): Decimal("367500"),
        Decimal("5300000"): Decimal("1697500"),
    }
    for esik, sabit in beklenen_sabitler.items():
        assert income_tax.tax_for_base(esik, dilimler) == sabit, f"eşik {esik}"


def test_tarife_seti_KENDI_DOGRULAMASINDAN_gecer():
    """Tohumlanacak set `normalize_brackets`ten GEÇMELİDİR.

    Geçmeseydi migration bozuk bir set basar, `compute` her satırı
    `uncomputed`a düşürür ve bordro TAMAMEN durur — üstelik yalnız CANLIDA.
    """
    dilimler = tuple(
        income_tax.TaxBracket(ordinal=o, upper_bound=u, rate_pct=r)
        for o, u, r in TAX_BRACKETS_2026_WAGE
    )
    dogrulanmis = income_tax.normalize_brackets(dilimler)

    assert len(dogrulanmis) == 5
    assert dogrulanmis[-1].upper_bound is None  # son dilim "üstü"


def test_UCRET_DISI_tarife_BASILMAZ():
    """K5 — `income_kind` MODELLENİR ama yalnız `wage` TOHUMLANIR.

    Ücret dışı tarife 3. dilimden itibaren ayrışır (1.000.000 / 232.500 /
    1.737.500) ve bordroda KULLANILMAZ; uydurulmaz (WORKFLOW §3). Kolonun
    şimdi açılması geçmiş tohumun hangi tabloya ait olduğunu belirsiz
    bırakmamak içindir.
    """
    assert _migration().WAGE_INCOME_KIND == "wage"


def test_DILIMLI_REJIME_gecen_tipler_SABITTIR():
    """K3 — yalnız `company` ve `subcontractor` dilimli motora geçer.

    `freelance` (%20, GVK m.94 serbest meslek stopajı) ve `intern` (0) DÜZ oran
    rejiminde KALIR. Buraya `intern` eklenirse stajyerin "kesinti yok" kararı
    (bir VERİ) sessizce fail-closed bir `NULL`a dönüşür ve satırları
    `uncomputed`a düşerdi.
    """
    mig = _migration()
    assert set(mig.BRACKET_REGIME_SOURCES) == {"company", "subcontractor"}
    assert mig.SEEDED_INCOME_TAX_PCT == Decimal("10")


def test_kilitli_donem_kumesi_SERVISLE_AYNIDIR():
    """Migration'ın kilitli-dönem kümesi `service.LOCKED_PERIOD_STATUSES` ile aynı.

    Migration uygulama kodunu IMPORT ETMEZ (uygulanmış bir migration DONMUŞ
    olmalıdır — `a477fdf00fdf` kanonu), değer KOPYALANMIŞTIR. Kopyanın
    ayrışması, korkuluğun sessizce başka bir olguyu ölçmesi demek olurdu.
    """
    from app.modules.payroll.service import LOCKED_PERIOD_STATUSES

    assert set(_migration().LOCKED_PERIOD_STATUSES) == {
        durum.value for durum in LOCKED_PERIOD_STATUSES
    }
