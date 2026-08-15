"""MU-1 T3b — yevmiye fişi uçları (spec §7, yollar 6-14).

| # | Uç | İzin |
|---|---|---|
| 1 | `GET /journal-entries` | `view` |
| 2 | `POST /journal-entries` | `full` → **201** |
| 3 | `GET /journal-entries/summary` | `view` |
| 4 | `GET /journal-entries/{id}` | `view` |
| 5 | `PATCH /journal-entries/{id}` | `full` |
| 6 | `DELETE /journal-entries/{id}` | **`admin`** → 204 |
| 7 | `PUT /journal-entries/{id}/lines` | `full` |
| 8 | `POST /journal-entries/{id}/post` | `full` |
| 9 | `POST /journal-entries/{id}/reverse` | `full` → **201** |

(`GET /journal` koşan bakiyesiyle birlikte `test_mu1_ledger.py`dedir.)

## Bu dosyanın kilitlediği kararlar

1. 🔴 **K1'in üç engeli TEK 422'de** toplanır ve kapı ÜÇ yolda birden koşar:
   `POST` · `PUT lines` · `POST /post`. Sonuncusu bilinçli bir TEKRARDIR: fiş
   taslakken yaprak olan bir hesabın altına (ORM'le) çocuk açılırsa
   kayıtlaştırma anında yeniden ısırır.
2. 🔴 **NULL-EŞİK / fail-closed:** `debit`/`credit` NULL, eksik ya da boş metin
   ise **422**. `None`ı `0` saymak `Σ`yı sessizce dengeler ve dengesiz fiş
   dengede sayılırdı (spec §4).
3. 🔴 **`posted` fişte PATCH/PUT lines/DELETE → 409, 403 DEĞİL:** yetki VARDIR,
   engelleyen kaydın DURUMUDUR.
4. 🔴 **`DELETE` düz `admin`:** `full` (muhasebe) 403 alır — ön koşullu testtir,
   aynı kullanıcı PATCH'i GEÇER.
5. 🔴 **Storno YENİ BİR FİŞTİR:** tarihi `timezone.today()`dir (K6 sınır
   çağrısı — orijinalin tarihi kapalı bir döneme düşerdi), açıklaması
   `REVERSAL_PREFIX`li, bacakları TAKASLIDIR ve orijinal `reversed` olur.
6. 🔴 **K3 uçtan uca:** orijinal + storno → hesabın bakiyesi **TAM SIFIR**
   (`POSTING_STATUSES`e `reversed` dahil olduğu için).
7. 🔴 **ROTA SIRASI:** `/journal-entries/summary` `{entry_id}`den ÖNCE
   kaydedilir; aksi hâlde `summary` bir UUID sanılıp 422'ye düşerdi (MK-2).
8. **Gövde türev/sunucu alanı GÖNDEREMEZ** (422): `status` · `total_debit` ·
   `total_credit` · `reversal_of_id` · `period_year`/`period_month`.
9. **Denetim:** yeni `AuditAction` üyesi AÇILMADI (`post → approve`,
   `reverse → update`) ve 🔴 **TUTAR metne GİRMEZ**.
"""

import uuid
from decimal import Decimal

from sqlalchemy import select

from app.core.text import FREE_TEXT_MAX_LENGTH
from app.core.timezone import today
from app.modules.accounting import guards, validation
from app.modules.accounting.models import ChartAccountType, JournalEntry, JournalEntryStatus
from app.modules.audit.models import AuditAction, AuditLog

_YOL = "/journal-entries"
_TARIH = "2026-07-17"


def _satir(account_id, debit: str = "0", credit: str = "0") -> dict:
    return {"account_id": str(account_id), "debit": debit, "credit": credit}


def _govde(borc_hesap, alacak_hesap, tutar: str = "1000.00", **ek) -> dict:
    govde = {
        "entry_date": _TARIH,
        "description": "Kasa tahsilatı",
        "detail_note": "Ziraat Bank · TRF-20260717",
        "lines": [
            _satir(borc_hesap.id, debit=tutar),
            _satir(alacak_hesap.id, credit=tutar),
        ],
    }
    govde.update(ek)
    return govde


async def _iki_yaprak(hesap_fabrikasi, sira: int = 0):
    """İki YAPRAK hesap — fiş satırı yalnızca çocuğu olmayana kesilebilir (§4c).

    `sira` kodları ayrıştırır: `uq_chart_of_accounts_code` tekildir ve aynı test
    içinde iki kez çağrılan bir yardımcı sessizce IntegrityError üretirdi.
    """
    kasa = await hesap_fabrikasi(f"10{sira}", name="Kasa", account_type=ChartAccountType.asset)
    saticilar = await hesap_fabrikasi(
        f"32{sira}", name="Satıcılar", account_type=ChartAccountType.liability
    )
    return kasa, saticilar


async def _fis_olustur(client, headers, hesap_fabrikasi, sira: int = 0, **ek) -> dict:
    kasa, saticilar = await _iki_yaprak(hesap_fabrikasi, sira)
    resp = await client.post(_YOL, json=_govde(kasa, saticilar, **ek), headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


# --------------------------------------------------------------------------- #
# Uç 2 — POST (oluştur)
# --------------------------------------------------------------------------- #


async def test_post_taslak_fis_uretir_201_ve_toplamlari_SUNUCU_yazar(
    client, muhasebe_headers, hesap_fabrikasi
) -> None:
    """Durum `draft`tır (`INITIAL_STATUS`), toplamlar satırlardan TÜREtilir.

    `total_debit`/`total_credit` gövdeden gelmez ve `_apply_totals` TEK yazım
    yoludur: iki yerde yazılsalardı `ck_journal_entries_posted_balanced` bir
    yolda sessizce devre dışı kalırdı.
    """
    kasa, saticilar = await _iki_yaprak(hesap_fabrikasi)
    resp = await client.post(_YOL, json=_govde(kasa, saticilar), headers=muhasebe_headers)

    assert resp.status_code == 201, resp.text
    govde = resp.json()
    assert govde["status"] == "draft"
    assert Decimal(govde["total_debit"]) == Decimal("1000.00")
    assert Decimal(govde["total_credit"]) == Decimal("1000.00")
    assert govde["period_year"] == 2026 and govde["period_month"] == 7
    assert govde["reversal_of_id"] is None
    assert [s["sort_order"] for s in govde["lines"]] == [0, 1]
    assert [s["account_code"] for s in govde["lines"]] == ["100", "320"]


async def test_post_govde_ici_hesap_referansi_YOKSA_404(
    client, muhasebe_headers, hesap_fabrikasi
) -> None:
    """🔴 ST kanonu: gövde içi VARLIK referansı 404'tür, 422 değil."""
    kasa, _ = await _iki_yaprak(hesap_fabrikasi)
    govde = {
        "entry_date": _TARIH,
        "description": "Hayalet hesap",
        "lines": [
            _satir(kasa.id, debit="10.00"),
            _satir(uuid.uuid4(), credit="10.00"),
        ],
    }
    resp = await client.post(_YOL, json=govde, headers=muhasebe_headers)
    assert resp.status_code == 404, resp.text
    assert resp.json()["detail"] == guards.LINE_ACCOUNT_MISSING


async def test_post_dengesiz_fis_422(client, muhasebe_headers, hesap_fabrikasi) -> None:
    kasa, saticilar = await _iki_yaprak(hesap_fabrikasi)
    govde = {
        "entry_date": _TARIH,
        "description": "Dengesiz",
        "lines": [_satir(kasa.id, debit="100.00"), _satir(saticilar.id, credit="99.99")],
    }
    resp = await client.post(_YOL, json=govde, headers=muhasebe_headers)
    assert resp.status_code == 422, resp.text
    assert validation.UNBALANCED in resp.json()["detail"]


async def test_post_yaprak_olmayan_hesaba_satir_422(
    client, muhasebe_headers, hesap_fabrikasi
) -> None:
    """§4c: üst hesabın bakiyesi çocuklarının toplamıdır; ikisine birden kayıt
    atılırsa MU-2'nin mizanı ÇİFT SAYAR."""
    ust = await hesap_fabrikasi("120", name="Alıcılar")
    await hesap_fabrikasi("120.01", name="Yurtiçi Alıcılar")
    _, saticilar = await _iki_yaprak(hesap_fabrikasi)

    govde = {
        "entry_date": _TARIH,
        "description": "Üst hesaba kayıt",
        "lines": [_satir(ust.id, debit="10.00"), _satir(saticilar.id, credit="10.00")],
    }
    resp = await client.post(_YOL, json=govde, headers=muhasebe_headers)
    assert resp.status_code == 422, resp.text
    assert validation.NON_LEAF_ACCOUNT in resp.json()["detail"]


async def test_post_UC_ENGEL_TEK_422de_toplanir(client, muhasebe_headers, hesap_fabrikasi) -> None:
    """🔴 K1'in üç engeli AYNI yanıtta görünür (FAT-1 `_raise_blockers` deseni).

    Tek tek gösterilseydi kullanıcı aynı formu üç kez gönderip üç kez
    reddedilirdi.
    """
    ust = await hesap_fabrikasi("120", name="Alıcılar")
    await hesap_fabrikasi("120.01", name="Yurtiçi Alıcılar")
    govde = {
        "entry_date": _TARIH,
        "description": "Üç engel",
        "lines": [_satir(ust.id, debit="10.00")],
    }
    resp = await client.post(_YOL, json=govde, headers=muhasebe_headers)
    assert resp.status_code == 422, resp.text
    detay = resp.json()["detail"]
    assert validation.UNBALANCED in detay
    assert validation.MIN_LINES_REQUIRED in detay
    assert validation.NON_LEAF_ACCOUNT in detay


# --- 🔴 NULL-EŞİK / fail-closed ---


async def test_satirda_debit_NULL_ise_422(client, muhasebe_headers, hesap_fabrikasi) -> None:
    """🔴 `None` `0` SAYILMAZ: sayılsaydı `Σ` NULL'ı yutar ve dengesiz fiş
    dengede görünürdü (spec §4 NULL fail-closed)."""
    kasa, saticilar = await _iki_yaprak(hesap_fabrikasi)
    govde = {
        "entry_date": _TARIH,
        "description": "NULL tutar",
        "lines": [
            {"account_id": str(kasa.id), "debit": None, "credit": "0"},
            _satir(saticilar.id, credit="10.00"),
        ],
    }
    resp = await client.post(_YOL, json=govde, headers=muhasebe_headers)
    assert resp.status_code == 422, resp.text


async def test_satirda_debit_ALANI_HIC_YOKSA_422(client, muhasebe_headers, hesap_fabrikasi) -> None:
    """Eksik alanın varsayılanı YOKTUR: `0` varsayılsaydı yarım gönderilen bir
    gövde sessizce tek taraflı bir fiş üretirdi."""
    kasa, saticilar = await _iki_yaprak(hesap_fabrikasi)
    govde = {
        "entry_date": _TARIH,
        "description": "Eksik alan",
        "lines": [
            {"account_id": str(kasa.id), "credit": "0"},
            _satir(saticilar.id, credit="10.00"),
        ],
    }
    resp = await client.post(_YOL, json=govde, headers=muhasebe_headers)
    assert resp.status_code == 422, resp.text


async def test_satirda_debit_BOS_METIN_ise_422(client, muhasebe_headers, hesap_fabrikasi) -> None:
    kasa, saticilar = await _iki_yaprak(hesap_fabrikasi)
    govde = {
        "entry_date": _TARIH,
        "description": "Boş metin",
        "lines": [
            {"account_id": str(kasa.id), "debit": "", "credit": "0"},
            _satir(saticilar.id, credit="10.00"),
        ],
    }
    resp = await client.post(_YOL, json=govde, headers=muhasebe_headers)
    assert resp.status_code == 422, resp.text


async def test_cift_dolu_ve_bos_satir_422(client, muhasebe_headers, hesap_fabrikasi) -> None:
    """E8'in her satırı TEK TARAFLIDIR (boş taraf hep `—`).

    `(0,0)` satırı toplama katkısız olduğu hâlde satır SAYISINI şişirir ve
    `len(lines) >= 2` engelini sahte biçimde geçirirdi; çift dolu satır ise
    `ck_journal_lines_single_side`e düşüp ayrımsız bir 409 üretirdi.
    """
    kasa, saticilar = await _iki_yaprak(hesap_fabrikasi)
    for bozuk in (
        _satir(kasa.id, debit="10.00", credit="10.00"),
        _satir(kasa.id),
    ):
        govde = {
            "entry_date": _TARIH,
            "description": "Tek taraf ihlali",
            "lines": [bozuk, _satir(saticilar.id, credit="10.00")],
        }
        resp = await client.post(_YOL, json=govde, headers=muhasebe_headers)
        assert resp.status_code == 422, resp.text


async def test_negatif_tutar_422(client, muhasebe_headers, hesap_fabrikasi) -> None:
    """Negatif tutar `Σ`yı sessizce dengeleyebilirdi (spec §4)."""
    kasa, saticilar = await _iki_yaprak(hesap_fabrikasi)
    govde = {
        "entry_date": _TARIH,
        "description": "Negatif",
        "lines": [_satir(kasa.id, debit="-10.00"), _satir(saticilar.id, credit="-10.00")],
    }
    resp = await client.post(_YOL, json=govde, headers=muhasebe_headers)
    assert resp.status_code == 422, resp.text


# --- Türev / sunucu alanları ---


async def test_turev_ve_sunucu_alanlari_govdeden_GELEMEZ(
    client, muhasebe_headers, hesap_fabrikasi
) -> None:
    """`extra="forbid"`: sessiz yok sayma YOK.

    Pydantic'in varsayılanı bunları ATMAK olurdu; istemci gönderdiği durumun
    ya da toplamın yazıldığını sanır, ekranda başka bir değer görürdü.
    """
    kasa, saticilar = await _iki_yaprak(hesap_fabrikasi)
    for alan, deger in (
        ("status", "posted"),
        ("total_debit", "1000.00"),
        ("total_credit", "1000.00"),
        ("reversal_of_id", str(uuid.uuid4())),
        ("period_year", 2026),
        ("period_month", 7),
        ("running_balance", "5.00"),
    ):
        resp = await client.post(
            _YOL, json=_govde(kasa, saticilar, **{alan: deger}), headers=muhasebe_headers
        )
        assert resp.status_code == 422, f"{alan}: {resp.text}"


async def test_description_tavani_ORTAK_sabitten(client, muhasebe_headers, hesap_fabrikasi) -> None:
    """Tavan `app.core.text.FREE_TEXT_MAX_LENGTH`tir ve TÜM giriş noktaları
    (POST + PATCH) aynı sabitten okur — ikisi ayrışsaydı tavan bir uçtan
    atlatılabilirdi (belge arşivi T4 dersi)."""
    kasa, saticilar = await _iki_yaprak(hesap_fabrikasi)
    uzun = "x" * (FREE_TEXT_MAX_LENGTH + 1)

    resp = await client.post(
        _YOL, json=_govde(kasa, saticilar, description=uzun), headers=muhasebe_headers
    )
    assert resp.status_code == 422, resp.text

    fis = await _fis_olustur(client, muhasebe_headers, hesap_fabrikasi, sira=1)
    resp = await client.patch(
        f"{_YOL}/{fis['id']}", json={"description": uzun}, headers=muhasebe_headers
    )
    assert resp.status_code == 422, resp.text


# --------------------------------------------------------------------------- #
# Uç 1 / 4 — liste ve detay
# --------------------------------------------------------------------------- #


async def test_liste_K7_zarfini_dondurur(client, muhasebe_headers, hesap_fabrikasi) -> None:
    await _fis_olustur(client, muhasebe_headers, hesap_fabrikasi)
    resp = await client.get(_YOL, headers=muhasebe_headers)
    assert resp.status_code == 200, resp.text
    govde = resp.json()
    assert set(govde) == {"items", "total", "limit", "offset"}
    assert govde["limit"] == 50 and govde["offset"] == 0
    assert govde["total"] == 1


async def test_limit_tavani_KIRPILMAZ_422dir(client, muhasebe_headers) -> None:
    assert (await client.get(f"{_YOL}?limit=200", headers=muhasebe_headers)).status_code == 200
    assert (await client.get(f"{_YOL}?limit=201", headers=muhasebe_headers)).status_code == 422


async def test_detay_ve_olmayan_fis_404(client, muhasebe_headers, hesap_fabrikasi) -> None:
    fis = await _fis_olustur(client, muhasebe_headers, hesap_fabrikasi)
    assert (await client.get(f"{_YOL}/{fis['id']}", headers=muhasebe_headers)).status_code == 200

    resp = await client.get(f"{_YOL}/{uuid.uuid4()}", headers=muhasebe_headers)
    assert resp.status_code == 404, resp.text
    assert resp.json()["detail"] == guards.JOURNAL_ENTRY_MISSING


# --------------------------------------------------------------------------- #
# 🔴 ROTA SIRASI bekçisi (MK-2 dersi)
# --------------------------------------------------------------------------- #


async def test_rota_sirasi_summary_UUID_SANILMAZ(client, muhasebe_headers) -> None:
    """🔴 `/journal-entries/summary` `{entry_id}`den ÖNCE kaydedilmiş olmalıdır.

    Sonra kaydedilseydi FastAPI onu `{entry_id}` ile eşler, `summary` bir UUID
    sanılır ve uç **422**'ye düşerdi (MK-2'de birebir yaşandı). Bekçi doğrudan
    bu ayrımı ölçer: 200 gelmesi sıranın DOĞRU olduğunun kanıtıdır.
    """
    resp = await client.get(f"{_YOL}/summary", headers=muhasebe_headers)
    assert resp.status_code == 200, resp.text
    assert set(resp.json()) == {"year", "month", "total_debit", "total_credit", "net_balance"}


# --------------------------------------------------------------------------- #
# Uç 5 — PATCH
# --------------------------------------------------------------------------- #


async def test_patch_taslakta_gecer_ve_DONEMI_birlikte_tasir(
    client, muhasebe_headers, hesap_fabrikasi
) -> None:
    """`entry_date` değişince `period_year/month` de değişir.

    Ayrı bırakılsaydı `ck_journal_entries_period_matches_date` ihlal edilir ve
    kullanıcıya ayrımsız bir 409 giderdi.
    """
    fis = await _fis_olustur(client, muhasebe_headers, hesap_fabrikasi)
    resp = await client.patch(
        f"{_YOL}/{fis['id']}",
        json={"entry_date": "2026-08-03", "description": "Düzeltildi"},
        headers=muhasebe_headers,
    )
    assert resp.status_code == 200, resp.text
    govde = resp.json()
    assert govde["entry_date"] == "2026-08-03"
    assert (govde["period_year"], govde["period_month"]) == (2026, 8)
    assert govde["description"] == "Düzeltildi"


async def test_patch_gonderilmeyen_alani_EZMEZ(client, muhasebe_headers, hesap_fabrikasi) -> None:
    """`exclude_unset` ŞARTTIR (İK dersi): dokunulmamış alan sunucudaki değeri
    ezmemelidir."""
    fis = await _fis_olustur(client, muhasebe_headers, hesap_fabrikasi)
    resp = await client.patch(
        f"{_YOL}/{fis['id']}", json={"description": "Yalnız açıklama"}, headers=muhasebe_headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["detail_note"] == "Ziraat Bank · TRF-20260717"


async def test_patch_kayitli_fiste_409(client, muhasebe_headers, hesap_fabrikasi) -> None:
    """🔴 409, 403 DEĞİL: yetki VARDIR, engelleyen kaydın DURUMUDUR."""
    fis = await _fis_olustur(client, muhasebe_headers, hesap_fabrikasi)
    assert (
        await client.post(f"{_YOL}/{fis['id']}/post", headers=muhasebe_headers)
    ).status_code == 200

    resp = await client.patch(
        f"{_YOL}/{fis['id']}", json={"description": "Olmaz"}, headers=muhasebe_headers
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"] == guards.JOURNAL_ENTRY_NOT_EDITABLE


# --------------------------------------------------------------------------- #
# Uç 7 — PUT lines
# --------------------------------------------------------------------------- #


async def test_put_lines_kumeyi_TOPTAN_yazar_ve_toplamlari_yeniler(
    client, muhasebe_headers, hesap_fabrikasi
) -> None:
    fis = await _fis_olustur(client, muhasebe_headers, hesap_fabrikasi)
    banka = await hesap_fabrikasi("102", name="Bankalar")
    saticilar = (await client.get(f"{_YOL}/{fis['id']}", headers=muhasebe_headers)).json()["lines"][
        1
    ]["account_id"]

    resp = await client.put(
        f"{_YOL}/{fis['id']}/lines",
        json={"lines": [_satir(banka.id, debit="250.00"), _satir(saticilar, credit="250.00")]},
        headers=muhasebe_headers,
    )
    assert resp.status_code == 200, resp.text
    govde = resp.json()
    assert Decimal(govde["total_debit"]) == Decimal("250.00")
    assert [s["account_code"] for s in govde["lines"]] == ["102", "320"]


async def test_put_lines_K1_kapisindan_gecer(client, muhasebe_headers, hesap_fabrikasi) -> None:
    fis = await _fis_olustur(client, muhasebe_headers, hesap_fabrikasi)
    banka = await hesap_fabrikasi("102", name="Bankalar")
    resp = await client.put(
        f"{_YOL}/{fis['id']}/lines",
        json={"lines": [_satir(banka.id, debit="250.00")]},
        headers=muhasebe_headers,
    )
    assert resp.status_code == 422, resp.text
    assert validation.MIN_LINES_REQUIRED in resp.json()["detail"]


async def test_put_lines_kayitli_fiste_409(client, muhasebe_headers, hesap_fabrikasi) -> None:
    """🔴 R5 — "posted fişin satırı UPDATE edilemez" DB'de zorlanamaz (trigger
    yok); satır yazan TEK yol budur ve kapı buradadır."""
    fis = await _fis_olustur(client, muhasebe_headers, hesap_fabrikasi)
    await client.post(f"{_YOL}/{fis['id']}/post", headers=muhasebe_headers)
    resp = await client.put(
        f"{_YOL}/{fis['id']}/lines", json={"lines": []}, headers=muhasebe_headers
    )
    assert resp.status_code == 409, resp.text


# --------------------------------------------------------------------------- #
# Uç 6 — DELETE
# --------------------------------------------------------------------------- #


async def test_delete_yalniz_admin_204_full_403(
    client, admin_headers, muhasebe_headers, hesap_fabrikasi
) -> None:
    """🔴 `full` silmeyi KAPSAMAZ. Ön koşul: aynı kullanıcı PATCH'i GEÇER, yani
    403 gerçekten YETKİ SEVİYESİNDEN gelir, kaydın durumundan değil."""
    fis = await _fis_olustur(client, muhasebe_headers, hesap_fabrikasi)
    assert (
        await client.patch(
            f"{_YOL}/{fis['id']}", json={"description": "Ön koşul"}, headers=muhasebe_headers
        )
    ).status_code == 200

    assert (await client.delete(f"{_YOL}/{fis['id']}", headers=muhasebe_headers)).status_code == 403
    assert (await client.delete(f"{_YOL}/{fis['id']}", headers=admin_headers)).status_code == 204
    assert (await client.get(f"{_YOL}/{fis['id']}", headers=muhasebe_headers)).status_code == 404


async def test_delete_kayitli_fiste_409(
    client, admin_headers, muhasebe_headers, hesap_fabrikasi
) -> None:
    fis = await _fis_olustur(client, muhasebe_headers, hesap_fabrikasi)
    await client.post(f"{_YOL}/{fis['id']}/post", headers=muhasebe_headers)
    resp = await client.delete(f"{_YOL}/{fis['id']}", headers=admin_headers)
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"] == guards.JOURNAL_ENTRY_NOT_DELETABLE


async def test_delete_olmayan_fis_404(client, admin_headers) -> None:
    assert (await client.delete(f"{_YOL}/{uuid.uuid4()}", headers=admin_headers)).status_code == 404


# --------------------------------------------------------------------------- #
# Uç 8 — post (kayıtlaştır)
# --------------------------------------------------------------------------- #


async def test_post_ucu_taslagi_kayitlastirir_ve_ikincisi_409(
    client, muhasebe_headers, hesap_fabrikasi
) -> None:
    fis = await _fis_olustur(client, muhasebe_headers, hesap_fabrikasi)
    resp = await client.post(f"{_YOL}/{fis['id']}/post", headers=muhasebe_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "posted"

    tekrar = await client.post(f"{_YOL}/{fis['id']}/post", headers=muhasebe_headers)
    assert tekrar.status_code == 409, tekrar.text
    assert tekrar.json()["detail"] == guards.INVALID_TRANSITION


async def test_post_ucu_K1_kapisini_YENIDEN_kosar(
    client, muhasebe_headers, hesap_fabrikasi, seeded_db
) -> None:
    """🔴 Kapı kayıtlaştırma anında TEKRAR ısırır (spec §4).

    Senaryo gerçektir: fiş taslakken `100` YAPRAKTI; sonra altına `100.01`
    açılırsa (uç K-Ş3 ile 409 verir, ama veri başka bir yoldan da doğabilir) o
    fiş artık üst hesaba kesilmiş sayılır ve kayıtlaştırılmamalıdır. Kapı yalnız
    yazma anında koşsaydı bu fiş sessizce deftere girer ve MU-2 mizanı çift
    sayardı.
    """
    fis = await _fis_olustur(client, muhasebe_headers, hesap_fabrikasi)
    await hesap_fabrikasi("100.01", name="Merkez Kasa")
    await seeded_db.flush()

    resp = await client.post(f"{_YOL}/{fis['id']}/post", headers=muhasebe_headers)
    assert resp.status_code == 422, resp.text
    assert validation.NON_LEAF_ACCOUNT in resp.json()["detail"]


async def test_post_ucu_olmayan_fiste_404(client, muhasebe_headers) -> None:
    resp = await client.post(f"{_YOL}/{uuid.uuid4()}/post", headers=muhasebe_headers)
    assert resp.status_code == 404, resp.text


# --------------------------------------------------------------------------- #
# Uç 9 — reverse (storno)
# --------------------------------------------------------------------------- #


async def test_reverse_YENI_FIS_uretir_bacaklar_TAKASLI(
    client, muhasebe_headers, hesap_fabrikasi
) -> None:
    """🔴 Storno bir alan ya da bayrak DEĞİL, YENİ BİR FİŞTİR (spec §5).

    * `status` doğrudan `posted` — storno taslak değildir;
    * 🔴 `entry_date` **`timezone.today()`**dir: orijinalin tarihi kullanılsaydı
      storno MU-2'nin kilitleyeceği KAPALI bir döneme düşerdi (K6 sınır çağrısı);
    * `description` `REVERSAL_PREFIX`lidir ve önek `guards.py`de TEK kopyadır;
    * `detail_note` kopyadır (dayanak aynıdır);
    * bacaklar `debit ↔ credit` TAKASLIDIR, `sort_order` KORUNUR.
    """
    fis = await _fis_olustur(client, muhasebe_headers, hesap_fabrikasi)
    await client.post(f"{_YOL}/{fis['id']}/post", headers=muhasebe_headers)

    resp = await client.post(f"{_YOL}/{fis['id']}/reverse", headers=muhasebe_headers)
    assert resp.status_code == 201, resp.text
    storno = resp.json()

    bugun = today()
    assert storno["status"] == "posted"
    assert storno["entry_date"] == bugun.isoformat()
    assert (storno["period_year"], storno["period_month"]) == (bugun.year, bugun.month)
    assert storno["description"] == f"{guards.REVERSAL_PREFIX}Kasa tahsilatı"
    assert storno["detail_note"] == "Ziraat Bank · TRF-20260717"
    assert storno["reversal_of_id"] == fis["id"]

    asil = {(s["account_code"], s["sort_order"]): (s["debit"], s["credit"]) for s in fis["lines"]}
    for satir in storno["lines"]:
        borc, alacak = asil[(satir["account_code"], satir["sort_order"])]
        assert (Decimal(satir["debit"]), Decimal(satir["credit"])) == (
            Decimal(alacak),
            Decimal(borc),
        )

    orijinal = await client.get(f"{_YOL}/{fis['id']}", headers=muhasebe_headers)
    assert orijinal.json()["status"] == "reversed"


async def test_reverse_K3_net_TAM_SIFIR(client, muhasebe_headers, hesap_fabrikasi) -> None:
    """🔴 R6 uçtan uca: `POSTING_STATUSES`e `reversed` DAHİL olduğu için
    orijinal + storno hesabın bakiyesini TAM SIFIRA götürür.

    Yalnız `posted` sayılsaydı orijinal defterden düşer, storno ters
    bacaklarıyla eklenir ve net **−orijinal** çıkardı (ÇİFT ters kayıt).
    """
    kasa, saticilar = await _iki_yaprak(hesap_fabrikasi)
    resp = await client.post(_YOL, json=_govde(kasa, saticilar), headers=muhasebe_headers)
    assert resp.status_code == 201, resp.text
    fis = resp.json()
    await client.post(f"{_YOL}/{fis['id']}/post", headers=muhasebe_headers)

    ara = await client.get(f"/chart-of-accounts/{kasa.id}", headers=muhasebe_headers)
    assert Decimal(ara.json()["balance"]) == Decimal("1000.00")

    await client.post(f"{_YOL}/{fis['id']}/reverse", headers=muhasebe_headers)

    for hesap in (kasa, saticilar):
        son = await client.get(f"/chart-of-accounts/{hesap.id}", headers=muhasebe_headers)
        assert Decimal(son.json()["balance"]) == Decimal("0"), hesap.code


async def test_ayni_fis_IKI_KEZ_terslenemez_409(client, muhasebe_headers, hesap_fabrikasi) -> None:
    """🔴 Normal yolda ısıran kapı **MATRİSTİR**, `ENTRY_ALREADY_REVERSED` değil.

    Sıra bilinçlidir ve EŞİK = KİLİT'in parçasıdır: (1) kilit, (2) matris,
    (3) stornoya özel kapılar. İlk storno orijinali `reversed` DAMGALAR ve
    `reversed` TERMİNALDİR — ikinci istek matrisi hiç geçemez. Bu iddia
    ayrıca sıranın kendisini kilitler: stornoya özel kapı öne alınsaydı burada
    başka bir cümle dönerdi.

    `ENTRY_ALREADY_REVERSED` kapısı ölü DEĞİLDİR; damgası atılmamış ama stornosu
    yazılmış bir fişi (UNIQUE'in servis karşılığı) kapatır ve
    `test_damgasiz_stornosu_olan_fis_409` onu DOĞRUDAN ölçer.
    """
    fis = await _fis_olustur(client, muhasebe_headers, hesap_fabrikasi)
    await client.post(f"{_YOL}/{fis['id']}/post", headers=muhasebe_headers)
    await client.post(f"{_YOL}/{fis['id']}/reverse", headers=muhasebe_headers)

    resp = await client.post(f"{_YOL}/{fis['id']}/reverse", headers=muhasebe_headers)
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"] == guards.INVALID_TRANSITION


async def test_damgasiz_stornosu_olan_fis_409(
    client, muhasebe_headers, hesap_fabrikasi, fis_fabrikasi
) -> None:
    """🔴 `uq_journal_entries_reversal_of`un SERVİS karşılığı — DOĞRUDAN ölçüm.

    Matrisin GÖREMEDİĞİ hâl: fiş hâlâ `posted`tır (damgası atılmamış) ama ona
    işaret eden bir storno VARDIR. Bu durum normal yoldan doğmaz; ileride
    fiş üreten başka bir yol (MU-3 entegrasyonu) ya da elle bir düzeltme onu
    üretebilir. Kapı olmasaydı ikinci storno UNIQUE'e düşer ve kullanıcı
    ayrımsız bir "Veri bütünlüğü hatası" alırdı — hangi fişin zaten terslendiğini
    öğrenemezdi.
    """
    kasa, saticilar = await _iki_yaprak(hesap_fabrikasi)
    orijinal = await fis_fabrikasi([(kasa, "10.00", "0"), (saticilar, "0", "10.00")])
    await fis_fabrikasi([(kasa, "0", "10.00"), (saticilar, "10.00", "0")], reversal_of=orijinal)

    resp = await client.post(f"{_YOL}/{orijinal.id}/reverse", headers=muhasebe_headers)
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"] == guards.ENTRY_ALREADY_REVERSED


async def test_STORNO_terslenemez_409(client, muhasebe_headers, hesap_fabrikasi) -> None:
    """Stornonun stornosu sonsuz zincir açardı, mali anlamı yoktur (spec §5)."""
    fis = await _fis_olustur(client, muhasebe_headers, hesap_fabrikasi)
    await client.post(f"{_YOL}/{fis['id']}/post", headers=muhasebe_headers)
    storno = (await client.post(f"{_YOL}/{fis['id']}/reverse", headers=muhasebe_headers)).json()

    resp = await client.post(f"{_YOL}/{storno['id']}/reverse", headers=muhasebe_headers)
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"] == guards.REVERSAL_NOT_REVERSIBLE


async def test_taslak_fis_terslenemez_409(client, muhasebe_headers, hesap_fabrikasi) -> None:
    """Matris dışı çift — `(draft, reverse)` tabloda YOKTUR."""
    fis = await _fis_olustur(client, muhasebe_headers, hesap_fabrikasi)
    resp = await client.post(f"{_YOL}/{fis['id']}/reverse", headers=muhasebe_headers)
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"] == guards.INVALID_TRANSITION


# --------------------------------------------------------------------------- #
# Uç 3 — summary (üç KPI)
# --------------------------------------------------------------------------- #


async def test_summary_UC_KPI_ve_net_ALACAK_EKSI_BORC(
    client, muhasebe_headers, hesap_fabrikasi, fis_fabrikasi
) -> None:
    """🔴 `net_balance = ALACAK − BORÇ` (E8:88 `4.120.000−3.842.600=277.400`).

    Yön burada ÖLÇÜLEBİLİR olmalıdır. Dengeli fişlerde iki toplam eşit olduğu
    için net her zaman **0** çıkar ve işaret yönü GÖRÜNMEZ. Probe bu yüzden
    dengesiz bir fiştir ve durumu bilinçli olarak **`reversed`**tır:
    `ck_journal_entries_posted_balanced` yalnız `posted`ta ısırır, dolayısıyla
    dengesiz bir kayıt DB'ye ancak bu durumda girebilir — ve `reversed`
    `POSTING_STATUSES`e DAHİLDİR, yani KPI onu sayar. KPI satırları toplar,
    başlığı değil.
    """
    kasa, saticilar = await _iki_yaprak(hesap_fabrikasi)
    await fis_fabrikasi(
        [(kasa, "100.00", "0"), (saticilar, "0", "400.00")],
        status=JournalEntryStatus.reversed,
    )
    resp = await client.get(f"{_YOL}/summary?year=2026&month=7", headers=muhasebe_headers)
    assert resp.status_code == 200, resp.text
    govde = resp.json()
    assert Decimal(govde["total_debit"]) == Decimal("100.00")
    assert Decimal(govde["total_credit"]) == Decimal("400.00")
    assert Decimal(govde["net_balance"]) == Decimal("300.00")


async def test_summary_taslagi_saymaz_reversedi_SAYAR(
    client, muhasebe_headers, hesap_fabrikasi, fis_fabrikasi
) -> None:
    """`POSTING_STATUSES` TEK kopyadır ve özet de onu okur."""
    kasa, saticilar = await _iki_yaprak(hesap_fabrikasi)
    await fis_fabrikasi(
        [(kasa, "10.00", "0"), (saticilar, "0", "10.00")], status=JournalEntryStatus.draft
    )
    await fis_fabrikasi(
        [(kasa, "20.00", "0"), (saticilar, "0", "20.00")], status=JournalEntryStatus.reversed
    )
    resp = await client.get(f"{_YOL}/summary?year=2026&month=7", headers=muhasebe_headers)
    assert Decimal(resp.json()["total_debit"]) == Decimal("20.00")


async def test_summary_varsayilan_donem_BUGUNUN_ayidir(client, muhasebe_headers) -> None:
    """🔴 K6 sınır çağrısı: `timezone.today()` (`date.today()` DEĞİL)."""
    bugun = today()
    govde = (await client.get(f"{_YOL}/summary", headers=muhasebe_headers)).json()
    assert (govde["year"], govde["month"]) == (bugun.year, bugun.month)


async def test_summary_HESAP_SUZGECI_ALMAZ(
    client, muhasebe_headers, hesap_fabrikasi, fis_fabrikasi
) -> None:
    """E8:72 — KPI şeridi tablonun DIŞINDADIR ve yalnız DÖNEME bağlıdır.

    Hesap süzgeci bir PARAMETRE olarak yoktur; gönderilse bile toplamları
    DEĞİŞTİRMEZ. İddia tam olarak budur: aynı dönemde iki hesap varken tek
    hesabın kimliğini geçirmek yanıtı oynatmamalıdır.
    """
    kasa, saticilar = await _iki_yaprak(hesap_fabrikasi)
    await fis_fabrikasi([(kasa, "50.00", "0"), (saticilar, "0", "50.00")])

    suzgecsiz = await client.get(f"{_YOL}/summary?year=2026&month=7", headers=muhasebe_headers)
    suzgecli = await client.get(
        f"{_YOL}/summary?year=2026&month=7&account_id={kasa.id}", headers=muhasebe_headers
    )
    assert suzgecli.status_code == 200, suzgecli.text
    assert suzgecli.json() == suzgecsiz.json()


# --------------------------------------------------------------------------- #
# Yetki kapıları
# --------------------------------------------------------------------------- #


async def test_pm_okur_yazamaz(client, pm_headers, muhasebe_headers, hesap_fabrikasi) -> None:
    fis = await _fis_olustur(client, muhasebe_headers, hesap_fabrikasi)
    assert (await client.get(_YOL, headers=pm_headers)).status_code == 200
    assert (
        await client.patch(f"{_YOL}/{fis['id']}", json={"description": "X"}, headers=pm_headers)
    ).status_code == 403
    assert (await client.post(f"{_YOL}/{fis['id']}/post", headers=pm_headers)).status_code == 403


async def test_yetkisiz_rol_okumada_bile_403(client, yetkisiz_headers) -> None:
    assert (await client.get(_YOL, headers=yetkisiz_headers)).status_code == 403
    assert (await client.get(f"{_YOL}/summary", headers=yetkisiz_headers)).status_code == 403


# --------------------------------------------------------------------------- #
# Denetim
# --------------------------------------------------------------------------- #


async def test_denetim_YENI_UYE_ACMAZ_ve_TUTAR_metne_girmez(
    client, muhasebe_headers, hesap_fabrikasi, seeded_db
) -> None:
    """🔴 `post → approve`, `reverse → update`; ayrım METİNDEDİR.

    Tutar metne girseydi bakiye (TÜREV, K3) günlükte donmuş bir kopya olarak
    yaşar ve ilk düzeltmede ayrışırdı (`bank_account_*` kanonu).
    """
    fis = await _fis_olustur(client, muhasebe_headers, hesap_fabrikasi)
    await client.post(f"{_YOL}/{fis['id']}/post", headers=muhasebe_headers)
    await client.post(f"{_YOL}/{fis['id']}/reverse", headers=muhasebe_headers)

    kayitlar = (
        (await seeded_db.execute(select(AuditLog).order_by(AuditLog.occurred_at))).scalars().all()
    )
    yevmiye = [k for k in kayitlar if "fiş" in k.detail.lower() or "Fiş" in k.detail]
    eylemler = [k.action for k in yevmiye]
    assert AuditAction.create in eylemler
    assert AuditAction.approve in eylemler  # post
    assert AuditAction.update in eylemler  # reverse
    for kayit in yevmiye:
        assert "1000" not in kayit.detail, kayit.detail


async def test_GET_uclari_denetim_YAZMAZ(
    client, muhasebe_headers, hesap_fabrikasi, seeded_db
) -> None:
    await _fis_olustur(client, muhasebe_headers, hesap_fabrikasi)
    once = len((await seeded_db.execute(select(AuditLog))).scalars().all())
    await client.get(_YOL, headers=muhasebe_headers)
    await client.get(f"{_YOL}/summary", headers=muhasebe_headers)
    sonra = len((await seeded_db.execute(select(AuditLog))).scalars().all())
    assert once == sonra


# --------------------------------------------------------------------------- #
# Yapısal bekçi
# --------------------------------------------------------------------------- #


async def test_silinen_fisin_satirlari_da_gider(
    client, admin_headers, muhasebe_headers, hesap_fabrikasi, seeded_db
) -> None:
    """`journal_lines.entry_id` CASCADE'tir; satırın ömrü başlığa bağlıdır."""
    fis = await _fis_olustur(client, muhasebe_headers, hesap_fabrikasi)
    await client.delete(f"{_YOL}/{fis['id']}", headers=admin_headers)
    kalan = (
        await seeded_db.execute(select(JournalEntry).where(JournalEntry.id == uuid.UUID(fis["id"])))
    ).scalar_one_or_none()
    assert kalan is None
