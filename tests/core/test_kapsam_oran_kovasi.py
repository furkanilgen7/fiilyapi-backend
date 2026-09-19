"""PARADAN TÜREYEN ORANLAR `para` kovasındadır (kullanıcı kararı 2026-09-19).

## Neden ayrı bir bekçi

`test_para_alani_siniflandirmasi` bir alanın ETİKETLİ OLDUĞUNU şart koşar, ama
HANGİ KOVADA olduğunu ölçmez. Bu ayrım ölçülmezse bir etiketi sessizce ters
çevirmek hiçbir testi kırmaz — nitekim mutasyonla ölçüldü: `progress_pct`i
`operasyonel`e geri almak TÜM kümeyi yeşil bıraktı. Kararın kendisi bekçisizdi.

## Karar

Bir oran, GİRDİLERİ paradan geliyorsa PARADIR. Aksi hâlde iki kusur birden doğar:

* `limited` rol bedeli göremezken ORANI görür — ve oran, gizlenen bedeli dolaylı
  olarak ele verir (kümülatif brüt biliniyorsa bedel `brüt / oran`dır).
* `finance` rol (muhasebe) kendi ASIL metriğini göremez: tahsilat oranı ve
  finansal ilerleme muhasebenin işidir.

Emsal: `projects/land_share_schemas.py`deki `our_actual_pct` · `owner_actual_pct`
· `deviation_pct` — üçü de değerden türer ve ÜÇÜ DE `para` etiketlidir.

## Karşıt emsal (bilerek DIŞARIDA)

FİZİKSEL ilerleme (`projects` kartlarındaki `physical_progress`, BOQ'un
`progress_pct`i) şantiye günlüğünden türer, paradan DEĞİL — o `operasyonel`
kalır ve bu ayrım KASITLIDIR (`boq/schemas.py` docstring'i gerekçelendirir).
"""

from decimal import Decimal

from app.core.access import Scope
from app.core.field_scope import Gorunurluk, maskele

#: Paradan türediği ÖLÇÜLMÜŞ oranlar: (şema, alan, üreticisinin formülü).
#: Yeni bir para-oranı eklendiğinde buraya da eklenir; liste kararın kendisidir.
PARA_ORANLARI = [
    ("contracts", "ContractListItem", "progress_pct", "kümülatif brüt ÷ sözleşme bedeli"),
    ("sales", "CollectionKpi", "collection_pct", "tahsil edilen ÷ sözleşmeye bağlanan"),
]


def _alan_kovalari(modul_key: str, sema_adi: str, alan_adi: str) -> set[Gorunurluk]:
    import importlib

    mod = importlib.import_module(f"app.modules.{modul_key}.schemas")
    alan = getattr(mod, sema_adi).model_fields[alan_adi]
    return {meta for meta in alan.metadata if isinstance(meta, Gorunurluk)}


def test_PARADAN_tureyen_oranlar_PARA_kovasindadir() -> None:
    yanlis = {
        f"{sema}.{alan} ({formul})": sorted(k.value for k in _alan_kovalari(modul, sema, alan))
        for modul, sema, alan, formul in PARA_ORANLARI
        if Gorunurluk.para not in _alan_kovalari(modul, sema, alan)
    }
    assert not yanlis, (
        "Paradan türeyen bir oran `para` kovasında DEĞİL. `operasyonel` etiketlemek "
        "iki kusur birden üretir: `limited` rol oranı görüp gizlenen bedeli dolaylı "
        f"öğrenir, `finance` rol kendi asıl metriğini göremez. {yanlis}"
    )


def test_oran_LIMITEDDE_gizlenir_FINANCETA_GORUNUR() -> None:
    """🔴 Etiket bir NİYETTİR; bu test onun DAVRANIŞA dönüştüğünü ölçer.

    Yalnız etiketi çakan bir test, maskenin kova eşlemesi bozulursa (ör. `para`
    artık `limited`te gizlenmez olursa) yine yeşil kalırdı.
    """
    from app.modules.contracts.schemas import ContractListItem

    kayit = ContractListItem(
        id="00000000-0000-0000-0000-000000000001",
        title="A Blok Kaba İnşaat",
        contract_no="SZ-1",
        counterparty_name="Akın İnşaat",
        amount=Decimal("1000000.00"),
        start_date=None,
        end_date=None,
        progress_pct=Decimal("42.50"),
        status="active",
        is_draft=False,
    )

    assert maskele(kayit, Scope.limited).progress_pct is None, "oran `limited`te SIZDI"
    assert maskele(kayit, Scope.finance).progress_pct == Decimal("42.50"), (
        "oran `finance`ta YANLIŞLIKLA gizlendi — muhasebe kendi metriğini göremez"
    )
    # 🔴 POZİTİF KONTROL: kısıtsız kapsamda değer BOZULMAZ.
    assert maskele(kayit, Scope.all).progress_pct == Decimal("42.50")
    # Kimlik alanı hiçbir kapsamda gizlenmez.
    assert maskele(kayit, Scope.limited).title == "A Blok Kaba İnşaat"
