"""İK-3 T3 — durum geçiş tablosu (spec §6/7, S8).

BY 56/303 ve BG durum sütunu iki zincir çiziyor:

    dönem : draft → pending_approval → approved → paid
    satır : uncomputed → pending → approved → paid

**Atlama YOKTUR** ve tabloda olmayan her çift 409'dur — "tanımlı olanı say,
gerisini reddet" (emsal: `progress_payments/transitions.py`). Yeni bir durum
eklendiğinde varsayılan davranış REDDETMEKTİR.
"""

import pytest

from app.core.errors import ConflictError
from app.modules.payroll import transitions
from app.modules.payroll.models import PayrollLineStatus, PayrollPeriodStatus


def test_donem_durum_ATLAMASI_409():
    """🔴 S8 — `draft → approved` bir ADIM ATLAR: onay bekleme hiç yaşanmamış olurdu."""
    with pytest.raises(ConflictError):
        transitions.assert_period_transition(
            PayrollPeriodStatus.draft, PayrollPeriodStatus.approved
        )


def test_donem_komsu_gecisleri_serbest():
    for kaynak, hedef in (
        (PayrollPeriodStatus.draft, PayrollPeriodStatus.pending_approval),
        (PayrollPeriodStatus.pending_approval, PayrollPeriodStatus.approved),
        (PayrollPeriodStatus.approved, PayrollPeriodStatus.paid),
    ):
        transitions.assert_period_transition(kaynak, hedef)


def test_odenmis_donem_TERMINALDIR():
    """`paid` hiçbir çiftte KAYNAK değildir — ödeme izi geri sarılmaz."""
    for hedef in PayrollPeriodStatus:
        with pytest.raises(ConflictError):
            transitions.assert_period_transition(PayrollPeriodStatus.paid, hedef)


def test_satir_hesaplaninca_pending_olur():
    """K3 override'ı `uncomputed` satırı ödenebilir kılar (S4'ün çıkış kapısı)."""
    transitions.assert_line_transition(PayrollLineStatus.uncomputed, PayrollLineStatus.pending)


def test_satir_durum_ATLAMASI_409():
    with pytest.raises(ConflictError):
        transitions.assert_line_transition(PayrollLineStatus.uncomputed, PayrollLineStatus.approved)
    with pytest.raises(ConflictError):
        transitions.assert_line_transition(PayrollLineStatus.pending, PayrollLineStatus.paid)


def test_taseron_satiri_HICBIR_hedefe_gecemez():
    """🔴 K2 — `excluded` yapısal bir terminaldir: çift ödeme imkânsız olmalı."""
    for hedef in PayrollLineStatus:
        with pytest.raises(ConflictError):
            transitions.assert_line_transition(PayrollLineStatus.excluded, hedef)


def test_onayli_satir_yalniz_PENDINGE_geri_alinir():
    """S5'in düzeltme yolu (spec §6/4): tek geri geçiş `approved → pending`.

    Dönem `paid` iken bunun da kapalı olması SERVİSİN işidir (T4) — tablo
    yalnız çiftin ŞEKLİNİ bilir, kaydın bağlamını değil.
    """
    transitions.assert_line_transition(PayrollLineStatus.approved, PayrollLineStatus.pending)
    with pytest.raises(ConflictError):
        transitions.assert_line_transition(PayrollLineStatus.paid, PayrollLineStatus.pending)
