"""P3.1 T12-T13 — KISMİ AKTARIM ve `import/validate` ucu (spec §6.1-§6.3, §12.5).

`test_units_import.py`nin ikinci parçası (800 satır tavanı bölmesi); paylaşılan
yardımcılar `_units_import.py`dedir.

HEP-YA-HİÇ artık KISMİdir: geçerli satırlar yazılır, hatalılar atlanır ve rapor
sayaçları (`created` / `skipped`) birebir ölçülür. `validate` ucu HİÇBİR satır
yazmaz ve denetim kaydı da bırakmaz — `imported` daima `false`.
"""

import uuid

from sqlalchemy import delete, func, select

from app.modules.audit.models import AuditLog
from app.modules.units.models import Block, Unit
from tests.modules.units._units_api import (
    _auth,
    _block,
    _login,
    _login_with_access,
    _site,
)

from ._units_import import (
    _XLSX_MIME,
    _count_blocks,
    _count_units,
    _post_import,
    _row,
    _xlsx,
)

#
# Bu bolumun tasidigi tek buyuk risk: "gecerli satir yazilmadi" ya da "hatali
# satir yazildi" SESSIZ veri hatasidir. Bu yuzden testler durum koduyla
# YETINMEZ, hangi unitenin DB'de oldugunu tek tek olcerler.


def _ei_rows() -> list[list]:
    """EI 94-99 senaryosu: 24 satir · 22 gecerli · 1 uyari · 1 hata.

    Uyari satiri EI 173 kuralindan dogar (fiyat maliyetin altinda), hata satiri
    EI 161'den (Oda Tipi bos + Brut m² sifir) ve BIR satirda IKI mesaj tasir.
    """
    rows = [_row(unit_no=str(n)) for n in range(1, 23)]
    rows.append(_row(unit_no="23", **{"Maliyet": 860000, "Liste Fiyatı": 800000}))
    rows.append(_row(unit_no="24", **{"Oda Tipi": None, "Brüt m²": 0}))
    return rows


async def test_summary_EI_sayaclari_birebir(client, db_session, user_factory, project_factory):
    """Spec §12.5: EI 95-98 kutulari — 24 / 22 / 1 / 1."""
    project = await project_factory("T12-1", project_type="kendi_yatirim")
    site = await _site(db_session, project)
    await _block(db_session, project, site, name="A Blok")
    token = await _login(client, user_factory, "system_admin")

    body = (await _post_import(client, project, _xlsx(_ei_rows()), token)).json()

    assert body["summary"] == {"total_rows": 24, "valid": 22, "warning": 1, "error": 1}


async def test_hatali_satir_iki_mesaj_tasir_raporda(
    client, db_session, user_factory, project_factory
):
    """EI 161: BIR satirda IKI mesaj → `messages` LISTEDIR, tek metin degil."""
    project = await project_factory("T12-2", project_type="kendi_yatirim")
    site = await _site(db_session, project)
    await _block(db_session, project, site, name="A Blok")
    token = await _login(client, user_factory, "system_admin")

    body = (await _post_import(client, project, _xlsx(_ei_rows()), token)).json()

    error_row = next(r for r in body["rows"] if r["status"] == "error")
    assert error_row["messages"] == ["Oda Tipi boş olamaz", "Brüt m² sıfır olamaz"]
    # EI 118-125: rapor satiri dosyadaki degerleri de tasir (kullanici satiri
    # ancak boyle bulur) — hatali satirda da.
    assert error_row["unit_no"] == "24"
    assert error_row["block_name"] == "A Blok"


async def test_import_include_warnings_true_created_23_skipped_1(
    client, db_session, user_factory, project_factory
):
    """Spec §12.5/42: varsayilan `include_warnings=True` → 22 gecerli + 1 uyarili."""
    project = await project_factory("T12-3", project_type="kendi_yatirim")
    site = await _site(db_session, project)
    await _block(db_session, project, site, name="A Blok")
    token = await _login(client, user_factory, "system_admin")

    body = (await _post_import(client, project, _xlsx(_ei_rows()), token)).json()

    assert (body["created"], body["skipped"]) == (23, 1)
    assert body["created"] + body["skipped"] == body["summary"]["total_rows"]
    assert await _count_units(db_session, project.id) == 23


async def test_import_include_warnings_false_created_22_skipped_2(
    client, db_session, user_factory, project_factory
):
    """Spec §12.5/43 (EI 192 kutucugu isaretsiz): uyarili satir da ATLANIR."""
    project = await project_factory("T12-4", project_type="kendi_yatirim")
    site = await _site(db_session, project)
    await _block(db_session, project, site, name="A Blok")
    token = await _login(client, user_factory, "system_admin")

    body = (
        await _post_import(client, project, _xlsx(_ei_rows()), token, include_warnings=False)
    ).json()

    assert (body["created"], body["skipped"]) == (22, 2)
    warning_row = next(r for r in body["rows"] if r["status"] == "warning")
    assert warning_row["imported"] is False
    assert await _count_units(db_session, project.id) == 22


async def test_import_hic_gecerli_satir_yoksa_422_nothing_to_write(
    client, db_session, user_factory, project_factory
):
    """Spec §12.5/45: `created=0` ile 200 DONMEZ — kullanici "aktarildi" sanardi.

    ISLEM SINIRI: 422 ilk `session.add`'DEN ONCE atilir; ustelik istisna tum
    istek transaction'ini geri alir. Iki kat guvence de olculur (unite VE blok).
    """
    project = await project_factory("T12-5", project_type="kendi_yatirim")
    site = await _site(db_session, project)
    await _block(db_session, project, site, name="A Blok")
    token = await _login(client, user_factory, "system_admin")
    content = _xlsx(
        [_row(unit_no="1", **{"Oda Tipi": None}), _row(block="Yeni Blok", kind="Villa")]
    )

    resp = await _post_import(client, project, content, token)

    assert resp.status_code == 422
    assert resp.json()["detail"] == "Aktarılabilecek geçerli satır yok"
    assert await _count_units(db_session, project.id) == 0
    assert await _count_blocks(db_session, project.id) == 1  # yalniz onceden var olan


async def test_import_ayni_dosya_ikinci_kez_hepsi_atlanir_422(
    client, db_session, user_factory, project_factory
):
    """Spec §6.1'in 2. gerekcesinin TESTI (§12.5/46).

    P3 hep-ya-hici "duzelt ve yeniden yukle imkânsizlasir" diye savunmustu.
    Kismi aktarimda bu itiraz ZARARSIZDIR: ikinci yuklemede zaten yazilmis
    satirlar "zaten kullaniliyor" hatasiyla RAPORLANIR ve atlanir.
    """
    project = await project_factory("T12-6", project_type="kendi_yatirim")
    site = await _site(db_session, project)
    await _block(db_session, project, site, name="A Blok")
    token = await _login(client, user_factory, "system_admin")
    content = _xlsx([_row(unit_no=str(n)) for n in range(1, 4)])

    first = await _post_import(client, project, content, token)
    second = await _post_import(client, project, content, token)

    assert first.json()["created"] == 3
    assert second.status_code == 422
    assert second.json()["detail"] == "Aktarılabilecek geçerli satır yok"
    assert await _count_units(db_session, project.id) == 3


async def test_import_yeni_blok_olusur_hatali_satirin_blogu_olusmaz(
    client, db_session, user_factory, project_factory
):
    """Spec §12.5/47: blok olusturma GECERLI satirlara baglidir.

    Hatali satirin blogu acilsaydi kullanici hicbir unitesi olmayan hayalet bir
    blokla kalirdi ve bunu ancak blok listesinde fark ederdi.
    """
    project = await project_factory("T12-7", project_type="kendi_yatirim")
    await _site(db_session, project)
    token = await _login(client, user_factory, "system_admin")
    content = _xlsx(
        [
            _row(block="İyi Blok", unit_no="1"),
            _row(block="Kötü Blok", unit_no="2", kind="Villa"),
        ]
    )

    body = (await _post_import(client, project, content, token)).json()

    assert (body["created"], body["skipped"], body["blocks_created"]) == (1, 1, 1)
    names = (
        (await db_session.execute(select(Block.name).where(Block.project_id == project.id)))
        .scalars()
        .all()
    )
    assert list(names) == ["İyi Blok"]


async def test_import_cok_santiyeli_site_id_yok_422_site_required(
    client, db_session, user_factory, project_factory
):
    """Spec §12.5/47b: cok santiyeli projede otomatik atama YANLIS veri uretirdi."""
    project = await project_factory("T12-8", project_type="kendi_yatirim")
    await _site(db_session, project, code="S1")
    await _site(db_session, project, code="S2")
    token = await _login(client, user_factory, "system_admin")

    resp = await _post_import(client, project, _xlsx([_row(block="Yeni Blok")]), token)

    assert resp.status_code == 422
    assert resp.json()["detail"] == "Birden fazla şantiye var, blok için şantiye seçilmelidir"
    assert await _count_blocks(db_session, project.id) == 0


async def test_import_site_id_ile_yeni_bloklar_o_santiyede(
    client, db_session, user_factory, project_factory
):
    """Spec §12.5/47b (EI 61 "Hedef Şantiye", karar 3): bugun 422 veren yol boyle acilir."""
    project = await project_factory("T12-9", project_type="kendi_yatirim")
    await _site(db_session, project, code="S1")
    second = await _site(db_session, project, code="S2")
    token = await _login(client, user_factory, "system_admin")

    resp = await _post_import(
        client, project, _xlsx([_row(block="Yeni Blok")]), token, site_id=second.id
    )

    assert resp.status_code == 200
    block = (
        await db_session.execute(select(Block).where(Block.project_id == project.id))
    ).scalar_one()
    assert block.site_id == second.id


async def test_import_mevcut_blogun_site_id_si_degismez(
    client, db_session, user_factory, project_factory
):
    """Spec §6.2: `site_id` YALNIZ yeni blok acarken kullanilir.

    SESSIZ VERI TASIMA RISKI: dosyadaki blok zaten varsa bloğun santiyesi
    DEGISTIRILMEZ — blok tasimak bu ucun isi degildir ve kullanici uniteye
    ekleme yaparken bloğunu tasidigini fark edemezdi.
    """
    project = await project_factory("T12-10", project_type="kendi_yatirim")
    first = await _site(db_session, project, code="S1")
    second = await _site(db_session, project, code="S2")
    block = await _block(db_session, project, first, name="A Blok")
    token = await _login(client, user_factory, "system_admin")

    resp = await _post_import(client, project, _xlsx([_row(unit_no="9")]), token, site_id=second.id)

    assert resp.status_code == 200
    await db_session.refresh(block)
    assert block.site_id == first.id


async def test_import_baska_projenin_site_id_404(client, db_session, user_factory, project_factory):
    """Spec §12.5/47c — YENI IDOR YUZEYI (karar 3 ile acildi).

    Baska projenin santiyesi VAR OLMAYAN kimlikle AYNI 404'u alir: aksi hâlde
    elinde UUID olan kullanici kaydin var oldugunu ve baskasina ait oldugunu
    ayirt edebilirdi.
    """
    project = await project_factory("T12-11A", project_type="kendi_yatirim")
    await _site(db_session, project, code="S-OWN")
    other = await project_factory("T12-11B", project_type="kendi_yatirim")
    foreign = await _site(db_session, other, code="S-FOREIGN")
    token = await _login(client, user_factory, "system_admin")
    content = _xlsx([_row(block="Yeni Blok")])

    foreign_resp = await _post_import(client, project, content, token, site_id=foreign.id)
    unknown_resp = await _post_import(client, project, content, token, site_id=uuid.uuid4())

    assert foreign_resp.status_code == 404
    assert foreign_resp.json() == {"detail": "Şantiye bulunamadı"}
    assert unknown_resp.json() == foreign_resp.json()
    assert await _count_blocks(db_session, project.id) == 0


async def test_import_maliyet_hicbir_kolona_yazilmaz(
    client, db_session, user_factory, project_factory
):
    """Spec §12.5/48 (karar 10): `Maliyet` DB'de karsiligi olmayan bir sutundur."""
    project = await project_factory("T12-12", project_type="kendi_yatirim")
    site = await _site(db_session, project)
    await _block(db_session, project, site, name="A Blok")
    token = await _login(client, user_factory, "system_admin")
    content = _xlsx([_row(unit_no="1", **{"Maliyet": 860000, "Liste Fiyatı": 890000})])

    resp = await _post_import(client, project, content, token)

    assert resp.status_code == 200
    unit = (
        await db_session.execute(select(Unit).where(Unit.project_id == project.id))
    ).scalar_one()
    values = {str(getattr(unit, column.name)) for column in Unit.__table__.columns}
    assert not any("860000" in value for value in values)


async def test_import_fiyat_maliyetin_altinda_warning(
    client, db_session, user_factory, project_factory
):
    """Spec §12.5/49 (EI 173) — mockup'taki TEK uyari kurali."""
    project = await project_factory("T12-13", project_type="kendi_yatirim")
    site = await _site(db_session, project)
    await _block(db_session, project, site, name="A Blok")
    token = await _login(client, user_factory, "system_admin")
    content = _xlsx([_row(unit_no="1", **{"Maliyet": 860000, "Liste Fiyatı": 800000})])

    body = (await _post_import(client, project, content, token)).json()

    assert body["rows"][0]["status"] == "warning"
    assert body["rows"][0]["messages"] == ["Fiyat maliyetin altında (₺860.000) — kontrol edin"]
    assert body["rows"][0]["imported"] is True


# --- P3.1 T13: POST /projects/{id}/units/import/validate (spec §6.2, §12.5/40-41) ---
#
# `bulk/preview` ile AYNI garanti: **HICBIR SEY YAZMAZ**. Garanti sessizce
# bozulabilecegi icin testler durum koduyla yetinmez; unite, blok VE denetim
# satiri sayimlarini olcer.


async def _post_validate(client, project, content: bytes, token: str, **form):
    return await client.post(
        f"/projects/{project.id}/units/import/validate",
        files={"file": ("uniteler.xlsx", content, _XLSX_MIME)},
        data={key: str(value) for key, value in form.items()},
        headers=_auth(token),
    )


async def test_validate_EI_senaryosu_summary_birebir(
    client, db_session, user_factory, project_factory
):
    """Spec §12.5/40: EI 95-98 kutulari 24 / 22 / 1 / 1; `rows` 24 satir."""
    project = await project_factory("T13-1", project_type="kendi_yatirim")
    site = await _site(db_session, project)
    await _block(db_session, project, site, name="A Blok")
    token = await _login(client, user_factory, "system_admin")

    resp = await _post_validate(client, project, _xlsx(_ei_rows()), token)

    assert resp.status_code == 200
    body = resp.json()
    assert body["summary"] == {"total_rows": 24, "valid": 22, "warning": 1, "error": 1}
    assert len(body["rows"]) == 24
    assert body["blocks_to_create"] == []
    error_row = next(r for r in body["rows"] if r["status"] == "error")
    assert error_row["messages"] == ["Oda Tipi boş olamaz", "Brüt m² sıfır olamaz"]


async def test_validate_hicbir_satir_yazilmaz(client, db_session, user_factory, project_factory):
    """Spec §12.5/41: oncesi/sonrasi unite VE blok sayimi ESIT.

    `blocks_to_create` dolu OLSA BILE hicbir blok acilmaz — dogrulama yalniz
    "acilacak" der, acmaz.
    """
    project = await project_factory("T13-2", project_type="kendi_yatirim")
    await _site(db_session, project)
    token = await _login(client, user_factory, "system_admin")
    content = _xlsx([_row(block="Yeni Blok", unit_no="1")])

    resp = await _post_validate(client, project, content, token)

    assert resp.status_code == 200
    assert resp.json()["blocks_to_create"] == ["Yeni Blok"]
    assert await _count_units(db_session, project.id) == 0
    assert await _count_blocks(db_session, project.id) == 0


async def test_validate_denetim_yazmaz(client, db_session, user_factory, project_factory):
    """Spec §9: dogrulama bir OKUMA ucudur → denetim satiri URETMEZ (P4 T7).

    Sayim MUTLAKTIR (`== 0`): tek satir bile "yazan uc denetim yazar" kuralini
    bir bayraga bagli hâle getirirdi.
    """
    project = await project_factory("T13-3", project_type="kendi_yatirim")
    site = await _site(db_session, project)
    await _block(db_session, project, site, name="A Blok")
    token = await _login(client, user_factory, "system_admin")
    await db_session.execute(delete(AuditLog))

    resp = await _post_validate(client, project, _xlsx(_ei_rows()), token)

    assert resp.status_code == 200
    assert (
        int((await db_session.execute(select(func.count()).select_from(AuditLog))).scalar_one())
        == 0
    )


async def test_validate_ve_import_ayni_rapor_uretir(
    client, db_session, user_factory, project_factory
):
    """TEK KAYNAK KANITI (spec §6.2): iki uc de `_plan_rows`'tan beslenir.

    Ayni dosya icin `rows` BIREBIR aynidir; tek fark `imported` bayragidir.
    Ayrisirlarsa "dogrulamada gecerli gorunup aktarimda atlanan satir" sinifi
    dogar ve kullanici bunu ancak eksik unitelerden fark ederdi.
    """
    project = await project_factory("T13-4", project_type="kendi_yatirim")
    site = await _site(db_session, project)
    await _block(db_session, project, site, name="A Blok")
    token = await _login(client, user_factory, "system_admin")
    content = _xlsx(_ei_rows())

    validated = (await _post_validate(client, project, content, token)).json()
    imported = (await _post_import(client, project, content, token)).json()

    assert validated["summary"] == imported["summary"]
    assert [{**r, "imported": None} for r in validated["rows"]] == [
        {**r, "imported": None} for r in imported["rows"]
    ]


async def test_validate_imported_daima_false(client, db_session, user_factory, project_factory):
    """Spec §6.3: dogrulamada `imported` DAIMA `False` — "gecerli" ile "yazildi"
    ayri sorulardir ve tek alana indirilseydi dogrulama sonucu aktarim sonucu
    gibi okunabilirdi."""
    project = await project_factory("T13-5", project_type="kendi_yatirim")
    site = await _site(db_session, project)
    await _block(db_session, project, site, name="A Blok")
    token = await _login(client, user_factory, "system_admin")

    body = (await _post_validate(client, project, _xlsx(_ei_rows()), token)).json()

    assert all(row["imported"] is False for row in body["rows"])
    assert any(row["status"] == "ok" for row in body["rows"])


async def test_validate_requires_full_permission(client, db_session, user_factory, project_factory):
    """Spec §6.2 / IDOR-13: `view` YETMEZ — dogrulama yazma akisinin parcasidir."""
    project = await project_factory("T13-6", project_type="kendi_yatirim")
    token = await _login_with_access(client, db_session, user_factory, "site_chief")

    resp = await _post_validate(client, project, _xlsx([_row()]), token)

    assert resp.status_code == 403


async def test_validate_baska_projenin_site_id_404(
    client, db_session, user_factory, project_factory
):
    """`site_id` dogrulama ucunda da denetlenir: kullanici gecersiz hedef
    santiyeyi AKTARIMDAN ONCE ogrenmelidir (spec §6.2)."""
    project = await project_factory("T13-7A", project_type="kendi_yatirim")
    await _site(db_session, project, code="S-OWN")
    other = await project_factory("T13-7B", project_type="kendi_yatirim")
    foreign = await _site(db_session, other, code="S-FOREIGN")
    token = await _login(client, user_factory, "system_admin")

    resp = await _post_validate(client, project, _xlsx([_row()]), token, site_id=foreign.id)

    assert resp.status_code == 404
    assert resp.json() == {"detail": "Şantiye bulunamadı"}
