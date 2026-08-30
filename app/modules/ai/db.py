"""AI okuma düzleminin **salt-okunur** veritabanı oturumu (AI-0a T3).

Kapı D — YAPISAL: AI hattında yazma reddedilmez, **imkânsızdır**. Python
disipliniyle ("araçlar `session.add` çağırmaz") kurulan bir kural bakım maliyeti
üretir, garanti üretmez; PostgreSQL'in kendisi reddederse garanti eder.

🔴 `get_ai_readonly_db` ile `app.core.db.get_db` arasındaki **davranış farkı
kasıtlıdır**: `get_db` temiz çıkışta `commit()` eder (hattın ucundaki yazıları
garantilemek için). Buradaki oturum **hiçbir koşulda commit etmez** — çıkışta her
zaman `rollback()` yapar. Bir kopyala-yapıştır `commit()` bu dosyanın tüm anlamını
sessizce siler; bekçisi `tests/modules/ai/test_ai0a_readonly_db.py`.

⚠️ Motor **modül yüklenirken** kurulur ama bağlantı açmaz (SQLAlchemy havuzu
tembeldir); yani `import` tek başına DB'ye dokunmaz.
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.core.db import build_engine

#: Ana motorun (`app.core.db.engine`) salt-okunur ikizi. AYNI yapılandırmayı
#: devralır (`pool_pre_ping`, `timeout`, `command_timeout`) — bu yüzden ayrı bir
#: `create_async_engine` çağrısı DEĞİL, `build_engine(..., read_only=True)`dir.
#: Aksi hâlde ana motorun ileride kazanacağı her ayar burada sessizce düşerdi.
ai_engine = build_engine(settings, read_only=True)

AiSessionLocal = async_sessionmaker(ai_engine, class_=AsyncSession, expire_on_commit=False)


async def get_ai_readonly_db() -> AsyncGenerator[AsyncSession, None]:
    """İstek başına salt-okunur bir session açar; **asla commit etmez**.

    Okuma düzlemi `get_db`yi bu bağımlılıkla değiştirir (`dependency_overrides`),
    böylece AI'nın çağırdığı uçlar ana (yazılabilir) havuza HİÇ ULAŞMAZ.
    """
    async with AiSessionLocal() as session:
        try:
            yield session
        finally:
            # `commit()` YOK — bilerek. Açık transaction'ı kapatmak için rollback:
            # `S30` sınıfı "yazan GET"ler (`get_or_create_singleton` gibi) bir şey
            # flush etmiş olsa bile burada geri alınır. PG zaten reddeder; bu ikinci
            # kilit, motorun yanlışlıkla yazılabilir kurulması hâlinde de tutar.
            await session.rollback()
