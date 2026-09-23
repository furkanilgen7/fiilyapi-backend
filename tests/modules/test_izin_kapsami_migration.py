"""`b2c3d4e5f8a1` — uygulanmayan izin kapsamlarını `all`a çeken migration.

## 🔴 BU DOSYA BİR KÖR BEKÇİDEN DOĞDU (2026-09-19)

İlk hâlinde migration'ın tek bekçisi `test_seed_migration_matches_seed_data.py`
idi ve o test migration'ın **SABİTLERİNİ** (`DUSEN`, `KAPSAMSIZ_MODUL`) okuyup
tohum matrisine uyguluyordu. Mutasyon bunu çürüttü: `upgrade()` içindeki İKİ
`op.execute` çağrısı da SİLİNDİĞİNDE test YEŞİL kaldı — sabitler yerinde
durduğu için. Yani bekçi migration'ın NİYETİNİ ölçüyordu, ETKİSİNİ değil.

Kanon: **bir bekçi, ölçtüğü yolu kendisi kuruyorsa hiçbir şey ölçmüyordur.**
Burada ölçüm GERÇEK alembic turudur: önceki revizyona kurulur, kirli satırlar
yazılır, `upgrade head` koşulur ve sonuç DB'den OKUNUR.

## Negatif kontrol ZORUNLUDUR

`finance` GENEL olarak düşmez — yalnız `approvals` modülünde düşer. "Her şeyi
`all` yap" diyen bozuk bir migration, negatif kontrol olmadan yeşil geçerdi.
"""

import uuid

import asyncpg
import pytest

from tests.modules.accounting._mu1_migration import (
    _asyncpg_dsn,
    _create_scratch_database,
    _drop_scratch_database,
    _run_alembic,
)

pytestmark = pytest.mark.asyncio

#: Revizyonlara AÇIKÇA çıkılır; `head`/`-1` KULLANILMAZ — sonraki dilimler
#: revizyon ekledikçe bu test sessizce yanlış şeyi ölçerdi (`_mu1_migration` dersi).
ONCEKI_REVISION = "a1b2c3d4e5f7"
KAPSAM_REVISION = "b2c3d4e5f8a1"


async def _rol_ve_izin(conn: asyncpg.Connection, kapsamlar: dict[str, str]) -> uuid.UUID:
    """`{modul_key: scope}` haritasını tek bir test rolüne yazar; modül yoksa AÇAR."""
    role_id = uuid.uuid4()
    await conn.execute(
        "INSERT INTO roles (id,key,name,emoji,description,is_system) "
        "VALUES ($1,'t_kapsam','Kapsam Testi','🔧','bekçi',false)",
        role_id,
    )
    for sira, (modul, scope) in enumerate(kapsamlar.items(), start=900):
        module_id = await conn.fetchval("SELECT id FROM modules WHERE key = $1", modul)
        if module_id is None:
            module_id = uuid.uuid4()
            await conn.execute(
                'INSERT INTO modules (id,key,name,"group",sort_order) '
                "VALUES ($1,$2,$2,'GENEL',$3)",
                module_id,
                modul,
                sira,
            )
        await conn.execute(
            "INSERT INTO role_permissions (id,role_id,module_id,access_level,scope) "
            "VALUES ($1,$2,$3,'view',$4)",
            uuid.uuid4(),
            role_id,
            module_id,
            scope,
        )
    return role_id


async def _kapsamlar(conn: asyncpg.Connection, role_id: uuid.UUID) -> dict[str, str]:
    satirlar = await conn.fetch(
        "SELECT m.key, rp.scope FROM role_permissions rp "
        "JOIN modules m ON m.id = rp.module_id WHERE rp.role_id = $1",
        role_id,
    )
    return {r["key"]: r["scope"] for r in satirlar}


async def test_migration_uygulanmayan_kapsamlari_ALL_yapar_ve_FINANCEI_KORUR() -> None:
    """İki adım ve bir negatif kontrol, TEK turda ölçülür.

    * `own`/`project`/`stock` HER modülde `all` olur (1. adım).
    * `approvals` modülündeki `finance` de `all` olur (2. adım, hedefli).
    * 🔴 NEGATİF KONTROL: `sales` modülündeki `finance` **DOKUNULMAZ** —
      `finance` genel olarak düşmez, yalnız `approvals`ta anlamsızdır.
    """
    database = await _create_scratch_database()
    try:
        _run_alembic("upgrade", ONCEKI_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            role_id = await _rol_ve_izin(
                conn,
                {
                    "t_own": "own",
                    "t_project": "project",
                    "t_stock": "stock",
                    "approvals": "finance",
                    "sales": "finance",
                    "t_limited": "limited",
                },
            )
            once = await _kapsamlar(conn, role_id)
            assert once["t_own"] == "own", "kurulum: kirli satır yazılamadı"
            assert once["approvals"] == "finance"
        finally:
            await conn.close()

        _run_alembic("upgrade", KAPSAM_REVISION, database=database)

        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            sonra = await _kapsamlar(conn, role_id)
        finally:
            await conn.close()

        assert sonra["t_own"] == "all", "1. adım: `own` çevrilmedi"
        assert sonra["t_project"] == "all", "1. adım: `project` çevrilmedi"
        assert sonra["t_stock"] == "all", "1. adım: `stock` çevrilmedi"
        assert sonra["approvals"] == "all", "2. adım: `approvals` kapsamı çevrilmedi"
        # 🔴 NEGATİF KONTROL — bu iki satır olmadan "her şeyi `all` yap" da geçerdi.
        assert sonra["sales"] == "finance", "AŞIRI SÜPÜRME: `sales` finance kapsamı silindi"
        assert sonra["t_limited"] == "limited", "AŞIRI SÜPÜRME: `limited` kapsamı silindi"
    finally:
        await _drop_scratch_database(database)
