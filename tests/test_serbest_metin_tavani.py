"""TB4 S3 — sınırsız serbest metin alanlarının 2000 karakter tavanı.

Kaynak: `docs/superpowers/specs/2026-08-09-tb4-borc-paketi-design.md` §1 B4 + §5 S3
(kullanıcı onayı 2026-08-09). Kapsam BİLİNÇLİ olarak dardır: yalnız kolonu `Text`
(DB'de sınırsız) olan `boq` + `contracts` alanları. Zaten `String(N)` ile sınırlı
alanlar (ör. `units.notes` 500, `subcontractors.name` 200) DOKUNULMAZ —
sıkılaştırma mevcut istemcileri kırardı.

Tavan ŞEMA düzeyindedir; kolon tipi değişmez, migration YOKTUR.

Bu dosya modüller arasıdır (iki aile aynı sabitten beslenmelidir), bu yüzden
`tests/` kökündedir.
"""

import uuid
from decimal import Decimal

import pytest
from pydantic import BaseModel, ValidationError

from app.core.text import FREE_TEXT_MAX_LENGTH
from app.modules.boq.schemas import (
    BoqGroupCreate,
    BoqGroupUpdate,
    BoqItemCreate,
    BoqItemUpdate,
)
from app.modules.contracts.schemas import (
    EmployerContractGroupCreate,
    EmployerContractGroupUpdate,
    EmployerContractItemCreate,
    EmployerContractItemUpdate,
    SubcontractorContractCreate,
    SubcontractorContractItemCreate,
    SubcontractorContractItemUpdate,
)

# Her satır BİR giriş noktasıdır: (şema, alan, alanın DIŞINDAKİ zorunlu gövde).
# BC dersi (belge arşivi T4 bulgusu #2): bir alanın birden fazla giriş noktası
# varsa HEPSİ aynı sabiti kullanmalıdır — biri atlanırsa kapı o uçtan atlatılır.
# Bu yüzden create/update çiftlerinin İKİSİ de burada listelidir.
_GIRIS_NOKTALARI: list[tuple[type[BaseModel], str, dict]] = [
    # --- boq ailesi (`boq_groups.name`, `boq_items.description`: Text) ---
    (BoqGroupCreate, "name", {}),
    (BoqGroupUpdate, "name", {}),
    (
        BoqItemCreate,
        "description",
        {
            "group_id": uuid.uuid4(),
            "code": "01.001",
            "unit": "m2",
            "quantity": Decimal("1"),
            "unit_price": Decimal("1"),
        },
    ),
    (BoqItemUpdate, "description", {}),
    # --- contracts / işveren ailesi (`employer_contract_*`: Text) ---
    (EmployerContractGroupCreate, "name", {}),
    (EmployerContractGroupUpdate, "name", {}),
    (
        EmployerContractItemCreate,
        "description",
        {
            "group_id": uuid.uuid4(),
            "code": "01.001",
            "unit": "m2",
            "quantity": Decimal("1"),
            "unit_price": Decimal("1"),
        },
    ),
    (EmployerContractItemUpdate, "description", {}),
    # --- contracts / taşeron ailesi (`subcontractor_contract_items.description`) ---
    (
        SubcontractorContractItemCreate,
        "description",
        {"code": "01.001", "unit": "m2", "quantity": Decimal("1")},
    ),
    (SubcontractorContractItemUpdate, "description", {}),
]

_KIMLIKLER = [f"{sema.__name__}.{alan}" for sema, alan, _ in _GIRIS_NOKTALARI]


@pytest.mark.parametrize(("sema", "alan", "govde"), _GIRIS_NOKTALARI, ids=_KIMLIKLER)
def test_tam_tavan_kabul_edilir(sema: type[BaseModel], alan: str, govde: dict) -> None:
    nesne = sema(**govde, **{alan: "ç" * FREE_TEXT_MAX_LENGTH})
    assert len(getattr(nesne, alan)) == FREE_TEXT_MAX_LENGTH


@pytest.mark.parametrize(("sema", "alan", "govde"), _GIRIS_NOKTALARI, ids=_KIMLIKLER)
def test_tavanin_bir_fazlasi_reddedilir(sema: type[BaseModel], alan: str, govde: dict) -> None:
    with pytest.raises(ValidationError) as hata:
        sema(**govde, **{alan: "ç" * (FREE_TEXT_MAX_LENGTH + 1)})
    assert any(h["loc"] == (alan,) for h in hata.value.errors())


@pytest.mark.parametrize(("sema", "alan", "govde"), _GIRIS_NOKTALARI, ids=_KIMLIKLER)
def test_tavan_paylasilan_sabitten_okunur(sema: type[BaseModel], alan: str, govde: dict) -> None:
    """Sabit yerine elle yazılmış bir sayı (ör. 1000) bu iddiayı kırar — iki aile
    ve gelecekteki her giriş noktası TEK kaynaktan beslenmek zorundadır."""
    del govde
    assert sema.model_fields[alan].metadata, f"{sema.__name__}.{alan} SINIRSIZ kalmış"
    tavanlar = [
        kural.max_length
        for kural in sema.model_fields[alan].metadata
        if getattr(kural, "max_length", None) is not None
    ]
    assert tavanlar == [FREE_TEXT_MAX_LENGTH]


def test_ic_ice_kalem_yolu_da_tavana_tabidir() -> None:
    """`SubcontractorContractItemCreate.description`'ın İKİNCİ giriş noktası:
    sözleşme oluşturmanın iç içe `items` listesi (spec §6.5). Tekil uç sınırlanıp
    bu yol atlanırsa tavan tamamen atlatılabilir olurdu."""
    kalem = {
        "code": "01.001",
        "unit": "m2",
        "quantity": Decimal("1"),
    }

    kabul = SubcontractorContractCreate(
        items=[{**kalem, "description": "ç" * FREE_TEXT_MAX_LENGTH}]
    )
    assert len(kabul.items[0].description) == FREE_TEXT_MAX_LENGTH

    with pytest.raises(ValidationError) as hata:
        SubcontractorContractCreate(
            items=[{**kalem, "description": "ç" * (FREE_TEXT_MAX_LENGTH + 1)}]
        )
    assert any(h["loc"] == ("items", 0, "description") for h in hata.value.errors())


def test_mevcut_dar_sinirlar_gevsetilmedi() -> None:
    """S3 kapsam sınırı: zaten sınırlı alanlar 2000'e ÇEKİLMEZ (ne gevşetme ne
    sıkılaştırma). `SubcontractorCreate.name` `String(200)` kolonuyla birebir
    kalmalıdır — kolon sınırının üstüne çıkan bir şema, kullanıcıya 422 yerine
    anlaşılmaz bir DB hatası döndürürdü."""
    from app.modules.contracts.schemas import SubcontractorCreate

    tavanlar = [
        kural.max_length
        for kural in SubcontractorCreate.model_fields["name"].metadata
        if getattr(kural, "max_length", None) is not None
    ]
    assert tavanlar == [200]
