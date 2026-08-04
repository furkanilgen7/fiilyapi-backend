"""Klasör uçları (T2) — spec §3 birinci satırı.

Dört uç, üç izin seviyesi:

| Uç | Yetki |
|---|---|
| `GET /projects/{id}/document-folders(?site_id=)` | `documents:view` |
| `POST /projects/{id}/document-folders` | `documents:full` |
| `PATCH /document-folders/{id}` | `documents:full` |
| `DELETE /document-folders/{id}` | `documents:admin` |

## Dondurulan iki karar

1. **`site_id` süzgeci** — parametre VERİLMEZSE yalnız PROJE DÜZEYİ klasörler
   (`site_id IS NULL`) döner; verilirse YALNIZ o şantiyenin klasörleri. Spec §3
   bunu netleştirmiyordu (E12 "kök = proje/şantiye" diyor); süzgecin açık ve
   öngörülebilir olması seçildi — "hepsi + şantiyeler" karışık bir liste, ekranın
   hangi kökte olduğunu gövdeden çıkaramamasına yol açardı.
2. **Dolu klasör silme → 409** (`RelatedRecordsExistError`). 403 DEĞİL: kullanıcının
   yetkisi vardır, engelleyen şey kaydın DURUMUDUR (`sites` `SITE_HAS_SECTIONS`
   deseninin birebiri).

## T1'den devralınan NULL tuzağı

`uq_document_folder_scope_name` Postgres'in `NULLS DISTINCT` semantiği yüzünden
`site_id` VEYA `parent_id`den biri NULL olduğu anda fiilen İŞLEMEZ (T2'de
ölçüldü: kısıt yalnız şantiye kapsamlı ALT klasörleri korur). Tekilliği uygulama
katmanı tutar; dört kapsam dalı da (şantiye kök, proje düzeyi kök, proje düzeyi
alt, şantiye alt) AYRI AYRI test edilir, ayrıca korunan dalda yarış durumunun DB
kısıtına düşüp yine 409 verdiği kanıtlanır.
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.models import AuditAction, AuditLog
from app.modules.documents.models import DocumentFolder


def _folders_url(project_id: uuid.UUID) -> str:
    return f"/projects/{project_id}/document-folders"


async def _audit_details(seeded_db: AsyncSession, action: AuditAction) -> list[str]:
    rows = (
        (await seeded_db.execute(select(AuditLog).where(AuditLog.action == action))).scalars().all()
    )
    return [row.detail for row in rows]


# --- POST: mutlu yol ---


async def test_proje_duzeyi_klasor_acilir(
    client: AsyncClient, seeded_db: AsyncSession, proje, sef_headers
) -> None:
    resp = await client.post(
        _folders_url(proje.id), json={"name": "Sözleşmeler"}, headers=sef_headers
    )

    assert resp.status_code == 201, resp.text
    govde = resp.json()
    assert govde["name"] == "Sözleşmeler"
    assert govde["site_id"] is None
    assert govde["parent_id"] is None
    assert govde["project_id"] == str(proje.id)


async def test_santiye_kapsamli_klasor_acilir(
    client: AsyncClient, proje, santiye, sef_headers
) -> None:
    resp = await client.post(
        _folders_url(proje.id),
        json={"name": "İzin & Ruhsat", "site_id": str(santiye.id)},
        headers=sef_headers,
    )

    assert resp.status_code == 201, resp.text
    assert resp.json()["site_id"] == str(santiye.id)


async def test_alt_klasor_acilir(
    client: AsyncClient, proje, santiye, klasor_fabrikasi, sef_headers
) -> None:
    ust = await klasor_fabrikasi(proje, "Sözleşmeler", site=santiye)

    resp = await client.post(
        _folders_url(proje.id),
        json={"name": "2026", "site_id": str(santiye.id), "parent_id": str(ust.id)},
        headers=sef_headers,
    )

    assert resp.status_code == 201, resp.text
    assert resp.json()["parent_id"] == str(ust.id)


async def test_klasor_olusturma_denetime_yazilir(
    client: AsyncClient, seeded_db: AsyncSession, proje, sef_headers
) -> None:
    await client.post(_folders_url(proje.id), json={"name": "Ruhsatlar"}, headers=sef_headers)

    detaylar = await _audit_details(seeded_db, AuditAction.create)
    assert any("Ruhsatlar" in d and proje.name in d for d in detaylar)


# --- POST: ad çakışması (409) ---


async def test_santiye_kapsaminda_ayni_ad_409(
    client: AsyncClient, proje, santiye, klasor_fabrikasi, sef_headers
) -> None:
    await klasor_fabrikasi(proje, "Sözleşmeler", site=santiye)

    resp = await client.post(
        _folders_url(proje.id),
        json={"name": "Sözleşmeler", "site_id": str(santiye.id)},
        headers=sef_headers,
    )

    assert resp.status_code == 409, resp.text


async def test_proje_duzeyinde_ayni_ad_409_NULL_kapsam(
    client: AsyncClient, proje, klasor_fabrikasi, sef_headers
) -> None:
    """T1'in dondurduğu tuzak: bu dalda DB kısıtı İŞLEMEZ, kontrol uygulamadadır.

    `site_id` ve `parent_id`in İKİSİ de NULL — `NULLS DISTINCT` yüzünden UNIQUE
    çakışmaz. Uygulama kontrolü kaldırılırsa bu test 201 görür (mutasyonla
    doğrulandı).
    """
    await klasor_fabrikasi(proje, "Genel")

    resp = await client.post(_folders_url(proje.id), json={"name": "Genel"}, headers=sef_headers)

    assert resp.status_code == 409, resp.text


async def test_ayni_ebeveyn_altinda_ayni_ad_409(
    client: AsyncClient, proje, klasor_fabrikasi, sef_headers
) -> None:
    """Proje düzeyi ALT klasör: `site_id` NULL, `parent_id` DOLU — yine NULL'lı dal."""
    ust = await klasor_fabrikasi(proje, "Arşiv")
    await klasor_fabrikasi(proje, "2025", parent=ust)

    resp = await client.post(
        _folders_url(proje.id), json={"name": "2025", "parent_id": str(ust.id)}, headers=sef_headers
    )

    assert resp.status_code == 409, resp.text


async def test_farkli_kapsamda_ayni_ad_serbesttir(
    client: AsyncClient, proje, santiye, klasor_fabrikasi, sef_headers
) -> None:
    """Kısıt KAPSAM içindedir: proje düzeyindeki "Genel" şantiyedekini engellemez."""
    await klasor_fabrikasi(proje, "Genel")

    resp = await client.post(
        _folders_url(proje.id),
        json={"name": "Genel", "site_id": str(santiye.id)},
        headers=sef_headers,
    )

    assert resp.status_code == 201, resp.text


async def test_yaris_durumu_db_kisitina_dusup_409_olur(
    client: AsyncClient,
    proje,
    santiye,
    klasor_fabrikasi,
    sef_headers,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Uygulama kontrolü rakip işlemi GÖREMEZSE emniyet ağı devrededir.

    Kontrol ile INSERT arasında başka bir istek aynı adı yazarsa uygulama kontrolü
    boş döner; `IntegrityError` → 409 eşlemesi bu deliği kapatır. Yarış burada
    kontrolün "hiçbir şey bulamaması" ile BİREBİR aynı şekilde taklit edilir.

    Senaryo ŞANTİYE KAPSAMLI ALT KLASÖRDÜR ve bu tesadüf değildir: `NULLS
    DISTINCT` yüzünden DB kısıtı yalnız `site_id` VE `parent_id`nin İKİSİ de dolu
    olduğunda çalışır. Diğer üç dalda emniyet ağı YOKTUR — orada yarışın tek
    savunması uygulama kontrolüdür (kabul edilen sınır, `service` docstring'i).
    """
    from app.modules.documents import repository

    ust = await klasor_fabrikasi(proje, "Arşiv", site=santiye)
    await klasor_fabrikasi(proje, "2026", site=santiye, parent=ust)

    async def _kor_kontrol(*args, **kwargs):
        return None

    monkeypatch.setattr(repository, "find_folder_by_name", _kor_kontrol)

    resp = await client.post(
        _folders_url(proje.id),
        json={"name": "2026", "site_id": str(santiye.id), "parent_id": str(ust.id)},
        headers=sef_headers,
    )

    assert resp.status_code == 409, resp.text


# --- POST: kapsam uyumsuzlukları (422) ---


async def test_baska_projenin_santiyesi_422(
    client: AsyncClient, proje, gorunmeyen_santiye, admin_headers
) -> None:
    """`site_id` bu projeye ait DEĞİL. 404 değil 422: istenen kaynak PROJEDİR,
    şantiye burada bir ALAN DEĞERİDİR (`sites` `USER_NOT_FOUND` gerekçesi)."""
    resp = await client.post(
        _folders_url(proje.id),
        json={"name": "Sözleşmeler", "site_id": str(gorunmeyen_santiye.id)},
        headers=admin_headers,
    )

    assert resp.status_code == 422, resp.text


async def test_var_olmayan_santiye_422(client: AsyncClient, proje, sef_headers) -> None:
    resp = await client.post(
        _folders_url(proje.id),
        json={"name": "Sözleşmeler", "site_id": str(uuid.uuid4())},
        headers=sef_headers,
    )

    assert resp.status_code == 422, resp.text


async def test_baska_projenin_klasoru_ebeveyn_olamaz_422(
    client: AsyncClient, proje, ikinci_proje, klasor_fabrikasi, admin_headers
) -> None:
    yabanci = await klasor_fabrikasi(ikinci_proje, "Sözleşmeler")

    resp = await client.post(
        _folders_url(proje.id),
        json={"name": "2026", "parent_id": str(yabanci.id)},
        headers=admin_headers,
    )

    assert resp.status_code == 422, resp.text


async def test_baska_santiyenin_klasoru_ebeveyn_olamaz_422(
    client: AsyncClient, proje, santiye, klasor_fabrikasi, sef_headers
) -> None:
    """Ebeveyn AYNI projede ama BAŞKA kapsamda (proje düzeyi ↔ şantiye).

    Kabul edilseydi şantiye klasörü proje düzeyi bir ağaca asılır ve E12 kökü
    ile SB sekmesi aynı kaydı iki farklı yerde gösterirdi.
    """
    proje_duzeyi = await klasor_fabrikasi(proje, "Arşiv")

    resp = await client.post(
        _folders_url(proje.id),
        json={"name": "2026", "site_id": str(santiye.id), "parent_id": str(proje_duzeyi.id)},
        headers=sef_headers,
    )

    assert resp.status_code == 422, resp.text


async def test_var_olmayan_ebeveyn_422(client: AsyncClient, proje, sef_headers) -> None:
    resp = await client.post(
        _folders_url(proje.id),
        json={"name": "2026", "parent_id": str(uuid.uuid4())},
        headers=sef_headers,
    )

    assert resp.status_code == 422, resp.text


# --- GET: süzgeç kararı ---


async def test_site_id_verilmezse_yalniz_proje_duzeyi(
    client: AsyncClient, proje, santiye, klasor_fabrikasi, pm_headers
) -> None:
    """DONDURULAN KARAR (1): parametre yoksa şantiye klasörleri KARIŞMAZ."""
    await klasor_fabrikasi(proje, "Proje Sözleşmeleri")
    await klasor_fabrikasi(proje, "Şantiye Tutanakları", site=santiye)

    resp = await client.get(_folders_url(proje.id), headers=pm_headers)

    assert resp.status_code == 200, resp.text
    adlar = [f["name"] for f in resp.json()["folders"]]
    assert adlar == ["Proje Sözleşmeleri"]


async def test_site_id_verilirse_yalniz_o_santiye(
    client: AsyncClient, proje, santiye, klasor_fabrikasi, pm_headers
) -> None:
    await klasor_fabrikasi(proje, "Proje Sözleşmeleri")
    await klasor_fabrikasi(proje, "Şantiye Tutanakları", site=santiye)

    resp = await client.get(
        _folders_url(proje.id), params={"site_id": str(santiye.id)}, headers=pm_headers
    )

    assert resp.status_code == 200, resp.text
    adlar = [f["name"] for f in resp.json()["folders"]]
    assert adlar == ["Şantiye Tutanakları"]


async def test_liste_alt_klasorleri_de_dondurur(
    client: AsyncClient, proje, klasor_fabrikasi, pm_headers
) -> None:
    """Ağaç DÜZ liste olarak döner; hiyerarşiyi `parent_id` taşır (UI iki seviye çizer)."""
    ust = await klasor_fabrikasi(proje, "Arşiv")
    await klasor_fabrikasi(proje, "2026", parent=ust)

    resp = await client.get(_folders_url(proje.id), headers=pm_headers)

    kayitlar = {f["name"]: f["parent_id"] for f in resp.json()["folders"]}
    assert kayitlar == {"Arşiv": None, "2026": str(ust.id)}


async def test_liste_ada_gore_siralanir(
    client: AsyncClient, proje, klasor_fabrikasi, pm_headers
) -> None:
    for ad in ("Zeyilname", "Ruhsat", "Ataşman"):
        await klasor_fabrikasi(proje, ad)

    resp = await client.get(_folders_url(proje.id), headers=pm_headers)

    assert [f["name"] for f in resp.json()["folders"]] == ["Ataşman", "Ruhsat", "Zeyilname"]


# --- IDOR ---


async def test_gorunmeyen_projenin_listesi_404(
    client: AsyncClient, ikinci_proje, sef_headers
) -> None:
    resp = await client.get(_folders_url(ikinci_proje.id), headers=sef_headers)

    assert resp.status_code == 404, resp.text


async def test_var_olmayan_proje_ile_ayni_govde(
    client: AsyncClient, ikinci_proje, sef_headers
) -> None:
    """Görünmeyen GERÇEK proje ile var OLMAYAN kimlik AYIRT EDİLEMEZ (WORKFLOW §4)."""
    gercek = await client.get(_folders_url(ikinci_proje.id), headers=sef_headers)
    hayali = await client.get(_folders_url(uuid.uuid4()), headers=sef_headers)

    assert gercek.status_code == hayali.status_code == 404
    assert gercek.json() == hayali.json()


async def test_gorunmeyen_projede_klasor_acilamaz_404(
    client: AsyncClient, ikinci_proje, sef_headers
) -> None:
    resp = await client.post(
        _folders_url(ikinci_proje.id), json={"name": "Sızıntı"}, headers=sef_headers
    )

    assert resp.status_code == 404, resp.text


async def test_gorunmeyen_klasor_patch_404_ve_govde_ayirt_edilemez(
    client: AsyncClient, ikinci_proje, klasor_fabrikasi, sef_headers
) -> None:
    yabanci = await klasor_fabrikasi(ikinci_proje, "Sözleşmeler")

    gercek = await client.patch(
        f"/document-folders/{yabanci.id}", json={"name": "Yeni"}, headers=sef_headers
    )
    hayali = await client.patch(
        f"/document-folders/{uuid.uuid4()}", json={"name": "Yeni"}, headers=sef_headers
    )

    assert gercek.status_code == hayali.status_code == 404
    assert gercek.json() == hayali.json()


async def test_var_olmayan_klasor_delete_404(client: AsyncClient, admin_headers) -> None:
    """Silme kapsam süzgecini AYNI yardımcıdan geçer; `system_admin`in `projects`
    izni `admin` olduğu için (kilitlenme koruması) görünmeyen-kapsam ayağı
    PATCH testinde sınanır — burada kimliğin yokluğu sınanır."""
    resp = await client.delete(f"/document-folders/{uuid.uuid4()}", headers=admin_headers)

    assert resp.status_code == 404, resp.text


# --- PATCH ---


async def test_klasor_adi_degistirilir(
    client: AsyncClient, seeded_db: AsyncSession, proje, klasor_fabrikasi, sef_headers
) -> None:
    klasor = await klasor_fabrikasi(proje, "Sozlesmeler")

    resp = await client.patch(
        f"/document-folders/{klasor.id}", json={"name": "Sözleşmeler"}, headers=sef_headers
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "Sözleşmeler"
    detaylar = await _audit_details(seeded_db, AuditAction.update)
    assert any("Sozlesmeler" in d and "Sözleşmeler" in d for d in detaylar)


async def test_patch_ad_cakismasi_409(
    client: AsyncClient, proje, klasor_fabrikasi, sef_headers
) -> None:
    await klasor_fabrikasi(proje, "Ruhsat")
    hedef = await klasor_fabrikasi(proje, "Tutanak")

    resp = await client.patch(
        f"/document-folders/{hedef.id}", json={"name": "Ruhsat"}, headers=sef_headers
    )

    assert resp.status_code == 409, resp.text


async def test_patch_ayni_adi_yeniden_yazmak_serbest(
    client: AsyncClient, proje, klasor_fabrikasi, sef_headers
) -> None:
    """Kaydın KENDİSİ çakışma sayılmaz — aksi hâlde "Kaydet" ikinci kez basılamazdı."""
    klasor = await klasor_fabrikasi(proje, "Ruhsat")

    resp = await client.patch(
        f"/document-folders/{klasor.id}", json={"name": "Ruhsat"}, headers=sef_headers
    )

    assert resp.status_code == 200, resp.text


async def test_patch_kapsami_degistiremez(
    client: AsyncClient, proje, santiye, klasor_fabrikasi, sef_headers
) -> None:
    """Gövde YALNIZ `name` taşır (spec §3): `site_id`/`parent_id` yok sayılmaz,
    şemada hiç YOKTUR — taşıma ucu açılmamıştır."""
    klasor = await klasor_fabrikasi(proje, "Ruhsat")

    resp = await client.patch(
        f"/document-folders/{klasor.id}",
        json={"name": "Ruhsat", "site_id": str(santiye.id)},
        headers=sef_headers,
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["site_id"] is None


# --- DELETE ---


async def test_bos_klasor_silinir(
    client: AsyncClient, seeded_db: AsyncSession, proje, klasor_fabrikasi, admin_headers
) -> None:
    klasor = await klasor_fabrikasi(proje, "Boş Klasör")

    resp = await client.delete(f"/document-folders/{klasor.id}", headers=admin_headers)

    assert resp.status_code == 204, resp.text
    assert await seeded_db.get(DocumentFolder, klasor.id) is None
    detaylar = await _audit_details(seeded_db, AuditAction.delete)
    assert any("Boş Klasör" in d for d in detaylar)


async def test_belge_iceren_klasor_409(
    client: AsyncClient, proje, klasor_fabrikasi, belge_fabrikasi, admin_headers
) -> None:
    klasor = await klasor_fabrikasi(proje, "Sözleşmeler")
    await belge_fabrikasi(proje, "Sozlesme.pdf", folder=klasor)

    resp = await client.delete(f"/document-folders/{klasor.id}", headers=admin_headers)

    assert resp.status_code == 409, resp.text


async def test_alt_klasor_iceren_klasor_409(
    client: AsyncClient, proje, klasor_fabrikasi, admin_headers
) -> None:
    ust = await klasor_fabrikasi(proje, "Arşiv")
    await klasor_fabrikasi(proje, "2026", parent=ust)

    resp = await client.delete(f"/document-folders/{ust.id}", headers=admin_headers)

    assert resp.status_code == 409, resp.text


async def test_engellenen_silme_denetime_yazilmaz(
    client: AsyncClient,
    seeded_db: AsyncSession,
    proje,
    klasor_fabrikasi,
    belge_fabrikasi,
    admin_headers,
) -> None:
    """Denetim GERÇEKLEŞEN olayı kaydeder, DENEMEYİ değil (`sites` dersi)."""
    klasor = await klasor_fabrikasi(proje, "Sözleşmeler")
    await belge_fabrikasi(proje, "Sozlesme.pdf", folder=klasor)

    await client.delete(f"/document-folders/{klasor.id}", headers=admin_headers)

    assert await _audit_details(seeded_db, AuditAction.delete) == []


# --- İzin seviyeleri ---


async def test_salt_okur_rol_klasor_acamaz_403(client: AsyncClient, proje, pm_headers) -> None:
    resp = await client.post(_folders_url(proje.id), json={"name": "Sızıntı"}, headers=pm_headers)

    assert resp.status_code == 403, resp.text


async def test_salt_okur_rol_ad_degistiremez_403(
    client: AsyncClient, proje, klasor_fabrikasi, pm_headers
) -> None:
    klasor = await klasor_fabrikasi(proje, "Ruhsat")

    resp = await client.patch(
        f"/document-folders/{klasor.id}", json={"name": "Yeni"}, headers=pm_headers
    )

    assert resp.status_code == 403, resp.text


async def test_tam_yetkili_rol_silemez_403(
    client: AsyncClient, proje, klasor_fabrikasi, sef_headers
) -> None:
    """`full` SİLMEYİ KAPSAMAZ (`app/core/access.py`): silme yalnız `admin`dedir."""
    klasor = await klasor_fabrikasi(proje, "Ruhsat")

    resp = await client.delete(f"/document-folders/{klasor.id}", headers=sef_headers)

    assert resp.status_code == 403, resp.text


async def test_yetki_kapisi_dolu_klasorden_ONCE_kosar(
    client: AsyncClient, proje, klasor_fabrikasi, belge_fabrikasi, sef_headers
) -> None:
    """Yetkisiz aktör klasörün DOLU olup olmadığını ÖĞRENEMEZ (403, 409 değil)."""
    klasor = await klasor_fabrikasi(proje, "Sözleşmeler")
    await belge_fabrikasi(proje, "Sozlesme.pdf", folder=klasor)

    resp = await client.delete(f"/document-folders/{klasor.id}", headers=sef_headers)

    assert resp.status_code == 403, resp.text


async def test_kimliksiz_istek_401(client: AsyncClient, proje) -> None:
    resp = await client.get(_folders_url(proje.id))

    assert resp.status_code == 401, resp.text
