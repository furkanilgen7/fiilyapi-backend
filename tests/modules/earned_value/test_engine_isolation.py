"""Modülerlik bekçisi (PLANLAMA-SPEC §2.7).

1. Motor (`app/modules/earned_value/engine/`) yalnız standart kütüphane ve KENDİ alt
   modüllerini import eder — DB, ORM, FastAPI, pydantic(-settings) YOK.
2. Çekirdek modüller planlama paketini import ETMEZ.

İki katman: AST taraması (yorumdaki/dizedeki metin tetiklemez) + ayrı süreçte gerçek
import (dolaylı bağımlılık da yakalanır). Tarayıcının kör olmadığı ayrıca iddia edilir.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[3] / "app"
ENGINE = APP / "modules" / "earned_value" / "engine"
PLANNING = APP / "modules" / "earned_value"
ENGINE_PKG = "app.modules.earned_value.engine"
PLANNING_PKG = "app.modules.earned_value"
FORBIDDEN_RUNTIME = (
    "sqlalchemy",
    "fastapi",
    "starlette",
    "pydantic",
    "pydantic_settings",
    "asyncpg",
)


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            found.append("." * node.level + (node.module or ""))
    return found


def _engine_files() -> list[Path]:
    files = sorted(ENGINE.rglob("*.py"))
    assert len(files) >= 15, f"Motor tarayıcısı kör: {len(files)} dosya"
    return files


def _violations(files: list[Path]) -> list[str]:
    bad = []
    for path in files:
        for name in _imports(path):
            if name.startswith("."):
                continue  # paket içi göreli import
            root = name.split(".")[0]
            if root == "__future__" or root in sys.stdlib_module_names:
                continue
            if name == ENGINE_PKG or name.startswith(ENGINE_PKG + "."):
                continue
            bad.append(f"{path.name}: {name}")
    return bad


def test_engine_imports_only_stdlib_and_itself() -> None:
    assert _violations(_engine_files()) == []


def test_engine_scanner_catches_a_forbidden_import(tmp_path: Path) -> None:
    leak = tmp_path / "leak.py"
    leak.write_text("# import sqlalchemy  (yorum tetiklemez)\nfrom sqlalchemy import select\n")
    ok = tmp_path / "ok.py"
    ok.write_text("import decimal\nfrom datetime import date\nfrom .types import Node\n")
    assert _violations([leak, ok]) == ["leak.py: sqlalchemy"]


def test_engine_import_loads_no_framework_at_runtime() -> None:
    probe = (
        f"import sys, {ENGINE_PKG}\n"
        f"bad = sorted(m for m in sys.modules if m.split('.')[0] in {FORBIDDEN_RUNTIME!r})\n"
        "print(','.join(bad))\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=APP.parent,
        capture_output=True,
        text=True,
        check=True,
    )
    assert out.stdout.strip() == ""


#: 🔴 Planlamayi import edebilen TEK uygulama dosyasi — BAGLANTI NOKTASI, cekirdek alan
#: modulu DEGIL. Spec §2.7'nin "cekirdek"i gunluk/puantaj/BOQ/bolum gibi ALAN modulleridir;
#: router kaydi uygulamanin kablo demetidir ve bir modul ancak oradan uca baglanir (modeller
#: ise `alembic/env.py` + `tests/conftest.py`ten — ikisi de `app/` disinda). Liste bayatlayamaz:
#: karsiligi kalmayan istisna `test_wiring_allowlist_is_not_stale` ile kirmizi olur.
WIRING_ALLOWLIST = frozenset({"app/core/router_registry.py"})


def _planning_importers() -> dict[str, list[str]]:
    files = [p for p in sorted(APP.rglob("*.py")) if PLANNING not in p.parents]
    assert len(files) >= 200, f"Çekirdek tarayıcısı kör: {len(files)} dosya"
    found: dict[str, list[str]] = {}
    for p in files:
        names = [n for n in _imports(p) if n == PLANNING_PKG or n.startswith(PLANNING_PKG + ".")]
        if names:
            found[str(p.relative_to(APP.parent))] = names
    return found


def test_core_modules_do_not_import_planning() -> None:
    offenders = {k: v for k, v in _planning_importers().items() if k not in WIRING_ALLOWLIST}
    assert offenders == {}


def test_wiring_allowlist_is_not_stale() -> None:
    assert set(_planning_importers()) >= WIRING_ALLOWLIST
