"""T4 — günlük kaydın durum akışı: `submit` / `reopen` (spec §2, §3; plan T4).

## Geçiş tablosu (BURADA testle sabitlenir)

| Durum       | submit                | reopen               |
|-------------|-----------------------|----------------------|
| `draft`     | → `submitted` (damga) | 409                  |
| `submitted` | 409                   | → `draft` (damga sil) |

Boş hücre SESSİZ geçiş DEĞİLDİR: idempotent davranmak, ikinci kez "Gönder"e
basan kullanıcıya ilk gönderimin damgasını sildirmeden "gönderdim" demek olurdu.

## Kapılar

`submit` → `site_diary` **full** (şef + saha müh. + patron; PM `view` olduğu için
403). `reopen` → `site_diary` **admin**: yanlış gönderimin düzeltilmesi kayıt
sahibinin değil sistem yöneticisinin işidir. Matriste `site_diary=_A` YALNIZ
`system_admin`dedir (patron `_F`) — matris DEĞİŞMEZ (spec §1), bu yüzden
"tam yetkili ama admin değil" hâli hem şef hem PATRON ile kanıtlanır.
"""

import uuid
from datetime import date
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.models import AuditLog
from app.modules.site_diary import guards
from app.modules.site_diary.models import DiaryStatus
from tests.site_diary.conftest import VARSAYILAN_TARIH

pytestmark = pytest.mark.asyncio


async def _olustur(
    client: AsyncClient, headers: dict[str, str], site_id, tarih: date = VARSAYILAN_TARIH
) -> dict:
    yanit = await client.post(
        f"/sites/{site_id}/diary", json={"entry_date": tarih.isoformat()}, headers=headers
    )
    assert yanit.status_code == 201, yanit.text
    return yanit.json()


async def _submit(client: AsyncClient, headers: dict[str, str], entry_id):
    return await client.post(f"/diary/{entry_id}/submit", headers=headers)


async def _reopen(client: AsyncClient, headers: dict[str, str], entry_id):
    return await client.post(f"/diary/{entry_id}/reopen", headers=headers)


# --- submit: mutlu yol + damga ---


async def test_submit_durumu_ve_damgayi_yazar(
    client: AsyncClient, admin_headers: dict[str, str], santiye
) -> None:
    site, _, _ = santiye
    kayit = await _olustur(client, admin_headers, site.id)
    assert kayit["status"] == DiaryStatus.draft.value
    assert kayit["submitted_at"] is None

    yanit = await _submit(client, admin_headers, kayit["id"])
    assert yanit.status_code == 200, yanit.text
    govde = yanit.json()
    assert govde["status"] == DiaryStatus.submitted.value
    assert govde["submitted_at"] is not None


async def test_submit_damgasi_kalicidir(
    client: AsyncClient, admin_headers: dict[str, str], santiye
) -> None:
    """Damga yanıtta değil KAYITTA durur — sonraki `GET` de aynı değeri döner."""
    site, _, _ = santiye
    kayit = await _olustur(client, admin_headers, site.id)
    gonderim = (await _submit(client, admin_headers, kayit["id"])).json()

    detay = (await client.get(f"/diary/{kayit['id']}", headers=admin_headers)).json()
    assert detay["status"] == DiaryStatus.submitted.value
    assert detay["submitted_at"] == gonderim["submitted_at"]


async def test_sef_submit_edebilir(
    client: AsyncClient, sef_headers: dict[str, str], santiye
) -> None:
    """Kapı `full`dur: şef kendi kaydını gönderebilmelidir."""
    site, _, _ = santiye
    kayit = await _olustur(client, sef_headers, site.id)
    assert (await _submit(client, sef_headers, kayit["id"])).status_code == 200


async def test_submit_yaniti_dropped_orphan_count_DOLDURMAZ(
    client: AsyncClient, admin_headers: dict[str, str], santiye
) -> None:
    """`dropped_orphan_count` YALNIZ `PUT …/lines` yanıtının alanıdır (T3)."""
    site, _, _ = santiye
    kayit = await _olustur(client, admin_headers, site.id)
    govde = (await _submit(client, admin_headers, kayit["id"])).json()
    assert govde["dropped_orphan_count"] is None


# --- Geçiş tablosunun REDDETTİĞİ hücreler ---


async def test_cift_submit_409(client: AsyncClient, admin_headers: dict[str, str], santiye) -> None:
    """İkinci `submit` SESSİZCE başarılı olmaz: idempotent geçiş, ilk gönderimin
    damgasını sessizce üzerine yazardı."""
    site, _, _ = santiye
    kayit = await _olustur(client, admin_headers, site.id)
    assert (await _submit(client, admin_headers, kayit["id"])).status_code == 200

    yanit = await _submit(client, admin_headers, kayit["id"])
    assert yanit.status_code == 409, yanit.text
    assert yanit.json()["detail"] == guards.INVALID_STATUS_TRANSITION


async def test_cift_submit_damgayi_DEGISTIRMEZ(
    client: AsyncClient, admin_headers: dict[str, str], santiye
) -> None:
    site, _, _ = santiye
    kayit = await _olustur(client, admin_headers, site.id)
    ilk = (await _submit(client, admin_headers, kayit["id"])).json()["submitted_at"]
    await _submit(client, admin_headers, kayit["id"])
    detay = (await client.get(f"/diary/{kayit['id']}", headers=admin_headers)).json()
    assert detay["submitted_at"] == ilk


async def test_taslak_reopen_409(
    client: AsyncClient, admin_headers: dict[str, str], santiye
) -> None:
    site, _, _ = santiye
    kayit = await _olustur(client, admin_headers, site.id)
    yanit = await _reopen(client, admin_headers, kayit["id"])
    assert yanit.status_code == 409, yanit.text
    assert yanit.json()["detail"] == guards.INVALID_STATUS_TRANSITION


# --- reopen: yalnız admin ---


async def test_reopen_durumu_ve_damgayi_geri_alir(
    client: AsyncClient, admin_headers: dict[str, str], santiye
) -> None:
    site, _, _ = santiye
    kayit = await _olustur(client, admin_headers, site.id)
    await _submit(client, admin_headers, kayit["id"])

    yanit = await _reopen(client, admin_headers, kayit["id"])
    assert yanit.status_code == 200, yanit.text
    govde = yanit.json()
    assert govde["status"] == DiaryStatus.draft.value
    # Damga TEMİZLENİR: taslak bir kaydın "gönderildi" saati kalsaydı ekran
    # gönderilmemiş bir kaydı gönderilmiş gibi etiketlerdi.
    assert govde["submitted_at"] is None


async def test_sef_full_ama_admin_degil_reopen_403(
    client: AsyncClient, sef_headers: dict[str, str], admin_headers: dict[str, str], santiye
) -> None:
    """Şef `site_diary=_F`tir; `submit` edebilir ama `reopen` EDEMEZ."""
    site, _, _ = santiye
    kayit = await _olustur(client, sef_headers, site.id)
    assert (await _submit(client, sef_headers, kayit["id"])).status_code == 200

    yanit = await _reopen(client, sef_headers, kayit["id"])
    assert yanit.status_code == 403, yanit.text
    # Kapı gerçekten KAPANDI: durum değişmedi.
    detay = (await client.get(f"/diary/{kayit['id']}", headers=admin_headers)).json()
    assert detay["status"] == DiaryStatus.submitted.value


async def test_patron_full_ama_admin_degil_reopen_403(
    client: AsyncClient, patron_headers: dict[str, str], santiye
) -> None:
    """Patron da `_F`tir (matris DEĞİŞMEZ) — `admin` kapısı yalnız `system_admin`e açılır."""
    site, _, _ = santiye
    kayit = await _olustur(client, patron_headers, site.id)
    assert (await _submit(client, patron_headers, kayit["id"])).status_code == 200
    assert (await _reopen(client, patron_headers, kayit["id"])).status_code == 403


# --- Yazma kapısının açılıp kapanması ---


async def test_submit_sonrasi_satir_yazma_KAPALI(
    client: AsyncClient, admin_headers: dict[str, str], santiye
) -> None:
    site, _, items = santiye
    kayit = await _olustur(client, admin_headers, site.id)
    await _submit(client, admin_headers, kayit["id"])

    yanit = await client.put(
        f"/diary/{kayit['id']}/lines",
        json={"lines": [{"boq_item_id": str(items[0].id), "quantity": "5"}]},
        headers=admin_headers,
    )
    assert yanit.status_code == 409, yanit.text
    assert yanit.json()["detail"] == guards.ENTRY_NOT_EDITABLE


async def test_submit_sonrasi_patch_KAPALI(
    client: AsyncClient, admin_headers: dict[str, str], santiye
) -> None:
    site, _, _ = santiye
    kayit = await _olustur(client, admin_headers, site.id)
    await _submit(client, admin_headers, kayit["id"])

    yanit = await client.patch(
        f"/diary/{kayit['id']}", json={"work_done": "x"}, headers=admin_headers
    )
    assert yanit.status_code == 409, yanit.text
    assert yanit.json()["detail"] == guards.ENTRY_NOT_EDITABLE


async def test_submit_sonrasi_silme_KAPALI(
    client: AsyncClient, admin_headers: dict[str, str], santiye
) -> None:
    site, _, _ = santiye
    kayit = await _olustur(client, admin_headers, site.id)
    await _submit(client, admin_headers, kayit["id"])
    yanit = await client.delete(f"/diary/{kayit['id']}", headers=admin_headers)
    assert yanit.status_code == 409, yanit.text
    assert yanit.json()["detail"] == guards.ENTRY_NOT_DELETABLE


async def test_reopen_yazma_kapisini_YENIDEN_ACAR(
    client: AsyncClient, admin_headers: dict[str, str], santiye
) -> None:
    """`reopen`ın VAR OLMA nedeni: yanlış gönderilen kayıt yeniden düzenlenebilmeli."""
    site, _, items = santiye
    kayit = await _olustur(client, admin_headers, site.id)
    assert (await _submit(client, admin_headers, kayit["id"])).status_code == 200
    assert (await _reopen(client, admin_headers, kayit["id"])).status_code == 200

    satirlar = await client.put(
        f"/diary/{kayit['id']}/lines",
        json={"lines": [{"boq_item_id": str(items[0].id), "quantity": "5"}]},
        headers=admin_headers,
    )
    assert satirlar.status_code == 200, satirlar.text
    patch = await client.patch(
        f"/diary/{kayit['id']}", json={"work_done": "düzeltildi"}, headers=admin_headers
    )
    assert patch.status_code == 200, patch.text


async def test_reopen_sonrasi_yeniden_submit_edilebilir(
    client: AsyncClient, admin_headers: dict[str, str], santiye
) -> None:
    site, _, _ = santiye
    kayit = await _olustur(client, admin_headers, site.id)
    ilk = (await _submit(client, admin_headers, kayit["id"])).json()["submitted_at"]
    await _reopen(client, admin_headers, kayit["id"])

    ikinci = await _submit(client, admin_headers, kayit["id"])
    assert ikinci.status_code == 200, ikinci.text
    # Damga YENİDEN yazılır (eski damga geri gelmez).
    assert ikinci.json()["submitted_at"] is not None
    assert ikinci.json()["submitted_at"] != ilk


# --- Geçiş matrisi: (durum × eylem × rol) ---


@pytest.mark.parametrize(
    ("baslangic", "eylem", "rol", "beklenen"),
    [
        # submit — full yeter, view yetmez, none hiç göremez
        (DiaryStatus.draft, "submit", "admin", 200),
        (DiaryStatus.draft, "submit", "sef", 200),
        (DiaryStatus.draft, "submit", "patron", 200),
        (DiaryStatus.draft, "submit", "pm", 403),
        (DiaryStatus.draft, "submit", "ik", 403),
        (DiaryStatus.submitted, "submit", "admin", 409),
        (DiaryStatus.submitted, "submit", "sef", 409),
        (DiaryStatus.submitted, "submit", "pm", 403),
        # reopen — YALNIZ admin; kapı durumdan ÖNCE koşar (şef taslakta da 403 alır)
        (DiaryStatus.submitted, "reopen", "admin", 200),
        (DiaryStatus.submitted, "reopen", "sef", 403),
        (DiaryStatus.submitted, "reopen", "patron", 403),
        (DiaryStatus.submitted, "reopen", "pm", 403),
        (DiaryStatus.submitted, "reopen", "ik", 403),
        (DiaryStatus.draft, "reopen", "admin", 409),
        (DiaryStatus.draft, "reopen", "sef", 403),
        (DiaryStatus.draft, "reopen", "pm", 403),
    ],
)
async def test_gecis_matrisi(
    client: AsyncClient,
    santiye,
    admin_headers: dict[str, str],
    sef_headers: dict[str, str],
    patron_headers: dict[str, str],
    pm_headers: dict[str, str],
    hr_headers: dict[str, str],
    baslangic: DiaryStatus,
    eylem: str,
    rol: str,
    beklenen: int,
) -> None:
    """Kapı SIRASI da sabitlenir: yetkisiz rol, geçiş tablosunun reddedeceği bir
    durumda bile 409 değil 403 alır — durum bilgisi yetkisize sızmaz."""
    basliklar = {
        "admin": admin_headers,
        "sef": sef_headers,
        "patron": patron_headers,
        "pm": pm_headers,
        "ik": hr_headers,
    }[rol]
    site, _, _ = santiye
    kayit = await _olustur(client, admin_headers, site.id)
    if baslangic is DiaryStatus.submitted:
        assert (await _submit(client, admin_headers, kayit["id"])).status_code == 200

    yanit = await client.post(f"/diary/{kayit['id']}/{eylem}", headers=basliklar)
    assert yanit.status_code == beklenen, yanit.text


# --- IDOR (kapsam süzgeci) ---


async def test_gorunmeyen_gunluge_submit_404(
    client: AsyncClient, sef_headers: dict[str, str], gorunmeyen_gunluk: uuid.UUID
) -> None:
    yanit = await _submit(client, sef_headers, gorunmeyen_gunluk)
    assert yanit.status_code == 404, yanit.text
    assert yanit.json()["detail"] == guards.ENTRY_MISSING


async def test_kapsami_kisitli_admin_de_tum_projeleri_gorur(
    client: AsyncClient,
    kapsamli_admin_headers: dict[str, str],
    gorunmeyen_gunluk: uuid.UUID,
) -> None:
    """DOKÜMANTE EDİLEN GERÇEK: `reopen`ın kapısı `site_diary=admin`dir ve bu
    seviye YALNIZ `system_admin` rolündedir; o rolün `projects` izni de `admin`
    olduğu için `visible_projects` kapsam süzgecini BİLEREK atlar (Ayarlar
    kilitlenme koruması). Yani `reopen` ucunun 404 dalı gerçek bir rolle
    tetiklenemez — `user_project_access` kaydı olsa bile.

    Kapsam süzgecinin kendisi `submit` ucuyla (şef, yukarıdaki test) ve ortak
    `service.visible_entry_locked` yoluyla kanıtlıdır; bu test kuralın sessizce
    değişmesini yakalar.
    """
    yanit = await _reopen(client, kapsamli_admin_headers, gorunmeyen_gunluk)
    assert yanit.status_code == 409, yanit.text
    assert yanit.json()["detail"] == guards.INVALID_STATUS_TRANSITION


async def test_olmayan_kayda_reopen_404(client: AsyncClient, admin_headers: dict[str, str]) -> None:
    """Kapsam kararı geçiş tablosundan ÖNCE koşar: var olmayan kayıt 409 değil 404."""
    yanit = await _reopen(client, admin_headers, uuid.uuid4())
    assert yanit.status_code == 404, yanit.text
    assert yanit.json()["detail"] == guards.ENTRY_MISSING


async def test_olmayan_kayda_submit_404(client: AsyncClient, admin_headers: dict[str, str]) -> None:
    yanit = await _submit(client, admin_headers, uuid.uuid4())
    assert yanit.status_code == 404, yanit.text
    assert yanit.json()["detail"] == guards.ENTRY_MISSING


# --- Denetim günlüğü ---


async def test_submit_denetim_gunlugune_yazar(
    client: AsyncClient, admin_headers: dict[str, str], santiye, seeded_db: AsyncSession
) -> None:
    site, _, _ = santiye
    kayit = await _olustur(client, admin_headers, site.id)
    await _submit(client, admin_headers, kayit["id"])

    kayitlar = (await seeded_db.execute(select(AuditLog))).scalars().all()
    assert any("Günlük kayıt gönderildi" in k.detail for k in kayitlar), [
        k.detail for k in kayitlar
    ]


async def test_reopen_denetim_gunlugune_yazar(
    client: AsyncClient, admin_headers: dict[str, str], santiye, seeded_db: AsyncSession
) -> None:
    site, _, _ = santiye
    kayit = await _olustur(client, admin_headers, site.id)
    await _submit(client, admin_headers, kayit["id"])
    await _reopen(client, admin_headers, kayit["id"])

    kayitlar = (await seeded_db.execute(select(AuditLog))).scalars().all()
    assert any("Günlük kayıt taslağa geri alındı" in k.detail for k in kayitlar), [
        k.detail for k in kayitlar
    ]


async def test_denetim_satiri_gun_ve_santiyeyi_tasir(
    client: AsyncClient, admin_headers: dict[str, str], santiye, seeded_db: AsyncSession
) -> None:
    """Denetim satırının kimliği UUID değil İNSAN-OKUR üçlüsüdür (T2 kuralı)."""
    site, proje, _ = santiye
    kayit = await _olustur(client, admin_headers, site.id)
    await _submit(client, admin_headers, kayit["id"])

    kayitlar = (await seeded_db.execute(select(AuditLog))).scalars().all()
    satir = next(k for k in kayitlar if "Günlük kayıt gönderildi" in k.detail)
    assert proje.name in satir.detail
    assert site.name in satir.detail
    assert VARSAYILAN_TARIH.isoformat() in satir.detail


# --- Kilit (TOCTOU) ---


async def test_submit_kilit_alir(
    client: AsyncClient, admin_headers: dict[str, str], santiye, monkeypatch
) -> None:
    """Durum geçişi KİLİTLİ satır üzerinden koşar: kilitsiz okunsaydı eşzamanlı
    bir `PUT …/lines` durum kapısını TOCTOU ile atlatabilirdi."""
    from app.modules.site_diary import repository

    site, _, _ = santiye
    kayit = await _olustur(client, admin_headers, site.id)

    cagrildi: list[uuid.UUID] = []
    orijinal = repository.get_entry_locked

    async def izleyen(session, entry_id):
        cagrildi.append(entry_id)
        return await orijinal(session, entry_id)

    monkeypatch.setattr(repository, "get_entry_locked", izleyen)
    assert (await _submit(client, admin_headers, kayit["id"])).status_code == 200
    assert uuid.UUID(kayit["id"]) in cagrildi


# --- Satır/işçi verisi geçişte KORUNUR ---


async def test_gecis_satirlari_bozmaz(
    client: AsyncClient, admin_headers: dict[str, str], santiye
) -> None:
    site, _, items = santiye
    kayit = await _olustur(client, admin_headers, site.id)
    await client.put(
        f"/diary/{kayit['id']}/lines",
        json={"lines": [{"boq_item_id": str(items[0].id), "quantity": "4.000"}]},
        headers=admin_headers,
    )
    govde = (await _submit(client, admin_headers, kayit["id"])).json()
    assert len(govde["lines"]) == 1
    assert Decimal(govde["lines"][0]["quantity"]) == Decimal("4.000")
    assert Decimal(govde["lines_total"]) == (items[0].unit_price * Decimal("4")).quantize(
        Decimal("0.01")
    )


async def test_ik_rolu_submit_403(
    client: AsyncClient, hr_headers: dict[str, str], admin_headers: dict[str, str], santiye
) -> None:
    site, _, _ = santiye
    kayit = await _olustur(client, admin_headers, site.id)
    assert (await _submit(client, hr_headers, kayit["id"])).status_code == 403
