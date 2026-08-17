"""IK3-RATE-FIX İŞ 2 — İKİ KATMAN EŞİTLİĞİ: migration zinciri ↔
`payroll/rate_seed_data.PAYROLL_RATES_2026`.

🔴 **NEDEN BU DOSYA VAR.** 2026 oran tohumu iki migration'ın BİLEŞKESİDİR:
`c5d6e7f8a9b0` (İK-3 çekirdeği) dört satırı basar, `f6a7b8c9d0e1`
(IK3-RATE-FIX) `short_work_pct`i KK-5 gereği `1`den `0`a çeker. Uygulama
katmanının doğruluk kaynağı (`rate_seed_data.PAYROLL_RATES_2026`) bu bileşkenin
sonucunu iddia eder. İki katman sessizce ayrışırsa canlıdaki oran ile ekibin
"doğru" sandığı oran farklı olur ve **hiçbir mevcut test bunu görmez**:
`test_payroll_migration.py` yalnız `c5d6e7f8a9b0`daki ARA durumu ölçer (o
revizyona AÇIKÇA çıkar, `short_work_pct = 1` orada hâlâ doğrudur), servis
testleri ise oranlarını kendi fixture'ından kurar.

## 🔴🔴 SAHTE YEŞİLE BAĞIŞIKLIK — bu dosyanın asıl tasarım kararı

Bu boşluğu kapatmanın en akla yatkın şekli **YANLIŞTIR**: "DB'yi oku,
`PAYROLL_RATES_2026` ile karşılaştır" diyen bir test normal suite'te
`tests/conftest.py:59-60`in `Base.metadata.create_all` ile kurduğu şemaya
bakar — orada alembic HİÇ KOŞMAZ, `payroll_rates` tablosu **BOŞTUR**. Satır
üzerinde dönen bir döngü sıfır kez döner ve test **vacuous** olarak yeşil
yanar: "aynı yeşil iki anlam taşır — maskeleme mi, boşluk mu" kanonu.

Bu yüzden eşitlik İKİ AYRI şekilde ölçülür ve **hiçbiri conftest'in DB'sine
bakmaz**:

* **(A) SEMBOLİK BİLEŞKE** (`test_iki_katman_sembolik_esitlik`) — DB'ye HİÇ
  dokunmaz. İki migration modülü dosyadan yüklenir, tohum + düzeltme
  Python'da bileştirilir ve sabitle karşılaştırılır. Bağışıktır çünkü ölçtüğü
  şeyin DB ile ilgisi yoktur; boş tablo onu yeşile boyayamaz.
* **(B) GERÇEK ZİNCİR** (`test_ik3_rate_fix_migration.py`) — kendi TEK
  KULLANIMLIK veritabanını açar, gerçek `alembic upgrade` koşturur ve aynı
  sabitle karşılaştırır. Ayrıca satır sayısını AÇIKÇA `== 4` diye iddia eder,
  böylece boş tablo orada da sessizce geçemez.

(A) hızlıdır ve her koşuda çalışır; (B) (A)'nın sembolik bileşkesinin gerçek
PostgreSQL davranışıyla örtüştüğünü kanıtlar. Biri olmadan öteki eksiktir.

### Bağışıklık ÖLÇÜLDÜ (mutasyon turu)

`rate_seed_data`daki KK-5 değeri `0`dan `1`e bozulduğunda: naif "DB'yi oku"
şekli **1 passed** (sahte yeşil), (A) **2 failed**. Aynı koşullar, aynı boş
tablo — fark yalnızca ölçüm şeklinden geliyor.

### 🔴 (A)'nın ÖLÇÜLMÜŞ SINIRI — (B) BU YÜZDEN SİLİNEMEZ

(A) migration'ın SABİTLERİNİ okur, `UPDATE` cümlesini DEĞİL. Mutasyon turunda
ölçüldü: `upgrade()`ten `UPDATE` ifadesi TAMAMEN silinip sabitler yerinde
bırakıldığında (A) **yeşil kalır**, (B) **4 failed** verir. Yani iki katman
farklı kusur sınıflarını yakalar:

* (A) → sabitlerin/kararın ayrışması ("biri 0 dedi, öteki 1"),
* (B) → SQL'in sabitlerle örtüşmemesi ("0 yazıyor ama yazmıyor").

🔴 **Birini "öteki zaten kapsıyor" diye silme.** Kapsamıyor; ölçüldü.

## Migration modülleri nasıl yüklenir

`alembic/versions/` bir PAKET DEĞİLDİR (`__init__.py` yok, dosya adları rakamla
başlar → Python tanımlayıcısı değil). Düz `import` çalışmaz; dosyadan
`importlib.util.spec_from_file_location` ile elle yüklenir (MU-SEED
`test_mu_seed_iki_katman_esitligi.py` emsali). Bu yükleme **DB'ye BAĞLANMAZ**:
her iki dosya da modül düzeyinde yalnız sabit ve `sa.Enum(...)`/`sa.text(...)`
tanımlar; `op.get_bind()` yalnız `upgrade()`/`downgrade()` GÖVDESİNDE çağrılır
ve bu dosya o fonksiyonları hiç ÇAĞIRMAZ.
"""

import importlib.util
from decimal import Decimal
from pathlib import Path
from types import ModuleType

from app.modules.payroll.rate_seed_data import (
    PAYROLL_RATES_2026,
    RATE_COLUMNS,
    RATE_SEED_YEAR,
)

_VERSIONS_DIR = Path(__file__).parents[3] / "alembic" / "versions"
_SEED_MIGRATION = _VERSIONS_DIR / "c5d6e7f8a9b0_ik3_bordro_cekirdegi.py"
_FIX_MIGRATION = _VERSIONS_DIR / "f6a7b8c9d0e1_ik3_rate_fix_kisa_calisma_sifir.py"


def _load(path: Path, adi: str) -> ModuleType:
    """Migration dosyasını modül olarak yükler — DB'ye BAĞLANMADAN."""
    assert path.is_file(), f"migration dosyası yok: {path}"
    spec = importlib.util.spec_from_file_location(adi, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _zincirin_sonucu() -> dict[str, dict[str, Decimal]]:
    """İki migration'ı SEMBOLİK olarak bileştirir: tohum + KK-5 düzeltmesi.

    Gerçek `UPDATE`in aynısını Python'da yapar — `= SEEDED` koşulu DÂHİL, ki
    koşul migration'dan kaldırılırsa (ya da değeri değişirse) bu bileşke de
    değişsin ve mutasyon KIRMIZI versin.
    """
    seed = _load(_SEED_MIGRATION, "ik3_seed_migration")
    fix = _load(_FIX_MIGRATION, "ik3_rate_fix_migration")

    assert fix.TARGET_YEAR == seed.RATE_SEED_YEAR, (
        f"düzeltme {fix.TARGET_YEAR} yılını hedefliyor ama tohum "
        f"{seed.RATE_SEED_YEAR} yılını basıyor — düzeltme boşa düşer"
    )

    sonuc: dict[str, dict[str, Decimal]] = {}
    for source, oranlar in seed.RATE_SEED_2026.items():
        satir = {alan: Decimal(deger) for alan, deger in oranlar.items()}
        if satir["short_work_pct"] == fix.SEEDED_SHORT_WORK_PCT:
            satir["short_work_pct"] = fix.CORRECTED_SHORT_WORK_PCT
        sonuc[source] = satir
    return sonuc


def test_iki_katman_sembolik_esitlik():
    """🔴 (A) Migration zincirinin bileşkesi = uygulama katmanı sabiti.

    DB'ye HİÇ dokunmaz → normal suite'in boş tablosu bu testi yeşile boyayamaz.
    """
    zincir = _zincirin_sonucu()

    assert set(zincir) == set(PAYROLL_RATES_2026), (
        "migration zinciri ile `rate_seed_data` FARKLI personel tipleri "
        f"kapsıyor: zincir={sorted(zincir)} sabit={sorted(PAYROLL_RATES_2026)}"
    )
    for source, beklenen in PAYROLL_RATES_2026.items():
        assert set(beklenen) == set(RATE_COLUMNS), f"{source}: oran sütunları eksik/fazla"
        for alan in RATE_COLUMNS:
            assert zincir[source][alan] == beklenen[alan], (
                f"{source}.{alan}: migration zinciri {zincir[source][alan]} üretiyor, "
                f"`rate_seed_data` {beklenen[alan]} diyor — iki katman AYRIŞTI"
            )


def test_kk5_kisa_calisma_orani_sifirdir():
    """🔑 **KK-5 — kullanıcı kararı, 2026-08-16: kısa çalışma ödeneği YOK.**

    🔴 **BU TESTİ "eksik veri" sanıp 1 yazarak DÜZELTME.** Değer karardır.
    `c5d6e7f8a9b0:102` mockup etiketine (SGK 81 "Kısa Çalışma Ödeneği (%1)")
    bakarak `1` basmıştı; mevzuatta ayrı bir %1 kısa çalışma primi YOKTUR.

    Kararın yalnız "satırı basmamakla" uygulanamayacağı ölçüldü:
    `short_work_total`, `sgk.py`de `_RATE_FIELDS[4:]` üzerinden
    `employer_burden_total`ın İÇİNDE taşınır ve `summary.py`nin maliyet
    tabanını brütün %1'i kadar şişirir. Tek doğru çözüm oranın `0` olmasıdır.
    """
    for source, oranlar in PAYROLL_RATES_2026.items():
        assert oranlar["short_work_pct"] == Decimal("0"), (
            f"{source}.short_work_pct = {oranlar['short_work_pct']} — KK-5 ihlali"
        )
    # Zincir de aynısını üretmeli: sabiti 0 yapıp migration'ı düzeltmeyi
    # unutmak bu satırda yakalanır.
    for source, oranlar in _zincirin_sonucu().items():
        assert oranlar["short_work_pct"] == Decimal("0"), (
            f"migration zinciri {source} için {oranlar['short_work_pct']} üretiyor — KK-5 ihlali"
        )


def test_general_kasten_disaridadir():
    """İŞ 3 — `general` bordro tipi DEĞİLDİR; oran satırı YOKTUR.

    Onaylı karardır (ŞEF KARARI 2), kusur değil: `site_diary/models.py:66`
    "`general` … bu değerin oran satırı yoktur" · `tests/.../conftest.py:61`
    "`general` KASTEN YOKTUR" · `test_payroll_compute_service.py:130` bunu
    ayrıca test eder. Buraya `general` eklenirse o karar sessizce ters döner.
    """
    assert "general" not in PAYROLL_RATES_2026
    assert set(PAYROLL_RATES_2026) == {"company", "subcontractor", "freelance", "intern"}


def test_yalniz_2026_kapsanir():
    """2027 KASTEN yoktur: oran tablosu yıllıktır, mevzuat icat edilmez.

    (Oran giren ekranın yokluğu AYRI bir dilimdir — bu sabit onu çözmez.)
    """
    assert RATE_SEED_YEAR == 2026
