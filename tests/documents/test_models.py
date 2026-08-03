"""Belge çekirdeği (T1) — üç tablonun şeması, FK davranışları ve UQ kısıtı.

Spec: `docs/superpowers/specs/2026-08-03-belge-cekirdegi-design.md` §2.
Uç YOKTUR (T2/T3); burada yalnız DB katmanı sınanır.
"""

import pytest
from sqlalchemy import delete, inspect, select
from sqlalchemy.exc import IntegrityError

from app.core.db import Base
from app.modules.documents.models import Document, DocumentBlob, DocumentFolder
from app.modules.projects.models import Project
from app.modules.sites.models import Site

# --- Şema ---


async def test_uc_tablo_metadata_da_kayitli() -> None:
    """`Base.metadata` üç tabloyu da tanımalı (env.py/conftest import zinciri)."""
    for tablo in ("document_folders", "documents", "document_blobs"):
        assert tablo in Base.metadata.tables


async def test_belge_kunyesinde_versiyon_onay_etiket_kolonu_yok() -> None:
    """Spec §2: künyede versiyon/onay/etiket kolonu YOKTUR — sızarsa bulgudur."""
    kolonlar = set(Base.metadata.tables["documents"].columns.keys())
    yasakli = {
        "version",
        "version_no",
        "revision",
        "approval_status",
        "approved_by",
        "approved_at",
        "tags",
        "tag",
        "thumbnail",
        "thumbnail_data",
    }
    assert kolonlar & yasakli == set()


async def test_blob_tablosunda_yalniz_document_id_ve_data_var() -> None:
    kolonlar = set(Base.metadata.tables["document_blobs"].columns.keys())
    assert kolonlar == {"document_id", "data"}


async def test_document_blobs_pk_document_id() -> None:
    tablo = Base.metadata.tables["document_blobs"]
    assert [c.name for c in tablo.primary_key.columns] == ["document_id"]


async def test_document_ile_blob_arasinda_eager_iliski_yok() -> None:
    """KRİTİK (spec §2): blob künye sorgusuna ASLA katılmamalı.

    `lazy="joined"`/`"selectin"`/`"subquery"` bir ilişki eklenirse her künye
    sorgusu 48 MB'lık bayt sütununu da çeker.
    """
    for iliski in inspect(Document).relationships:
        assert iliski.lazy not in ("joined", "selectin", "subquery", "immediate"), (
            f"Document.{iliski.key} eager yükleniyor ({iliski.lazy}) — blob izolasyonu kırılır."
        )


# --- Yazma / okuma ---


async def test_proje_duzeyi_klasor_site_id_null(seeded_db, proje, klasor_fabrikasi) -> None:
    klasor = await klasor_fabrikasi(proje, "Sözleşmeler")
    assert klasor.site_id is None
    assert klasor.parent_id is None
    assert klasor.created_at is not None


async def test_alt_klasor_parent_id_ile_baglanir(
    seeded_db, proje, santiye, klasor_fabrikasi
) -> None:
    ust = await klasor_fabrikasi(proje, "İzin & Ruhsat", site=santiye)
    alt = await klasor_fabrikasi(proje, "2026", site=santiye, parent=ust)
    assert alt.parent_id == ust.id


async def test_belge_kunyesi_blobsuz_yazilabilir(seeded_db, proje, belge_fabrikasi) -> None:
    """Künye tek başına anlamlıdır; blob AYRI tablodadır (spec §2)."""
    belge = await belge_fabrikasi(
        proje,
        "Ruhsat-Rev3.pdf",
        description="Aylık denetim",
        uploaded_by_name="Şantiye Şefi: S. Öztürk",
        size_bytes=48 * 1024 * 1024,
    )
    assert belge.folder_id is None
    assert belge.site_id is None
    assert belge.size_bytes == 48 * 1024 * 1024
    blob_sayisi = (
        (await seeded_db.execute(select(DocumentBlob).where(DocumentBlob.document_id == belge.id)))
        .scalars()
        .all()
    )
    assert blob_sayisi == []


async def test_blob_baytlari_geri_okunur(seeded_db, proje, belge_fabrikasi) -> None:
    veri = b"%PDF-1.7\x00\xff" * 16
    belge = await belge_fabrikasi(proje, "Sozlesme.pdf", data=veri)
    blob = (
        await seeded_db.execute(select(DocumentBlob).where(DocumentBlob.document_id == belge.id))
    ).scalar_one()
    assert blob.data == veri


# --- FK davranışları ---


async def test_belge_silinince_blob_cascade_ile_gider(seeded_db, proje, belge_fabrikasi) -> None:
    belge = await belge_fabrikasi(proje, "Silinecek.pdf", data=b"veri")
    await seeded_db.execute(delete(Document).where(Document.id == belge.id))
    await seeded_db.flush()
    kalan = (await seeded_db.execute(select(DocumentBlob.document_id))).scalars().all()
    assert kalan == []


async def test_klasor_silinince_belge_folder_id_null_olur(
    seeded_db, proje, santiye, klasor_fabrikasi, belge_fabrikasi
) -> None:
    """SET NULL: klasör kaldırılınca belge KAYBOLMAZ, köke düşer (spec §2)."""
    klasor = await klasor_fabrikasi(proje, "Fotoğraflar", site=santiye)
    belge = await belge_fabrikasi(proje, "Saha.jpg", site=santiye, folder=klasor)
    await seeded_db.execute(delete(DocumentFolder).where(DocumentFolder.id == klasor.id))
    await seeded_db.flush()
    seeded_db.expunge_all()
    folder_id = (
        await seeded_db.execute(select(Document.folder_id).where(Document.id == belge.id))
    ).scalar_one()
    assert folder_id is None


async def test_ust_klasor_silinince_alt_klasor_parent_id_null_olur(
    seeded_db, proje, santiye, klasor_fabrikasi
) -> None:
    ust = await klasor_fabrikasi(proje, "Onay & İzinler", site=santiye)
    alt = await klasor_fabrikasi(proje, "Belediye", site=santiye, parent=ust)
    await seeded_db.execute(delete(DocumentFolder).where(DocumentFolder.id == ust.id))
    await seeded_db.flush()
    seeded_db.expunge_all()
    parent_id = (
        await seeded_db.execute(select(DocumentFolder.parent_id).where(DocumentFolder.id == alt.id))
    ).scalar_one()
    assert parent_id is None


async def test_proje_silinince_klasor_ve_belge_cascade_ile_gider(
    seeded_db, proje, santiye, klasor_fabrikasi, belge_fabrikasi
) -> None:
    klasor = await klasor_fabrikasi(proje, "Sözleşmeler", site=santiye)
    await belge_fabrikasi(proje, "Ana.pdf", site=santiye, folder=klasor, data=b"x")
    await seeded_db.execute(delete(Project).where(Project.id == proje.id))
    await seeded_db.flush()
    assert (await seeded_db.execute(select(DocumentFolder.id))).scalars().all() == []
    assert (await seeded_db.execute(select(Document.id))).scalars().all() == []
    assert (await seeded_db.execute(select(DocumentBlob.document_id))).scalars().all() == []


async def test_santiye_silinince_klasor_ve_belge_cascade_ile_gider(
    seeded_db, proje, santiye, klasor_fabrikasi, belge_fabrikasi
) -> None:
    klasor = await klasor_fabrikasi(proje, "Saha Fotoğrafları", site=santiye)
    await belge_fabrikasi(proje, "Beton.jpg", site=santiye, folder=klasor)
    await seeded_db.execute(delete(Site).where(Site.id == santiye.id))
    await seeded_db.flush()
    assert (await seeded_db.execute(select(DocumentFolder.id))).scalars().all() == []
    assert (await seeded_db.execute(select(Document.id))).scalars().all() == []


# --- UQ kısıtı ---


async def test_ayni_kapsamda_ayni_adli_klasor_ikinci_kez_acilamaz(
    seeded_db, proje, santiye, klasor_fabrikasi
) -> None:
    ust = await klasor_fabrikasi(proje, "İzin & Ruhsat", site=santiye)
    await klasor_fabrikasi(proje, "2026", site=santiye, parent=ust)
    with pytest.raises(IntegrityError):
        await klasor_fabrikasi(proje, "2026", site=santiye, parent=ust)


async def test_farkli_santiyede_ayni_ad_serbest(
    seeded_db, proje, santiye, klasor_fabrikasi
) -> None:
    ikinci = Site(project_id=proje.id, code="BC-B", name="B-Blok")
    seeded_db.add(ikinci)
    await seeded_db.flush()
    a = await klasor_fabrikasi(proje, "Fotoğraflar", site=santiye)
    b = await klasor_fabrikasi(proje, "Fotoğraflar", site=ikinci)
    assert a.id != b.id


async def test_farkli_projede_ayni_ad_serbest(
    seeded_db, proje, ikinci_proje, santiye, klasor_fabrikasi
) -> None:
    diger_santiye = Site(project_id=ikinci_proje.id, code="BC-C", name="C-Blok")
    seeded_db.add(diger_santiye)
    await seeded_db.flush()
    a = await klasor_fabrikasi(proje, "Sözleşmeler", site=santiye)
    b = await klasor_fabrikasi(ikinci_proje, "Sözleşmeler", site=diger_santiye)
    assert a.id != b.id


async def test_uq_kisiti_beklenen_adla_tanimli() -> None:
    tablo = Base.metadata.tables["document_folders"]
    uq = {
        k.name: tuple(c.name for c in k.columns)
        for k in tablo.constraints
        if k.__class__.__name__ == "UniqueConstraint"
    }
    assert uq == {"uq_document_folder_scope_name": ("project_id", "site_id", "parent_id", "name")}


async def test_null_kapsamda_uq_postgres_te_ISLEMEZ_bilinen_sinir(
    seeded_db, proje, klasor_fabrikasi
) -> None:
    """BİLİNEN SINIR — davranışı dondurur, hata DEĞİLDİR.

    Postgres'in varsayılan `NULLS DISTINCT` semantiği yüzünden proje düzeyi kök
    klasörlerde (`site_id IS NULL` **ve** `parent_id IS NULL`) UQ fiilen işlemez;
    `SitePlanRow`daki `section_id` NULL dalıyla aynı durum. Tekillik o dalda
    T2'nin yazma ucunun (mevcut-ad kontrolü → 409) sorumluluğundadır.

    Bu test kırıldığı gün kısıt `NULLS NOT DISTINCT`e çevrilmiş demektir; o zaman
    T2'deki uygulama-katmanı kontrolü gözden geçirilir.
    """
    a = await klasor_fabrikasi(proje, "Genel")
    b = await klasor_fabrikasi(proje, "Genel")
    assert a.id != b.id
