"""İK-1 T3 — belge durum TÜREVİ SINIRLARI (spec §2, §3, §5 K1).

`status.derive_document_status` TEK KAYNAKTIR (T4 summary de bunu çağırır);
burada sabit tarihlerle sınırlar dondurulur — saat farkına bağlı test gece
yarısı kırılmasın diye `today` ENJEKTE edilir.

Eşik `EXPIRING_THRESHOLD_DAYS = 30`: 30 DAHİL (`expiring`), 31 HARİÇ (`valid`).
"""

from datetime import date, timedelta

from app.modules.personnel.status import (
    EXPIRING_THRESHOLD_DAYS,
    days_until,
    derive_document_status,
)

BUGUN = date(2026, 6, 15)


def test_esik_sabiti_otuz():
    assert EXPIRING_THRESHOLD_DAYS == 30


def test_valid_until_yok_suresiz_tip_valid():
    """valid_until NULL + validity_months NULL → valid (süresiz belge)."""
    assert derive_document_status(None, None, today=BUGUN) == "valid"


def test_valid_until_yok_sureli_tip_de_valid():
    """valid_until NULL + validity_months DOLU → yine valid: tarih girilmemiş,
    süre takibi başlamamıştır (spec §5 K1)."""
    assert derive_document_status(None, 12, today=BUGUN) == "valid"


def test_dun_expired():
    assert derive_document_status(BUGUN - timedelta(days=1), 12, today=BUGUN) == "expired"


def test_bugun_expiring():
    """Bugün son gün — henüz geçmemiş ama pencere içinde → expiring."""
    assert derive_document_status(BUGUN, 12, today=BUGUN) == "expiring"


def test_bugun_arti_30_expiring_sinir_dahil():
    assert derive_document_status(BUGUN + timedelta(days=30), 12, today=BUGUN) == "expiring"


def test_bugun_arti_31_valid_sinir_haric():
    assert derive_document_status(BUGUN + timedelta(days=31), 12, today=BUGUN) == "valid"


def test_uzak_gelecek_valid():
    assert derive_document_status(BUGUN + timedelta(days=400), None, today=BUGUN) == "valid"


def test_days_left_pozitif_negatif_ve_none():
    assert days_until(BUGUN + timedelta(days=5), today=BUGUN) == 5
    assert days_until(BUGUN - timedelta(days=3), today=BUGUN) == -3
    assert days_until(None, today=BUGUN) is None
