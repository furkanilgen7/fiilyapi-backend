"""ÖLÇÜM (kayıt 2 + 3): `get_db` teardown commit'i patladığında istemci NE görür.

Bu dosya kalıcı bir bekçi DEĞİL, kayıt 2/3'ün "kalan kol" iddiasını bugünün
kodunda (`app/core/db.py:83`, FastAPI 0.141.1) fiilen üretip belgelemek için
yazıldı. `get_db` bir async generator olduğu için FastAPI onu hesaplanmış
`scope="request"` ile ele alır (ölçüldü:
`.venv/.../fastapi/dependencies/models.py:229-234` `_get_computed_scope` —
generator/async-generator `call`larda `scope` açıkça verilmemişse "request"
döner), yani teardown `routing.py:145`teki
`await response(scope, receive, send)`ten SONRA çalışır.

## İki ayrı ölçüm, iki farklı görünür sonuç

1. `test_INPROCESS_asgi_transport_istisnayi_ceteveir` — `httpx.ASGITransport`
   ile İÇ SÜREÇTE çağrı: `request_stack.__aexit__`teki hata hiçbir ASGI
   sunucu sınırı geçmeden doğrudan çağırana (`await client.post(...)`)
   fırlar. Bu, hiçbir kayıtlı exception handler'ın (409 IntegrityError, 422
   DomainError, ...) ÇAĞRILMADIĞININ kanıtıdır: hata FastAPI'nin
   `wrap_app_handling_exceptions` sınırının DIŞINDA doğar.

2. `test_GERCEK_soket_uzerinden_istemci_200_gorur` — gerçek bir uvicorn
   sürecini alt süreç olarak başlatıp GERÇEK bir TCP soketi üzerinden
   isteği yapar. Burada ASGI sunucusu `await response(...)`i tamamlayıp
   yanıtı SOKETE YAZDIKTAN SONRA teardown patlar; istemci `200 {"ok": true}`
   görür (yazı zaten gönderilmiştir), sunucu ise `ERROR: Exception in ASGI
   application` diye ayrıca loglar. Kayıt 3'ün "istemci 200+gövde görür,
   veritabanına hiçbir şey yazılmamış olabilir" iddiası TAM BURADA doğrulanır.
"""

from __future__ import annotations

import socket
import subprocess
import sys
import time
from collections.abc import AsyncGenerator
from typing import Annotated

import httpx
import pytest
from fastapi import Depends, FastAPI

from app.core.exception_handlers import register_exception_handlers


class _PatlayanSession:
    async def commit(self) -> None:
        raise RuntimeError("teardown commit anında patladı")


async def _get_db_taklit() -> AsyncGenerator[_PatlayanSession, None]:
    session = _PatlayanSession()
    try:
        yield session
        await session.commit()
    except Exception:
        raise


#: 🔴 Rota kasıtlı olarak MODÜL DÜZEYİNDEDİR, `_uygulama_kur()`nun İÇİNE
#: gömülmez: `from __future__ import annotations` altında bir kapanış
#: (closure) fonksiyonunun `Annotated[...]` imzası `typing.get_type_hints`
#: ile çözülürken çevreleyen fonksiyonun yerel adlarını GÖRMEZ — bu da
#: FastAPI'nin `Depends()`i hiç fark etmeyip `db`yi sıradan bir ZORUNLU QUERY
#: parametresi sanmasına yol açar (ölçüldü: istemci `422 "db" query eksik`
#: görür, endpoint hiç çağrılmaz). Modül düzeyinde tanımlamak bu çözümleme
#: sorununu ortadan kaldırır.
_olcum_app = FastAPI()
register_exception_handlers(_olcum_app)


@_olcum_app.post("/kaydet")
async def _kaydet(
    db: Annotated[_PatlayanSession, Depends(_get_db_taklit)],
) -> dict[str, bool]:
    return {"ok": True}


async def test_INPROCESS_asgi_transport_istisnayi_ceteveir() -> None:
    """İç süreç çağrısında teardown hatası ASGI sınırını hiç geçmeden çağırana
    fırlar — yani HİÇBİR kayıtlı exception handler'a UĞRAMAZ."""
    transport = httpx.ASGITransport(app=_olcum_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        with pytest.raises(RuntimeError, match="teardown commit anında patladı"):
            await client.post("/kaydet")


def _bos_port_bul() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_GERCEK_soket_uzerinden_istemci_200_gorur() -> None:
    """🔴 ASIL ÖLÇÜM. Gerçek uvicorn süreci + gerçek TCP soketi.

    İstemci 200 + `{"ok": true}` görür; sunucu STDERR'ine ayrıca
    `Exception in ASGI application` basılır. İkisi birlikte kayıt 3'ün
    iddiasını KANITLAR: teardown'da patlayan commit istemciye SESSİZCE
    başarı gibi görünür.
    """
    port = _bos_port_bul()
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "tests.core._teardown_commit_asgi_app:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "info",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        base_url = f"http://127.0.0.1:{port}"
        for _ in range(50):
            try:
                httpx.get(f"{base_url}/openapi.json", timeout=0.2)
                break
            except httpx.TransportError:
                time.sleep(0.1)
        else:
            pytest.fail("uvicorn alt süreci zamanında ayağa kalkmadı")

        response = httpx.post(f"{base_url}/kaydet", timeout=5)
        assert response.status_code == 200, (
            "Beklenmedik: teardown hatası gerçek soket üzerinde 200 DIŞINDA bir "
            f"kod üretti (yani BEKLENENDEN İYİ davranıyor olabilir): "
            f"{response.status_code} {response.text}"
        )
        assert response.json() == {"ok": True}, response.text
    finally:
        proc.terminate()
        try:
            stdout, stderr = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, stderr = proc.communicate(timeout=5)

    assert "Exception in ASGI application" in stderr, (
        "Sunucu STDERR'inde beklenen 'Exception in ASGI application' izi yok; "
        f"ölçüm koşulları değişmiş olabilir. STDERR:\n{stderr}"
    )
    assert "teardown commit anında patladı" in stderr, stderr
