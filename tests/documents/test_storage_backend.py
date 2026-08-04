"""`StorageBackend` SOYUTLAMA + PARÇALI OKUMA KANITI (spec §2 / §7 S1).

İki iddia burada ölçülür; ikisi de "R2/S3 geçişi TEK sınıf" sözünün karşılığıdır:

1. **Soyutlama gerçek:** servis katmanı somut `DbStorageBackend`i DEĞİL arayüzü
   görür. Sahte (bellek içi) bir backend takılınca servis fonksiyonları
   değişmeden çalışır ve FastAPI bağımlılığı `dependency_overrides` ile
   değiştirilebilir. `app/modules/documents/service.py` içinde `DbStorageBackend`
   adı GEÇMEZ — bu da ayrıca denetlenir.
2. **Streaming gerçek:** `DbStorageBackend.stream` baytları TEK `SELECT data` ile
   belleğe almaz, `substring(data from … for …)` ile parça parça okur. Kanıt SQL
   düzeyindedir (`test_blob_isolation.py`nin `before_cursor_execute` yöntemi):
   birden fazla `substring`li sorgu görülmeli, çıplak bir tam-sütun SELECT'i
   GÖRÜLMEMELİDİR.

İkinci iddia olmadan 48 MB'lık bir indirme uygulamanın belleğinde tam boy
kopyalanırdı (spec §3'ün StreamingResponse şartının tek gerekçesi budur).
"""

import inspect
import uuid
from collections.abc import AsyncIterator
from typing import Annotated

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.modules.documents import service
from app.modules.documents.deps import get_storage_backend
from app.modules.documents.models import DocumentBlob
from app.modules.documents.storage import STREAM_CHUNK_BYTES, DbStorageBackend, StorageBackend


class FakeStorageBackend:
    """Bellek içi backend — `StorageBackend` arayüzünün DB dışı bir gerçeklemesi.

    Bir R2/S3 backend'inin yazması gereken TEK kodun bu kadar olduğunu gösterir:
    üç metot, DB'ye ya da oturuma hiçbir bağ yok.
    """

    def __init__(self) -> None:
        self.icerik: dict[uuid.UUID, bytes] = {}

    async def put(self, document_id: uuid.UUID, data: bytes) -> None:
        self.icerik[document_id] = data

    async def stream(self, document_id: uuid.UUID) -> AsyncIterator[bytes]:
        veri = self.icerik.get(document_id)
        if veri is None:
            raise NotFoundError("Belge içeriği bulunamadı")
        for offset in range(0, len(veri), 8):
            yield veri[offset : offset + 8]

    async def delete(self, document_id: uuid.UUID) -> None:
        self.icerik.pop(document_id, None)


def test_sahte_backend_arayuzu_karsiliyor() -> None:
    """`Protocol` yapısal olduğundan uyum ancak açıkça sınanırsa garanti edilir."""
    assert isinstance(FakeStorageBackend(), StorageBackend)


def test_db_backend_arayuzu_karsiliyor() -> None:
    """Üretim gerçeklemesi de aynı sözleşmeye bağlıdır — bir metodu yeniden
    adlandırmak (ör. `stream` → `read`) bu testi kırar."""
    assert issubclass(DbStorageBackend, StorageBackend)


def test_servis_somut_backendi_import_etmez() -> None:
    """Soyutlamanın SÖZLEŞMESİ: servis katmanı DB gerçeklemesini tanımaz.

    Kaynak metni denetlenir — bir `import`u geri koymak bu testi kırar.
    """
    kaynak = inspect.getsource(service)
    assert "DbStorageBackend" not in kaynak


# --- 1) Soyutlama: servis sahte backend'le çalışır ---


async def test_servis_sahte_backendle_yazar_ve_okur() -> None:
    backend = FakeStorageBackend()
    belge_id = uuid.uuid4()

    await service.store_document_content(backend, belge_id, b"merhaba dunya")
    parcalar = [p async for p in service.open_document_content(backend, belge_id)]

    assert b"".join(parcalar) == b"merhaba dunya"


async def test_servis_sahte_backendle_siler() -> None:
    backend = FakeStorageBackend()
    belge_id = uuid.uuid4()
    await service.store_document_content(backend, belge_id, b"veri")

    await service.delete_document_content(backend, belge_id)

    with pytest.raises(NotFoundError):
        [p async for p in service.open_document_content(backend, belge_id)]


async def test_bagimlilik_override_ile_degistirilebilir() -> None:
    """DI dikişi: `get_storage_backend` override edilince uçlar sahteyle çalışır.

    T2'de belge UCU yoktur (o T3'tür), bu yüzden dikiş test-içi minik bir uygulama
    üzerinde kanıtlanır — üretim koduna sırf test için uç açılmaz.
    """
    backend = FakeStorageBackend()
    app = FastAPI()

    @app.get("/probe")
    async def probe(
        storage: Annotated[StorageBackend, Depends(get_storage_backend)],
    ) -> dict[str, str]:
        return {"tip": type(storage).__name__}

    app.dependency_overrides[get_storage_backend] = lambda: backend
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/probe")

    assert resp.json() == {"tip": "FakeStorageBackend"}


async def test_db_backend_bagimlilik_uzerinden_kurulur(seeded_db: AsyncSession) -> None:
    """Override YOKKEN üretim gerçeklemesi gelir — dikiş boşta kalmaz."""
    backend = get_storage_backend(seeded_db)

    assert isinstance(backend, DbStorageBackend)


# --- 2) DbStorageBackend davranışı ---


async def test_db_backend_yazar_ve_geri_okur(
    seeded_db: AsyncSession, proje, belge_fabrikasi
) -> None:
    belge = await belge_fabrikasi(proje, "Ruhsat.pdf")
    backend = DbStorageBackend(seeded_db)

    await backend.put(belge.id, b"pdf-baytlari")
    parcalar = [p async for p in backend.stream(belge.id)]

    assert b"".join(parcalar) == b"pdf-baytlari"


async def test_db_backend_siler(seeded_db: AsyncSession, proje, belge_fabrikasi) -> None:
    belge = await belge_fabrikasi(proje, "Ruhsat.pdf", data=b"veri")
    backend = DbStorageBackend(seeded_db)

    await backend.delete(belge.id)

    kalan = (
        await seeded_db.execute(
            select(DocumentBlob.document_id).where(DocumentBlob.document_id == belge.id)
        )
    ).scalar_one_or_none()
    assert kalan is None


async def test_db_backend_icerigi_olmayan_belgede_404(
    seeded_db: AsyncSession, proje, belge_fabrikasi
) -> None:
    """Künye var, bayt yok: sessizce boş akış DÖNÜLMEZ (bozuk dosya indirilmiş
    gibi görünürdü) — açık `NotFoundError`."""
    belge = await belge_fabrikasi(proje, "Kunye.pdf")
    backend = DbStorageBackend(seeded_db)

    with pytest.raises(NotFoundError):
        [p async for p in backend.stream(belge.id)]


async def test_db_backend_ustune_yazar(seeded_db: AsyncSession, proje, belge_fabrikasi) -> None:
    """`put` aynı belge için ikinci kez çağrılırsa PK çakışmasına düşmez.

    Belge başına en fazla bir içerik vardır (`document_id` hem PK hem FK); T3'ün
    yeniden yükleme akışı ikinci bir satır AÇMAMALIDIR.
    """
    belge = await belge_fabrikasi(proje, "Ruhsat.pdf", data=b"eski")
    backend = DbStorageBackend(seeded_db)

    await backend.put(belge.id, b"yeni")

    assert b"".join([p async for p in backend.stream(belge.id)]) == b"yeni"


# --- 3) STREAMING KANITI (SQL düzeyinde) ---


class _SqlKaydedici:
    """`test_blob_isolation.py`nin yöntemi — koşan tüm SQL ifadelerini toplar."""

    def __init__(self) -> None:
        self.ifadeler: list[str] = []

    def __call__(self, conn, cursor, statement, parameters, context, executemany) -> None:
        self.ifadeler.append(statement)

    def substringli(self) -> list[str]:
        return [s for s in self.ifadeler if "substring" in s.lower()]

    def tam_sutun_okumalari(self) -> list[str]:
        """`document_blobs.data`yı PARÇALAMADAN seçen ifadeler — yasak olan bu."""
        return [
            s
            for s in self.ifadeler
            if "document_blobs" in s.lower()
            and "data" in s.lower()
            and "substring" not in s.lower()
            and s.lower().lstrip().startswith("select")
        ]


async def test_stream_parcali_okur_tek_selectle_bellege_almaz(
    seeded_db: AsyncSession, proje, belge_fabrikasi
) -> None:
    """ASIL KANIT: 2.5 MB'lık içerik VARSAYILAN parça boyuyla üç sorguda okunur.

    Chunk boyu testte küçültülMEZ — küçültülseydi kanıt yalnız test yapılandırması
    için geçerli olurdu. `stream` gövdesi `select(DocumentBlob.data)`ya çevrilirse
    bu test kırılır (mutasyonla doğrulandı).
    """
    boyut = STREAM_CHUNK_BYTES * 2 + STREAM_CHUNK_BYTES // 2
    icerik = b"x" * boyut
    belge = await belge_fabrikasi(proje, "Buyuk.zip", data=icerik, size_bytes=boyut)
    backend = DbStorageBackend(seeded_db)

    kaydedici = _SqlKaydedici()
    bind = seeded_db.sync_session.get_bind()
    event.listen(bind, "before_cursor_execute", kaydedici)
    try:
        parcalar = [p async for p in backend.stream(belge.id)]
    finally:
        event.remove(bind, "before_cursor_execute", kaydedici)

    assert b"".join(parcalar) == icerik
    assert len(parcalar) == 3, "parçalı okuma beklenirken tek parça döndü"
    assert len(kaydedici.substringli()) >= 3
    assert kaydedici.tam_sutun_okumalari() == []


async def test_stream_parca_boyu_asilmaz(seeded_db: AsyncSession, proje, belge_fabrikasi) -> None:
    """Hiçbir parça tavanı aşmamalı — aşarsa bellek sözü tutulmaz."""
    boyut = STREAM_CHUNK_BYTES + 7
    belge = await belge_fabrikasi(proje, "Buyuk.zip", data=b"y" * boyut, size_bytes=boyut)
    backend = DbStorageBackend(seeded_db)

    parcalar = [len(p) async for p in backend.stream(belge.id)]

    assert parcalar == [STREAM_CHUNK_BYTES, 7]


async def test_varsayilan_parca_boyu_bir_megabayt() -> None:
    """Sabit sessizce büyütülürse (ör. 64 MB) streaming sözü ANLAMINI YİTİRİR."""
    assert STREAM_CHUNK_BYTES == 1024 * 1024
