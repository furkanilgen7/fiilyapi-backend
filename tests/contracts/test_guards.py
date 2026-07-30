from datetime import date

import pytest

from app.core.errors import SiteValidationError
from app.modules.contracts import guards


class _Sozlesme:
    def __init__(self, **kw):
        self.project_id = kw.get("project_id", "p")
        self.subcontractor_id = kw.get("subcontractor_id", "s")
        self.work_category = kw.get("work_category", "Betonarme")
        self.contract_no = kw.get("contract_no", "TSZ-2026-004")
        self.signature_date = kw.get("signature_date", date(2026, 1, 1))
        self.start_date = kw.get("start_date", date(2026, 1, 5))
        self.end_date = kw.get("end_date", date(2026, 12, 31))
        self.items = kw.get("items", [])


def test_taslak_eksik_alanlari_kabul_eder():
    guards.validate_subcontract(_Sozlesme(subcontractor_id=None, contract_no=None), is_draft=True)


def test_yayinda_taseron_zorunlu():
    with pytest.raises(SiteValidationError) as hata:
        guards.validate_subcontract(_Sozlesme(subcontractor_id=None), is_draft=False)
    assert str(hata.value) == guards.SUBCONTRACTOR_REQUIRED


def test_bitis_baslangictan_once_olamaz_taslakta_bile():
    with pytest.raises(SiteValidationError) as hata:
        guards.validate_subcontract(
            _Sozlesme(start_date=date(2026, 5, 1), end_date=date(2026, 4, 1)), is_draft=True
        )
    assert str(hata.value) == guards.END_BEFORE_START


def test_santiye_zorunlu_degildir():
    """K4 onaylı sapma: FORM 59'daki * uygulanmaz."""
    guards.validate_subcontract(_Sozlesme(), is_draft=False)


def test_yayinda_proje_zorunlu():
    with pytest.raises(SiteValidationError) as hata:
        guards.validate_subcontract(_Sozlesme(project_id=None), is_draft=False)
    assert str(hata.value) == guards.PROJECT_REQUIRED


def test_yayinda_is_kategorisi_zorunlu():
    with pytest.raises(SiteValidationError) as hata:
        guards.validate_subcontract(_Sozlesme(work_category=""), is_draft=False)
    assert str(hata.value) == guards.CATEGORY_REQUIRED


def test_yayinda_is_kategorisi_bosluk_ise_zorunlu():
    with pytest.raises(SiteValidationError) as hata:
        guards.validate_subcontract(_Sozlesme(work_category="   "), is_draft=False)
    assert str(hata.value) == guards.CATEGORY_REQUIRED


def test_yayinda_sozlesme_no_zorunlu():
    with pytest.raises(SiteValidationError) as hata:
        guards.validate_subcontract(_Sozlesme(contract_no=None), is_draft=False)
    assert str(hata.value) == guards.CONTRACT_NO_REQUIRED


def test_yayinda_imza_tarihi_zorunlu():
    with pytest.raises(SiteValidationError) as hata:
        guards.validate_subcontract(_Sozlesme(signature_date=None), is_draft=False)
    assert str(hata.value) == guards.SIGNATURE_DATE_REQUIRED


def test_yayinda_tarihler_zorunlu():
    with pytest.raises(SiteValidationError) as hata:
        guards.validate_subcontract(_Sozlesme(start_date=None, end_date=None), is_draft=False)
    assert str(hata.value) == guards.DATES_REQUIRED


class _Kalem:
    def __init__(self, unit_price=None):
        self.unit_price = unit_price


def test_yayinda_kalem_birim_fiyati_zorunlu():
    with pytest.raises(SiteValidationError) as hata:
        guards.validate_subcontract(
            _Sozlesme(items=[_Kalem(unit_price=100), _Kalem(unit_price=None)]), is_draft=False
        )
    assert str(hata.value) == guards.ITEM_PRICES_REQUIRED


def test_yayinda_kalemler_bossa_fiyat_kurali_kosmaz():
    guards.validate_subcontract(_Sozlesme(items=[]), is_draft=False)


def test_taslakta_zorunluluk_kurallari_kosmaz_ama_tutarlilik_kosar():
    guards.validate_subcontract(
        _Sozlesme(project_id=None, subcontractor_id=None, work_category="", contract_no=None,
                  signature_date=None, start_date=None, end_date=None),
        is_draft=True,
    )
