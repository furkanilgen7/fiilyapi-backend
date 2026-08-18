"""FIN-1 T3 — govde/yanit semalari.

🔴 **SEMA KATMANI BEKCILERI SUITE'E GORUNMEZ (MU-1 dersi):** modeli DOGRUDAN
kurup `session.add()` yapan testler bir Pydantic kuralini ASLA sinamaz. Bu dosya
semayi ACIKCA cagirir; uctan gecen ikinci katman `test_fin1_api.py`dedir ve
IKISI DE gereklidir (birincisi kuralin varligini, ikincisi ucta BAGLI oldugunu
kanitlar).
"""

import uuid
from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.modules.treasury.instruments import schemas
from app.modules.treasury.models import (
    FinancialInstrumentDirection,
    FinancialInstrumentKind,
    FinancialInstrumentStatus,
)

_GECERLI = {
    "instrument_kind": "cheque",
    "direction": "received",
    "serial_no": "0123456789",
    "drawer_name": "Güneşkent A.Ş.",
    "issue_date": "2026-07-01",
    "due_date": "2026-07-25",
    "amount": "1200000.00",
}


def _create(**degisiklik) -> schemas.FinancialInstrumentCreate:
    return schemas.FinancialInstrumentCreate(**{**_GECERLI, **degisiklik})


def test_asgari_govde_kabul_edilir() -> None:
    """E10:115-121 satirinin ZORUNLU alanlari: no · keşideci · iki tarih · tutar
    (+ tur ve yon, sekmelerden). Banka/açıklama/proje/hesap OPSIYONELDIR."""
    data = _create()
    assert data.instrument_kind is FinancialInstrumentKind.cheque
    assert data.direction is FinancialInstrumentDirection.received
    assert data.amount == Decimal("1200000.00")
    assert data.bank_name is None
    assert data.project_id is None


# --------------------------------------------------------------------------- #
# 🔴 K7 — `status` GOVDEDEN GELEMEZ
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("sema_adi", ["FinancialInstrumentCreate", "FinancialInstrumentUpdate"])
def test_status_govdede_REDDEDILIR(sema_adi: str) -> None:
    """🔴 K7'nin ta kendisi: gecis kurallari, terminal korumasi ve `direction`
    uyumu TEK bir kapidan gecmeli.

    Alan duzeltmesi ile durum degisimi ayni uca konsaydi **invaryantin IKI YAZMA
    KAPISI** dogar (BOQ-SEC-B kanonu) ve biri kilitsiz kalirdi. `extra="forbid"`
    sessiz yok saymayi da engeller: Pydantic'in varsayilani `status`u SESSIZCE
    atmak olurdu ve istemci gonderdigi durumun yazildigini SANIRDI.

    Kural her IKI govde semasinda da gecerlidir — POST'a konan bir sinir PATCH'i
    KORUMAZ (BOR-TEMIZ kanonu).
    """
    sema = getattr(schemas, sema_adi)
    with pytest.raises(ValidationError) as hata:
        sema(
            **(
                {**_GECERLI, "status": "collected"}
                if "Create" in sema_adi
                else {"status": "collected"}
            )
        )
    assert "status" in str(hata.value)


def test_turev_alanlar_govdede_REDDEDILIR() -> None:
    """`is_due` TUREVDIR (K2). Govdede kabul edilseydi istemci kendi rozetini
    yazdirdigini sanir, ekranda formulun urettigi baska bir deger gorurdu
    (`bank_accounts.balance` kanonu)."""
    for yasak in ("is_due", "id", "created_at", "updated_at", "uydurma_alan"):
        with pytest.raises(ValidationError):
            _create(**{yasak: "x"})


# --------------------------------------------------------------------------- #
# Tutar — para ölçegi
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("bozuk", ["0", "0.00", "-1.00"])
def test_tutar_pozitif_olmali(bozuk: str) -> None:
    """Sifir hicbir sey ifade etmez, negatif gizli bir ters kayit olurdu."""
    with pytest.raises(ValidationError):
        _create(amount=bozuk)


def test_tutar_YARIM_KURUS_reddedilir_SESSIZCE_YUVARLANMAZ() -> None:
    """🔴 Emrin ayrisma noktasi: `0.005` **422** vermeli, sessizce `0.01`e
    yuvarlanmamalidir.

    Yuvarlansaydi kullanici girdiginden BASKA bir tutari kaydetmis olur ve fark
    yalnizca mutabakatta gorunurdu. `decimal_places=2` bunu SINIRDA keser.
    """
    with pytest.raises(ValidationError):
        _create(amount="0.005")
    # Sinirin KABUL tarafi da olculur: iki hane MESRUDUR.
    assert _create(amount="0.01").amount == Decimal("0.01")


def test_tutar_18_hane_tavani() -> None:
    """`Numeric(18, 2)` — tavan asilirsa DB'de `NumericValueOutOfRange` (500)
    olurdu; sema onu 422'ye cevirir."""
    with pytest.raises(ValidationError):
        _create(amount="12345678901234567.00")


# --------------------------------------------------------------------------- #
# Uzunluk sinirlari — her sinir DEGERIYLE (BOR-TEMIZ kanonu: N kabul, N+1 ret)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("alan", "tavan"),
    [("serial_no", 50), ("drawer_name", 200), ("description", 200), ("bank_name", 100)],
)
def test_uzunluk_sinirlari_SINIR_DEGERIYLE(alan: str, tavan: int) -> None:
    """🔴 Sinir kaldirilirsa deger dogrudan `varchar(N)`e gider ve kullanici
    duzeltilebilir bir 422 yerine **500** (`StringDataRightTruncation`) gorur —
    BOR-TEMIZ'in `document_no` bulgusunun ayni sinifi."""
    assert getattr(_create(**{alan: "a" * tavan}), alan) == "a" * tavan
    with pytest.raises(ValidationError):
        _create(**{alan: "a" * (tavan + 1)})


@pytest.mark.parametrize("alan", ["serial_no", "drawer_name"])
def test_zorunlu_metinler_BOS_olamaz(alan: str) -> None:
    """Bos "Çek No" ya da bos "Keşideci" satiri ekranda kimligi olmayan bir kayit
    uretirdi (E10:104-105 iki sutun da her satirda doludur)."""
    with pytest.raises(ValidationError):
        _create(**{alan: "   "})


# --------------------------------------------------------------------------- #
# PATCH govdesi
# --------------------------------------------------------------------------- #


def test_update_BOS_govde_kabul_eder_ama_gonderilmeyen_alani_EZMEZ() -> None:
    """`exclude_unset` SARTTIR: gonderilmeyen alan ile acikca `null` gonderilen
    alan AYNI SEY DEGILDIR. Onsuz, yalniz `bank_name` duzelten bir istek kaydin
    aciklamasini ve proje bagini SESSIZCE silerdi."""
    kismi = schemas.FinancialInstrumentUpdate(bank_name="Ziraat Bank")
    assert kismi.model_dump(exclude_unset=True) == {"bank_name": "Ziraat Bank"}


def test_update_acikca_null_gondermek_TEMIZLEMEKTIR() -> None:
    temizleme = schemas.FinancialInstrumentUpdate(project_id=None)
    assert temizleme.model_dump(exclude_unset=True) == {"project_id": None}


# --------------------------------------------------------------------------- #
# Durum gecisi govdesi
# --------------------------------------------------------------------------- #


def test_gecis_govdesi_YALNIZ_status_tasir() -> None:
    """Uc, hedef durumu alir; kural tablosu servistedir. Govdeye baska alan
    (or. `amount`) sizsaydi durum degisimi sirasinda para da degistirilebilirdi."""
    govde = schemas.FinancialInstrumentStatusChange(status="collected")
    assert govde.status is FinancialInstrumentStatus.collected
    with pytest.raises(ValidationError):
        schemas.FinancialInstrumentStatusChange(status="collected", amount="5.00")


def test_gecis_govdesi_PORTFOLIO_hedefini_de_KABUL_EDER_karari_SERVISTE() -> None:
    """Sema hedefi DOGRULAMAZ, yalniz TIPLER. `portfolio` hedefi bir geristir ve
    tabloda YOKTUR → **409** (422 degil): sema bunu reddetseydi "gecersiz gecis"
    hatasi iki ayri kod donduren iki ayri katmana bolunurdu."""
    assert (
        schemas.FinancialInstrumentStatusChange(status="portfolio").status
        is FinancialInstrumentStatus.portfolio
    )


# --------------------------------------------------------------------------- #
# Yanit — `is_due` TUREVDIR
# --------------------------------------------------------------------------- #


class _SahteSatir:
    def __init__(self, status: FinancialInstrumentStatus, due_date: date) -> None:
        self.id = uuid.uuid4()
        self.instrument_kind = FinancialInstrumentKind.cheque
        self.direction = FinancialInstrumentDirection.received
        self.serial_no = "0123456789"
        self.drawer_name = "Güneşkent A.Ş."
        self.description = "Proje iş avansı"
        self.bank_name = "Ziraat Bank"
        self.issue_date = date(2026, 7, 1)
        self.due_date = due_date
        self.amount = Decimal("1200000.00")
        self.status = status
        self.project_id = None
        self.bank_account_id = None
        self.created_at = None
        self.updated_at = None


def test_yanit_is_due_alanini_STATUS_ile_AYRI_tasir() -> None:
    """🔴 K2: `status` (kalici) ve `is_due` (turev) AYRI alanlardir; frontend
    rozeti IKISINDEN kurar. Tek alanda birlestirilseydi (or. `status='due'`)
    kalici durum kaybolur ve ertesi ay geri getirilemezdi."""
    satir = _SahteSatir(FinancialInstrumentStatus.portfolio, date(2026, 7, 25))
    yanit = schemas.FinancialInstrumentResponse.from_row(satir, as_of=date(2026, 7, 15))
    assert yanit.status is FinancialInstrumentStatus.portfolio
    assert yanit.is_due is True

    gelecek = schemas.FinancialInstrumentResponse.from_row(
        _SahteSatir(FinancialInstrumentStatus.portfolio, date(2026, 8, 15)),
        as_of=date(2026, 7, 15),
    )
    assert gelecek.is_due is False
