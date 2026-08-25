"""HZ-1 T5 — `GET /treasury/upcoming-payments` testlerinin PAYLAŞILAN yardımcıları.

Gövdeler `test_hz1_upcoming.py`den TAŞINDI (kopyalanmadı): üç test dosyası
(`test_hz1_upcoming.py` · `_bordro.py` · `_kapsam.py`) aynı `YOL`, aynı gün
aritmetiği ve aynı sorgu sayacını kullanır; iki kopya kaçınılmaz olarak ayrışırdı.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, time, timedelta

from fastapi.routing import APIRoute
from httpx import AsyncClient
from sqlalchemy import event

from app.core.timezone import DISPLAY_TIMEZONE, today
from app.main import app
from tests.conftest import test_engine

YOL = "/treasury/upcoming-payments"


def _gun(offset: int):
    """Bugünden `offset` gün sonrası — pencere sınırlarının TEK kaynağı."""
    return today() + timedelta(days=offset)


def _onay_zamani(gun) -> datetime:  # noqa: ANN001
    """Hakedişin `approved_at` damgası: TR gününün ÖĞLE vakti.

    Gün başı/sonu seçilseydi UTC'ye çevrildiğinde komşu güne düşer ve vade
    hesabı bir gün kayardı — testin kendisi tuzağa düşerdi.
    """
    return datetime.combine(gun, time(12, 0), tzinfo=DISPLAY_TIMEZONE)


@contextmanager
def _sorgu_sayaci() -> Iterator[list[str]]:
    """Sürücüye giden HER ifadeyi toplar (`test_hz1_balance.py` deseni)."""
    ifadeler: list[str] = []

    def kaydet(conn, cursor, statement, parameters, context, executemany) -> None:  # noqa: ANN001
        ifadeler.append(" ".join(statement.split()))

    event.listen(test_engine.sync_engine, "before_cursor_execute", kaydet)
    try:
        yield ifadeler
    finally:
        event.remove(test_engine.sync_engine, "before_cursor_execute", kaydet)


async def _liste(client: AsyncClient, headers: dict[str, str], **params) -> list[dict]:
    resp = await client.get(YOL, headers=headers, params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()["items"]


def _bordro(items: list[dict]) -> list[dict]:
    """Yanıttaki BORDRO satırları — `source_type` **DEĞERİ** ile süzülür.

    🔴 **K1.1 — SAHTE-YEŞİL TUZAĞI.** "Bordro satırı gelmedi" biçimindeki her
    negatif iddia, kaynak henüz HİÇ yokken de KENDİLİĞİNDEN geçer ve hiçbir şeyi
    bekçilemez. Süzgeç bu yüzden `len(items) == 0` gibi zayıf bir iddiaya değil
    ALT KÜMENİN KENDİSİNE bakar: pozitif testler alt kümenin tek elemanını ve
    tutarını çakar, negatif testler ise yanında DAİMA listeye girmesi gereken
    ikinci bir dönem/evrak taşır — böylece "hiç satır üretilmiyor" hâli ile
    "doğru satır süzülüyor" hâli birbirinden ayrılır.

    Karşılaştırma STRING iledir, `UpcomingSourceType.payroll` ile değil: üye T2'de
    açılacaktır ve şimdiden içe aktarılsaydı testler `ImportError`la kırmızı
    olurdu — yani bekçi, iddiasını hiç ölçmeden kırmızı kalırdı (fixture/import
    hatası bekçilik DEĞİLDİR).
    """
    return [satir for satir in items if satir["source_type"] == "payroll"]


def _kayitli_yollar() -> list[str]:
    """Uygulamanın TÜM yolları, KAYIT SIRASINDA.

    ⚠️ `app.routes` YETMEZ: bu FastAPI sürümü `include_router`ı tembel bir
    `_IncludedRouter` sarmalayıcısı olarak tutar ve düz listede yalnız
    doğrudan dekoratörle tanımlanmış yollar (`/health`) görünür. Sarmalayıcı
    açılmasaydı bekçi HER ZAMAN "yol kayıtlı değil" derdi — yani gerçek sırayı
    hiç ölçmeden kırmızı kalırdı.
    """

    def gez(rotalar) -> list[str]:  # noqa: ANN001
        toplanan: list[str] = []
        for rota in rotalar:
            if isinstance(rota, APIRoute):
                toplanan.append(rota.path)
            elif type(rota).__name__ == "_IncludedRouter":
                toplanan += gez(rota.original_router.routes)
        return toplanan

    return gez(app.routes)
