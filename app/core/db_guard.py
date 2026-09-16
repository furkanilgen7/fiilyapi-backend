"""Uzak veritabanına yanlışlıkla bağlanmayı engelleyen FAIL-CLOSED kapı.

🔴 **Ölçülmüş olay (P7).** `backend/.env` içindeki `DATABASE_URL` ve `TEST_DATABASE_URL`
UZAK Railway sunucusunu gösterir (`tokaido.proxy.rlwy.net:31217` → `railway` ve
`fiil_erp_test`). Backend kökünde override'sız `alembic upgrade head` yazan biri —
insan ya da ajan — CANLI şemayı değiştirdi ve `alembic_version`ı damgaladı; damga imajın
beklediği revizyondan ayrışınca `Dockerfile`ın `alembic upgrade head && uvicorn …` açılışı
`Can't locate revision` ile patladı, `&&` kısa devre yaptı, uvicorn hiç başlamadı.
`alembic downgrade` ise doğrudan veri kaybıdır. Tuzağın ikinci ağzı test tarafındadır:
`tests/conftest.py` oturum başında `Base.metadata.drop_all` koşar.

Bugüne kadar bu yalnızca bir SÜREÇ KURALIYLA idare ediliyordu ("her alembic çağrısının
önüne DSN koy"); yapısal bir önlem yoktu ve CI de göremiyordu, çünkü `ci.yml` zaten
`localhost` veriyor — **uzak bir DSN hiçbir kapıda denenmiyordu.**

Kapı saftır: DB'ye BAĞLANMAZ, yalnız DSN dizesine ve ortam sözlüğüne bakar.
Kasıtlı uzak işlem hâlâ mümkündür, ama artık İKİ adım ister (bayrak + komut).
"""

from __future__ import annotations

import os
from collections.abc import Mapping

from sqlalchemy.engine import make_url

#: `alembic` komutlarının uzak DSN'e vurmasına izin veren bayrak. `Dockerfile` CMD'si
#: bunu verir (Railway'in kendi DSN'i de "uzak"tır); insan yalnız kasıtlı olarak verir.
ALEMBIC_IZIN_DEGISKENI = "ALEMBIC_ALLOW_REMOTE"

#: `pytest` koşusunun uzak bir TEST veritabanını `drop_all` etmesine izin veren bayrak.
PYTEST_IZIN_DEGISKENI = "PYTEST_ALLOW_REMOTE"

#: Host'u olmayan DSN (unix soketi) de yereldir.
YEREL_HOSTLAR = frozenset({"localhost", "127.0.0.1", "::1"})


def yerel_mi(url: str) -> bool:
    """DSN'in host'u bu makine mi?"""
    host = (make_url(url).host or "").strip().lower().strip("[]")
    return host == "" or host in YEREL_HOSTLAR


def uzak_veritabani_kapisi(
    url: str,
    *,
    izin_degiskeni: str,
    baglam: str,
    ortam: Mapping[str, str] | None = None,
) -> None:
    """Uzak bir DSN'e açık izin olmadan devam edilmesini `RuntimeError` ile durdurur.

    `ortam` verilmezse `os.environ` okunur. Bayrağın değeri TAM `"1"` olmalıdır:
    kazara set edilmiş bir `0`/`false` kapıyı açmaz.
    """
    if yerel_mi(url):
        return

    ortam = os.environ if ortam is None else ortam
    if ortam.get(izin_degiskeni) == "1":
        return

    host = make_url(url).host
    raise RuntimeError(
        f"🔴 UZAK VERİTABANI REDDEDİLDİ ({baglam}): host `{host}` yerel değil.\n"
        "Bu kapı, ölçülmüş bir CANLI ÇÖKÜŞÜN ardından kondu (P7: uzak DB'ye koşan "
        "migration `alembic_version`ı damgaladı, konteyner açılamadı).\n"
        "Yerelde çalışmak istiyorsan komutun önüne yerel DSN'i koy, örn.:\n"
        "    DATABASE_URL=postgresql+asyncpg://fiil:fiil@localhost:5433/fiil_erp \\\n"
        "    TEST_DATABASE_URL=postgresql+asyncpg://fiil:fiil@localhost:5433/fiil_erp_test "
        "<komut>\n"
        f"Gerçekten uzak sunucuda çalışman gerekiyorsa {izin_degiskeni}=1 ver."
    )
