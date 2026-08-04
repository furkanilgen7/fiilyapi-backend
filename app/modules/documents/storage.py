"""Belge içeriği (baytlar) için DEPOLAMA SOYUTLAMASI — spec §2 / §7 S1.

v1 depolama DB'dir (`document_blobs`); ileride R2/S3'e geçiş **tek sınıf**
değişimidir. Bu sözün karşılığı burada iki şeyle verilir:

1. `StorageBackend` arayüzü oturum/DB tipi TAŞIMAZ — üç metot (`put`/`stream`/
   `delete`) ve tek bir `document_id` dışında hiçbir şey bilmez. Bir R2 backend'i
   yazmak için bu dosyaya ikinci bir sınıf eklemek yeterlidir; künye şeması,
   servis ve uçlar DEĞİŞMEZ.
2. Servis katmanı somut gerçeklemeyi import ETMEZ; backend `deps.py`deki
   bağımlılıktan gelir (kanıt: `tests/documents/test_storage_backend.py`).

## `stream` neden zorunlu

Spec §3 indirmeyi `StreamingResponse` olarak şart koşar: 48 MB'lık bir ZIP
(mockup E12) tek `SELECT data` ile okunursa uygulamanın belleğinde tam boy
kopyalanır ve eşzamanlı birkaç indirme süreci düşürür. Bu yüzden
`DbStorageBackend.stream` baytları Postgres'in `substring(data, offset, length)`
işleviyle SABİT BOYUTLU parçalar hâlinde okur — çıplak bir `select(
DocumentBlob.data)` bu dosyaya GERİ KONULMAMALIDIR (SQL düzeyinde test edilir).

`octet_length` ile önce toplam boy SORULMAZ: o sorgu da `document_blobs.data`ya
dokunan parçalanmamış bir okumadır ve "her blob sorgusu bir parça sorgusudur"
kuralını kirletirdi. Bunun yerine döngü KISA parça görene kadar sürer.
"""

import uuid
from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable

from sqlalchemy import delete as sql_delete
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.modules.documents.models import DocumentBlob

STREAM_CHUNK_BYTES = 1024 * 1024
"""Tek okumada belleğe alınan azami bayt (1 MB).

Tavan sessizce büyütülmemelidir: 50 MB'lık sınırla (config `document_max_bytes`)
birlikte düşünüldüğünde, bu sabit "bir indirme en fazla ne kadar bellek tutar"
sorusunun cevabıdır. Testi bu sabiti ayrıca dondurur.
"""

CONTENT_MISSING = "Belge içeriği bulunamadı"
"""Künye var ama baytı yok. Boş akış DÖNÜLMEZ: kullanıcı 0 baytlık bozuk bir
dosya indirir ve hatayı ancak dosyayı açmaya çalışınca görürdü."""


@runtime_checkable
class StorageBackend(Protocol):
    """Belge baytlarının saklandığı yer — DB, R2, S3, dosya sistemi…

    `AsyncSession` GEÇMEZ: oturum yalnız DB gerçeklemesinin bir ayrıntısıdır ve
    imzaya girseydi soyutlama adı dışında DB'ye bağlı kalırdı.
    """

    async def put(self, document_id: uuid.UUID, data: bytes) -> None:
        """İçeriği yazar; aynı belge için ikinci çağrı ÜSTÜNE yazar.

        Baytların tamamını alır (parçalı yazma YOK): yükleme sınırı 50 MB'dır ve
        künye + içerik TEK transaction'da yazılmalıdır (T3) — parçalı bir yazma
        yarım kalmış içerik ihtimalini açardı.
        """
        ...

    def stream(self, document_id: uuid.UUID) -> AsyncIterator[bytes]:
        """İçeriği PARÇA PARÇA okur. İçerik yoksa `NotFoundError`.

        `async def` DEĞİL bildirimi: gerçeklemeler asenkron ÜRETEÇTİR, yani
        çağrıldığında doğrudan bir `AsyncIterator` döner (coroutine değil).
        """
        ...

    async def delete(self, document_id: uuid.UUID) -> None:
        """İçeriği siler. Zaten yoksa SESSİZCE geçer (silme ISTEĞE göre idempotenttir)."""
        ...


class DbStorageBackend:
    """v1 gerçekleme: baytlar `document_blobs.data` sütununda (spec §7 S1).

    Oturumu constructor'dan alır — istek başına bir örnek üretilir (`deps.py`).
    Kendi transaction'ını AÇMAZ/kapatmaz: künye ile içeriğin atomik yazılabilmesi
    (T3) çağıranın transaction'ında kalmasına bağlıdır.
    """

    def __init__(self, session: AsyncSession, chunk_bytes: int = STREAM_CHUNK_BYTES) -> None:
        self._session = session
        self._chunk_bytes = chunk_bytes

    async def put(self, document_id: uuid.UUID, data: bytes) -> None:
        """UPSERT — `document_id` hem PK hem FK olduğu için belge başına tek satır.

        Düz `INSERT` olsaydı T3'ün "aynı belgeye yeniden yükle" akışı PK
        çakışmasına düşerdi; önce `DELETE` sonra `INSERT` ise iki ifade arasında
        içeriği OLMAYAN bir pencere açardı.
        """
        stmt = (
            pg_insert(DocumentBlob)
            .values(document_id=document_id, data=data)
            .on_conflict_do_update(index_elements=[DocumentBlob.document_id], set_={"data": data})
        )
        await self._session.execute(stmt)

    async def stream(self, document_id: uuid.UUID) -> AsyncIterator[bytes]:
        """`substring(data, offset, length)` ile sabit boyutlu parçalar.

        Döngü KISA bir parça görünce biter; tam katlarda son sorgu boş parça
        döndürür ve o da kısa sayılır. Satır hiç yoksa (ilk sorgu `None`) içerik
        yok demektir — 404.
        """
        offset = 0
        while True:
            # SQL: substring(document_blobs.data, :offset, :length) — Postgres'te
            # bayt indeksleri 1-TABANLIDIR, bu yüzden `offset + 1`.
            stmt = select(func.substring(DocumentBlob.data, offset + 1, self._chunk_bytes)).where(
                DocumentBlob.document_id == document_id
            )
            chunk = (await self._session.execute(stmt)).scalar_one_or_none()
            if chunk is None:
                if offset == 0:
                    raise NotFoundError(CONTENT_MISSING)
                return
            if chunk:
                yield chunk
            if len(chunk) < self._chunk_bytes:
                return
            offset += len(chunk)

    async def delete(self, document_id: uuid.UUID) -> None:
        await self._session.execute(
            sql_delete(DocumentBlob).where(DocumentBlob.document_id == document_id)
        )
