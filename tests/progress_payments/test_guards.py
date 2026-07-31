"""Task H3 — `app/modules/progress_payments/guards.py` submit kuralı testleri
(spec §7 zorunluluk tablosu). DB'siz sahte nesnelerle — `contracts/test_guards.py`
deseninin birebiri.
"""

from decimal import Decimal

import pytest

from app.core.errors import SiteValidationError
from app.modules.progress_payments import guards


class _Satir:
    def __init__(self, quantity=Decimal("10")):
        self.quantity = quantity


class _Hakedis:
    def __init__(self, **kw):
        self.period_year = kw.get("period_year", 2026)
        self.lines = kw.get("lines", [_Satir()])


class _Sozlesme:
    def __init__(self, **kw):
        self.amount = kw.get("amount", Decimal("11200000"))


def test_submit_donem_zorunlu():
    with pytest.raises(SiteValidationError) as hata:
        guards.validate_submit(_Hakedis(period_year=None), _Sozlesme())
    assert str(hata.value) == guards.PERIOD_REQUIRED


def test_submit_donem_doluysa_geciyor():
    guards.validate_submit(_Hakedis(period_year=2026), _Sozlesme())


def test_submit_satirsiz_reddedilir():
    with pytest.raises(SiteValidationError) as hata:
        guards.validate_submit(_Hakedis(lines=[]), _Sozlesme())
    assert str(hata.value) == guards.LINES_REQUIRED


def test_submit_toplami_sifir_reddedilir():
    """Σ line_total > 0 şartı — satır var ama hepsi 0 miktar."""
    with pytest.raises(SiteValidationError) as hata:
        guards.validate_submit(_Hakedis(lines=[_Satir(quantity=0)]), _Sozlesme())
    assert str(hata.value) == guards.LINES_REQUIRED


def test_submit_en_az_bir_satir_pozitifse_geciyor():
    guards.validate_submit(
        _Hakedis(lines=[_Satir(quantity=0), _Satir(quantity=Decimal("5"))]), _Sozlesme()
    )


def test_submit_sozlesme_bedelsiz_reddedilir():
    """Spec §6.3: amount NULL iken avans tavanı kurulamaz."""
    with pytest.raises(SiteValidationError) as hata:
        guards.validate_submit(_Hakedis(), _Sozlesme(amount=None))
    assert str(hata.value) == guards.CONTRACT_AMOUNT_REQUIRED


def test_submit_sozlesme_bedeli_doluysa_geciyor():
    guards.validate_submit(_Hakedis(), _Sozlesme(amount=Decimal("1")))


def test_submit_hata_sirasi_donem_once_kontrol_edilir():
    """Tablo sırası: dönem satırlardan önce kontrol edilir."""
    with pytest.raises(SiteValidationError) as hata:
        guards.validate_submit(_Hakedis(period_year=None, lines=[]), _Sozlesme())
    assert str(hata.value) == guards.PERIOD_REQUIRED
