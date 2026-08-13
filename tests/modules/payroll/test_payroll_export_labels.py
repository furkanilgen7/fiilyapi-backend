"""İK-3 T5 — Excel etiket sözlüklerinin dayanıklılığı (saf, DB'siz).

🔴 **T2 dersi:** `SOZLUK[enum]` yazımı, paylaşılan bir enum genişlediğinde
(İK-3 `worker_source` tipine `freelance` + `intern` ekledi) export'u sessizce
`KeyError` → **500** yapıyordu. Erişim `_label` üzerinden dayanıklıdır ama düşüş
SESSİZ DEĞİLDİR (WORKFLOW §3): etiket eklemeyi unutan sonraki dilim hücrede
`?yeni_deger` görür.

Bu dosya `test_payroll_export.py`ten AYRIDIR çünkü buradaki testler saf
fonksiyon testleridir: DB, istemci ve olay döngüsü GEREKTİRMEZ.
"""

from app.modules.payroll.export import (
    SECTION_LABELS,
    SOURCE_LABELS,
    STATUS_LABELS,
    section_label,
    source_label,
    status_label,
)
from app.modules.payroll.models import PayrollLineStatus
from app.modules.site_diary.models import WorkerSource


class _Tanimsiz:
    """Sözlüklerde KARŞILIĞI OLMAYAN bir enum değerini taklit eder."""

    value = "yeni_deger"


def test_tanimsiz_deger_GORUNUR_duser_500_URETMEZ():
    tanimsiz = _Tanimsiz()
    assert status_label(tanimsiz) == "?yeni_deger"
    assert section_label(tanimsiz) == "?yeni_deger"
    assert source_label(tanimsiz) == "?yeni_deger"


def test_bes_satir_durumunun_da_etiketi_vardir():
    for durum in PayrollLineStatus:
        assert status_label(durum) == STATUS_LABELS[durum]
        assert not STATUS_LABELS[durum].startswith("?")


def test_tum_personel_tiplerinin_bolum_ve_rozet_etiketi_vardir():
    """`general` dahil: bordro tipi değildir ama satırı varsa GİZLENMEZ."""
    for kaynak in WorkerSource:
        assert not section_label(kaynak).startswith("?")
        assert not source_label(kaynak).startswith("?")
        assert kaynak in SECTION_LABELS
        assert kaynak in SOURCE_LABELS
