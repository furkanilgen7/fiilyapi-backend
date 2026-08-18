"""FIN-1 T4 — K2 durum makinesinin TAM matrisi.

Emrin T6 maddesi acikca soyler: *"her gecerli gecis + her gecersiz gecis AYRI"*.
Bu dosya matrisi **TURETIR**, elle saymaz: `Status × Status × Direction`in
tamami gezilir ve tabloda olmayan her cift icin 409 beklenir. Elle yazilmis bir
liste, enum'a yeni bir uye eklendiginde SESSIZCE bayatlardi — turetilmis matris
o uyeyi ertesi kosuda kapsar.

🔴 **"%100 kapsam bir dogruluk kanıtı degildir" (MT-2 kanonu):** bir kumeyle
calisan bekci KUMENIN KENDISINI de sinamalidir. Bu yuzden asagida
`TRANSITIONS`in ve `TERMINAL_STATUSES`in KENDI icerigi de ayrica iddia edilir —
tablo yanlis olsaydi matris testi onu "dogru" sayarak yesil kalirdi.
"""

import itertools

import pytest

from app.core.errors import ConflictError
from app.modules.treasury.instruments import guards, transitions
from app.modules.treasury.models import FinancialInstrumentDirection as Yon
from app.modules.treasury.models import FinancialInstrumentStatus as Durum

_TUM_DURUMLAR = tuple(Durum)
_TUM_YONLER = tuple(Yon)


# --------------------------------------------------------------------------- #
# 🔴 Once TABLONUN KENDISI (MT-2 kanonu) — matris testi tabloyu dogrulamaz
# --------------------------------------------------------------------------- #


def test_gecis_tablosu_K2_ile_BIREBIR() -> None:
    """Emrin K2 metni burada KILITLI. Tablo degisirse bu test kirmizi olur ve
    degisiklik BILINCLI olmak zorunda kalir."""
    assert transitions.TRANSITIONS == {
        Yon.received: frozenset(
            {
                (Durum.portfolio, Durum.collected),
                (Durum.portfolio, Durum.returned),
                (Durum.portfolio, Durum.cancelled),
            }
        ),
        Yon.issued: frozenset(
            {
                (Durum.portfolio, Durum.paid),
                (Durum.portfolio, Durum.returned),
                (Durum.portfolio, Durum.cancelled),
            }
        ),
    }


def test_terminal_kumesi_TABLODAN_turetilir() -> None:
    """🔴 Elle yazilmis olsaydi tablodan sapabilirdi. Dort durum terminaldir ve
    `portfolio` DEGILDIR."""
    assert transitions.TERMINAL_STATUSES == frozenset(
        {Durum.collected, Durum.paid, Durum.returned, Durum.cancelled}
    )
    assert Durum.portfolio not in transitions.TERMINAL_STATUSES


def test_hicbir_gecis_TERMINALDEN_CIKMAZ() -> None:
    """K2'nin en sert kurali. Tabloya bir gun `(collected, portfolio)` eklenirse
    bu test kirmizi olur — matris testi ise onu "gecerli" sayip YESIL kalirdi."""
    for cift_kumesi in transitions.TRANSITIONS.values():
        for kaynak, _ in cift_kumesi:
            assert kaynak is Durum.portfolio


# --------------------------------------------------------------------------- #
# GECERLI gecisler — her biri AYRI (emir T6)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("yon", "hedef"),
    [
        (Yon.received, Durum.collected),
        (Yon.received, Durum.returned),
        (Yon.received, Durum.cancelled),
        (Yon.issued, Durum.paid),
        (Yon.issued, Durum.returned),
        (Yon.issued, Durum.cancelled),
    ],
)
def test_GECERLI_gecis_gecer(yon: Yon, hedef: Durum) -> None:
    transitions.assert_transition(yon, Durum.portfolio, hedef)


# --------------------------------------------------------------------------- #
# 🔴 YON UYUMU — iki dal AYRI testlerle (emir: "tek testte toplama")
# --------------------------------------------------------------------------- #


def test_ALINAN_cek_ODENDI_olamaz() -> None:
    """Parayi biz odemedik: `paid` verilen cekin hedefidir. Tani da AYRIDIR —
    kullanici hedefi degil YONU yanlis okumustur."""
    with pytest.raises(ConflictError) as hata:
        transitions.assert_transition(Yon.received, Durum.portfolio, Durum.paid)
    assert str(hata.value) == guards.DIRECTION_MISMATCH


def test_VERILEN_cek_TAHSIL_EDILDI_olamaz() -> None:
    """Verilen cekin karsiligi CIKAR, tahsil edilmez."""
    with pytest.raises(ConflictError) as hata:
        transitions.assert_transition(Yon.issued, Durum.portfolio, Durum.collected)
    assert str(hata.value) == guards.DIRECTION_MISMATCH


# --------------------------------------------------------------------------- #
# TERMINAL koruma — dort durumun DORDU DE
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("kaynak", sorted(transitions.TERMINAL_STATUSES, key=lambda d: d.value))
@pytest.mark.parametrize("yon", _TUM_YONLER)
def test_TERMINAL_kaynaktan_HICBIR_hedefe_gidilmez(kaynak: Durum, yon: Yon) -> None:
    """Tani `TERMINAL_STATUS`tur, "gecersiz gecis" DEGIL: kullanicinin
    yapabilecegi sey farklidir (yeni kayit ac vs. baska hedef sec)."""
    for hedef in _TUM_DURUMLAR:
        with pytest.raises(ConflictError) as hata:
            transitions.assert_transition(yon, kaynak, hedef)
        assert str(hata.value) == guards.TERMINAL_STATUS, (kaynak, hedef)


def test_TERMINAL_kaydin_tanisi_TERMINAL_STATUS_tur() -> None:
    """`collected` bir "alinan" cekte `paid` denenirse asil engel kaydin KAPALI
    olmasidir, yon degil."""
    with pytest.raises(ConflictError) as hata:
        transitions.assert_transition(Yon.received, Durum.collected, Durum.paid)
    assert str(hata.value) == guards.TERMINAL_STATUS


def test_terminal_ve_yon_dallari_BUGUN_ORTUSMEZ_ve_bu_YAPISAL_olarak_kanitlanir() -> None:
    """🔴 T4 MUTASYON TURU BULGUSU — "ayni yesil iki farkli anlam tasir"
    (BOR-TEMIZ kanonu).

    `assert_transition` icindeki terminal ve yon dallarinin YERINI DEGISTIREN
    mutasyon 66 testin HICBIRINI kirmizi yapmadi. Once "bekci eksik" sanildi;
     olculdugunde sebep BASKA cikti: **iki dal bugun ASLA ayni girdide
    bulusamaz.** Cunku tablodaki her cifin kaynagi `portfolio`dur, yani
    "kaynak terminal" ile "cift obur yonun tablosunda" kosullari KESISMEZ.

    Yani sira bugun GOZLENEBILIR DEGILDIR ve deger testi yazmak MUMKUN DEGILDIR
    — bir davranis testi yazilsaydi hicbir sey kanitlamayan bir bekci olurdu.
    Iddia bu yuzden YAPISALDIR: kesisimin bos oldugu dogrudan olculur.

    Tabloya bir gun terminal kaynakli bir cift eklenirse (or.
    `(returned, portfolio)`) bu test KIRMIZI olur ve o gun sira GERCEKTEN onem
    kazanir — o an davranis bekcisi de yazilabilir hâle gelir.
    """
    for yon in _TUM_YONLER:
        obur_kaynaklar = {kaynak for kaynak, _ in transitions.TRANSITIONS[_obur(yon)]}
        assert obur_kaynaklar & transitions.TERMINAL_STATUSES == set(), yon


def _obur(yon: Yon) -> Yon:
    return Yon.issued if yon is Yon.received else Yon.received


# --------------------------------------------------------------------------- #
# TAM MATRIS — tabloda olmayan HER cift 409
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("yon", "kaynak", "hedef"),
    [
        (yon, kaynak, hedef)
        for yon, kaynak, hedef in itertools.product(_TUM_YONLER, _TUM_DURUMLAR, _TUM_DURUMLAR)
        if (kaynak, hedef) not in transitions.TRANSITIONS[yon]
    ],
)
def test_TABLODA_OLMAYAN_her_cift_409(yon: Yon, kaynak: Durum, hedef: Durum) -> None:
    """ "Tanimli olani say, gerisini reddet": yeni bir durum eklendiginde
    varsayilan davranis REDDETMEKTIR."""
    with pytest.raises(ConflictError):
        transitions.assert_transition(yon, kaynak, hedef)


def test_matris_gercekten_GENIS() -> None:
    """🔴 Matris parametrelerinin BOS olmadigi ayrica olculur.

    `TRANSITIONS` bir gun yanlislikla TUM ciftleri iceren bir kumeye
    donusturulseydi yukaridaki parametre listesi BOSALIR ve test "0 kosu ile
    yesil" gorunurdu — hicbir sey kanitlamayan bir bekci (2026-08-14'un
    `length > 0` dersi).
    """
    gecersiz = [
        (yon, kaynak, hedef)
        for yon, kaynak, hedef in itertools.product(_TUM_YONLER, _TUM_DURUMLAR, _TUM_DURUMLAR)
        if (kaynak, hedef) not in transitions.TRANSITIONS[yon]
    ]
    # 2 yon × 5 kaynak × 5 hedef = 50 cift; 6'si gecerli → 44 gecersiz.
    assert len(gecersiz) == 44


def test_portfolio_portfolio_gecisi_YOKTUR() -> None:
    """ "Degismedi" sessizce basari sayilsaydi ekran, gecersiz bir dugmeyi
    calisiyor sanirdi (`assert_order_transition` kanonu)."""
    for yon in _TUM_YONLER:
        with pytest.raises(ConflictError) as hata:
            transitions.assert_transition(yon, Durum.portfolio, Durum.portfolio)
        assert str(hata.value) == guards.INVALID_TRANSITION
