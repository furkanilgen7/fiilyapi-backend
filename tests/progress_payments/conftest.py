"""`progress_payments` modülüne özgü fixture'lar — H1 · H4 · H5 · H6 · H8 · H9.

Kök `tests/conftest.py`'deki `db_session`/`seeded_db`/`user_factory`/`project_factory`
üzerine kurulur. Login/erişim fixture'ları `tests/contracts/conftest.py` deseninin
BİREBİRİDİR — pytest sibling `tests/contracts/conftest.py`'yi OTOMATİK yüklemez
(yalnız üst dizin ağacındaki conftest'ler yüklenir), bu yüzden aynı desen burada
YENİDEN kurulur (fixture adları doğrulanır, uydurulmaz).

🔴 800 SATIR TAVANI BÖLMESİ — GÖRÜNÜRLÜK DEĞİŞMEDİ. Dosya 1532 satırdı. Fixture
GÖVDELERİ aynı DİZİNDEKİ `_fixtures_*.py` modüllerine taşındı; `conftest.py`
yerinde kaldı ve hepsini AÇIKÇA import ediyor. pytest bir fixture'ın adını
conftest modülünün NAMESPACE'indeki öznitelik adından okur — ad da, kapsam
(scope) da, görünürlük de aynen korunur.

🔴 Fixture'lar bir ALT PAKETE taşınMADI: taşınsaydı görünürlük DARALIR ve bu
dizindeki testler sessizce başka bir fixture alırdı. Bölme öncesi ve sonrası
toplanan test sayısı birebir aynıdır (6140).
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from ._fixtures_base import (  # noqa: F401
    _auth,
    _dagit,
    _login,
    admin_headers,
    gorunmeyen_hakedis,
    gorunmeyen_proje,
    hakedis_kalemi,
    hakedis_olusturan,
    hakedis_santiyesi,
    hakedis_sozlesmesi,
    hr_headers,
    ikinci_proje_kalemi,
    ikinci_proje_santiyesi,
    ikinci_sozlesmeli_proje,
    kisitli_headers,
    kisitli_proje,
    onay_bekleyen_hakedis,
    site_chief_headers,
    sozlesmeli_proje,
    sozlesmesiz_proje,
    taslak_hakedisli_proje,
)
from ._fixtures_delete import (  # noqa: F401
    _kisitli_proje_sozlesmesi,
    baskasinin_taslagi,
    hakedisli_santiye,
    kendi_taslagi,
    kisitli_kullanicisi,
    sef_kullanicisi,
)
from ._fixtures_lines import (  # noqa: F401
    _gecmisli_ortam,
    dagitilmamis_kalem,
    ff_kapali_hakedissiz_proje,
    ff_kapali_ortam,
    ikinci_dagitilmis_kalem,
    taslak_hakedis,
)
from ._fixtures_state import (  # noqa: F401
    bedelsiz_sozlesmede_taslak,
    gecerli_taslak,
    hakedis_fabrikasi,
    kisitli_projede_onay_bekleyen,
    kota_bolusen_iki_hakedis,
    muhasebe_headers,
    onayli_gecmisli_ortam,
    saha_headers,
    taslak_gecmisli_ortam,
    ters_sirali_onayli_gecmis,
)
from ._fixtures_summary import (  # noqa: F401
    _ozet_ortami,
    avans_tavanina_dayanan_proje,
    dort_onayli_hakedisli_proje,
    iki_projeli_ozet_ortami,
    iki_santiyeli_cok_hakedisli_proje,
    karisik_durumlu_proje,
    taslakli_proje,
    tavana_dayanan_iki_proje,
    zincir_onaycilari,
)


@pytest.fixture(autouse=True)
async def _mu3d_esleme(seeded_db: AsyncSession) -> None:
    """🔴 MU-3D — işveren hakedişi `posting_rules` eşlemesi, **AUTOUSE**.

    ## Neden autouse

    MU-3D'den sonra `approve` bir YEVMİYE FİŞİ yazar ve eşleme yoksa **422**
    verir. Bu paketteki testlerin ölçtüğü şey geçiş tablosu · kota bekçisi ·
    denetim günlüğü · onay zinciridir — fişleme DEĞİL. Eşleme onlar için
    `seeded_db`nin rol matrisi gibi bir ALTYAPI ÖN KOŞULUDUR; her testin
    imzasına elle eklenseydi, eklenmeyi unutulan bir test kuralı değil
    kurulumu gösteren bir kırmızı verirdi.

    ## 🔴 Bu, fail-closed dalını MASKELEMEZ

    Eşlemesiz onayın **422** verdiği ve geçişin GERİ ALINDIĞI ayrı bir pakette,
    autouse'un ULAŞMADIĞI yerde ölçülür:
    `tests/modules/posting/test_mu3d_hakedis_fisleme.py::
    test_ESLEME_YOKSA_422_ve_ONAY_da_GERI_ALINIR`. O test bu fixture'ı
    BİLEREK görmez.
    """
    from app.modules.accounting.models import JournalSourceType
    from app.modules.progress_payments.posting import PROGRESS_PAYMENT_POSTING_RULES
    from tests._hakedis_esleme import esleme_kur

    await esleme_kur(seeded_db, JournalSourceType.progress_payment, PROGRESS_PAYMENT_POSTING_RULES)
