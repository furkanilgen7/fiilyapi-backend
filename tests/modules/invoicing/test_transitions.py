"""FAT-1 T2 — durum matrisi (`invoicing/transitions.py`, spec §3 · K1/K2).

İKİ YÖNÜN matrisleri AYRIDIR ve uçlar kendi `if status == …` denetimini
YAZMAZ — geçerli geçişlerin tamamı bu iki tablodadır.

Bu dosyanın en kritik iddiası **RET SEBEBİNİN AYIRT EDİLEBİLİRLİĞİDİR**: giden
faturaya `approve` atmak ile taslak faturaya `mark-collected` atmak ikisi de
409'dur ama AYNI HATA DEĞİLDİR. Birincisi "bu işlem bu yöne ait değil"
(istemci yanlış ucu çağırdı), ikincisi "kayıt bu aşamada değil" (yarış /
bayat ekran). Tek bir hata sınıfına indirgenseydi FGE ekranındaki bir düğme
kusuru ile eşzamanlı iki isteğin normal çekişmesi birbirinden ayrılamazdı.
"""

import pytest

from app.core.errors import ConflictError
from app.modules.invoicing import transitions
from app.modules.invoicing.models import InvoiceDirection, InvoiceStatus
from app.modules.invoicing.transitions import (
    INCOMING_TRANSITIONS,
    INITIAL_STATUS,
    OUTGOING_TRANSITIONS,
    InvoiceAction,
    TransitionRejection,
    classify_transition,
    next_status,
)

GIDEN = InvoiceDirection.outgoing
GELEN = InvoiceDirection.incoming


# --------------------------------------------------------------------------- #
# Matrisin İÇİ
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("durum", "islem", "beklenen"),
    [
        (InvoiceStatus.draft, InvoiceAction.send, InvoiceStatus.sent),
        (InvoiceStatus.sent, InvoiceAction.mark_collected, InvoiceStatus.collected),
    ],
)
def test_giden_matrisi_spec_zinciri(durum, islem, beklenen):
    """§3 giden: `draft ──send──▶ sent ──mark-collected──▶ collected`."""
    assert next_status(GIDEN, durum, islem) is beklenen


@pytest.mark.parametrize(
    ("islem", "beklenen"),
    [
        (InvoiceAction.approve, InvoiceStatus.approved),
        (InvoiceAction.dispute, InvoiceStatus.disputed),
    ],
)
def test_gelen_matrisi_pendingden_iki_yola_ayrilir(islem, beklenen):
    assert next_status(GELEN, InvoiceStatus.pending, islem) is beklenen


def test_islem_degerleri_uc_yollariyla_birebir():
    """`RequestAction` deseni: değerler uç yollarıdır, böylece router ile matris
    arasında ikinci bir eşleme sözlüğü gerekmez. `mark_collected`ın DEĞERİ
    tireli olmalıdır — alt çizgi olsaydı `/invoices/{id}/mark_collected` gibi
    repo dışı bir yol doğardı."""
    assert InvoiceAction.mark_collected.value == "mark-collected"
    assert {islem.value for islem in InvoiceAction} == {
        "send",
        "mark-collected",
        "approve",
        "dispute",
    }


def test_baslangic_durumu_yone_gore_ayrisir():
    """K2 — `draft` YALNIZ giden tarafta vardır; gelen fatura sisteme zaten
    kesilmiş olarak girer (FGE:69)."""
    assert INITIAL_STATUS[GIDEN] is InvoiceStatus.draft
    assert INITIAL_STATUS[GELEN] is InvoiceStatus.pending


# --------------------------------------------------------------------------- #
# YÖN DIŞI ≠ MATRİS DIŞI (bu dosyanın asıl sebebi)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("yon", "durum", "islem"),
    [
        (GIDEN, InvoiceStatus.draft, InvoiceAction.approve),
        (GIDEN, InvoiceStatus.sent, InvoiceAction.dispute),
        (GELEN, InvoiceStatus.pending, InvoiceAction.send),
        (GELEN, InvoiceStatus.approved, InvoiceAction.mark_collected),
    ],
)
def test_yon_disi_gecis_YON_sebebiyle_reddedilir(yon, durum, islem):
    assert classify_transition(yon, durum, islem) is TransitionRejection.wrong_direction


@pytest.mark.parametrize(
    ("yon", "durum", "islem"),
    [
        (GIDEN, InvoiceStatus.draft, InvoiceAction.mark_collected),
        (GIDEN, InvoiceStatus.sent, InvoiceAction.send),
        (GIDEN, InvoiceStatus.collected, InvoiceAction.mark_collected),
        (GELEN, InvoiceStatus.approved, InvoiceAction.approve),
        (GELEN, InvoiceStatus.disputed, InvoiceAction.dispute),
        (GELEN, InvoiceStatus.disputed, InvoiceAction.approve),
    ],
)
def test_matris_disi_gecis_MATRIS_sebebiyle_reddedilir(yon, durum, islem):
    assert classify_transition(yon, durum, islem) is TransitionRejection.invalid_transition


def test_iki_ret_sebebi_BIRBIRINDEN_AYIRT_EDILIR():
    """Çağıran (T4) ayrımı yapabilmelidir; ikisi de 409'a çıkacak olsa bile."""
    yon_disi = classify_transition(GIDEN, InvoiceStatus.draft, InvoiceAction.approve)
    matris_disi = classify_transition(GIDEN, InvoiceStatus.draft, InvoiceAction.mark_collected)
    assert yon_disi is not matris_disi
    assert {yon_disi, matris_disi} == set(TransitionRejection)


def test_yon_denetimi_durum_denetiminden_ONCE_kosar():
    """Gelen faturaya `send` atıldığında sebep YÖNDÜR — `draft` durumu gelen
    tarafta zaten hiç oluşmaz, ama sıra ters olsaydı hata "kayıt bu aşamada
    değil" derdi ve istemci yanlış ucu çağırdığını hiç öğrenemezdi."""
    assert (
        classify_transition(GELEN, InvoiceStatus.draft, InvoiceAction.send)
        is TransitionRejection.wrong_direction
    )


def test_gecerli_gecis_hic_reddedilmez():
    assert classify_transition(GIDEN, InvoiceStatus.draft, InvoiceAction.send) is None


# --------------------------------------------------------------------------- #
# `next_status` — tek kapı, iki mesaj
# --------------------------------------------------------------------------- #


def test_yon_disi_gecis_conflict_atar_ve_mesaji_ayrittir():
    with pytest.raises(ConflictError) as yon_hatasi:
        next_status(GIDEN, InvoiceStatus.draft, InvoiceAction.approve)
    with pytest.raises(ConflictError) as matris_hatasi:
        next_status(GIDEN, InvoiceStatus.draft, InvoiceAction.mark_collected)

    assert str(yon_hatasi.value) == transitions.WRONG_DIRECTION_MESSAGE
    assert str(matris_hatasi.value) == transitions.INVALID_TRANSITION_MESSAGE
    assert transitions.WRONG_DIRECTION_MESSAGE != transitions.INVALID_TRANSITION_MESSAGE


# --------------------------------------------------------------------------- #
# Matrisin ŞEKLİ — neyin OLMADIĞI da bir karardır
# --------------------------------------------------------------------------- #


def test_iki_matris_durum_kumeleri_KESISMEZ():
    """K1/K2 — giden ve gelen durumları ayrı kümelerdir. Kesişselerdi tek bir
    `status` süzgeci iki yönün kayıtlarını sessizce karıştırırdı."""
    giden_durumlar = {durum for durum, _ in OUTGOING_TRANSITIONS} | set(
        OUTGOING_TRANSITIONS.values()
    )
    gelen_durumlar = {durum for durum, _ in INCOMING_TRANSITIONS} | set(
        INCOMING_TRANSITIONS.values()
    )
    assert giden_durumlar == {InvoiceStatus.draft, InvoiceStatus.sent, InvoiceStatus.collected}
    assert gelen_durumlar == {
        InvoiceStatus.pending,
        InvoiceStatus.approved,
        InvoiceStatus.disputed,
    }
    assert not giden_durumlar & gelen_durumlar


def test_terminal_durumlar_hicbir_ciftte_KAYNAK_degildir():
    """`collected` / `approved` / `disputed` TERMİNALDİR. İptal/iade geçişi ve
    `approved` sonrası ödeme durumu KASITLI olarak yoktur (§3): ilki hiçbir
    mockup'ta çizilmemiştir, ikincisi Hazine diliminindir."""
    kaynaklar = {durum for durum, _ in OUTGOING_TRANSITIONS} | {
        durum for durum, _ in INCOMING_TRANSITIONS
    }
    assert InvoiceStatus.collected not in kaynaklar
    assert InvoiceStatus.approved not in kaynaklar
    assert InvoiceStatus.disputed not in kaynaklar


def test_matris_boyutlari_spec_ile_birebir():
    """Yeni bir geçiş eklemek bu sayıyı bozar — spec güncellenmeden matris
    büyüyemez ("tanımlı olanı say, gerisini reddet")."""
    assert len(OUTGOING_TRANSITIONS) == 2
    assert len(INCOMING_TRANSITIONS) == 2


def test_her_islem_TEK_bir_yone_aittir():
    giden_islemler = {islem for _, islem in OUTGOING_TRANSITIONS}
    gelen_islemler = {islem for _, islem in INCOMING_TRANSITIONS}
    assert giden_islemler == {InvoiceAction.send, InvoiceAction.mark_collected}
    assert gelen_islemler == {InvoiceAction.approve, InvoiceAction.dispute}
    assert not giden_islemler & gelen_islemler
    assert giden_islemler | gelen_islemler == set(InvoiceAction)
