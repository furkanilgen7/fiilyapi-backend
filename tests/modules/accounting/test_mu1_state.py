"""MU-1 T3b — K2 durum makinesi + K1 kapısının SAF çekirdeği (spec §4, §5).

Bu dosya DB'ye ve HTTP'ye HİÇ dokunmaz: `transitions.py` ile `validation.py`nin
karar veren kısmı saf fonksiyonlardır ve burada tek tek kilitlenir. Uçtan geçen
karşılıkları `test_mu1_journal_api.py`dedir; ikisi birden olmadan bir kusur ya
uçta ya matriste saklanabilirdi.

## Kilitlenen kararlar

1. 🔴 **Matris TEK KOPYADIR ve tabloda olmayan HER çift 409'dur.** "Tanımlı
   olanı say, gerisini reddet": ileride yeni bir durum eklenirse varsayılan
   davranış REDDETMEKTİR.
2. 🔴 **`reversed` TERMİNALDİR** — hiçbir çiftte KAYNAK değildir. Stornonun
   stornosu sonsuz zincir açardı, mali anlamı yoktur.
3. **Düzenleme/silme kapıları da DURUM kapısıdır** ve matrisin yanında durur:
   servis ya da uçta `if status == …` YOKTUR.
4. 🔴 **K1'in üç engeli TEK listede toplanır** (FAT-1 `_raise_blockers` deseni):
   kullanıcıya eksikleri birer birer keşfettirmek kabul edilemez.
5. 🔴 **Denge karşılaştırması TAM, tolerans YOKTUR** (HZ-1 K6): bir kuruş fark
   dengesizliktir.
6. **K1 kapısı yalnız `post`ta koşar** — `reverse` dengeli bir `posted` fişten
   gelir ve kendi 409'ları vardır (spec §7: reverse'ün 422'si yoktur).
"""

from decimal import Decimal

import pytest

from app.core.errors import ConflictError
from app.modules.accounting import guards, transitions, validation
from app.modules.accounting.models import JournalEntryStatus
from app.modules.accounting.transitions import JournalAction


class _Satir:
    """`.debit`/`.credit` taşıyan asgari çift — kapı ORM'e bağlı DEĞİLDİR.

    Aynı fonksiyon hem gövdedeki Pydantic satırlarından hem DB'deki
    `JournalLine`lardan çağrılır; şekil dayatsaydı "dengesiz fiş" tanımı iki
    yerde ayrışırdı.
    """

    def __init__(self, debit: str, credit: str) -> None:
        self.debit = Decimal(debit)
        self.credit = Decimal(credit)


# --------------------------------------------------------------------------- #
# 1. Matris
# --------------------------------------------------------------------------- #


def test_matris_TAM_OLARAK_iki_gecis_tanimlar() -> None:
    """`draft ──post──▶ posted ──reverse──▶ reversed` — üçüncü bir çift YOKTUR.

    Sayı iddiası bilinçlidir: sessizce eklenen bir geçiş (ör. `posted → draft`
    "geri al") mali izi delerdi ve davranış testleri onu görmezdi.
    """
    assert transitions.JOURNAL_TRANSITIONS == {
        (JournalEntryStatus.draft, JournalAction.post): JournalEntryStatus.posted,
        (JournalEntryStatus.posted, JournalAction.reverse): JournalEntryStatus.reversed,
    }


def test_baslangic_durumu_SUNUCUDA_taslaktir() -> None:
    """Gövde `status` gönderemez (şema 422); başlangıç TEK yerde durur."""
    assert transitions.INITIAL_STATUS is JournalEntryStatus.draft


@pytest.mark.parametrize(
    ("status", "action"),
    [
        (JournalEntryStatus.posted, JournalAction.post),
        (JournalEntryStatus.reversed, JournalAction.post),
        (JournalEntryStatus.draft, JournalAction.reverse),
        (JournalEntryStatus.reversed, JournalAction.reverse),
    ],
)
def test_matris_disi_her_cift_409(status: JournalEntryStatus, action: JournalAction) -> None:
    """Tabloda olmayan çift **409**dur — 403 DEĞİL: yetki VARDIR, engel DURUMDUR."""
    with pytest.raises(ConflictError) as hata:
        transitions.next_status(status, action)
    assert str(hata.value) == guards.INVALID_TRANSITION


def test_reversed_TERMINALDIR_hicbir_ciftte_kaynak_degildir() -> None:
    """🔴 Stornolanmış fiş bir daha hareket etmez (spec §5)."""
    kaynaklar = {durum for durum, _ in transitions.JOURNAL_TRANSITIONS}
    assert JournalEntryStatus.reversed not in kaynaklar


def test_gecerli_gecisler_hedef_durumu_dondurur() -> None:
    assert (
        transitions.next_status(JournalEntryStatus.draft, JournalAction.post)
        is JournalEntryStatus.posted
    )
    assert (
        transitions.next_status(JournalEntryStatus.posted, JournalAction.reverse)
        is JournalEntryStatus.reversed
    )


# --------------------------------------------------------------------------- #
# 2. Düzenleme / silme kapıları
# --------------------------------------------------------------------------- #


def test_uc_kapi_da_YALNIZ_taslagi_kabul_eder() -> None:
    tek = frozenset({JournalEntryStatus.draft})
    assert transitions.EDITABLE_STATUS == tek
    assert transitions.LINES_EDITABLE_STATUS == tek
    assert transitions.DELETABLE_STATUS == tek


@pytest.mark.parametrize("status", [JournalEntryStatus.posted, JournalEntryStatus.reversed])
def test_kayitli_fis_duzenlenemez_ve_silinemez(status: JournalEntryStatus) -> None:
    """Üçü de **409**dur (403 değil): kullanıcının yetkisi VARDIR."""
    for kapi, metin in (
        (transitions.assert_editable, guards.JOURNAL_ENTRY_NOT_EDITABLE),
        (transitions.assert_lines_editable, guards.JOURNAL_ENTRY_NOT_EDITABLE),
        (transitions.assert_deletable, guards.JOURNAL_ENTRY_NOT_DELETABLE),
    ):
        with pytest.raises(ConflictError) as hata:
            kapi(status)
        assert str(hata.value) == metin


def test_taslakta_uc_kapi_da_gecer() -> None:
    transitions.assert_editable(JournalEntryStatus.draft)
    transitions.assert_lines_editable(JournalEntryStatus.draft)
    transitions.assert_deletable(JournalEntryStatus.draft)


# --------------------------------------------------------------------------- #
# 3. K1 — tutar engelleri (SAF kısım)
# --------------------------------------------------------------------------- #


def test_dengeli_iki_satirda_engel_YOKTUR() -> None:
    assert validation.amount_blockers([_Satir("100.00", "0"), _Satir("0", "100.00")]) == []


def test_denge_KURUS_bazinda_TAMdir_tolerans_yoktur() -> None:
    """🔴 HZ-1 K6: bir kuruş fark dengesizliktir. Tolerans girseydi her fişte
    bir kuruş kaçak meşrulaşır ve mizan yıl sonunda kayardı."""
    engeller = validation.amount_blockers([_Satir("100.00", "0"), _Satir("0", "99.99")])
    assert engeller == [validation.UNBALANCED]


def test_olceksiz_esitlik_dengesizlik_SAYILMAZ() -> None:
    """`Decimal("100.00") == Decimal("100.000")` sayısal eşitliktir; ölçek farkı
    bir kuruş farkı DEĞİLDİR ve sahte 422 üretmemelidir."""
    assert validation.amount_blockers([_Satir("100.000", "0"), _Satir("0", "100.00")]) == []


def test_tek_satirli_fis_ENGELLIDIR() -> None:
    """Çift taraflı kaydın tanımı gereği en az iki bacak olmalıdır."""
    assert validation.amount_blockers([_Satir("100.00", "0")]) == [
        validation.UNBALANCED,
        validation.MIN_LINES_REQUIRED,
    ]


def test_bos_satir_kumesi_ENGELLIDIR() -> None:
    """Satırsız fiş `Σ = 0 = Σ` olduğu için DENGELİ görünür — ama fiş değildir.

    Engel yalnız satır SAYISINDAN gelir; denge engeli burada ısırmaz ve bu
    ayrım bilinçlidir (NULL-EŞİK kanonunun kardeşi: "hesap doğru, kayıt yanlış").
    """
    assert validation.amount_blockers([]) == [validation.MIN_LINES_REQUIRED]


def test_engeller_TEK_listede_birikir_sira_sabittir() -> None:
    """🔴 Kullanıcı eksikleri birer birer keşfetmez (FAT-1 `_raise_blockers`)."""
    engeller = validation.amount_blockers([_Satir("100.00", "0")])
    assert len(engeller) == 2


def test_K1_kapisi_YALNIZ_post_islemine_uygulanir() -> None:
    """`reverse` dengeli bir `posted` fişten gelir; kendi engelleri 409'dur
    (spec §7: `reverse`ün 422'si YOKTUR)."""
    assert validation.GATE_ACTIONS == frozenset({JournalAction.post})
