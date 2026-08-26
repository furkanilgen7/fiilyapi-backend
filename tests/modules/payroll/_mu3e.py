"""MU-3E test yardımcıları — bordro fişleme paketinin ORTAK tabanı.

`tests/modules/posting/_mu3d.py` ve `tests/modules/treasury/_mu3c.py`nin
kardeşi ve aynı sebeple bir `conftest.py` DEĞİLDİR: bu isimler `tests/modules/
payroll/conftest.py`nin fixture'larıyla (`donem`, `oranlar`, `dort_tip`) YAN
YANA kullanılır ve bir fixture olarak tanımlansalardı gölgeleme/adlandırma
çakışması riskini büyütürlerdi. Düz fonksiyonlar çağıranın işini açık bırakır.

🔴 `hesap_neti` · `bacaklar` · `canli_fis` YENİDEN YAZILMAZ, `_mu3d`den İTHAL
EDİLİR: "yevmiyeden türeyen net" ifadesinin (özellikle `posting_filter()` ile
`reversed` fişleri defterde TUTMASININ) iki ayrı yazımı bir gün ayrışırdı.

## 🔴 BEKLENEN SAYILAR ELLE YAZILIR, ÜRÜNDEN TÜRETİLMEZ

Aşağıdaki sabitler `dort_tip` fixture'ının ürettiği satırlardan **elle**
hesaplanmıştır. `compute`/`sgk` çağrılarak türetilselerdi test, ölçtüğü şeyin
tanımını ölçtüğü koddan alır ve o kod bozulduğunda YEŞİL kalırdı.

    şirket   · brüt  9.000,00 · kesinti 1.350,00 · net  7.650,00 · GV 0,00
    serbest  · brüt 12.500,00 · kesinti 2.500,00 · net 10.000,00 · GV 2.500,00
    stajyer  · brüt  7.500,00 · kesinti     0,00 · net  7.500,00 · GV 0,00
    taşeron  · brüt  9.000,00 · **EXCLUDED** — fişe GİRMEZ (çift sayım)
    ücretsiz · ücret tanımsız → `uncomputed` — fişe GİRMEZ

🔴 Şirket ve serbestin gelir vergisi 0,00 ve 2.500,00 olması bir tesadüf
DEĞİLDİR: 9.000 brüt 2026 asgari ücretinin (33.030,00) altındadır ve KK-7
istisnası dilimli vergiyi TAMAMEN karşılar; serbest ise GVK m.94 DÜZ %20
stopajındadır ve istisna oraya UYGULANMAZ. Yani küme hem sıfır hem sıfır-dışı
bir vergi bacağı taşır — `360` bacağı GERÇEKTEN ölçülür.
"""

from decimal import Decimal

from app.modules.payroll.models import PayrollLine
from app.modules.payroll.posting import SOURCE_TYPE
from tests.modules.posting._mu3d import bacaklar, canli_fis, hesap_neti

__all__ = [
    "GIDER_BACAGI",
    "KOD_GIDER",
    "KOD_PERSONEL_BORC",
    "KOD_SGK_BORC",
    "KOD_VERGI_BORC",
    "SGK_BACAGI",
    "SOURCE_TYPE",
    "TASERON_BRUT",
    "TOPLAM_BRUT",
    "TOPLAM_NET",
    "VERGI_BACAGI",
    "bacaklar",
    "bordro_fisi",
    "canli_fis",
    "hesap_neti",
    "satirlar",
]

KOD_GIDER = "730"
KOD_PERSONEL_BORC = "335"
KOD_VERGI_BORC = "360"
KOD_SGK_BORC = "361"

#: Fişe GİREN satırların brüt toplamı (şirket + serbest + stajyer).
TOPLAM_BRUT = Decimal("29000.00")
#: `335` bacağı — ödenebilir satırların neti.
TOPLAM_NET = Decimal("25150.00")
#: 🔴 Fişe GİRMEYEN taşeron brütü. Ayrı bir sabit olarak durur ki çift sayım
#: bekçisi "ne kadarı DIŞARIDA kaldı" sorusunu SAYIYLA sorabilsin.
TASERON_BRUT = Decimal("9000.00")

#: `730` = brüt + işveren üçlüsü. Yalnız ŞİRKET satırının işveren oranları
#: sıfır-dışıdır (serbest ve stajyer `ZERO` setindedir):
#:   SGK işveren %20,5 → 1.845,00 · işsizlik işveren %2 → 180,00 ·
#:   kısa çalışma %1 → 90,00   ⇒ 2.115,00
GIDER_BACAGI = Decimal("31115.00")
#: `360` = gelir vergisi (2.500,00, yalnız serbest) + damga (0,00).
VERGI_BACAGI = Decimal("2500.00")
#: `361` = SGK işçi 1.260,00 + işsizlik işçi 90,00 + işveren üçlüsü 2.115,00.
SGK_BACAGI = Decimal("3465.00")


async def satirlar(session, period_id) -> list[PayrollLine]:
    """Dönemin satırları — ürün servisinden GEÇİLMEZ, tablodan okunur."""
    from sqlalchemy import select

    return list(
        (
            await session.execute(
                select(PayrollLine)
                .where(PayrollLine.payroll_period_id == period_id)
                .execution_options(populate_existing=True)
            )
        )
        .scalars()
        .all()
    )


async def bordro_fisi(session, period_id):
    """Dönemin CANLI bordro fişi (yoksa `None`)."""
    return await canli_fis(session, SOURCE_TYPE, period_id)
