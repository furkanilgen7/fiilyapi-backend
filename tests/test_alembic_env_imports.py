"""`alembic/env.py` TUM model modullerini import ediyor mu? (TB1)

NEDEN BU TEST VAR: `env.py` bir model modulunu import etmezse o modulun tablolari
`Base.metadata`ya kaydolmaz ve `alembic check` / autogenerate onlari "silinecek"
diye raporlar. Bu SESSIZ bir borctur — hicbir test kirilmaz, yalnizca bir gun
birisi autogenerate ciktisina guvenip `boq_items`i dusuren bir migration uretir.

Borcun kendisi tam boyle olustu: `boq` ve `progress_payments` modulleri acildi,
`env.py`ye eklenmedi ve sahte diff "bilinen borc" olarak tasindi. Test listeyi
DIZIN GERCEGINE baglar: yeni bir `models.py` acilip `env.py`ye eklenmezse kirilir.
"""

import ast
import pathlib

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
_ENV_PY = _REPO_ROOT / "alembic" / "env.py"
_MODULES_DIR = _REPO_ROOT / "app" / "modules"


def _modules_with_models() -> set[str]:
    """Diskteki gercek: `app/modules/<ad>/models.py` tasiyan her modul."""
    return {path.parent.name for path in _MODULES_DIR.glob("*/models.py")}


def _modules_imported_by_env() -> set[str]:
    """`env.py`nin `from app.modules.<ad> import models` satirlarindaki modul adlari.

    Kaynak AST ile okunur, `env.py` CALISTIRILMAZ: import etmek Alembic'in
    `context` nesnesini ve bir DB baglantisini gerektirir.
    """
    tree = ast.parse(_ENV_PY.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or node.module is None:
            continue
        parts = node.module.split(".")
        # Yalniz `from app.modules.<ad> import models` bicimi sayilir.
        if parts[:2] == ["app", "modules"] and len(parts) == 3:
            if any(alias.name == "models" for alias in node.names):
                imported.add(parts[2])
    return imported


def test_env_py_imports_every_module_with_models() -> None:
    eksik = _modules_with_models() - _modules_imported_by_env()
    assert not eksik, (
        f"alembic/env.py su modullerin models.py'sini import etmiyor: {sorted(eksik)}. "
        "Tablolari Base.metadata'ya girmez -> `alembic check` sahte 'silinecek' diff'i uretir."
    )


def test_env_py_imports_no_unknown_module() -> None:
    """Ters yon: silinmis ya da adi degismis bir modul `env.py`de kalirsa ImportError."""
    fazla = _modules_imported_by_env() - _modules_with_models()
    assert not fazla, f"alembic/env.py var olmayan modulleri import ediyor: {sorted(fazla)}"
