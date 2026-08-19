"""İK-2.1 — self-servis izin talebi (HTTP uçtan uca).

Görev emri: `GOREV-EMRI-IK21-BACKEND.md` (kullanıcı kararı 2026-08-19).

**Bu dilim bir YETKİ YÜZEYİDİR.** Ölçülmüş taban: `POST /leave-requests` kapısı
`personnel=full`dur, yani izin talebini YALNIZ İK/admin girebiliyordu. Yeni
`/leave-requests/self` çifti (POST + GET) bu kapıyı GENİŞLETMEZ; **ayrı ve dar**
bir yüzey açar:

- Kapı **yalnız kimlik doğrulamasıdır** (`personnel` izni ARANMAZ) — çünkü yetki
  modülden değil **SAHİPLİKTEN** gelir. Bu yüzden testlerin çoğu `procurement`
  rolüyle koşar: matriste `personnel=_N`, yani bu kullanıcı `/leave-requests`
  uçlarının HİÇBİRİNE giremez ama KENDİ talebini açabilmelidir.
- Gövde `personnel_id` **KABUL ETMEZ** (`extra="forbid"`): başkasının adına talep
  yapısal olarak imkânsızdır, 403/404 kararına gerek kalmaz — cevap 422'dir ve
  hedefin VAR OLUP OLMADIĞINA GÖRE DEĞİŞMEZ (IDOR testi bunu kanıtlar).
- Onay/red uçlarına DOKUNULMADI: self kullanıcı kendi talebini onaylayamaz (403).
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.personnel.models import LeaveStatus, LeaveType, Personnel
from app.modules.site_diary.models import WorkerSource
from app.modules.users.models import User


@pytest.fixture
async def yillik(seeded_db: AsyncSession) -> LeaveType:
    tip = LeaveType(name="Yıllık İzin", deducts_from_annual=True, color="#2563eb", sort_order=1)
    seeded_db.add(tip)
    await seeded_db.flush()
    return tip


async def _login(client, user_factory, role_key: str, email: str) -> tuple[User, dict[str, str]]:
    user = await user_factory(email=email, password="parola1234", role_key=role_key)
    resp = await client.post("/auth/login", json={"email": email, "password": "parola1234"})
    assert resp.status_code == 200, resp.text
    return user, {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.fixture
async def calisan(client, seeded_db: AsyncSession, user_factory):
    """`procurement` rolü (`personnel=_N`) + KENDİ personel kaydı.

    Rol bilinçli seçildi: bu kullanıcı `personnel` modülünde HİÇBİR yetkiye sahip
    değildir; self ucu çalışıyorsa yetkinin kaynağı sahipliktir, modül izni değil.
    """
    user, headers = await _login(client, user_factory, "procurement", "calisan@ik21.co")
    kayit = Personnel(
        full_name="Mehmet Yılmaz",
        trade="Muhasebe Elemanı",
        source=WorkerSource.company,
        user_id=user.id,
    )
    seeded_db.add(kayit)
    await seeded_db.flush()
    return user, headers, kayit


@pytest.fixture
async def baskasi(seeded_db: AsyncSession) -> Personnel:
    """Login'i OLMAYAN başka bir personel — IDOR hedefi."""
    kayit = Personnel(full_name="Ali Kaya", trade="Demir Ustası", source=WorkerSource.company)
    seeded_db.add(kayit)
    await seeded_db.flush()
    return kayit


def _govde(tip: LeaveType, **ek) -> dict:
    return {
        "leave_type_id": str(tip.id),
        "start_date": "2026-09-01",
        "end_date": "2026-09-03",
        **ek,
    }


# --- 1. Mutlu yol ----------------------------------------------------------


async def test_self_kendi_talebini_olusturur_201(client, calisan, baskasi, yillik):
    """`baskasi` fixture'ı BİLİNÇLİ olarak burada: kartotekste BAŞKA bir personel
    YOKSA "kendi kaydını çözdü" iddiası hiçbir şey kanıtlamaz — tek kayıtlı bir
    tabloda süzgeçsiz sorgu da aynı satırı döndürür (AYRIŞMA NOKTASI kuralı)."""
    user, headers, kayit = calisan
    resp = await client.post("/leave-requests/self", json=_govde(yillik), headers=headers)
    assert resp.status_code == 201, resp.text
    govde = resp.json()
    # Talep AKTÖRÜN KENDİ personel kaydına bağlandı — gövdeden gelmedi, sunucu çözdü.
    assert govde["personnel_id"] == str(kayit.id)
    assert govde["personnel_name"] == "Mehmet Yılmaz"
    assert govde["status"] == LeaveStatus.pending.value
    assert govde["days"] == 3  # SUNUCU hesabı (spec §5 K2)


async def test_self_ucu_personnel_iznini_ARAMAZ(client, calisan, yillik):
    """Aynı kullanıcı klasik uca girerse 403 — genişleme SADECE self ucundadır."""
    _, headers, _ = calisan
    resp = await client.get("/leave-requests", headers=headers)
    assert resp.status_code == 403, resp.text


# --- 2. IDOR: başkasının adına talep ---------------------------------------


async def test_baskasinin_personnel_id_si_REDDEDILIR_govde_var_olmayanla_AYNI(
    client, calisan, baskasi, yillik, seeded_db
):
    """K2 — IDOR. Gövdeye `personnel_id` konması KABUL EDİLMEZ ve cevap, hedefin
    VAR OLUP OLMADIĞINA GÖRE DEĞİŞMEZ.

    Tek fark istemcinin KENDİ gönderdiği değerin yankısıdır (`input`) — o değeri
    zaten istemci biliyor, sızıntı değildir. Yankı sabitlendiğinde iki gövde
    BİREBİR aynıdır: sunucu "bu personel var" bilgisini hiçbir biçimde vermez.
    """
    _, headers, _ = calisan
    yok = uuid.uuid4()

    var_olan = await client.post(
        "/leave-requests/self", json=_govde(yillik, personnel_id=str(baskasi.id)), headers=headers
    )
    olmayan = await client.post(
        "/leave-requests/self", json=_govde(yillik, personnel_id=str(yok)), headers=headers
    )

    assert var_olan.status_code == olmayan.status_code == 422, var_olan.text

    def _yankisiz(payload: dict) -> dict:
        return {
            "detail": [
                {k: ("<yankı>" if k == "input" else v) for k, v in hata.items()}
                for hata in payload["detail"]
            ]
        }

    assert _yankisiz(var_olan.json()) == _yankisiz(olmayan.json())

    # Ve HİÇBİR talep doğmadı — ne aktörün ne de hedefin adına.
    from sqlalchemy import func, select

    from app.modules.personnel.models import LeaveRequest

    toplam = await seeded_db.scalar(select(func.count()).select_from(LeaveRequest))
    assert toplam == 0


async def test_self_ucu_baskasinin_talebini_LISTELEMEZ(
    client, calisan, baskasi, yillik, ik_headers
):
    """K6 — self liste YALNIZ kendi kayıtlarını döndürür."""
    _, headers, kayit = calisan
    # İK, BAŞKASI adına bir talep açar (klasik yol).
    ik = await client.post(
        "/leave-requests",
        json=_govde(yillik, personnel_id=str(baskasi.id)),
        headers=ik_headers,
    )
    assert ik.status_code == 201, ik.text

    benim = await client.post("/leave-requests/self", json=_govde(yillik), headers=headers)
    assert benim.status_code == 201, benim.text

    resp = await client.get("/leave-requests/self", headers=headers)
    assert resp.status_code == 200, resp.text
    zarf = resp.json()
    assert zarf["total"] == 1
    assert [s["id"] for s in zarf["items"]] == [benim.json()["id"]]
    assert {s["personnel_id"] for s in zarf["items"]} == {str(kayit.id)}


async def test_self_GORUNMEYEN_arsiv_belgesine_bag_kuramaz_404(
    client, calisan, yillik, seeded_db, project_factory
):
    """`document_id` self gövdesindeki TEK varlık referansıdır — BC IDOR korkuluğu
    self yolunda da koşar (`_create_leave_request_for` TEK gövde olduğu için).

    Aktör (`procurement`, hiçbir projeye erişimi yok) göremediği bir arşiv
    belgesine bağ kuramaz; cevap var olmayan belgeninkiyle AYNI 404'tür."""
    from app.modules.documents.models import Document

    _, headers, _ = calisan
    proje = await project_factory(code="IK21-GRN", name="Görünmeyen Proje")
    belge = Document(
        project_id=proje.id, filename="rapor.pdf", mime_type="application/pdf", size_bytes=10
    )
    seeded_db.add(belge)
    await seeded_db.flush()

    gorunmeyen = await client.post(
        "/leave-requests/self", json=_govde(yillik, document_id=str(belge.id)), headers=headers
    )
    olmayan = await client.post(
        "/leave-requests/self",
        json=_govde(yillik, document_id=str(uuid.uuid4())),
        headers=headers,
    )
    assert gorunmeyen.status_code == olmayan.status_code == 404, gorunmeyen.text
    assert gorunmeyen.json() == olmayan.json()


# --- 3. Bağlı personel kaydı yok -------------------------------------------


async def test_baglantisiz_kullanici_ANLAMLI_hata_alir_500_DEGIL(client, user_factory, yillik):
    """K3 — `user_id` köprüsü olmayan kullanıcı (saha personelinin çoğu) için yol KAPALI."""
    _, headers = await _login(client, user_factory, "hr_manager", "baglantisiz@ik21.co")

    post = await client.post("/leave-requests/self", json=_govde(yillik), headers=headers)
    assert post.status_code == 404, post.text
    assert "personel" in post.json()["detail"].lower()

    get = await client.get("/leave-requests/self", headers=headers)
    assert get.status_code == 404, get.text


async def test_kimliksiz_istek_401(client, yillik):
    post = await client.post("/leave-requests/self", json=_govde(yillik))
    assert post.status_code == 401, post.text
    get = await client.get("/leave-requests/self")
    assert get.status_code == 401, get.text


# --- 4. K4: iki personel kaydı aynı `user_id`ye bağlıysa -------------------


async def test_iki_personel_ayni_user_id_FAIL_CLOSED_409(client, calisan, seeded_db, yillik):
    """K4 — ölçüldü: `personnel.user_id` üzerinde UNIQUE kısıt YOKTUR (yalnız
    `ix_personnel_user_id`, tekil DEĞİL). Belirsizlikte YAZMA YOK: sunucu hangi
    kaydın kastedildiğini TAHMİN ETMEZ, 409 döner.

    Kısıt eklemek migration ister — bu dilimde AÇILMADI (slot TB6'da).
    """
    user, headers, _ = calisan
    ikinci = Personnel(
        full_name="Mehmet Yılmaz (kopya)", source=WorkerSource.company, user_id=user.id
    )
    seeded_db.add(ikinci)
    await seeded_db.flush()

    post = await client.post("/leave-requests/self", json=_govde(yillik), headers=headers)
    assert post.status_code == 409, post.text

    get = await client.get("/leave-requests/self", headers=headers)
    assert get.status_code == 409, get.text


# --- 5. K5: kendi talebini onaylayamaz -------------------------------------


async def test_self_kullanici_KENDI_talebini_ONAYLAYAMAZ(client, calisan, yillik):
    """K5 — genişleme YALNIZ talep OLUŞTURMADIR. Onay/red kapıları (`personnel=full`)
    olduğu gibi kaldı; self kullanıcı kendi talebini onaylayamaz, reddedemez,
    düzenleyemez."""
    _, headers, _ = calisan
    talep = await client.post("/leave-requests/self", json=_govde(yillik), headers=headers)
    assert talep.status_code == 201, talep.text
    talep_id = talep.json()["id"]

    onay = await client.post(f"/leave-requests/{talep_id}/approve", headers=headers)
    assert onay.status_code == 403, onay.text

    red = await client.post(
        f"/leave-requests/{talep_id}/reject", json={"reason": "olmaz"}, headers=headers
    )
    assert red.status_code == 403, red.text

    duzenle = await client.patch(
        f"/leave-requests/{talep_id}", json={"end_date": "2026-09-30"}, headers=headers
    )
    assert duzenle.status_code == 403, duzenle.text

    # Ve talep hâlâ `pending` — hiçbir kapı sızdırmadı.
    liste = await client.get("/leave-requests/self", headers=headers)
    assert liste.json()["items"][0]["status"] == LeaveStatus.pending.value


# --- 6. Regresyon: İK yolu eskisi gibi -------------------------------------


async def test_ik_yolu_ESKISI_GIBI_calisir(client, ik_headers, baskasi, yillik):
    resp = await client.post(
        "/leave-requests", json=_govde(yillik, personnel_id=str(baskasi.id)), headers=ik_headers
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["personnel_id"] == str(baskasi.id)

    liste = await client.get("/leave-requests", headers=ik_headers)
    assert liste.status_code == 200, liste.text
    assert liste.json()["total"] == 1


async def test_self_govdesi_sunucu_alanlarini_KABUL_ETMEZ(client, calisan, yillik):
    """`days`/`status` istemciden ALINMAZ (spec §5 K2) — sessizce yutulmaz, 422."""
    _, headers, _ = calisan
    for ek in ({"days": 99}, {"status": "approved"}, {"decided_by": str(uuid.uuid4())}):
        resp = await client.post("/leave-requests/self", json=_govde(yillik, **ek), headers=headers)
        assert resp.status_code == 422, (ek, resp.text)


async def test_self_ters_tarih_422(client, calisan, yillik):
    _, headers, _ = calisan
    resp = await client.post(
        "/leave-requests/self",
        json={
            "leave_type_id": str(yillik.id),
            "start_date": "2026-09-10",
            "end_date": "2026-09-01",
        },
        headers=headers,
    )
    assert resp.status_code == 422, resp.text


async def test_self_pasif_personel_kaydi_da_cozulur_ama_gorunur(client, calisan, yillik):
    """Ölçülmüş sınır: self çözümü YALNIZ `user_id` köprüsüne bakar; `is_active`
    süzgeci EKLENMEDİ.

    Gerekçe: süzgeç eklemek K4'ün belirsizlik kuralını sessizce "çözerdi" (iki
    kayıttan biri pasifse sunucu tahmin yürütürdü). Login'in kendi durumu
    (`users.status`) zaten ayrı bir kapıdır. Bu test kararı SABİTLER."""
    _, headers, kayit = calisan
    kayit.is_active = False
    resp = await client.post("/leave-requests/self", json=_govde(yillik), headers=headers)
    assert resp.status_code == 201, resp.text


async def test_self_rotasi_uuid_rotasina_YEM_OLMAZ(client, calisan):
    """Rota sırası tuzağı (MK-2 dersi): `/leave-requests/self`, `/leave-requests/{uuid}`
    rotasından ÖNCE tanımlanmalı — yoksa "self" UUID sanılır ve 422 gelir."""
    _, headers, _ = calisan
    resp = await client.get("/leave-requests/self", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"items": [], "total": 0, "limit": 50, "offset": 0}
