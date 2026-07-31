"""Task H3 — `app/modules/progress_payments/schemas.py` Pydantic şema testleri.

Spec kaynağı: docs/superpowers/specs/2026-07-31-alt-proje-2-p7-isveren-hakedisi-design.md
§4 (alan sınırları), §5.1 (`is_price_stale`), §6.5 (miktar korkulukları — şema
tarafı), §7 (submit zorunluluk kuralları — guards'a devredilir), §9.7, §10/3-5-6.

Her kuralın hem KABUL hem RET tarafı test edilir (tautolojiden kaçınma).
"""

import uuid
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.modules.progress_payments.schemas import (
    ProgressPaymentCreate,
    ProgressPaymentLineInput,
    ProgressPaymentLinesSave,
    ProgressPaymentUpdate,
)

# --- ProgressPaymentLineInput: zorunlu UUID alanları (denetim H3 bulgusu) ---
#
# `contract_item_id`/`site_id` yanlışlıkla `Optional` yapılırsa hiçbir mevcut
# test kırılmıyordu (denetim bulgusu) — bu iki test o mutasyonu yakalar.


def test_contract_item_id_eksikse_reddedilir():
    with pytest.raises(ValidationError):
        ProgressPaymentLineInput(site_id=uuid.uuid4(), quantity=1)


def test_site_id_eksikse_reddedilir():
    with pytest.raises(ValidationError):
        ProgressPaymentLineInput(contract_item_id=uuid.uuid4(), quantity=1)


# --- ProgressPaymentLineInput: quantity >= 0, coefficient > 0 ---


def test_satir_miktari_sifir_kabul():
    """OLU 172: 0 meşru — P5 dağılımının '0 → 422' kuralı hakedişe TAŞINMAZ (spec §10/3)."""
    satir = ProgressPaymentLineInput(
        contract_item_id=uuid.uuid4(), site_id=uuid.uuid4(), quantity=0
    )
    assert satir.quantity == 0


def test_satir_miktari_pozitif_kabul():
    satir = ProgressPaymentLineInput(
        contract_item_id=uuid.uuid4(), site_id=uuid.uuid4(), quantity=Decimal("61.2")
    )
    assert satir.quantity == Decimal("61.2")


def test_negatif_miktar_reddedilir():
    with pytest.raises(ValidationError):
        ProgressPaymentLineInput(contract_item_id=uuid.uuid4(), site_id=uuid.uuid4(), quantity=-1)


def test_katsayi_sifir_reddedilir():
    with pytest.raises(ValidationError):
        ProgressPaymentLineInput(
            contract_item_id=uuid.uuid4(), site_id=uuid.uuid4(), quantity=1, coefficient=0
        )


def test_katsayi_pozitif_kabul():
    satir = ProgressPaymentLineInput(
        contract_item_id=uuid.uuid4(),
        site_id=uuid.uuid4(),
        quantity=1,
        coefficient=Decimal("1.142"),
    )
    assert satir.coefficient == Decimal("1.142")


def test_katsayi_gonderilmezse_none():
    """§4.1: default_coefficient yalnız coefficient GÖNDERİLMEYEN satıra öntanımlı iner —
    servis katmanı yapar, şema `None` bırakır."""
    satir = ProgressPaymentLineInput(
        contract_item_id=uuid.uuid4(), site_id=uuid.uuid4(), quantity=1
    )
    assert satir.coefficient is None


# --- ProgressPaymentCreate: dönem aralığı, taslakta serbestlik ---


def test_donem_ayi_araligi():
    with pytest.raises(ValidationError):
        ProgressPaymentCreate(period_year=2026, period_month=13)


def test_donem_ayi_geçerli_kabul():
    govde = ProgressPaymentCreate(period_year=2026, period_month=7)
    assert govde.period_month == 7


def test_aciklama_taslakta_bos_olabilir():
    assert ProgressPaymentCreate().description is None


def test_govde_bos_taslak_olusturmayi_engellemez():
    """Kalıcı karar 4: `POST .../progress-payments` gövdesiz de geçerli (taslak)."""
    govde = ProgressPaymentCreate()
    assert govde.period_year is None
    assert govde.lines is None


def test_satirli_govde_kabul():
    govde = ProgressPaymentCreate(
        lines=[
            ProgressPaymentLineInput(
                contract_item_id=uuid.uuid4(), site_id=uuid.uuid4(), quantity=5
            )
        ]
    )
    assert len(govde.lines) == 1


def test_default_coefficient_sifir_reddedilir():
    with pytest.raises(ValidationError):
        ProgressPaymentCreate(default_coefficient=0)


# --- ProgressPaymentUpdate: tüm alanlar isteğe bağlı (PATCH) ---


def test_update_tum_alanlar_istege_bagli():
    govde = ProgressPaymentUpdate()
    assert govde.period_year is None
    assert govde.description is None


def test_update_donem_ayi_araligi():
    with pytest.raises(ValidationError):
        ProgressPaymentUpdate(period_month=0)


# --- ProgressPaymentLinesSave: `PUT .../lines` gövdesi ---


def test_lines_save_bos_liste_kabul():
    """Değiştirme semantiği: boş gövde = tüm satırları sil (spec §9.2/§10-2)."""
    govde = ProgressPaymentLinesSave(lines=[])
    assert govde.lines == []


def test_lines_save_varsayilan_bos_liste():
    govde = ProgressPaymentLinesSave()
    assert govde.lines == []


# --- ProgressPaymentLineDetail: snapshot alanları modeldeki String(N) ile
# BİREBİR (denetim H3 bulgusu) — JSON şemasında `maxLength` çıktığını doğrular,
# frontend `maxLength`'i buradan okur (spec §10/6).
#
# `app.openapi()` yerine `model_json_schema()`: bu modülün router'ı henüz
# uygulamaya bağlı değil (H4+ kapsamı), dolayısıyla `ProgressPaymentLineDetail`
# `app.openapi()` çıktısında YOK. Pydantic'in ürettiği şema, FastAPI'nin
# OpenAPI gövdesine BİREBİR aktardığı şemayla aynıdır (FastAPI ekstra kısıtlama
# eklemez), bu yüzden `model_json_schema()` burada eşdeğer ve DOĞRU bir vekildir.


def test_line_detail_snapshot_alanlari_max_length_tasir():
    from app.modules.progress_payments.schemas import ProgressPaymentLineDetail

    schema = ProgressPaymentLineDetail.model_json_schema()
    properties = schema["properties"]

    assert properties["code"]["maxLength"] == 50
    assert properties["unit"]["maxLength"] == 50
    # `group_name: str | None` → `anyOf` dallı şema; string dalı `maxLength` taşır.
    group_name_string_variant = next(
        variant for variant in properties["group_name"]["anyOf"] if variant.get("type") == "string"
    )
    assert group_name_string_variant["maxLength"] == 200
