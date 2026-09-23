"""🔴 `get_db`: commit `try`in DIŞINDAYDI (kayıt 21).

Patlayan commit açık `rollback` dalına GİRMİYORDU.

## Kusur

`app/core/db.py:76-82` şöyleydi:

    try:
        yield session
    except Exception:
        await session.rollback()
        raise
    else:
        await session.commit()

Docstring "bir istisna oluşursa rollback yapıp yeniden fırlatıyoruz" der; ama
`commit()` `else` dalındadır, yani KENDİ patlaması o `except`e HİÇ uğramaz.
Session `async with` kapanışında yalnız `close()` edilir (ölçüldü:
`AsyncSession.__aexit__` yalnızca `close()` çağırır) — rollback ÖRTÜK kalır.

## ⚠️ BU DOSYANIN SINIRI — neyi ölçmez

Bu testler `get_db`nin AKIŞ SIRASINI ölçer, HTTP kodunu DEĞİL. Teardown
commit'inde doğan bir hatanın 409'a dönememesi AYRI ve DAHA BÜYÜK bir kusurdur
(FastAPI 0.141.1 `routing.py:140-146`: `get_db` `request_stack`te sonlanır ve o
stack `await response(...)`ten SONRA çözülür; Starlette 1.6.0
`_exception_handler.py:55` `response_started` olduğu için işleyiciyi ÇAĞIRMAZ).
Onun onarımı 362 çağrı yerini `Depends(get_db, scope="function")`a çevirmeyi
gerektirir ve ÖLÇÜLMEDEN yapılamaz (`StreamingResponse` uçları gövdelerini
`function_stack` çözüldükten SONRA üretir — session kapanmış olurdu).
Ulaşılabilir somut hâli `tests/site_planning/test_ertelenmis_uq_http.py`de
kapatıldı.
"""

import pytest

import app.core.db as core_db
from app.core.db import get_db


class _SahteSession:
    """`AsyncSession`in `get_db`nin kullandığı SÖZLEŞMESİ kadarı.

    `__aexit__` yalnız `close()` çağırır — gerçeğinin birebiri (ölçüldü:
    `AsyncSession.__aexit__` → `asyncio.shield(self.close())`). Rollback'i bu
    kapanış YAPMAZ; dolayısıyla `cagrilar` listesinde "rollback" görünüyorsa
    onu `get_db` AÇIKÇA çağırmıştır.
    """

    def __init__(self, cagrilar: list[str], *, commit_patlar: bool) -> None:
        self.cagrilar = cagrilar
        self._commit_patlar = commit_patlar

    async def __aenter__(self) -> "_SahteSession":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def commit(self) -> None:
        self.cagrilar.append("commit")
        if self._commit_patlar:
            raise RuntimeError("commit anında veritabanı hatası")

    async def rollback(self) -> None:
        self.cagrilar.append("rollback")

    async def close(self) -> None:
        self.cagrilar.append("close")


def _yamala(monkeypatch: pytest.MonkeyPatch, *, commit_patlar: bool) -> list[str]:
    cagrilar: list[str] = []
    monkeypatch.setattr(
        core_db,
        "SessionLocal",
        lambda: _SahteSession(cagrilar, commit_patlar=commit_patlar),
    )
    return cagrilar


async def test_PATLAYAN_commit_ACIK_rollback_dalina_girer(monkeypatch) -> None:
    """🔴 ASIL BEKÇİ. Mutasyon: `commit()` yeniden `else:` dalına alınınca
    "rollback" listeden düşer ve bu test KIRMIZI olur."""
    cagrilar = _yamala(monkeypatch, commit_patlar=True)

    gen = get_db()
    await anext(gen)
    with pytest.raises(RuntimeError, match="commit anında veritabanı hatası"):
        await anext(gen)

    assert cagrilar == ["commit", "rollback", "close"], (
        "Patlayan commit açık `rollback` dalına girmedi; transaction'ın geri "
        f"alınması session kapanışının ÖRTÜK davranışına bırakıldı. Bulunan: {cagrilar}"
    )


async def test_TEMIZ_cikis_commit_eder_rollback_ETMEZ(monkeypatch) -> None:
    """🔴 POZİTİF KONTROL (aynası): "her hâlükârda rollback" mutantı yakalanır.

    Commit'i `try`in içine almak temiz yolu DEĞİŞTİRMEMELİ — `last_login_at`
    gibi flush edilmiş yazılar hâlâ commit edilmelidir.
    """
    cagrilar = _yamala(monkeypatch, commit_patlar=False)

    gen = get_db()
    await anext(gen)
    with pytest.raises(StopAsyncIteration):
        await anext(gen)

    assert cagrilar == ["commit", "close"], cagrilar


async def test_GOVDEDEN_gelen_istisna_rollback_edip_YENIDEN_firlatir(monkeypatch) -> None:
    """Mevcut `except` dalının gerilemesi: uç patlarsa rollback + yeniden fırlatma."""
    cagrilar = _yamala(monkeypatch, commit_patlar=False)

    gen = get_db()
    await anext(gen)
    with pytest.raises(ValueError, match="uç patladı"):
        await gen.athrow(ValueError("uç patladı"))

    assert cagrilar == ["rollback", "close"], cagrilar
