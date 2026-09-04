"""🔴 FAT-HAK — fatura ↔ hakediş TUTAR kuralının SAF tarafı ve evren bekçileri.

Bu dosya kuralın YALNIZ karşılaştırma ayağını ölçer (`source_amount_matches`).
Kapının GERÇEKTEN kurulu olduğunu bu dosya SÖYLEYEMEZ — pür fonksiyon testi,
o fonksiyonun ÇAĞRISINI silen mutantı öldürmez (deponun "çağrı yeri de
mutanttır" kanonu). Çağrıların bekçileri uçtan koşan üç dosyadadır:

* `tests/progress_payments/test_fat_hak.py`
  (işveren ailesi · `send` · `mark-paid`)
* `tests/subcontractor_progress_payments/test_fat_hak.py`
  (taşeron ailesi · `POST /invoices` · `mark-paid`)

Buradaki değer SINIRLARDADIR: ±0,01 tolerans yalnız dört değerin (0,00 · 0,01 ·
0,02 ve işaretlileri) yan yana konmasıyla kilitlenir ve o dört değeri bir uç
testinde kurmak dört ayrı fatura + dört ayrı ödeme demektir.
"""

from decimal import Decimal

import pytest

from app.modules.invoicing.source_amounts import SOURCE_GROSS_MODELS
from app.modules.invoicing.validation import (
    SOURCE_AMOUNT_TOLERANCE,
    source_amount_blockers,
    source_amount_matches,
    source_amount_mismatch,
)
from app.modules.treasury.realized import SOURCE_DIRECTION

_BRUT = Decimal("233500.00")


# --------------------------------------------------------------------------- #
# SINIR — toleransın İKİ yönü de ölçülür
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "sapma",
    [Decimal("0.00"), Decimal("0.01"), Decimal("-0.01")],
    ids=["tam_esit", "arti_bir_kurus", "eksi_bir_kurus"],
)
def test_TOLERANS_ICINDEKI_fark_KABUL_EDILIR(sapma: Decimal) -> None:
    """🔴 `<=` yerine `<` yazan mutant YALNIZ ±0,01 satırlarında görünür."""
    assert source_amount_matches(_BRUT + sapma, _BRUT) is True
    assert source_amount_blockers(_BRUT + sapma, _BRUT) == []


@pytest.mark.parametrize(
    "sapma",
    [Decimal("0.02"), Decimal("-0.02")],
    ids=["arti_iki_kurus", "eksi_iki_kurus"],
)
def test_TOLERANS_DISINDAKI_fark_REDDEDILIR(sapma: Decimal) -> None:
    """🔴 `abs()`i düşüren mutant YALNIZ `-0,02` satırında görünür: mutlak değer
    olmadan `subtotal − gross = −0,02 <= 0,01` sağlanır ve EKSİK faturalı her
    hakediş sessizce geçerdi."""
    assert source_amount_matches(_BRUT + sapma, _BRUT) is False
    assert source_amount_blockers(_BRUT + sapma, _BRUT) == [
        source_amount_mismatch(_BRUT + sapma, _BRUT)
    ]


def test_BIR_TL_lik_sahte_fatura_REDDEDILIR() -> None:
    """Dilime adını veren canlı kusurun birebir hâli: 1.000.000'a 1 ₺."""
    assert source_amount_matches(Decimal("1.00"), Decimal("1000000.00")) is False


def test_KALEMSIZ_faturanin_SIFIR_ara_toplami_REDDEDILIR() -> None:
    """🔴 `total > 0` şartıyla ÇAKIŞMAZ, onu TAMAMLAR: sıfır ara toplam burada
    "tutar uyuşmuyor" olarak da düşer ve hakediş brütü 0 olsaydı (kalemsiz
    hakediş) tek başına `total > 0` şartı bunu ayırt edemezdi."""
    assert source_amount_matches(Decimal("0.00"), _BRUT) is False


def test_KAYNAKSIZ_fatura_kuraldan_MUAFTIR() -> None:
    """`None` = hakediş kaynağı yok (çoğunluk · kira hakedişi · sipariş).

    🔴 Bu dalın POZİTİF KONTROL değeri şudur: kural "her faturayı reddet"
    hâline gelirse kaynaksız faturalar da düşer ve bu satır kırmızıya döner.
    """
    assert source_amount_blockers(Decimal("1.00"), None) == []


def test_TOLERANS_SABITI_bir_kurustur() -> None:
    """Sabit kullanıcı kararının kendisidir (±0,01 ₺); gevşetilirse kırmızı."""
    assert SOURCE_AMOUNT_TOLERANCE == Decimal("0.01")


# --------------------------------------------------------------------------- #
# EVREN — iki tablo AYNI iki hakediş kolonunu taşımalıdır
# --------------------------------------------------------------------------- #


def test_TUTAR_evreni_YON_evreniyle_AYNIDIR() -> None:
    """🔴 Üçüncü bir hakediş ailesi eklendiğinde biri güncellenip öteki
    unutulursa, o ailede YA yön YA tutar bekçisiz kalırdı ve açık YALNIZ o
    ailede, yalnız canlıda görünürdü.

    İki tablo AYRI durur (biri `invoicing`de, biri `treasury`de) çünkü ayrı
    soruları cevaplar; ama kapsamları aynı olmak ZORUNDADIR.
    """
    assert set(SOURCE_GROSS_MODELS) == set(SOURCE_DIRECTION)


def test_TUTAR_evreni_KIRA_ve_SIPARIS_kaynaklarini_TASIMAZ() -> None:
    """Kapsam DARALTMASI kasıtlıdır ve gerekçesi `source_amounts` modülündedir:
    kira hakedişinin tek bir "brüt" kolonu yoktur, sipariş ise kısmi
    faturalanabilir. Bir gün eklenirlerse bugün çalışan meşru faturalar
    reddedilirdi."""
    assert "equipment_rental_invoice_id" not in SOURCE_GROSS_MODELS
    assert "purchase_order_id" not in SOURCE_GROSS_MODELS


# --------------------------------------------------------------------------- #
# MIGRATION — donmus kopyalar (b4d7e1c9f2a3, SALT OKUMA olcumu)
# --------------------------------------------------------------------------- #


def _migration_kaynagi() -> str:
    from pathlib import Path

    yol = (
        Path(__file__).resolve().parents[3]
        / "alembic"
        / "versions"
        / "b4d7e1c9f2a3_fathak_canli_tutarsiz_fatura_olcumu.py"
    )
    return yol.read_text(encoding="utf-8")


def test_migration_SUZGEC_metni_MODEL_sabitiyle_AYNIDIR() -> None:
    """🔴 Migration uygulama kodunu bilerek IMPORT ETMEZ (uygulanmış migration
    DONMUŞ olmalıdır). Bedeli iki metnin sessizce ayrışabilmesidir: biri iadeleri
    süzer, öteki süzmez — ve ölçüm YANLIŞ bir kümeyi sayardı."""
    from app.modules.invoicing.models import BINDING_SOURCE_WHERE

    assert f'WHERE_SQL = "{BINDING_SOURCE_WHERE}"' in _migration_kaynagi()


def test_migration_TOLERANSI_urun_sabitiyle_AYNIDIR() -> None:
    """Ölçüm, kapının saydığından BAŞKA bir kümeyi sayarsa rapor yalan olur."""
    assert f'TOLERANS = "{SOURCE_AMOUNT_TOLERANCE}"' in _migration_kaynagi()


def test_migration_AILE_kumesi_YON_evreniyle_AYNIDIR() -> None:
    """Ölçüm, kapının bağladığı İKİ aileyi de saymalıdır — birini atlayan bir
    ölçüm "ihlal yok" der ve kullanıcı canlıda kilitli hakedişle karşılaşır."""
    kaynak = _migration_kaynagi()
    for kolon in SOURCE_DIRECTION:
        assert f'"{kolon}",' in kaynak, f"migration ölçümünde eksik aile: {kolon}"


def test_migration_ebeveyni_BEKLENEN_revizyondur() -> None:
    """Araya başka bir dilim merge edilirse re-parent ŞART (P8/TH dersi)."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    from tests.modules.accounting._mu1_migration import BACKEND_DIR

    script = ScriptDirectory.from_config(Config(str(BACKEND_DIR / "alembic.ini")))
    assert script.get_revision("b4d7e1c9f2a3").down_revision == "a7c2e9d4b6f1"
