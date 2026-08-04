"""`GET /documents/{id}/download` — StreamingResponse (T3, spec §3).

Kapı `documents:view` (SB:147 "İndir" düğmesi her satırda vardır; salt okur
roller de indirir).

## Kanıtlanan iki iddia

1. **Tam-bellek okuma YASAK.** 48 MB'lık bir ZIP (E12:180) tek `SELECT data` ile
   okunsaydı uygulamanın belleğinde tam boy kopyalanır, birkaç eşzamanlı indirme
   süreci düşürürdü. Kanıt T2'nin yöntemidir: istek boyunca koşan SQL yakalanır,
   `substring`li sorgu sayısı ≥ parça sayısı olmalı ve `document_blobs.data`yı
   PARÇALAMADAN seçen ÇIPLAK bir SELECT hiç görülmemelidir.
2. **Başlıklar doğru.** `Content-Type` künyedeki (uzantıdan türetilmiş) tiptir,
   `Content-Length` künyedeki `size_bytes`, `Content-Disposition` ise Türkçe
   karakterli adı RFC 5987 (`filename*=UTF-8''…`) ile taşır.

`X-Content-Type-Options: nosniff` + `attachment` company logo ucundan gelen
desendir: tarayıcı içeriği sniff'leyip HTML olarak çalıştıramaz.
"""

import uuid
from urllib.parse import quote

from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.documents.storage import STREAM_CHUNK_BYTES


class _SqlKaydedici:
    def __init__(self) -> None:
        self.ifadeler: list[str] = []

    def __call__(self, conn, cursor, statement, parameters, context, executemany) -> None:
        self.ifadeler.append(statement)

    def substringli(self) -> list[str]:
        return [s for s in self.ifadeler if "substring" in s.lower()]

    def tam_sutun_okumalari(self) -> list[str]:
        return [
            s
            for s in self.ifadeler
            if "document_blobs" in s.lower()
            and "data" in s.lower()
            and "substring" not in s.lower()
            and s.lower().lstrip().startswith("select")
        ]


async def test_belge_indirilir(client: AsyncClient, proje, belge_fabrikasi, sef_headers) -> None:
    belge = await belge_fabrikasi(proje, "Hakedis_47.pdf", data=b"%PDF icerik", size_bytes=11)

    resp = await client.get(f"/documents/{belge.id}/download", headers=sef_headers)

    assert resp.status_code == 200, resp.text
    assert resp.content == b"%PDF icerik"


async def test_content_type_kunyeden_gelir(
    client: AsyncClient, proje, belge_fabrikasi, sef_headers
) -> None:
    """İstemcinin yükleme sırasındaki beyanı DEĞİL, künyedeki tip sunulur."""
    belge = await belge_fabrikasi(
        proje, "Metraj.xlsx", data=b"xls", size_bytes=3, mime_type="application/vnd.ms-excel"
    )

    resp = await client.get(f"/documents/{belge.id}/download", headers=sef_headers)

    assert resp.headers["content-type"] == "application/vnd.ms-excel"
    assert resp.headers["x-content-type-options"] == "nosniff"


async def test_content_length_kunyedeki_boyuttur(
    client: AsyncClient, proje, belge_fabrikasi, sef_headers
) -> None:
    icerik = b"y" * 5000
    belge = await belge_fabrikasi(proje, "Rapor.pdf", data=icerik, size_bytes=len(icerik))

    resp = await client.get(f"/documents/{belge.id}/download", headers=sef_headers)

    assert resp.headers["content-length"] == str(len(icerik))
    assert len(resp.content) == len(icerik)


async def test_turkce_karakterli_ad_rfc5987_ile_tasinir(
    client: AsyncClient, proje, belge_fabrikasi, sef_headers
) -> None:
    """ŞART (görev emri): Türkçe karakterli dosya adı bozulmadan inmeli.

    Latin-1 dışı karakterler HTTP başlığına ham yazılamaz; `filename*` yüzde
    kodlaması olmadan ad ya bozulur ya da başlık tamamen düşer.
    """
    ad = "Günlük Rapor 17.07.2026.pdf"
    belge = await belge_fabrikasi(proje, ad, data=b"veri", size_bytes=4)

    resp = await client.get(f"/documents/{belge.id}/download", headers=sef_headers)

    disposition = resp.headers["content-disposition"]
    assert disposition.startswith("attachment;")
    assert f"filename*=UTF-8''{quote(ad, safe='')}" in disposition
    assert 'filename="Gunluk Rapor 17.07.2026.pdf"' in disposition


async def test_STREAMING_KANITI_parcali_okunur(
    client: AsyncClient, seeded_db: AsyncSession, proje, belge_fabrikasi, sef_headers
) -> None:
    """ASIL KANIT: 2,5 MB'lık içerik VARSAYILAN parça boyuyla üç sorguda iner.

    Parça boyu testte küçültülMEZ — küçültülseydi kanıt yalnız test
    yapılandırması için geçerli olurdu.
    """
    boyut = STREAM_CHUNK_BYTES * 2 + STREAM_CHUNK_BYTES // 2
    icerik = b"x" * boyut
    belge = await belge_fabrikasi(proje, "Santiye_Foto.zip", data=icerik, size_bytes=boyut)

    kaydedici = _SqlKaydedici()
    bind = seeded_db.sync_session.get_bind()
    event.listen(bind, "before_cursor_execute", kaydedici)
    try:
        resp = await client.get(f"/documents/{belge.id}/download", headers=sef_headers)
    finally:
        event.remove(bind, "before_cursor_execute", kaydedici)

    assert resp.status_code == 200, resp.text
    assert len(resp.content) == boyut
    assert len(kaydedici.substringli()) >= 3, "parçalı okuma görülmedi"
    assert kaydedici.tam_sutun_okumalari() == [], "blob tek SELECT ile belleğe alınmış"


async def test_icerigi_olmayan_kunye_404(
    client: AsyncClient, proje, belge_fabrikasi, sef_headers
) -> None:
    """Künye var, bayt yok: boş 200 DÖNÜLMEZ (kullanıcı 0 baytlık bozuk dosya
    indirir ve hatayı ancak açmaya çalışınca görürdü).

    Bu aynı zamanda akışın ilk parçasının yanıt BAŞLAMADAN ÖNCE alındığının
    kanıtıdır: gövde akmaya başlasaydı hata 404'e çevrilemez, yarım bir 200
    olarak inerdi.
    """
    belge = await belge_fabrikasi(proje, "Kunye.pdf")

    resp = await client.get(f"/documents/{belge.id}/download", headers=sef_headers)

    assert resp.status_code == 404, resp.text


async def test_salt_okur_rol_indirebilir(
    client: AsyncClient, proje, belge_fabrikasi, pm_headers
) -> None:
    belge = await belge_fabrikasi(proje, "Ruhsat.pdf", data=b"veri", size_bytes=4)

    resp = await client.get(f"/documents/{belge.id}/download", headers=pm_headers)

    assert resp.status_code == 200, resp.text


# --- IDOR ---


async def test_gorunmeyen_projenin_belgesi_indirilemez_404(
    client: AsyncClient, ikinci_proje, belge_fabrikasi, sef_headers
) -> None:
    belge = await belge_fabrikasi(ikinci_proje, "Gizli.pdf", data=b"veri", size_bytes=4)

    resp = await client.get(f"/documents/{belge.id}/download", headers=sef_headers)

    assert resp.status_code == 404, resp.text


async def test_gorunmeyen_belge_var_olmayandan_ayirt_edilemez(
    client: AsyncClient, ikinci_proje, belge_fabrikasi, sef_headers
) -> None:
    belge = await belge_fabrikasi(ikinci_proje, "Gizli.pdf", data=b"veri", size_bytes=4)

    gorunmeyen = await client.get(f"/documents/{belge.id}/download", headers=sef_headers)
    yok = await client.get(f"/documents/{uuid.uuid4()}/download", headers=sef_headers)

    assert gorunmeyen.status_code == yok.status_code == 404
    assert gorunmeyen.json() == yok.json()


async def test_kimliksiz_indirme_401(client: AsyncClient, proje, belge_fabrikasi) -> None:
    belge = await belge_fabrikasi(proje, "Ruhsat.pdf", data=b"veri", size_bytes=4)

    resp = await client.get(f"/documents/{belge.id}/download")

    assert resp.status_code == 401
