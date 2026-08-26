"""TB-TMPDIR bekçisi: xdist işçisinin geçici dizini KENDİNE ait olmalı.

Kanon: `--dist loadfile` DOSYA bütünlüğünü korur, SÜREÇ bütünlüğünü korumaz.
`tests/conftest.py`teki işçi başına `TMPDIR` yaması kaldırılırsa bu test
`-n` ile koşulan turda KIRMIZI olur (seri koşuda anlamsız → atlanır).
"""

import os
import tempfile

import pytest

XDIST_ISCI = os.environ.get("PYTEST_XDIST_WORKER")

pytestmark = pytest.mark.skipif(
    not XDIST_ISCI, reason="Seri koşuda işçi yalıtımı diye bir şey yoktur"
)


def test_gettempdir_isci_son_ekini_tasir():
    assert os.path.basename(tempfile.gettempdir()) == f"fiil-erp-test-{XDIST_ISCI}"


def test_tmpdir_ortam_degiskeni_de_yamalanir():
    """Alt süreçler `tempfile.tempdir`i DEĞİL `TMPDIR`i okur; ikisi de gerekir."""
    assert os.environ.get("TMPDIR") == tempfile.gettempdir()


def test_uretilen_gecici_dosya_isci_dizinine_duser():
    with tempfile.NamedTemporaryFile(prefix="tbtmpdir.") as f:
        assert os.path.dirname(f.name) == tempfile.gettempdir()
