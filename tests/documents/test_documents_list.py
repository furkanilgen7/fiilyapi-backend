"""`GET /documents` — künye listesi (T3, spec §3) + klasör sayaçları.

Kapı `documents:view`. Sıralama SABİTTİR (`created_at` azalan): mockup'ın tek
sıralama kavramı "Son Eklenenler"dir (E12:168, SB:139) ve seçilebilir bir `sort`
parametresi mockup'ta YOKTUR — icat edilmez. Aynı sebeple SAYFALAMA yoktur;
`limit` yalnız "Son Eklenenler" panelini kısaltmak içindir (spec §3).

## Dondurulan üç karar

1. **`project_id` ZORUNLUDUR.** Her iki mockup da her an TEK bir kökün (proje ya
   da proje/şantiye) içindedir: E12'nin sol ağacında kökler projelerdir (E12:78,
   100-108), SB ise bir şantiye sekmesidir (SB:79). Projeler arası birleşik bir
   arşiv ekranı YOKTUR. Zorunlu tutulmasaydı uç, görünen tüm projelerin tüm
   belgelerini sınırsız döndüren, hiçbir ekranın istemediği bir sorguya dönerdi.
2. **`site_id` bir SÜZGEÇTİR** (T2 klasör listesiyle BİREBİR aynı semantik):
   verilmezse yalnız PROJE DÜZEYİ belgeler (`site_id IS NULL`), verilirse yalnız
   o şantiyeninkiler. İki uç aynı kökü farklı yorumlasaydı ekran, klasörleri bir
   kapsamdan belgeleri başka kapsamdan çizerdi.
3. **`folder_id` verilmezse KLASÖR SÜZGECİ YOKTUR** — kapsamdaki tüm belgeler
   döner. Gerekçe mockup: SB'nin kökü "Tüm Belgeler"dir (SB:43, SB:84) ve
   listedeki satırlar farklı klasörlere aittir (SB:144 "Günlük Raporlar",
   SB:151 "Fotoğraflar", SB:158 "İş Güvenliği"). `site_id`den farklı davranması
   bu yüzden tutarsızlık değil, mockup'ın kendisidir.
"""

import uuid
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import event

from tests.documents.test_blob_isolation import BLOB_TABLOSU


def _adlar(govde: dict) -> list[str]:
    return [b["filename"] for b in govde["documents"]]


# --- Kapsam süzgeçleri ---


async def test_proje_duzeyi_belgeler_listelenir(
    client: AsyncClient, proje, santiye, belge_fabrikasi, sef_headers
) -> None:
    await belge_fabrikasi(proje, "Proje_Sozlesme.pdf")
    await belge_fabrikasi(proje, "Santiye_Hakedis.pdf", site=santiye)

    resp = await client.get("/documents", params={"project_id": str(proje.id)}, headers=sef_headers)

    assert resp.status_code == 200, resp.text
    assert _adlar(resp.json()) == ["Proje_Sozlesme.pdf"]


async def test_santiye_suzgeci_yalniz_o_santiyeyi_dondurur(
    client: AsyncClient, proje, santiye, belge_fabrikasi, sef_headers
) -> None:
    await belge_fabrikasi(proje, "Proje_Sozlesme.pdf")
    await belge_fabrikasi(proje, "Santiye_Hakedis.pdf", site=santiye)

    resp = await client.get(
        "/documents",
        params={"project_id": str(proje.id), "site_id": str(santiye.id)},
        headers=sef_headers,
    )

    assert _adlar(resp.json()) == ["Santiye_Hakedis.pdf"]


async def test_klasor_suzgeci_verilmezse_kapsamin_tamami_doner(
    client: AsyncClient, proje, santiye, klasor_fabrikasi, belge_fabrikasi, sef_headers
) -> None:
    """SB kökü "Tüm Belgeler": farklı klasörlerin belgeleri aynı listede."""
    gunluk = await klasor_fabrikasi(proje, "Günlük Raporlar", site=santiye)
    foto = await klasor_fabrikasi(proje, "Fotoğraflar", site=santiye)
    await belge_fabrikasi(proje, "Gunluk.pdf", site=santiye, folder=gunluk)
    await belge_fabrikasi(proje, "Foto.zip", site=santiye, folder=foto)
    await belge_fabrikasi(proje, "Klasorsuz.pdf", site=santiye)

    resp = await client.get(
        "/documents",
        params={"project_id": str(proje.id), "site_id": str(santiye.id)},
        headers=sef_headers,
    )

    assert sorted(_adlar(resp.json())) == ["Foto.zip", "Gunluk.pdf", "Klasorsuz.pdf"]


async def test_klasor_suzgeci_yalniz_o_klasoru_dondurur(
    client: AsyncClient, proje, santiye, klasor_fabrikasi, belge_fabrikasi, sef_headers
) -> None:
    gunluk = await klasor_fabrikasi(proje, "Günlük Raporlar", site=santiye)
    await belge_fabrikasi(proje, "Gunluk.pdf", site=santiye, folder=gunluk)
    await belge_fabrikasi(proje, "Klasorsuz.pdf", site=santiye)

    resp = await client.get(
        "/documents",
        params={
            "project_id": str(proje.id),
            "site_id": str(santiye.id),
            "folder_id": str(gunluk.id),
        },
        headers=sef_headers,
    )

    assert _adlar(resp.json()) == ["Gunluk.pdf"]


async def test_project_id_zorunludur(client: AsyncClient, sef_headers) -> None:
    resp = await client.get("/documents", headers=sef_headers)

    assert resp.status_code == 422


# --- Arama (q) ---


async def test_q_dosya_adinda_arar_buyuk_kucuk_harf_duyarsiz(
    client: AsyncClient, proje, belge_fabrikasi, sef_headers
) -> None:
    await belge_fabrikasi(proje, "Hakedis_47.pdf")
    await belge_fabrikasi(proje, "Metraj.xlsx")

    resp = await client.get(
        "/documents", params={"project_id": str(proje.id), "q": "hakedis"}, headers=sef_headers
    )

    assert _adlar(resp.json()) == ["Hakedis_47.pdf"]


async def test_q_aciklamada_da_arar(
    client: AsyncClient, proje, belge_fabrikasi, sef_headers
) -> None:
    """Spec §3: arama YALNIZ dosya adı + açıklama (SB:151 "48 fotoğraf")."""
    await belge_fabrikasi(proje, "Santiye_Foto.zip", description="48 fotoğraf")
    await belge_fabrikasi(proje, "Metraj.xlsx", description="Aylık denetim")

    resp = await client.get(
        "/documents", params={"project_id": str(proje.id), "q": "fotoğraf"}, headers=sef_headers
    )

    assert _adlar(resp.json()) == ["Santiye_Foto.zip"]


async def test_q_joker_karakterleri_duz_metin_sayar(
    client: AsyncClient, proje, belge_fabrikasi, sef_headers
) -> None:
    """`%` kaçırılmazsa arama kutusuna `%` yazan kullanıcı TÜM arşivi görür."""
    await belge_fabrikasi(proje, "Metraj.xlsx")
    await belge_fabrikasi(proje, "Yuzde %20 Zam.pdf")

    hepsi = await client.get(
        "/documents", params={"project_id": str(proje.id), "q": "%"}, headers=sef_headers
    )
    # `_` joker olsaydı "M_traj" deseni "Metraj"ı yakalardı; düz metin olarak
    # hiçbir dosya adında geçmez.
    alt_cizgi = await client.get(
        "/documents", params={"project_id": str(proje.id), "q": "M_traj"}, headers=sef_headers
    )

    assert _adlar(hepsi.json()) == ["Yuzde %20 Zam.pdf"]
    assert alt_cizgi.json()["documents"] == []


# --- Sıralama + limit (Son Eklenenler) ---


async def test_liste_en_yeniden_eskiye_siralanir(
    client: AsyncClient, proje, belge_fabrikasi, sef_headers
) -> None:
    simdi = datetime.now(UTC)
    eski = await belge_fabrikasi(proje, "Eski.pdf")
    yeni = await belge_fabrikasi(proje, "Yeni.pdf")
    eski.created_at = simdi - timedelta(days=3)
    yeni.created_at = simdi

    resp = await client.get("/documents", params={"project_id": str(proje.id)}, headers=sef_headers)

    assert _adlar(resp.json()) == ["Yeni.pdf", "Eski.pdf"]


async def test_limit_son_eklenenleri_kisaltir(
    client: AsyncClient, proje, belge_fabrikasi, sef_headers
) -> None:
    simdi = datetime.now(UTC)
    for i in range(4):
        belge = await belge_fabrikasi(proje, f"Dosya-{i}.pdf")
        belge.created_at = simdi - timedelta(days=i)

    resp = await client.get(
        "/documents", params={"project_id": str(proje.id), "limit": 2}, headers=sef_headers
    )

    assert _adlar(resp.json()) == ["Dosya-0.pdf", "Dosya-1.pdf"]


async def test_sifir_limit_reddedilir(client: AsyncClient, proje, sef_headers) -> None:
    resp = await client.get(
        "/documents", params={"project_id": str(proje.id), "limit": 0}, headers=sef_headers
    )

    assert resp.status_code == 422


async def test_sayfalama_parametresi_YOKTUR(client: AsyncClient, proje, sef_headers) -> None:
    """Spec §3: mockup'ta sayfalama yok — `offset`/`page` icat edilmedi.

    Uç bilinmeyen parametreyi sessizce YOK SAYAR; bu test, birinin ileride
    yarım bir sayfalama eklemesini yakalamak için şemayı dondurur.
    """
    from app.main import app as fastapi_app

    yol = fastapi_app.openapi()["paths"]["/documents"]["get"]
    adlar = {p["name"] for p in yol.get("parameters", [])}

    assert adlar == {"project_id", "site_id", "folder_id", "q", "limit"}


# --- BLOB İZOLASYON KANITI (uç düzeyinde) ---


class _SqlKaydedici:
    def __init__(self) -> None:
        self.ifadeler: list[str] = []

    def __call__(self, conn, cursor, statement, parameters, context, executemany) -> None:
        self.ifadeler.append(statement)

    def blob_dokunuslari(self) -> list[str]:
        return [s for s in self.ifadeler if BLOB_TABLOSU in s.lower()]


async def test_liste_ucu_blob_tablosuna_DOKUNMAZ(
    client: AsyncClient, seeded_db, proje, santiye, klasor_fabrikasi, belge_fabrikasi, sef_headers
) -> None:
    """ASIL KANIT (spec §2/§7 S1): 48 MB'lık sütun liste sorgusuna GİRMEZ.

    T1'in `test_blob_isolation.py` yöntemi UÇ düzeyinde tekrarlanır: istek
    boyunca koşan HER SQL ifadesi yakalanır ve hiçbirinde `document_blobs`
    geçmediği doğrulanır. Bir gün `Document`a eager bir blob ilişkisi eklenirse
    ya da liste sorgusu blob'u JOIN'lerse bu test kırılır.
    """
    klasor = await klasor_fabrikasi(proje, "Hakedişler", site=santiye)
    for i in range(3):
        await belge_fabrikasi(
            proje, f"Dosya-{i}.pdf", site=santiye, folder=klasor, data=b"x" * 4096, size_bytes=4096
        )

    kaydedici = _SqlKaydedici()
    bind = seeded_db.sync_session.get_bind()
    event.listen(bind, "before_cursor_execute", kaydedici)
    try:
        resp = await client.get(
            "/documents",
            params={"project_id": str(proje.id), "site_id": str(santiye.id)},
            headers=sef_headers,
        )
    finally:
        event.remove(bind, "before_cursor_execute", kaydedici)

    assert resp.status_code == 200, resp.text
    assert len(resp.json()["documents"]) == 3
    assert kaydedici.ifadeler, "hiç SQL yakalanmadı — kanıt geçersiz"
    assert kaydedici.blob_dokunuslari() == []


# --- Klasör listesi sayacı (mockup rozeti; şef kararı 2026-08-04) ---


async def test_klasor_listesi_belge_sayaci_dondurur(
    client: AsyncClient, proje, santiye, klasor_fabrikasi, belge_fabrikasi, sef_headers
) -> None:
    klasor = await klasor_fabrikasi(proje, "Sözleşmeler", site=santiye)
    bos = await klasor_fabrikasi(proje, "Faturalar", site=santiye)
    for i in range(2):
        await belge_fabrikasi(proje, f"S-{i}.pdf", site=santiye, folder=klasor)

    resp = await client.get(
        f"/projects/{proje.id}/document-folders",
        params={"site_id": str(santiye.id)},
        headers=sef_headers,
    )

    assert resp.status_code == 200, resp.text
    sayaclar = {k["name"]: k["document_count"] for k in resp.json()["folders"]}
    assert sayaclar == {"Sözleşmeler": 2, "Faturalar": 0}
    assert bos.name == "Faturalar"


async def test_sayac_yalniz_DOGRUDAN_icindeki_belgeleri_sayar(
    client: AsyncClient, proje, santiye, klasor_fabrikasi, belge_fabrikasi, sef_headers
) -> None:
    """KAPSAM KARARI: alt klasörler DAHİL DEĞİL.

    Rozetin sözü, kullanıcı o klasöre TIKLADIĞINDA göreceği belge sayısıdır;
    `GET /documents?folder_id=` yalnız doğrudan içindekileri döndürür. Alt
    klasörler sayılsaydı ekranda "12" yazan klasör tıklanınca 5 belge gösterir,
    üstelik alt klasörün kendi rozetiyle çifte sayım yapılırdı (mockup ağacı
    ebeveyni ve çocuğu YAN YANA listeler — E12:78-92).
    """
    ust = await klasor_fabrikasi(proje, "Sözleşmeler", site=santiye)
    alt = await klasor_fabrikasi(proje, "2026", site=santiye, parent=ust)
    await belge_fabrikasi(proje, "Ust.pdf", site=santiye, folder=ust)
    await belge_fabrikasi(proje, "Alt-1.pdf", site=santiye, folder=alt)
    await belge_fabrikasi(proje, "Alt-2.pdf", site=santiye, folder=alt)

    resp = await client.get(
        f"/projects/{proje.id}/document-folders",
        params={"site_id": str(santiye.id)},
        headers=sef_headers,
    )

    sayaclar = {k["name"]: k["document_count"] for k in resp.json()["folders"]}
    assert sayaclar == {"Sözleşmeler": 1, "2026": 2}


async def test_sayac_tek_sorguda_hesaplanir_N_ARTI_BIR_YOK(
    client: AsyncClient, seeded_db, proje, santiye, klasor_fabrikasi, belge_fabrikasi, sef_headers
) -> None:
    """Klasör sayısı arttıkça sorgu sayısı ARTMAMALI (N+1 yasağı).

    Ölçüt SABİT bir sayı değil, DEĞİŞMEZLİKTİR: aynı istek önce 1, sonra 6
    klasörle koşulur ve koşan SQL ifadesi sayısının AYNI kaldığı doğrulanır.
    "Tek klasör sorgusu var" demek yeterli olmazdı — klasör başına `documents`
    tablosuna atılan ayrı bir `COUNT` bu kontrolden kaçardı (mutasyonla
    doğrulandı).
    """
    bind = seeded_db.sync_session.get_bind()

    async def _sorgu_sayisi() -> int:
        kaydedici = _SqlKaydedici()
        event.listen(bind, "before_cursor_execute", kaydedici)
        try:
            resp = await client.get(
                f"/projects/{proje.id}/document-folders",
                params={"site_id": str(santiye.id)},
                headers=sef_headers,
            )
        finally:
            event.remove(bind, "before_cursor_execute", kaydedici)
        assert resp.status_code == 200, resp.text
        return len(kaydedici.ifadeler)

    ilk = await klasor_fabrikasi(proje, "Klasör-0", site=santiye)
    await belge_fabrikasi(proje, "D-0.pdf", site=santiye, folder=ilk)
    tek_klasorle = await _sorgu_sayisi()

    for i in range(1, 6):
        klasor = await klasor_fabrikasi(proje, f"Klasör-{i}", site=santiye)
        await belge_fabrikasi(proje, f"D-{i}.pdf", site=santiye, folder=klasor)
    alti_klasorle = await _sorgu_sayisi()

    assert alti_klasorle == tek_klasorle, "klasör başına ek sorgu koşuyor (N+1)"


# --- IDOR + yetki ---


async def test_gorunmeyen_projenin_listesi_404(
    client: AsyncClient, ikinci_proje, sef_headers
) -> None:
    resp = await client.get(
        "/documents", params={"project_id": str(ikinci_proje.id)}, headers=sef_headers
    )

    assert resp.status_code == 404


async def test_gorunmeyen_proje_var_olmayandan_ayirt_edilemez(
    client: AsyncClient, ikinci_proje, sef_headers
) -> None:
    gorunmeyen = await client.get(
        "/documents", params={"project_id": str(ikinci_proje.id)}, headers=sef_headers
    )
    yok = await client.get(
        "/documents", params={"project_id": str(uuid.uuid4())}, headers=sef_headers
    )

    assert gorunmeyen.status_code == yok.status_code == 404
    assert gorunmeyen.json() == yok.json()


async def test_salt_okur_rol_listeleyebilir(
    client: AsyncClient, proje, belge_fabrikasi, pm_headers
) -> None:
    """`documents` satırında hiçbir rol `_N` değildir (spec §6) — okuma herkese açıktır."""
    await belge_fabrikasi(proje, "Ruhsat.pdf")

    resp = await client.get("/documents", params={"project_id": str(proje.id)}, headers=pm_headers)

    assert resp.status_code == 200, resp.text
    assert _adlar(resp.json()) == ["Ruhsat.pdf"]


async def test_kimliksiz_liste_401(client: AsyncClient, proje) -> None:
    resp = await client.get("/documents", params={"project_id": str(proje.id)})

    assert resp.status_code == 401


async def test_baska_projenin_belgesi_sizmaz(
    client: AsyncClient, proje, ikinci_proje, belge_fabrikasi, sef_headers
) -> None:
    await belge_fabrikasi(proje, "Bizim.pdf")
    await belge_fabrikasi(ikinci_proje, "Yabanci.pdf")

    resp = await client.get("/documents", params={"project_id": str(proje.id)}, headers=sef_headers)

    assert _adlar(resp.json()) == ["Bizim.pdf"]
