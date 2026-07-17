"""Migration'daki elle kopyalanmis izin matrisinin seed_data.py ile birebir
ayni oldugunu dogrular.

app/modules/roles/seed_data.py (testlerin seed ettigi kaynak) ile
alembic/versions/a477fdf00fdf_...py (production'a giden dondurulmus kopya)
iki ayri yerde ayni 8x13 matrisi tutar. Migration app kodunu KASITLI olarak
import etmez (uygulanmis bir migration donmus olmalidir), bu yuzden ikisinin
esitligini garanti eden hicbir mekanizma yoktur. Bu test o bosluğu kapatir.

DB gerektirmez: migration'in upgrade() fonksiyonu, gercek `alembic.op` yerine
satirlari bellekte toplayan sahte bir `op` ile cagrilir (bulk_insert
cagrilarini yakalar), boylece roller/moduller icin migration'in gercekte
INSERT edecegi satirlar hicbir veritabanina dokunmadan elde edilir.
"""

import importlib.util
import sys
import uuid
from pathlib import Path
from unittest.mock import patch

from app.modules.roles import seed_data as app_seed_data

MIGRATION_PATH = (
    Path(__file__).parents[2]
    / "alembic"
    / "versions"
    / "a477fdf00fdf_seed_roller_modul_ve_izinler.py"
)


def _load_migration_module():
    """Dosya adi revizyon hash'i ile basladigi icin nokta-yollu import edilemez."""
    spec = importlib.util.spec_from_file_location("_migration_a477fdf00fdf", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _value(x) -> str:
    """Enum uyesi veya string oldugu farketmeksizin karsilastirilabilir deger."""
    return x.value if hasattr(x, "value") else str(x)


def _captured_bulk_inserts(migration) -> dict[str, list[dict]]:
    """migration.upgrade()'i sahte bir op ile calistirip bulk_insert satirlarini yakalar.

    Gercek DB baglantisi kurulmaz; op.bulk_insert cagrilari kaydedilir ve
    upgrade() gercek SQL yerine bu kayda yazar.
    """
    captured: dict[str, list[dict]] = {}

    def fake_bulk_insert(table, rows):
        captured[table.name] = rows

    with patch.object(migration.op, "bulk_insert", side_effect=fake_bulk_insert):
        migration.upgrade()

    return captured


def _permission_map_from_app() -> dict[tuple[str, str], tuple[str, str]]:
    result: dict[tuple[str, str], tuple[str, str]] = {}
    for module_key, cells in app_seed_data.MATRIX.items():
        for role_key, (level, scope) in zip(app_seed_data.ROLE_ORDER, cells, strict=True):
            result[(role_key, module_key)] = (_value(level), _value(scope))
    return result


def _permission_map_from_migration(
    migration, captured: dict[str, list[dict]]
) -> dict[tuple[str, str], tuple[str, str]]:
    role_key_by_id = {v: k for k, v in migration.ROLE_IDS.items()}
    module_key_by_id = {v: k for k, v in migration.MODULE_IDS.items()}
    result: dict[tuple[str, str], tuple[str, str]] = {}
    for row in captured["role_permissions"]:
        role_key = role_key_by_id[row["role_id"]]
        module_key = module_key_by_id[row["module_id"]]
        result[(role_key, module_key)] = (_value(row["access_level"]), _value(row["scope"]))
    return result


def _roles_set_from_app() -> set[tuple[str, str, bool, str]]:
    return {
        (row["key"], row["emoji"], row["is_system"], row["description"])
        for row in app_seed_data.ROLES
    }


def _roles_set_from_migration(captured: dict[str, list[dict]]) -> set[tuple[str, str, bool, str]]:
    return {
        (row["key"], row["emoji"], row["is_system"], row["description"])
        for row in captured["roles"]
    }


def _modules_set_from_app() -> set[tuple[str, str, str, int]]:
    return {
        (row["key"], row["name"], _value(row["group"]), row["sort_order"])
        for row in app_seed_data.MODULES
    }


def _modules_set_from_migration(captured: dict[str, list[dict]]) -> set[tuple[str, str, str, int]]:
    return {
        (row["key"], row["name"], _value(row["group"]), row["sort_order"])
        for row in captured["modules"]
    }


def _all_uuids_unique(captured: dict[str, list[dict]]) -> bool:
    ids = [row["id"] for row in captured["roles"]]
    ids += [row["id"] for row in captured["modules"]]
    ids += [row["id"] for row in captured["role_permissions"]]
    assert all(isinstance(i, uuid.UUID) for i in ids)
    return len(ids) == len(set(ids))


def test_migration_permission_matrix_matches_seed_data():
    migration = _load_migration_module()
    captured = _captured_bulk_inserts(migration)
    assert _permission_map_from_app() == _permission_map_from_migration(migration, captured)


def test_migration_permission_matrix_has_104_cells():
    migration = _load_migration_module()
    captured = _captured_bulk_inserts(migration)
    app_map = _permission_map_from_app()
    migration_map = _permission_map_from_migration(migration, captured)
    assert len(app_map) == 104
    assert len(migration_map) == 104


def test_migration_role_keys_match_seed_data():
    migration = _load_migration_module()
    assert set(migration.ROLE_IDS.keys()) == {row["key"] for row in app_seed_data.ROLES}
    assert list(migration.ROLE_ORDER) == list(app_seed_data.ROLE_ORDER)


def test_migration_module_keys_match_seed_data():
    migration = _load_migration_module()
    assert set(migration.MODULE_IDS.keys()) == {row["key"] for row in app_seed_data.MODULES}


def test_migration_role_rows_match_seed_data():
    migration = _load_migration_module()
    captured = _captured_bulk_inserts(migration)
    assert _roles_set_from_app() == _roles_set_from_migration(captured)


def test_migration_module_rows_match_seed_data():
    migration = _load_migration_module()
    captured = _captured_bulk_inserts(migration)
    assert _modules_set_from_app() == _modules_set_from_migration(captured)


def test_migration_generated_ids_are_unique():
    """bulk_insert satirlari gercekten benzersiz UUID'ler tasiyor mu (sahte op, gercek
    DB kisitlarini calistirmadigi icin bunu ayrica dogrulamak gerekir)."""
    migration = _load_migration_module()
    captured = _captured_bulk_inserts(migration)
    assert _all_uuids_unique(captured)
