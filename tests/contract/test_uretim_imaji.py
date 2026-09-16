"""🔴 ÜRETİM İMAJI ORTAM BEYANI (altyapi-fail-closed, kayıt 1).

**Ölçüm:** `command grep -rn 'ENVIRONMENT' .` (backend içinden, `.venv`/`.git` hariç) →
yalnız `.env:4` ve `.env.example:4`, ikisi de `development`. `Dockerfile`da YOK, `ci.yml`de
YOK; depoda `railway.json`/`railway.toml`/`nixpacks.toml`/`Procfile` de YOK. Yani **üretim
imajının kendisi hangi ortamda koştuğunu HİÇ beyan etmiyor**; `ENVIRONMENT`in tek tüketicisi
`app/core/config.py:113`teki varsayılan-JWT-secret reddidir ve o kapı imajda yapısal olarak
ölüdür — canlıda açık olması yalnızca Railway panelinde elle girilmiş bir değişkene bağlıdır
(bugün girilmiş; ölçüldü: `railway variables --service fiilyapi-backend` → `ENVIRONMENT`,
`JWT_SECRET` VAR). Panelden silinen tek bir satır o kapıyı sessizce kapatır.

Bu kapı imaj KURMAZ — `Dockerfile` metnini okur (emsal:
`tests/contract/test_bagimlilik_kilidi.py`). Bugün hiçbir test `Dockerfile`ın `ENV` bloğunu
okumuyordu.
"""

from __future__ import annotations

from pathlib import Path

BACKEND_KOKU = Path(__file__).resolve().parents[2]
DOCKERFILE = BACKEND_KOKU / "Dockerfile"


def _yorumsuz(metin: str) -> str:
    """`#` ile başlayan satırları atar — gerekçe yorumu KANIT sayılmasın."""
    return "\n".join(s for s in metin.splitlines() if not s.lstrip().startswith("#"))


def test_DOCKERFILE_ENVIRONMENT_production_beyan_eder() -> None:
    dockerfile = _yorumsuz(DOCKERFILE.read_text(encoding="utf-8"))
    assert "ENVIRONMENT=production" in dockerfile, (
        "🔴 Üretim imajı `ENVIRONMENT`i beyan etmiyor. `app/core/config.py`deki "
        "varsayılan-JWT-secret reddi böylece YALNIZCA Railway panelindeki elle girilmiş "
        "bir değişkene bağlı kalır; o satır silinirse canlı, herkese açık "
        "`dev-only-change-me` ile token imzalamaya sessizce devam eder."
    )
