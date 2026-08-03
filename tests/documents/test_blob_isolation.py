"""BLOB İZOLASYON KANITI — künye sorguları `document_blobs`a DOKUNMAZ.

Spec §2 / §7 S1'in tek gerekçesi budur: baytlar ayrı tabloda durur ki liste ve
arama sorguları 48 MB'lık sütunu okumasın (TOAST şişmesi izole kalsın).

Bu bir "sözleşme testi"dir: iddia edilen davranış SQL düzeyinde ölçülür. Koşulan
her ifade `before_cursor_execute` ile yakalanır ve hiçbirinde `document_blobs`
geçmediği doğrulanır. `Document` ile `DocumentBlob` arasına eager (`joined`/
`selectin`) bir ilişki eklenirse ya da liste sorgusu blob tablosunu JOIN'lerse
bu test KIRILIR — mutasyonla doğrulanmıştır.

Dinleyici motora değil, oturumun ÜZERİNDE ÇALIŞTIĞI senkron bağlantıya bağlanır:
`tests/conftest.py`in bağlantısı fixture kurulurken zaten açılmış olduğundan,
sonradan motora eklenen bir dinleyici o bağlantının dispatch zincirine girmez.
"""

from sqlalchemy import event, select

from app.modules.documents.models import Document, DocumentFolder

BLOB_TABLOSU = "document_blobs"


def _sync_connection(session):
    """AsyncSession'ın altındaki senkron `Connection` — olay bağlama noktası."""
    return session.sync_session.get_bind()


class _SqlKaydedici:
    """`before_cursor_execute` ile koşan tüm SQL ifadelerini toplar."""

    def __init__(self) -> None:
        self.ifadeler: list[str] = []

    def __call__(self, conn, cursor, statement, parameters, context, executemany) -> None:
        self.ifadeler.append(statement)

    def blob_dokunuslari(self) -> list[str]:
        return [s for s in self.ifadeler if BLOB_TABLOSU in s.lower()]


async def _kaydederek_kosi(session, coro_factory) -> _SqlKaydedici:
    kaydedici = _SqlKaydedici()
    bind = _sync_connection(session)
    event.listen(bind, "before_cursor_execute", kaydedici)
    try:
        await coro_factory()
    finally:
        event.remove(bind, "before_cursor_execute", kaydedici)
    return kaydedici


async def test_kaydedici_gercekten_calisiyor(seeded_db, proje, belge_fabrikasi) -> None:
    """Kontrol testi: dinleyici hiç SQL yakalamıyorsa asıl iddia sahte yeşildir."""
    belge = await belge_fabrikasi(proje, "Kontrol.pdf")

    async def sorgu() -> None:
        await seeded_db.execute(select(Document).where(Document.id == belge.id))

    kaydedici = await _kaydederek_kosi(seeded_db, sorgu)
    assert kaydedici.ifadeler, "before_cursor_execute hiç tetiklenmedi — kanıt geçersiz."
    assert any("documents" in s.lower() for s in kaydedici.ifadeler)


async def test_kaydedici_blob_dokunusunu_gorebiliyor(seeded_db, proje, belge_fabrikasi) -> None:
    """Karşı kontrol: blob'a GERÇEKTEN dokunan bir sorgu yakalanabilmeli.

    Bu olmadan "hiç dokunulmadı" iddiası, dinleyicinin körlüğünden de gelebilirdi.
    """
    from app.modules.documents.models import DocumentBlob

    belge = await belge_fabrikasi(proje, "Bloblu.pdf", data=b"veri")

    async def sorgu() -> None:
        await seeded_db.execute(
            select(DocumentBlob.document_id).where(DocumentBlob.document_id == belge.id)
        )

    kaydedici = await _kaydederek_kosi(seeded_db, sorgu)
    assert kaydedici.blob_dokunuslari()


async def test_kunye_listesi_blob_tablosuna_dokunmaz(
    seeded_db, proje, santiye, klasor_fabrikasi, belge_fabrikasi
) -> None:
    """ASIL KANIT — E12/SB liste sorgusunun ORM eşleniği."""
    klasor = await klasor_fabrikasi(proje, "Sözleşmeler", site=santiye)
    for i in range(3):
        await belge_fabrikasi(
            proje,
            f"Dosya-{i}.pdf",
            site=santiye,
            folder=klasor,
            data=b"x" * 4096,
            size_bytes=4096,
        )

    async def liste() -> None:
        await seeded_db.execute(
            select(Document)
            .where(Document.project_id == proje.id, Document.site_id == santiye.id)
            .order_by(Document.created_at.desc())
        )

    kaydedici = await _kaydederek_kosi(seeded_db, liste)
    assert kaydedici.ifadeler
    assert kaydedici.blob_dokunuslari() == []


async def test_kunye_niteliklerine_erisim_blob_sorgusu_tetiklemez(
    seeded_db, proje, belge_fabrikasi
) -> None:
    """Lazy ilişki tuzağı: künye alanlarını okumak blob SELECT'i doğurmamalı."""
    belge = await belge_fabrikasi(proje, "Ruhsat.pdf", data=b"y" * 2048, size_bytes=2048)
    seeded_db.expunge_all()

    async def oku() -> None:
        satir = (
            await seeded_db.execute(select(Document).where(Document.id == belge.id))
        ).scalar_one()
        assert satir.filename == "Ruhsat.pdf"
        assert satir.size_bytes == 2048
        assert satir.mime_type

    kaydedici = await _kaydederek_kosi(seeded_db, oku)
    assert kaydedici.blob_dokunuslari() == []


async def test_klasor_listesi_blob_tablosuna_dokunmaz(
    seeded_db, proje, santiye, klasor_fabrikasi, belge_fabrikasi
) -> None:
    klasor = await klasor_fabrikasi(proje, "Fotoğraflar", site=santiye)
    await belge_fabrikasi(proje, "Saha.jpg", site=santiye, folder=klasor, data=b"z" * 1024)

    async def liste() -> None:
        await seeded_db.execute(select(DocumentFolder).where(DocumentFolder.project_id == proje.id))

    kaydedici = await _kaydederek_kosi(seeded_db, liste)
    assert kaydedici.ifadeler
    assert kaydedici.blob_dokunuslari() == []
