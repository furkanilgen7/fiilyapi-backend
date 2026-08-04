"""`POST /documents` — multipart yükleme (T3, spec §3 / §4).

Kapı `documents:full`tür (okuma `view`, silme `admin`). Sınırlar spec §4:
50 MB (`document_max_bytes`) aşımı **413**, beyaz liste dışı uzantı **422**.

## Burada dondurulan üç karar

1. **Boyut sınırı BELLEĞE ALMADAN uygulanır** — gövde 64 KB'lık parçalar hâlinde
   okunur ve toplam tavanı aştığı ANDA okuma kesilip 413 dönülür (company logo
   deseni). Tamamını okuyup sonra bakmak, 2 GB'lık bir gövdeyle uygulamayı
   düşürebilecek bir DoS yüzeyi olurdu; testte tavan config override'ıyla
   küçültülüp "sınırın üstünde kalan baytların okunmadığı" ölçülür.
2. **Künye + blob ATOMİK** — `storage.put` künye INSERT'i ile AYNI transaction
   içindedir. `put` patlarsa künye de YAZILMAZ (aşağıdaki atomiklik testi bunu
   üretim `get_db` semantiğiyle kanıtlar).
3. **Klasöre yazarken klasör PAYLAŞIMLI kilitlenir** (`lock_folder_shared`) —
   T2'nin silme yolu aynı satırı `FOR UPDATE` ile kilitler. Kilitsiz bırakılsaydı
   "boş klasörü sil" ile "içine belge yükle" yarışında belge, silinmiş klasörün
   içine yazılır ve `folder_id` SET NULL ile sessizce köke düşerdi.
"""

import uuid
from collections.abc import AsyncGenerator, AsyncIterator

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_db
from app.main import app
from app.modules.audit.models import AuditAction, AuditLog
from app.modules.documents.deps import get_storage_backend
from app.modules.documents.models import Document, DocumentBlob

PDF = b"%PDF-1.4 sahte icerik"


def _multipart(
    filename: str = "Hakedis_47.pdf",
    content: bytes = PDF,
    content_type: str = "application/pdf",
) -> dict:
    return {"file": (filename, content, content_type)}


def _form(project_id: uuid.UUID, **extra: str) -> dict[str, str]:
    return {"project_id": str(project_id), **extra}


# --- Mutlu yol ---


async def test_belge_yuklenir(
    client: AsyncClient, seeded_db: AsyncSession, proje, sef_headers
) -> None:
    resp = await client.post(
        "/documents", data=_form(proje.id), files=_multipart(), headers=sef_headers
    )

    assert resp.status_code == 201, resp.text
    govde = resp.json()
    assert govde["filename"] == "Hakedis_47.pdf"
    assert govde["size_bytes"] == len(PDF)
    assert govde["mime_type"] == "application/pdf"
    assert govde["project_id"] == str(proje.id)
    assert govde["site_id"] is None
    assert govde["folder_id"] is None


async def test_yuklenen_baytlar_blob_tablosuna_yazilir(
    client: AsyncClient, seeded_db: AsyncSession, proje, sef_headers
) -> None:
    resp = await client.post(
        "/documents", data=_form(proje.id), files=_multipart(), headers=sef_headers
    )

    belge_id = uuid.UUID(resp.json()["id"])
    veri = (
        await seeded_db.execute(
            select(DocumentBlob.data).where(DocumentBlob.document_id == belge_id)
        )
    ).scalar_one()
    assert veri == PDF


async def test_santiye_ve_klasor_kapsaminda_yuklenir(
    client: AsyncClient, proje, santiye, klasor_fabrikasi, sef_headers
) -> None:
    klasor = await klasor_fabrikasi(proje, "Hakedişler", site=santiye)

    resp = await client.post(
        "/documents",
        data=_form(proje.id, site_id=str(santiye.id), folder_id=str(klasor.id)),
        files=_multipart(),
        headers=sef_headers,
    )

    assert resp.status_code == 201, resp.text
    assert resp.json()["site_id"] == str(santiye.id)
    assert resp.json()["folder_id"] == str(klasor.id)


async def test_aciklama_kaydedilir(client: AsyncClient, proje, sef_headers) -> None:
    """SB151 alt-satırı: "Fotoğraflar · 48 fotoğraf" — serbest metin."""
    resp = await client.post(
        "/documents",
        data=_form(proje.id, description="48 fotoğraf"),
        files=_multipart("Santiye_Foto.zip", b"PK\x03\x04veri", "application/zip"),
        headers=sef_headers,
    )

    assert resp.status_code == 201, resp.text
    assert resp.json()["description"] == "48 fotoğraf"


async def test_yukleyen_adi_snapshot_alinir(
    client: AsyncClient, seeded_db: AsyncSession, proje, sef_headers
) -> None:
    """SB144 "Şantiye Şefi: S. Öztürk" — ad künyeye KOPYALANIR, JOIN'le
    çözülmez; kullanıcı silinse de arşivde kim yüklediyse o yazar."""
    resp = await client.post(
        "/documents", data=_form(proje.id), files=_multipart(), headers=sef_headers
    )

    belge = (
        await seeded_db.execute(select(Document).where(Document.id == uuid.UUID(resp.json()["id"])))
    ).scalar_one()
    assert belge.uploaded_by_name
    assert belge.uploaded_by_user_id is not None
    assert resp.json()["uploaded_by_name"] == belge.uploaded_by_name


async def test_yukleme_denetime_yazilir(
    client: AsyncClient, seeded_db: AsyncSession, proje, sef_headers
) -> None:
    await client.post("/documents", data=_form(proje.id), files=_multipart(), headers=sef_headers)

    detaylar = [
        satir.detail
        for satir in (
            await seeded_db.execute(select(AuditLog).where(AuditLog.action == AuditAction.create))
        )
        .scalars()
        .all()
    ]
    assert any("Hakedis_47.pdf" in d and proje.name in d for d in detaylar)


# --- Beyaz liste BYPASS denemeleri (422) ---


@pytest.mark.parametrize(
    "ad",
    [
        "virus.exe",
        # ÇİFT UZANTI — karar SON uzantıya göre verilir.
        "rapor.pdf.exe",
        "arsiv.zip.sh",
        # Uzantısız dosya.
        "LICENSE",
        # Nokta/boşlukla gizlenmiş yasak uzantı.
        "rapor.exe.",
        "  rapor.exe  ",
    ],
)
async def test_beyaz_liste_disi_uzanti_422(
    client: AsyncClient, proje, sef_headers, ad: str
) -> None:
    resp = await client.post(
        "/documents",
        data=_form(proje.id),
        files=_multipart(ad, b"zararli", "application/pdf"),
        headers=sef_headers,
    )

    assert resp.status_code == 422, resp.text


async def test_buyuk_harfli_uzanti_kabul_edilir(client: AsyncClient, proje, sef_headers) -> None:
    resp = await client.post(
        "/documents",
        data=_form(proje.id),
        files=_multipart("RAPOR.PDF", PDF, "application/pdf"),
        headers=sef_headers,
    )

    assert resp.status_code == 201, resp.text
    assert resp.json()["filename"] == "RAPOR.PDF"
    assert resp.json()["mime_type"] == "application/pdf"


async def test_content_type_yalan_soylerse_uzanti_kazanir(
    client: AsyncClient, proje, sef_headers
) -> None:
    """OTORİTE UZANTIDIR: istemcinin `Content-Type`ı künyeye YAZILMAZ.

    Aksi hâlde `.pdf` adıyla yüklenen bir HTML, indirme ucundan `text/html`
    olarak sunulur ve depolanmış XSS olurdu.
    """
    resp = await client.post(
        "/documents",
        data=_form(proje.id),
        files=_multipart("rapor.pdf", b"<script>alert(1)</script>", "text/html"),
        headers=sef_headers,
    )

    assert resp.status_code == 201, resp.text
    assert resp.json()["mime_type"] == "application/pdf"


async def test_izinli_uzanti_yasak_content_type_ile_reddedilmez(
    client: AsyncClient, proje, sef_headers
) -> None:
    """Tersi de doğrudur: tarayıcı `dwg` için tuhaf bir MIME gönderse de meşru
    dosya reddedilmez (beyaz liste UZANTI listesidir)."""
    resp = await client.post(
        "/documents",
        data=_form(proje.id),
        files=_multipart("Mimari_Rev3.dwg", b"dwgdata", "application/octet-stream"),
        headers=sef_headers,
    )

    assert resp.status_code == 201, resp.text
    assert resp.json()["mime_type"] == "image/vnd.dwg"


async def test_yol_adi_enjeksiyonu_temizlenir_ama_gorunen_ad_korunur(
    client: AsyncClient, proje, sef_headers
) -> None:
    resp = await client.post(
        "/documents",
        data=_form(proje.id),
        files=_multipart("../../etc/Günlük Rapor.pdf", PDF, "application/pdf"),
        headers=sef_headers,
    )

    assert resp.status_code == 201, resp.text
    assert resp.json()["filename"] == "Günlük Rapor.pdf"


async def test_bos_dosya_adi_422(client: AsyncClient, proje, sef_headers) -> None:
    resp = await client.post(
        "/documents",
        data=_form(proje.id),
        files=_multipart("../", PDF, "application/pdf"),
        headers=sef_headers,
    )

    assert resp.status_code == 422, resp.text


# --- Boyut sınırı (413) ---


@pytest.fixture
def kucuk_tavan(monkeypatch: pytest.MonkeyPatch) -> int:
    """Tavanı test için küçültür — 50 MB'lık gerçek gövde üretmek testi
    saniyeler boyunca meşgul ederdi. Sınırın KENDİSİ config'ten okunduğu için
    davranış aynıdır (`test_config.py` gerçek değeri ayrıca dondurur)."""
    monkeypatch.setattr(settings, "document_max_bytes", 1024)
    return 1024


async def test_tavani_asan_dosya_413(
    client: AsyncClient, seeded_db: AsyncSession, proje, sef_headers, kucuk_tavan: int
) -> None:
    resp = await client.post(
        "/documents",
        data=_form(proje.id),
        files=_multipart("buyuk.zip", b"x" * (kucuk_tavan + 1), "application/zip"),
        headers=sef_headers,
    )

    assert resp.status_code == 413, resp.text
    sayi = (await seeded_db.execute(select(func.count()).select_from(Document))).scalar_one()
    assert sayi == 0, "413 dönen istek künye YAZMAMALI"


async def test_tam_tavandaki_dosya_kabul_edilir(
    client: AsyncClient, proje, sef_headers, kucuk_tavan: int
) -> None:
    resp = await client.post(
        "/documents",
        data=_form(proje.id),
        files=_multipart("tam.zip", b"x" * kucuk_tavan, "application/zip"),
        headers=sef_headers,
    )

    assert resp.status_code == 201, resp.text


async def test_boyut_sinirinda_govde_tamamen_bellege_alinmaz(
    client: AsyncClient, proje, sef_headers, kucuk_tavan: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DoS KANITI: okuma, tavanı aşan ilk parçadan SONRA durur.

    `UploadFile.read` sarmalanır ve okunan toplam bayt ölçülür. Gövde tavanın 100
    katıdır; tamamı okunsaydı ölçülen toplam gövde boyuna eşit çıkardı
    (mutasyonla doğrulandı: sınır kontrolü döngüden SONRAYA alınınca kırılır).

    ⚠️ Yama STARLETTE'in sınıfına uygulanır, `fastapi.UploadFile`e DEĞİL: gövdeyi
    ayrıştıran taraf Starlette'tir ve uca gelen nesne onun sınıfındandır. FastAPI
    alt sınıfına yamanmış bir sayaç hiç tetiklenmez ve test SESSİZCE boş bir
    ölçümle "geçer" — bu yüzden aşağıda sayacın çalıştığı ayrıca doğrulanır.

    Not: gövdeyi ağdan alan katman onu zaten diske (spooled temp file) yazar;
    burada verilen söz UYGULAMANIN gövdeyi tek bir `bytes` nesnesine ALMAMASIDIR.
    """
    from starlette.datastructures import UploadFile as StarletteUploadFile

    okunan: list[int] = []
    orijinal = StarletteUploadFile.read

    async def sayan_read(self: StarletteUploadFile, size: int = -1) -> bytes:
        parca = await orijinal(self, size)
        okunan.append(len(parca))
        return parca

    monkeypatch.setattr(StarletteUploadFile, "read", sayan_read)
    govde = b"x" * (kucuk_tavan * 100)

    resp = await client.post(
        "/documents",
        data=_form(proje.id),
        files=_multipart("dev.zip", govde, "application/zip"),
        headers=sef_headers,
    )

    assert resp.status_code == 413, resp.text
    assert okunan, "sayaç hiç tetiklenmedi — ölçüm geçersiz"
    toplam = sum(okunan)
    assert toplam < len(govde), "gövdenin tamamı okunmuş — sınır belleğe alınarak uygulanıyor"
    assert toplam <= kucuk_tavan + 65536


# --- ATOMİKLİK: künye yazıldı ama blob yazılamadı YARIMLIĞI İMKÂNSIZ ---


class _PatlayanBackend:
    """`put` her zaman patlar — atomikliğin tek sınama yolu budur."""

    def __init__(self) -> None:
        self.cagrildi = False

    async def put(self, document_id: uuid.UUID, data: bytes) -> None:
        self.cagrildi = True
        raise RuntimeError("depolama arizasi")

    async def stream(self, document_id: uuid.UUID) -> AsyncIterator[bytes]:
        yield b""

    async def delete(self, document_id: uuid.UUID) -> None:
        return None


async def test_blob_yazilamazsa_kunye_de_yazilmaz(
    client: AsyncClient, seeded_db: AsyncSession, proje, sef_headers
) -> None:
    """ATOMİKLİK KANITI — üretim `get_db` semantiğiyle.

    Kök `client` fixture'ı `get_db`yi commit/rollback YAPMAYAN bir sarmalayıcıyla
    değiştirir; o hâliyle bu iddia ölçülemezdi. Bu yüzden bağımlılık burada
    üretimdeki gibi (istisna → `rollback`, temiz çıkış → `commit`) yeniden
    takılır. Fixture'lar önce `commit` ile SAVEPOINT dışına alınır ki geri alma
    yalnız isteğin yazdıklarını götürsün.
    """
    await seeded_db.commit()
    backend = _PatlayanBackend()

    async def _uretim_gibi_get_db() -> AsyncGenerator[AsyncSession, None]:
        try:
            yield seeded_db
        except Exception:
            await seeded_db.rollback()
            raise
        else:
            await seeded_db.commit()

    app.dependency_overrides[get_db] = _uretim_gibi_get_db
    app.dependency_overrides[get_storage_backend] = lambda: backend
    try:
        with pytest.raises(RuntimeError):
            await client.post(
                "/documents", data=_form(proje.id), files=_multipart(), headers=sef_headers
            )
    finally:
        app.dependency_overrides.pop(get_storage_backend, None)

    assert backend.cagrildi, "put hiç çağrılmadı — test kendi iddiasını sınamıyor"
    sayi = (await seeded_db.execute(select(func.count()).select_from(Document))).scalar_one()
    assert sayi == 0, "blob yazılamadığı hâlde künye kaldı — yazma ATOMİK DEĞİL"
    denetim = (
        await seeded_db.execute(
            select(func.count()).select_from(AuditLog).where(AuditLog.action == AuditAction.create)
        )
    ).scalar_one()
    assert denetim == 0


# --- Kapsam korkulukları (422) ---


async def test_baska_projenin_santiyesine_yuklenemez(
    client: AsyncClient, proje, gorunmeyen_santiye, sef_headers
) -> None:
    resp = await client.post(
        "/documents",
        data=_form(proje.id, site_id=str(gorunmeyen_santiye.id)),
        files=_multipart(),
        headers=sef_headers,
    )

    assert resp.status_code == 422, resp.text


async def test_baska_kapsamin_klasorune_yuklenemez(
    client: AsyncClient, proje, santiye, klasor_fabrikasi, sef_headers
) -> None:
    """Klasör ŞANTİYE kapsamlı, yükleme PROJE düzeyi — kapsam ayrışırsa belge iki
    farklı kökte görünürdü."""
    klasor = await klasor_fabrikasi(proje, "Hakedişler", site=santiye)

    resp = await client.post(
        "/documents",
        data=_form(proje.id, folder_id=str(klasor.id)),
        files=_multipart(),
        headers=sef_headers,
    )

    assert resp.status_code == 422, resp.text


async def test_var_olmayan_klasor_422(client: AsyncClient, proje, sef_headers) -> None:
    resp = await client.post(
        "/documents",
        data=_form(proje.id, folder_id=str(uuid.uuid4())),
        files=_multipart(),
        headers=sef_headers,
    )

    assert resp.status_code == 422, resp.text


async def test_klasore_yazarken_klasor_paylasimli_kilitlenir(
    client: AsyncClient, proje, santiye, klasor_fabrikasi, sef_headers, monkeypatch
) -> None:
    """T2'den DEVREDİLEN UYARI: kilit alınmazsa "boş klasörü sil" yarışı açık kalır."""
    from app.modules.documents import repository

    kilitlenen: list[uuid.UUID] = []
    orijinal = repository.lock_folder_shared

    async def izleyen(session, folder_id):
        kilitlenen.append(folder_id)
        await orijinal(session, folder_id)

    monkeypatch.setattr(repository, "lock_folder_shared", izleyen)
    klasor = await klasor_fabrikasi(proje, "Hakedişler", site=santiye)

    resp = await client.post(
        "/documents",
        data=_form(proje.id, site_id=str(santiye.id), folder_id=str(klasor.id)),
        files=_multipart(),
        headers=sef_headers,
    )

    assert resp.status_code == 201, resp.text
    assert klasor.id in kilitlenen


# --- IDOR + yetki ---


async def test_gorunmeyen_projeye_yuklenemez_404(
    client: AsyncClient, ikinci_proje, sef_headers
) -> None:
    resp = await client.post(
        "/documents", data=_form(ikinci_proje.id), files=_multipart(), headers=sef_headers
    )

    assert resp.status_code == 404, resp.text


async def test_var_olmayan_proje_ile_ayni_govde(
    client: AsyncClient, ikinci_proje, sef_headers
) -> None:
    """Görünmeyen proje ile var OLMAYAN proje AYIRT EDİLEMEZ."""
    gorunmeyen = await client.post(
        "/documents", data=_form(ikinci_proje.id), files=_multipart(), headers=sef_headers
    )
    yok = await client.post(
        "/documents", data=_form(uuid.uuid4()), files=_multipart(), headers=sef_headers
    )

    assert gorunmeyen.status_code == yok.status_code == 404
    assert gorunmeyen.json() == yok.json()


async def test_salt_okur_rol_yukleyemez_403(client: AsyncClient, proje, pm_headers) -> None:
    resp = await client.post(
        "/documents", data=_form(proje.id), files=_multipart(), headers=pm_headers
    )

    assert resp.status_code == 403, resp.text


async def test_kimliksiz_yukleme_401(client: AsyncClient, proje) -> None:
    resp = await client.post("/documents", data=_form(proje.id), files=_multipart())

    assert resp.status_code == 401
