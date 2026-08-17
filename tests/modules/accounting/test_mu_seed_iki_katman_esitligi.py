"""MU-SEED T5 — İKİ KATMAN EŞİTLİĞİ: `chart_seed_data.CHART_ACCOUNTS` ↔
`e5f6a7b8c9d0.SEED_ACCOUNTS`.

🔴 **NEDEN BU DOSYA VAR.** K1 (`e5f6a7b8c9d0`) gereği migration, uygulama
kodunu (`chart_seed_data.py`) **kasıtlı olarak import ETMEZ**:

    "uygulanmış bir migration DONMUŞ olmalıdır, uygulama kodu zamanla
    değişir." (`a477fdf00fdf:23-26`)

Bu doğru bir karardır ama bedeli **iki kopyanın sessizce ayrışabilmesidir**:
`CHART_ACCOUNTS` (T1, servis katmanı) düzeltilip `SEED_ACCOUNTS` (T3, migration
katmanı — ya da tam tersi) unutulursa, canlıdaki tohum (migration koşar,
`Dockerfile:22`) ile testlerin ölçtüğü tohum (`tests/conftest.py` yalnız
`Base.metadata.create_all` yapar, migration'ı HİÇ koşturmaz → çoğu test
`seed_chart_of_accounts()` üzerinden servis katmanını ölçer) FARKLI olur ve
hiçbir mevcut test bunu görmez: `test_mu_seed_chart_of_accounts.py` yalnız
`CHART_ACCOUNTS`ı, `test_mu_seed_tdhp_migration.py` yalnız `SEED_ACCOUNTS`ı
(gerçek `alembic upgrade` üzerinden) ölçer — ikisini birbiriyle KARŞILAŞTIRAN
yoktur. Bu dosya o boşluğun TEK bekçisidir.

## Migration modülü nasıl yüklenir

`alembic/versions/` bir PAKET DEĞİLDİR (`__init__.py` yok, dosya adı Python
tanımlayıcısı da değildir — `e5f6a7b8c9d0_...` rakamla başlar). Bu yüzden düz
`import` çalışmaz; dosyadan `importlib.util.spec_from_file_location` ile
elle yüklenir. Bu yükleme DB'ye BAĞLANMAZ — migration dosyası modül
düzeyinde yalnız `SEED_ACCOUNTS` demetini ve `chart_of_accounts_table`
(bir `sa.table()`, gerçek bağlantı gerektirmez) tanımlar; `op.get_bind()`
yalnız `upgrade()`/`downgrade()` GÖVDESİNDE çağrılır ve bu dosya o
fonksiyonları hiç ÇAĞIRMAZ.

## Karşılaştırma biçimi

`ChartSeedAccount` alanları `(code, name, account_type.value, is_contra)`
demetine indirgenir — `SEED_ACCOUNTS`ın ham `tuple[str, str, str, bool]`
biçimiyle doğrudan karşılaştırılabilsin diye.
"""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

from app.modules.accounting.chart_seed_data import CHART_ACCOUNTS

_MIGRATION_PATH = (
    Path(__file__).parents[3] / "alembic" / "versions" / "e5f6a7b8c9d0_mu_seed_tdhp.py"
)


def _load_migration_module() -> ModuleType:
    """`alembic/versions/e5f6a7b8c9d0_mu_seed_tdhp.py`yi dosyadan yükler.

    🔴 Bu yükleme sırasında DB'ye BAĞLANILMAZ (yukarıdaki modül docstring'i) —
    yalnız modül düzeyindeki `SEED_ACCOUNTS` demeti ve `sa.table()` tanımı
    çalışır; `upgrade()`/`downgrade()` hiç ÇAĞRILMAZ.
    """
    assert _MIGRATION_PATH.is_file(), f"migration dosyası yok: {_MIGRATION_PATH}"
    spec = importlib.util.spec_from_file_location("mu_seed_tdhp_migration", _MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # standart idiom — göreli import'lar için gerekirdi
    spec.loader.exec_module(module)
    return module


_MIGRATION = _load_migration_module()
SEED_ACCOUNTS: tuple[tuple[str, str, str, bool], ...] = _MIGRATION.SEED_ACCOUNTS

#: Servis katmanını migration katmanının ham demet biçimine indirger —
#: `(code, name, account_type.value, is_contra)`.
_SERVICE_AS_TUPLES: tuple[tuple[str, str, str, bool], ...] = tuple(
    (row.code, row.name, row.account_type.value, row.is_contra) for row in CHART_ACCOUNTS
)

#: Sabit bekçi — T2/T3/T4 testleriyle AYNI sayılar, burada da BAĞIMSIZCA ölçülür.
BEKLENEN_SATIR = 316
BEKLENEN_KONTRA = 34


def test_migration_modulu_db_baglantisi_olmadan_yuklenebilir() -> None:
    """Yükleme yan etkisiz olmalı — bu dosyanın DB gerektirmediğinin kanıtı.

    `sys.modules`e giren yalnız bu testin kendi elle yüklediği modüldür;
    migration dosyası `import`la kirletici bir global durum bırakmaz.
    """
    assert "mu_seed_tdhp_migration" in sys.modules
    assert isinstance(SEED_ACCOUNTS, tuple)
    assert len(SEED_ACCOUNTS) > 0


def test_satir_sayisi_iki_katmanda_esit() -> None:
    """(a) — satır sayısı eşit. Sessiz bir ekleme/eksilme burada patlar."""
    assert len(CHART_ACCOUNTS) == len(SEED_ACCOUNTS), (
        f"servis katmanı {len(CHART_ACCOUNTS)} satır, migration katmanı "
        f"{len(SEED_ACCOUNTS)} satır — İKİ KATMAN AYRIŞMIŞ"
    )


def test_toplam_ve_kontra_sabitleri_iki_katmanda_ayri_ayri_olculur() -> None:
    """316 · 34 sabiti HER İKİ katmanda BAĞIMSIZ ölçülür (T2/T4 sabitleriyle aynı)."""
    assert len(CHART_ACCOUNTS) == BEKLENEN_SATIR, (
        f"servis katmanı {len(CHART_ACCOUNTS)} satır, {BEKLENEN_SATIR} bekleniyordu"
    )
    assert len(SEED_ACCOUNTS) == BEKLENEN_SATIR, (
        f"migration katmanı {len(SEED_ACCOUNTS)} satır, {BEKLENEN_SATIR} bekleniyordu"
    )

    servis_kontra = sum(1 for row in CHART_ACCOUNTS if row.is_contra)
    migration_kontra = sum(1 for _c, _n, _t, kontra in SEED_ACCOUNTS if kontra)
    assert servis_kontra == BEKLENEN_KONTRA, (
        f"servis katmanında {servis_kontra} kontra satır, {BEKLENEN_KONTRA} bekleniyordu"
    )
    assert migration_kontra == BEKLENEN_KONTRA, (
        f"migration katmanında {migration_kontra} kontra satır, {BEKLENEN_KONTRA} bekleniyordu"
    )


def test_kod_kumeleri_esit() -> None:
    """(b) — kod kümeleri eşit; fark varsa eksik/fazla kodlar mesajda listelenir."""
    servis_kodlar = {row.code for row in CHART_ACCOUNTS}
    migration_kodlar = {code for code, _n, _t, _k in SEED_ACCOUNTS}

    yalniz_serviste = sorted(servis_kodlar - migration_kodlar)
    yalniz_migrationda = sorted(migration_kodlar - servis_kodlar)

    assert not yalniz_serviste and not yalniz_migrationda, (
        "kod kümeleri ayrışmış — "
        f"yalnız servis katmanında: {yalniz_serviste or '(yok)'}; "
        f"yalnız migration katmanında: {yalniz_migrationda or '(yok)'}"
    )


def test_her_kodun_ad_tur_kontra_uclusu_esit() -> None:
    """(c) — her kod için `(ad, tür, kontra)` üçlüsü eşit.

    İlk uyuşmazlık KOD ve ALAN ADIYLA raporlanır — tek bir toplu `assert`
    "hangi kodda hangi alan" sorusuna cevap vermez.
    """
    servis_by_code = {row.code: row for row in CHART_ACCOUNTS}
    migration_by_code = {code: (name, tur, kontra) for code, name, tur, kontra in SEED_ACCOUNTS}

    ortak_kodlar = sorted(set(servis_by_code) & set(migration_by_code))
    assert ortak_kodlar, "iki katman arasında ortak kod bile yok"

    uyusmazliklar: list[str] = []
    for code in ortak_kodlar:
        servis_row = servis_by_code[code]
        migration_name, migration_type, migration_contra = migration_by_code[code]

        if servis_row.name != migration_name:
            uyusmazliklar.append(
                f"{code}.name: servis={servis_row.name!r} migration={migration_name!r}"
            )
        if servis_row.account_type.value != migration_type:
            uyusmazliklar.append(
                f"{code}.account_type: servis={servis_row.account_type.value!r} "
                f"migration={migration_type!r}"
            )
        if servis_row.is_contra != migration_contra:
            uyusmazliklar.append(
                f"{code}.is_contra: servis={servis_row.is_contra!r} migration={migration_contra!r}"
            )

    assert not uyusmazliklar, "alan uyuşmazlıkları:\n" + "\n".join(uyusmazliklar)


def test_sira_iki_katmanda_ayni() -> None:
    """(d) — sıra aynı. Alan içerikleri eşit olsa bile sıra kayarsa migration'ın
    ham SQL çıktısı (satır satır INSERT sırası) servis katmanından SAPAR."""
    servis_sira = [row.code for row in CHART_ACCOUNTS]
    migration_sira = [code for code, _n, _t, _k in SEED_ACCOUNTS]
    assert servis_sira == migration_sira, "kod sırası iki katmanda FARKLI"


def test_tam_demet_esitligi() -> None:
    """Toplayıcı iddia: yukarıdaki dört ayrı iddianın hepsi doğruysa zaten
    geçer, ama tek bir `assert a == b` olarak da doğrulanır — regresyon ağı."""
    assert _SERVICE_AS_TUPLES == SEED_ACCOUNTS
