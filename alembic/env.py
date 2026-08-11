import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context
from app.core.config import settings
from app.core.db import Base

# TUM modullerin `models` modulu BURADA import edilir (TB1). Import bir YAN ETKI
# icindir: model modulu yuklenmeden tablolari `Base.metadata`ya kaydolmaz ve
# autogenerate / `alembic check` o tablolari "silinecek" diye raporlar (sahte diff).
#
# Bu liste `app/modules/*/models.py` ile BIREBIR ayni olmak zorundadir.
#
# >>> YENI BIR MODUL ACARSAN models.py'sini BURAYA DA EKLE. <<<
from app.modules.audit import models as audit_models  # noqa: F401
from app.modules.boq import models as boq_models  # noqa: F401
from app.modules.company import models as company_models  # noqa: F401
from app.modules.contracts import models as contracts_models  # noqa: F401
from app.modules.customers import models as customers_models  # noqa: F401
from app.modules.documents import models as documents_models  # noqa: F401
from app.modules.inventory import models as inventory_models  # noqa: F401
from app.modules.personnel import models as personnel_models  # noqa: F401
from app.modules.progress_payments import models as progress_payments_models  # noqa: F401
from app.modules.projects import models as projects_models  # noqa: F401
from app.modules.roles import models as roles_models  # noqa: F401
from app.modules.sales import models as sales_models  # noqa: F401
from app.modules.settings import models as settings_models  # noqa: F401
from app.modules.site_diary import models as site_diary_models  # noqa: F401
from app.modules.site_planning import models as site_planning_models  # noqa: F401
from app.modules.sites import models as sites_models  # noqa: F401
from app.modules.subcontractor_progress_payments import (  # noqa: F401
    models as subcontractor_progress_payments_models,
)
from app.modules.timesheet import models as timesheet_models  # noqa: F401
from app.modules.units import models as units_models  # noqa: F401
from app.modules.users import models as users_models  # noqa: F401

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url)

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """In this scenario we need to create an Engine
    and associate a connection with the context.

    """

    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""

    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
