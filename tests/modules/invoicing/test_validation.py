"""FAT-1 T2 — K6 kapısı ve gövde kuralları (`invoicing/validation.py`).

K6, NULL-EŞİK kanonunun (SA dersi) kardeşidir: **"kalem yok" ile "tutar sıfır"
aynı 0'ı üretmemelidir.** Kalemsiz bir fatura `amounts.compute` tarafından
kusursuz biçimde 0,00₺ olarak hesaplanır — hesap doğrudur, FATURA yanlıştır.
Ayrımı yapan tek yer bu modüldür ve kapı `send`/`approve` anındadır; `draft`
kaydetmek serbesttir (FK:24 "Taslak Kaydet" yarım formu saklayabilmelidir,
`procurement/validation.py` deseninin aynısı).

Fonksiyonlar İSTİSNA ATMAZ, ENGEL LİSTESİ döndürür — T3/T4 hepsini tek 422'de
gösterebilsin (kullanıcıya eksikleri birer birer keşfettirmek FK gibi uzun bir
formda kabul edilemez).
"""

from decimal import Decimal

import pytest

from app.modules.invoicing import validation
from app.modules.invoicing.models import InvoiceDirection
from app.modules.invoicing.transitions import InvoiceAction

GIDEN = InvoiceDirection.outgoing
GELEN = InvoiceDirection.incoming


class _Kalem:
    """Kalem yerine geçen en küçük nesne — `validation` ORM'e BAĞLI DEĞİLDİR."""


# --------------------------------------------------------------------------- #
# K6 — kalemsiz fatura kapıdan geçemez
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("islem", [InvoiceAction.send, InvoiceAction.approve])
def test_k6_kalemsiz_fatura_kapidan_GECEMEZ(islem):
    assert validation.gate_blockers(islem, []) == [validation.LINES_REQUIRED]


@pytest.mark.parametrize("islem", [InvoiceAction.send, InvoiceAction.approve])
def test_kalemli_fatura_kapidan_gecer(islem):
    assert validation.gate_blockers(islem, [_Kalem()]) == []


@pytest.mark.parametrize("islem", [InvoiceAction.mark_collected, InvoiceAction.dispute])
def test_kapi_YALNIZ_send_ve_approve_icindir(islem):
    """`mark-collected` ve `dispute` kalem denetimi YAPMAZ: ilki zaten kalemli
    bir `sent` faturadan gelir, ikincisi bir REDDETMEDİR — eksik kalem itirazı
    engellemek için sebep değildir."""
    assert validation.gate_blockers(islem, []) == []


def test_kapi_islemleri_kumesi_spec_ile_birebir():
    assert validation.GATE_ACTIONS == frozenset({InvoiceAction.send, InvoiceAction.approve})


# --------------------------------------------------------------------------- #
# Gövde kuralları
# --------------------------------------------------------------------------- #


def test_kesinti_oranlari_toplami_100u_asamaz():
    """Aşarsa `tax_base` NEGATİF olurdu (§5 4. adım) — `total` üzerindeki DB
    CHECK'i onu ancak KDV'den sonra, kullanıcıya 500 olarak gösterirdi."""
    engeller = validation.body_blockers(advance_rate=Decimal("70"), retention_rate=Decimal("40"))
    assert engeller == [validation.DEDUCTION_RATES_EXCEED_TOTAL]


def test_kesinti_oranlari_toplami_tam_100_serbesttir():
    """Matrahı sıfırlayan fatura anlamlıdır (tamamı avanstan mahsup) ve
    `amounts` onu 0,00₺ olarak hesaplar — negatif değildir."""
    assert validation.body_blockers(advance_rate=Decimal("60"), retention_rate=Decimal("40")) == []


def test_isaretlenmemis_kesinti_NULL_sifir_gibi_sayilir():
    assert validation.body_blockers(advance_rate=None, retention_rate=Decimal("100")) == []
    assert validation.body_blockers(advance_rate=None, retention_rate=None) == []


# --------------------------------------------------------------------------- #
# Numara sahipliği (§4 / S5)
# --------------------------------------------------------------------------- #


def test_giden_faturada_istemci_numara_GONDEREMEZ():
    """Numarayı sunucu üretir (§4). İstemci gönderebilseydi `FIL` serisinde
    boşluk/çakışma açardı ve advisory kilidin garantisi anlamsızlaşırdı."""
    assert validation.invoice_no_blockers(GIDEN, "FIL2026000184") == [
        validation.OUTGOING_NUMBER_IS_SERVER_ASSIGNED
    ]
    assert validation.invoice_no_blockers(GIDEN, None) == []


def test_gelen_faturada_numara_ZORUNLUDUR():
    """Satıcının kendi serisi (FY:165/174/183 üç ayrı seri kökü) — sunucu
    üretemez, üretseydi gerçek belgeyle bağ kopardı."""
    assert validation.invoice_no_blockers(GELEN, None) == [validation.INCOMING_NUMBER_REQUIRED]
    assert validation.invoice_no_blockers(GELEN, "   ") == [validation.INCOMING_NUMBER_REQUIRED]
    assert validation.invoice_no_blockers(GELEN, "LT2026070184") == []
