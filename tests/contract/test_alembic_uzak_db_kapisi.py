"""🔴 UZAK VERİTABANI KAPISI (altyapi-fail-closed, kayıt 0).

**Ölçülmüş olay (P7):** `backend/.env` içindeki `DATABASE_URL` **uzak Railway CANLI**
veritabanını gösteriyor (bugün de öyle: `… -> tokaido.proxy.rlwy.net:31217/railway`).
Backend kökünde override'sız `alembic upgrade head` yazan biri şemayı CANLIDA değiştirdi,
`alembic_version` damgalandı ve konteyner açılışta `Can't locate revision` ile öldü.
`alembic downgrade` ise doğrudan **veri kaybıdır**.

**Neden bugüne kadar hiçbir kapı görmedi:** `alembic/env.py`nin TEK URL kaynağı
`settings.database_url`dir (`alembic.ini:89 sqlalchemy.url =` BOŞ) ve CI'ın
`alembic-cycle` işi (`ci.yml:77`) zaten `localhost` verir — **uzak bir DSN hiçbir kapıda
denenmiyor.** Aynı tuzağın ikinci ağzı test tarafındadır: `TEST_DATABASE_URL` de aynı
uzak sunucuyu gösterir ve `tests/conftest.py`nin `_create_schema` fikstürü oturum başında
`Base.metadata.drop_all` koşar.

Bu dosya kapıyı **DB'ye BAĞLANMADAN** sınar: `app/core/db_guard.py` saf bir
dize/ortam fonksiyonudur.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.db_guard import (
    ALEMBIC_IZIN_DEGISKENI,
    PYTEST_IZIN_DEGISKENI,
    uzak_veritabani_kapisi,
)

BACKEND_KOKU = Path(__file__).resolve().parents[2]
ENV_PY = BACKEND_KOKU / "alembic" / "env.py"
DOCKERFILE = BACKEND_KOKU / "Dockerfile"
CONFTEST = BACKEND_KOKU / "tests" / "conftest.py"

# `.env`deki gerçek canlı DSN'in biçimi (parola uydurma).
CANLI_DSN = "postgresql+asyncpg://fiil:gizli@tokaido.proxy.rlwy.net:31217/railway"
RAILWAY_IC_DSN = "postgresql+asyncpg://fiil:gizli@postgres.railway.internal:5432/railway"
YEREL_DSN = "postgresql+asyncpg://fiil:fiil@localhost:5433/fiil_erp"


def _yorumsuz(metin: str) -> str:
    """`#` ile başlayan satırları atar — kapı kendi gerekçe yorumunu KANIT sanmasın."""
    return "\n".join(s for s in metin.splitlines() if not s.lstrip().startswith("#"))


def test_UZAK_dsn_BAYRAKSIZ_reddedilir() -> None:
    """Kapının tek işi bu: uzak host + bayrak yok → çalışmadan dur."""
    with pytest.raises(RuntimeError) as hata:
        uzak_veritabani_kapisi(
            CANLI_DSN, izin_degiskeni=ALEMBIC_IZIN_DEGISKENI, ortam={}, baglam="alembic"
        )

    mesaj = str(hata.value)
    assert "tokaido.proxy.rlwy.net" in mesaj, f"Hata hangi host'u reddettiğini söylemiyor: {mesaj}"
    assert ALEMBIC_IZIN_DEGISKENI in mesaj, f"Hata kaçış yolunu söylemiyor: {mesaj}"


def test_RAILWAY_IC_host_da_UZAK_sayilir() -> None:
    """`*.railway.internal` de localhost DEĞİLDİR — Dockerfile bayrağı bu yüzden ŞARTTIR."""
    with pytest.raises(RuntimeError):
        uzak_veritabani_kapisi(
            RAILWAY_IC_DSN, izin_degiskeni=ALEMBIC_IZIN_DEGISKENI, ortam={}, baglam="alembic"
        )


def test_UZAK_dsn_BAYRAKLA_gecer() -> None:
    """Kasıtlı uzak migration hâlâ mümkün — ama artık İKİ adım ister."""
    uzak_veritabani_kapisi(
        CANLI_DSN,
        izin_degiskeni=ALEMBIC_IZIN_DEGISKENI,
        ortam={ALEMBIC_IZIN_DEGISKENI: "1"},
        baglam="alembic",
    )


@pytest.mark.parametrize(
    "dsn",
    [
        YEREL_DSN,
        "postgresql+asyncpg://fiil:fiil@127.0.0.1:5433/fiil_erp",
        "postgresql+asyncpg://fiil:fiil@/fiil_erp",  # unix soketi: host YOK
    ],
)
def test_YEREL_dsn_bayraksiz_gecer(dsn: str) -> None:
    """Geliştiricinin ve CI'ın yolu DEĞİŞMEZ (ci.yml:77 zaten localhost verir)."""
    uzak_veritabani_kapisi(dsn, izin_degiskeni=ALEMBIC_IZIN_DEGISKENI, ortam={}, baglam="alembic")


def test_BAYRAGIN_degeri_TAM_1_olmali() -> None:
    """`ALEMBIC_ALLOW_REMOTE=0` / `=false` kapıyı AÇMAZ — kazara set edilmiş değişken geçmez."""
    for deger in ("0", "false", "", "yes"):
        with pytest.raises(RuntimeError):
            uzak_veritabani_kapisi(
                CANLI_DSN,
                izin_degiskeni=ALEMBIC_IZIN_DEGISKENI,
                ortam={ALEMBIC_IZIN_DEGISKENI: deger},
                baglam="alembic",
            )


def test_alembic_env_py_KAPIYI_FIILEN_CAGIRIR() -> None:
    """🔴 Kapı, onu çağıran satır olmadan yalnızca bir dekorasyondur.

    `env.py` URL'yi `config.set_main_option`a verdikten SONRA kapıdan geçmelidir.
    """
    kaynak = _yorumsuz(ENV_PY.read_text(encoding="utf-8"))
    assert "from app.core.db_guard import" in kaynak, (
        "🔴 alembic/env.py kapıyı import etmiyor — uzak DSN'e migration koşmak serbest."
    )
    assert "uzak_veritabani_kapisi(" in kaynak, "🔴 alembic/env.py kapıyı ÇAĞIRMIYOR."


def test_conftest_TEST_DSN_ICIN_KAPIYI_CAGIRIR() -> None:
    """Tuzağın ikinci ağzı: seri `pytest` koşusu uzak `fiil_erp_test`i `drop_all` ile siler."""
    kaynak = _yorumsuz(CONFTEST.read_text(encoding="utf-8"))
    assert "uzak_veritabani_kapisi(" in kaynak, (
        "🔴 tests/conftest.py kapıyı çağırmıyor — uzak TEST_DATABASE_URL'e `drop_all` serbest."
    )
    assert "izin_degiskeni=PYTEST_IZIN_DEGISKENI" in kaynak, (
        "🔴 conftest kapıyı ALEMBIC bayrağıyla çağırıyor olabilir; test koşusunun KENDİ "
        f"bayrağı ({PYTEST_IZIN_DEGISKENI}) olmalı — biri açıldığında öbürü açılmamalı."
    )
    assert ALEMBIC_IZIN_DEGISKENI != PYTEST_IZIN_DEGISKENI, (
        "🔴 İki bayrak AYNI olursa tek `export` her iki kapıyı birden açar."
    )


def test_DOCKERFILE_CMD_BAYRAGI_TASIR() -> None:
    """🔴 KAPIYLA AYNI COMMIT'TE OLMAK ZORUNDA.

    Railway'in kendi DSN'i de 'uzak'tır; bayrak `CMD`de değilse `alembic upgrade head`
    patlar, `&&` kısa devre yapar ve **uvicorn hiç başlamaz** → canlı 502.
    """
    dockerfile = _yorumsuz(DOCKERFILE.read_text(encoding="utf-8"))
    cmd_satirlari = [s for s in dockerfile.splitlines() if s.startswith("CMD")]
    assert len(cmd_satirlari) == 1, f"Beklenen tek CMD satırı, bulunan: {cmd_satirlari}"
    cmd = cmd_satirlari[0]
    assert "alembic upgrade head" in cmd, f"CMD migration koşmuyor: {cmd}"
    assert f"{ALEMBIC_IZIN_DEGISKENI}=1" in cmd, (
        "🔴 CANLI DEPLOY AÇILMAZ: Dockerfile CMD'si "
        f"`{ALEMBIC_IZIN_DEGISKENI}=1` taşımıyor ama kapı devrede.\n"
        f"CMD: {cmd}"
    )
