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

🔴 **BÖLÜNDÜ (800 satır tavanı):** dosya 821 satıra çıkmıştı. Aynı uç ailesinin
üç parçası artık üç dosyadadır ve HİÇBİR testin iddiası değişmedi:

* bu dosya — `POST` · liste/detay · rota sırası · `PATCH` · `PUT lines`;
* `test_mu1_journal_state.py` — `DELETE` · `POST /post` · storno (durum makinesi);
* `test_mu1_journal_summary.py` — `summary` · izin · denetim · kalıntı.

Paylaşılan gövde kurucuları `_journal.py`dedir.
"""

import uuid
from decimal import Decimal

from app.core.text import FREE_TEXT_MAX_LENGTH
from app.modules.accounting import guards, validation
from tests.modules.accounting._journal import TARIH as _TARIH
from tests.modules.accounting._journal import YOL as _YOL
from tests.modules.accounting._journal import fis_olustur as _fis_olustur
from tests.modules.accounting._journal import govde as _govde
from tests.modules.accounting._journal import iki_yaprak as _iki_yaprak
from tests.modules.accounting._journal import satir as _satir

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
