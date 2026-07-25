"""Migration'lardaki elle kopyalanmis izin matrisinin seed_data.py ile birebir
ayni oldugunu dogrular.

app/modules/roles/seed_data.py (testlerin seed ettigi kaynak) ile
alembic/versions/*.py (production'a giden dondurulmus kopyalar) ayni matrisi
iki ayri yerde tutar. Migration'lar app kodunu KASITLI olarak import ETMEZ
(uygulanmis bir migration donmus olmalidir), bu yuzden ikisinin esitligini
garanti eden hicbir mekanizma yoktur. Bu test o boslugu kapatir.

Matris tek bir migration'da degil, uc uca eklenen migration'larda birikir:
  * a477fdf00fdf -> ilk 8 rol x 13 modul (bulk_insert)
  * 2cffc2fcfcf0 -> 14. modul "invoicing" + 8 izin satiri + sort_order kaydirmasi
Bu yuzden karsilastirma, migration'larin BILESKESI ile seed_data arasinda yapilir.

DB gerektirmez: ilk migration'in upgrade() fonksiyonu, gercek `alembic.op` yerine
satirlari bellekte toplayan sahte bir `op` ile cagrilir (bulk_insert cagrilarini
yakalar). Ikinci migration satirlari calisma aninda DB'den okunan id'lerle
INSERT ettigi icin bulk_insert kullanmaz; onun yerine upgrade()'in SQL uretirken
okudugu modul-duzeyi sabitleri karsilastirilir.
"""

import importlib.util
import sys
import uuid
from pathlib import Path
from unittest.mock import patch

from app.modules.roles import seed_data as app_seed_data

VERSIONS_DIR = Path(__file__).parents[2] / "alembic" / "versions"
SEED_MIGRATION_PATH = VERSIONS_DIR / "a477fdf00fdf_seed_roller_modul_ve_izinler.py"
INVOICING_MIGRATION_PATH = VERSIONS_DIR / "2cffc2fcfcf0_invoicing_izin_modulu.py"


def _load_migration_module(path: Path):
    """Dosya adi revizyon hash'i ile basladigi icin nokta-yollu import edilemez."""
    name = f"_migration_{path.stem}"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_seed_migration():
    return _load_migration_module(SEED_MIGRATION_PATH)


def _load_invoicing_migration():
    return _load_migration_module(INVOICING_MIGRATION_PATH)


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


def _permission_map_from_migrations() -> dict[tuple[str, str], tuple[str, str]]:
    seed_migration = _load_seed_migration()
    captured = _captured_bulk_inserts(seed_migration)
    role_key_by_id = {v: k for k, v in seed_migration.ROLE_IDS.items()}
    module_key_by_id = {v: k for k, v in seed_migration.MODULE_IDS.items()}

    result: dict[tuple[str, str], tuple[str, str]] = {}
    for row in captured["role_permissions"]:
        role_key = role_key_by_id[row["role_id"]]
        module_key = module_key_by_id[row["module_id"]]
        result[(role_key, module_key)] = (_value(row["access_level"]), _value(row["scope"]))

    invoicing = _load_invoicing_migration()
    for module_key, cells in invoicing.MATRIX.items():
        for role_key, (level, scope) in zip(invoicing.ROLE_ORDER, cells, strict=True):
            result[(role_key, module_key)] = (_value(level), _value(scope))
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


def _modules_set_from_migrations() -> set[tuple[str, str, str, int]]:
    """Ilk migration'in modul satirlari + invoicing migration'inin ekledigi/kaydirdigi hali."""
    captured = _captured_bulk_inserts(_load_seed_migration())
    invoicing = _load_invoicing_migration()

    result: set[tuple[str, str, str, int]] = set()
    for row in captured["modules"]:
        sort_order = invoicing.SORT_ORDER_UPDATES.get(row["key"], row["sort_order"])
        result.add((row["key"], row["name"], _value(row["group"]), sort_order))
    result.add(
        (
            invoicing.MODULE_KEY,
            invoicing.MODULE_NAME,
            invoicing.MODULE_GROUP,
            invoicing.MODULE_SORT_ORDER,
        )
    )
    return result


def _all_uuids_unique(captured: dict[str, list[dict]]) -> bool:
    ids = [row["id"] for row in captured["roles"]]
    ids += [row["id"] for row in captured["modules"]]
    ids += [row["id"] for row in captured["role_permissions"]]
    assert all(isinstance(i, uuid.UUID) for i in ids)
    return len(ids) == len(set(ids))


def test_migration_permission_matrix_matches_seed_data():
    assert _permission_map_from_app() == _permission_map_from_migrations()


def test_migration_permission_matrix_has_112_cells():
    app_map = _permission_map_from_app()
    migration_map = _permission_map_from_migrations()
    assert len(app_map) == 112
    assert len(migration_map) == 112


def test_migration_role_keys_match_seed_data():
    migration = _load_seed_migration()
    assert set(migration.ROLE_IDS.keys()) == {row["key"] for row in app_seed_data.ROLES}
    assert list(migration.ROLE_ORDER) == list(app_seed_data.ROLE_ORDER)


def test_invoicing_migration_role_order_matches_seed_data():
    """Sutun sirasi kaymissa izinler yanlis rollere yazilir — sessiz yetki sizintisi."""
    invoicing = _load_invoicing_migration()
    assert list(invoicing.ROLE_ORDER) == list(app_seed_data.ROLE_ORDER)


def test_migration_module_keys_match_seed_data():
    migration = _load_seed_migration()
    invoicing = _load_invoicing_migration()
    keys = set(migration.MODULE_IDS.keys()) | {invoicing.MODULE_KEY}
    assert keys == {row["key"] for row in app_seed_data.MODULES}


def test_migration_role_rows_match_seed_data():
    captured = _captured_bulk_inserts(_load_seed_migration())
    assert _roles_set_from_app() == _roles_set_from_migration(captured)


def test_migration_module_rows_match_seed_data():
    assert _modules_set_from_app() == _modules_set_from_migrations()


def test_invoicing_migration_downgrade_restores_previous_sort_orders():
    """downgrade() eski sort_order'lari geri yazar; bunlar ilk migration'in degerleri olmali."""
    captured = _captured_bulk_inserts(_load_seed_migration())
    invoicing = _load_invoicing_migration()
    original = {row["key"]: row["sort_order"] for row in captured["modules"]}
    assert invoicing.PREVIOUS_SORT_ORDERS == {
        key: original[key] for key in invoicing.SORT_ORDER_UPDATES
    }


def test_migration_generated_ids_are_unique():
    """bulk_insert satirlari gercekten benzersiz UUID'ler tasiyor mu (sahte op, gercek
    DB kisitlarini calistirmadigi icin bunu ayrica dogrulamak gerekir)."""
    captured = _captured_bulk_inserts(_load_seed_migration())
    assert _all_uuids_unique(captured)
