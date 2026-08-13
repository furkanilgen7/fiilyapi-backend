"""İK-2 T3 — yıllık hak / kalan / kullanım türevleri (saf hesap, HTTP'siz).

Spec: `docs/superpowers/specs/2026-08-12-ik2-izin-yonetimi-design.md` §2, §5 K1/K5.

Bu dosya `leave.py`nin **para-benzeri eşik yüzeyini** sınar: yıllık hak kademeleri
(4857), kalan formülü ve NULL-eşik kanonu (fail-closed). Kademe SINIRLARI tam tam
(0/1/5/15 yıl) ve İKİ YANDAN sınanır — tek yandan bakmak `<` ile `<=` arasındaki
kaymayı yakalamaz ve o kayma bir güne kadar fazla izin verdirir.

**Kıdem referans tarihi** (`balance_reference_date`) bilinçlidir: `min(bugün,
yılın 31 Aralık'ı)`. Geçmiş yıl için yıl sonu (o yıl kaç gün hak edildiyse o),
içinde bulunulan yıl için BUGÜN (henüz hak edilmemiş kademe verilmez), gelecek
yıl için yine BUGÜN — üçü de fail-closed yöndedir.
"""

from datetime import date
from decimal import Decimal

import pytest

from app.modules.personnel import leave

# 4857 kademe sınırlarının okunur adları — testte sihirli sayı bırakmamak için.
HAK_YOK = None
HAK_14 = 14
HAK_20 = 20
HAK_26 = 26


# --- Kıdem referans tarihi ---------------------------------------------------


@pytest.mark.parametrize(
    ("yil", "bugun", "beklenen"),
    [
        # Geçmiş yıl → o yılın 31 Aralık'ı (yıl kapandı, kıdem yıl sonunda dondu).
        (2024, date(2026, 8, 12), date(2024, 12, 31)),
        # İçinde bulunulan yıl → BUGÜN (henüz gelmemiş kademe peşin verilmez).
        (2026, date(2026, 8, 12), date(2026, 8, 12)),
        # Gelecek yıl → yine BUGÜN (fail-closed: ileri kademe peşin verilmez).
        (2030, date(2026, 8, 12), date(2026, 8, 12)),
    ],
)
def test_referans_tarihi_min_bugun_ve_yil_sonu(yil: int, bugun: date, beklenen: date) -> None:
    assert leave.balance_reference_date(yil, bugun) == beklenen


# --- Kıdem ayı ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("giris", "referans", "beklenen"),
    [
        (date(2024, 1, 1), date(2026, 2, 1), 25),  # 2 yıl 1 ay (mockup İZ 134)
        (date(2024, 1, 15), date(2026, 1, 14), 23),  # yıldönümü GÜNÜ dolmadan 23 ay
        (date(2024, 1, 15), date(2026, 1, 15), 24),  # yıldönümü GÜNÜ tam 24 ay
        (date(2026, 12, 1), date(2026, 8, 12), 0),  # gelecek işe giriş → 0 (fail-closed)
    ],
)
def test_kidem_ayi(giris: date, referans: date, beklenen: int) -> None:
    assert leave.completed_service_months(giris, referans) == beklenen


def test_kidem_ayi_hire_date_yoksa_none() -> None:
    """`hire_date` NULL → kıdem BİLİNMEZ (0 DEĞİL). Ayrım kritiktir: 0 "yeni işe
    girdi" demektir ve gelecek yıl hak doğurur; None "veri yok" demektir ve
    fail-closed engel üretir."""
    assert leave.completed_service_months(None, date(2026, 8, 12)) is None


# --- 4857 kademe sınırları (0 / 1 / 5 / 15 yıl) — İKİ YANDAN ----------------


@pytest.mark.parametrize(
    ("giris", "referans", "beklenen", "gerekce"),
    [
        # 0-1 yıl sınırı: yıldönümünden BİR GÜN ÖNCE hak YOK, yıldönümü GÜNÜ 14.
        (date(2025, 8, 12), date(2026, 8, 11), HAK_YOK, "1 yıl dolmadı (İZ 163)"),
        (date(2025, 8, 12), date(2026, 8, 12), HAK_14, "1 yıl tam doldu"),
        # 5 yıl sınırı: 4857 m.53 "bir yıldan BEŞ YILA KADAR (beş dahil)" → 5 tam = 14.
        (date(2021, 8, 13), date(2026, 8, 12), HAK_14, "4 yıl 11 ay"),
        (date(2021, 8, 12), date(2026, 8, 12), HAK_14, "tam 5 yıl (beş DAHİL → 14)"),
        (date(2021, 8, 11), date(2026, 8, 12), HAK_20, "5 yıl 1 gün → 20"),
        # 15 yıl sınırı: "onbeş yıl (dahil) ve daha fazla" → 15 tam = 26.
        (date(2011, 8, 13), date(2026, 8, 12), HAK_20, "14 yıl 11 ay"),
        (date(2011, 8, 12), date(2026, 8, 12), HAK_26, "tam 15 yıl (dahil → 26)"),
        (date(2000, 1, 1), date(2026, 8, 12), HAK_26, "26 yıl"),
    ],
)
def test_yillik_hak_kademe_sinirlari(
    giris: date, referans: date, beklenen: int | None, gerekce: str
) -> None:
    assert leave.annual_entitlement(giris, referans) == beklenen, gerekce


def test_yillik_hak_hire_date_yoksa_none() -> None:
    """🔴 NULL-EŞİK KANONU: `hire_date` NULL → hak BİLİNMEZ (None), 0 DEĞİL.

    0 döndürmek "hakkı yok ama hesap yapıldı" der ve `remaining` 0 çıkar; None
    "hesaplanamadı" der ve onay yolunda ENGEL üretir (fail-closed).
    """
    assert leave.annual_entitlement(None, date(2026, 8, 12)) is None


def test_yillik_hak_gelecek_ise_giris_none() -> None:
    """İşe giriş REFERANSTAN sonra → kıdem 0 → hak yok (negatif kıdem uydurulmaz)."""
    assert leave.annual_entitlement(date(2027, 1, 1), date(2026, 8, 12)) is None


# --- Kalan formülü (İZ doğrulaması: 14 + 3 − 6 = 11) ------------------------


def test_kalan_mockup_formulu() -> None:
    """İZ 134 satırı: hak 14 + devreden 3 − kullanılan 6 = 11."""
    assert leave.remaining_leave(14, Decimal("3"), 6) == Decimal("11")


def test_kalan_devreden_yoksa() -> None:
    """İZ 141 satırı: 14 + 0 − 5 = 9."""
    assert leave.remaining_leave(14, Decimal("0"), 5) == Decimal("9")


def test_kalan_negatif_olabilir() -> None:
    """Kalan NEGATİF çıkabilir ve 0'a KIRPILMAZ: hak aşımı zaten olmuş bir kayıt
    (elle düzeltilmiş bakiye / geçmiş onay) gizlenmemeli — ekran borcu görmeli."""
    assert leave.remaining_leave(14, Decimal("0"), 20) == Decimal("-6")


def test_kalan_hak_bilinmiyorsa_none() -> None:
    """🔴 fail-closed: hak None ise kalan da None — devreden dolu olsa BİLE.

    `None + 3 − 0 = 3` gibi bir "iyimser" sonuç üretmek, kıdemi dolmamış personele
    onay yolunu açardı.
    """
    assert leave.remaining_leave(None, Decimal("3"), 0) is None


# --- Kullanım yüzdesi (mockup ilerleme çubuğu) ------------------------------


@pytest.mark.parametrize(
    ("hak", "devreden", "kullanilan", "beklenen"),
    [
        (14, Decimal("3"), 6, 35),  # İZ 137: 6/17 = %35.29 → 35
        (14, Decimal("0"), 5, 36),  # İZ 144: 5/14 = %35.71 → 36 (YUVARLAMA yukarı)
        (14, Decimal("6"), 12, 60),  # İZ 151: 12/20 = %60
        (14, Decimal("0"), 0, 0),  # hiç kullanılmadı
    ],
)
def test_kullanim_yuzdesi(hak: int, devreden: Decimal, kullanilan: int, beklenen: int) -> None:
    assert leave.usage_pct(hak, devreden, kullanilan) == beklenen


def test_kullanim_yuzdesi_hak_bilinmiyorsa_none() -> None:
    assert leave.usage_pct(None, Decimal("0"), 0) is None


def test_kullanim_yuzdesi_payda_sifirsa_none() -> None:
    """Hak + devreden 0 ise yüzde TANIMSIZDIR — 0 ya da 100 uydurulmaz (bölme
    hatası da verilmez)."""
    assert leave.usage_pct(0, Decimal("0"), 0) is None


# --- Talebin sayıldığı YIL (yıl sınırı tuzağı) ------------------------------


@pytest.mark.parametrize(
    ("baslangic", "bitis", "beklenen"),
    [
        (date(2026, 8, 4), date(2026, 8, 8), 2026),
        # Yıl sınırını AŞAN talep BAŞLADIĞI yıla sayılır — gün BÖLÜNMEZ.
        (date(2026, 12, 30), date(2027, 1, 2), 2026),
        (date(2026, 1, 1), date(2026, 1, 1), 2026),
    ],
)
def test_talebin_sayildigi_yil_baslangic_yilidir(
    baslangic: date, bitis: date, beklenen: int
) -> None:
    """Karar: talep BAŞLANGIÇ tarihinin yılına sayılır, günler iki yıla BÖLÜNMEZ.

    Gerekçe: `days` TEK bir kolondur (spec §5 K2) ve bölme, kaydın kendi
    değeriyle bakiyeye giren değeri ayrıştırırdı (iki gerçek kaynak). Ayrıca
    onay anında tek bir yılın kalanına bakılır — bölünmüş talepte hangi yılın
    eşiği uygulanacağı belirsizleşirdi.
    """
    assert leave.leave_year(baslangic, bitis) == beklenen
