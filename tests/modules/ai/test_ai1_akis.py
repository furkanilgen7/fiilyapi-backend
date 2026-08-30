"""AI-1 SSE kodlaması bekçileri (`app/modules/ai/stream.py`).

🔴 Akış sözleşmesi **olay adlarıdır**, sınıf adları değil. Bir sınıf yeniden
adlandırılırsa `_OLAY_ADLARI` üzerinden ad da değişir ve panel sessizce sağır
kalırdı; bu dosya o bağı görünür kılar.
"""

from __future__ import annotations

import pytest

from app.modules.ai.providers.base import (
    AracSonuclandi,
    Kullanim,
    MetinParcasi,
    TurBitti,
    TurSebebi,
)
from app.modules.ai.stream import sse_akisi, sse_kodla

pytestmark = pytest.mark.asyncio


def test_sse_karesi_TEK_SATIR_data_tasir() -> None:
    kare = sse_kodla(MetinParcasi(metin="satır1\nsatır2")).decode()
    assert kare.startswith("event: metin\n")
    govde = kare.split("data: ", 1)[1]
    assert govde.count("\n") == 2  # yalnız kapanış \n\n
    assert kare.endswith("\n\n")


def test_sse_olay_adlari_SABIT_kume() -> None:
    """Sınıf adı değişirse akış sözleşmesi değişir; bu satır onu görünür kılar."""
    assert sse_kodla(MetinParcasi(metin="x")).startswith(b"event: metin")
    assert sse_kodla(
        AracSonuclandi(cagri_id="c", arac_adi="a", hal="Ok", mesaj="m", satir_sayisi=1)
    ).startswith(b"event: arac_sonuc")
    assert sse_kodla(TurBitti(sebep=TurSebebi.bitti, kullanim=Kullanim())).startswith(
        b"event: tur_bitti"
    )


async def test_sse_akisi_ON_YORUMU_ILK_gonderir() -> None:
    async def _olaylar():
        yield MetinParcasi(metin="a")

    kareler = [k async for k in sse_akisi(_olaylar())]
    assert kareler[0].startswith(b": ")
    assert kareler[1].startswith(b"event: metin")


def test_sse_tur_bitti_SEBEBI_metin_olarak_kodlar() -> None:
    kare = sse_kodla(
        TurBitti(sebep=TurSebebi.filtrelendi, kullanim=Kullanim(girdi=1, cikti=2))
    ).decode()
    assert '"sebep": "filtrelendi"' in kare
    assert '"girdi": 1' in kare
