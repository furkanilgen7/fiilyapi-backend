"""MU-1 T3a — hesap planı uçları (spec §7, yollar 1-5).

| # | Uç | İzin |
|---|---|---|
| 1 | `GET /chart-of-accounts` | `view` |
| 2 | `POST /chart-of-accounts` | `full` |
| 3 | `GET /chart-of-accounts/{id}` | `view` |
| 4 | `PATCH /chart-of-accounts/{id}` | `full` |
| 5 | `DELETE /chart-of-accounts/{id}` | **`admin`** |

## Bu dosyanın kilitlediği kararlar

1. **`balance` TÜRETİLİR** (K3) ve uçtan görünür. Saklanmadığı için hiçbir kolon
   onu doğrulamaz; `balance.py` çağrısı düşürülüp sabit `0` basılsaydı satırsız
   hesap testleri YİNE geçerdi — bu yüzden fişli hesap testi ZORUNLUDUR.
2. **`class_code` + `level` KODDAN türer** (K4/K15) ve gövdeden GELEMEZ (422).
3. **`limit` tavanı KIRPILMAZ, 422'dir** (K7).
4. **`DELETE` yalnız `admin`**; `full` (muhasebe) 403 alır — ön koşullu testtir:
   aynı kullanıcı PATCH'i GEÇER, yani 403 yetki seviyesinden gelir.
5. **DELETE 409** iki sebepten: fiş satırı VAR ya da ALT HESABI var. İkisi de
   SERVİS kararıdır — ham FK ihlalinin 500'ü kullanıcıya SIZMAZ.
6. 🔴 **K-Ş3 (§11):** fiş satırı OLAN hesabın altına çocuk açmak **409**dur.
   Yoksa `120`e satır atıp sonra `120.01` açmak yaprak kuralını GEÇMİŞE DÖNÜK
   delerdi ve MU-2 mizanı çift sayardı.
7. **PATCH `code` değişimi** yalnız hiç fiş satırı olmayan hesapta serbesttir;
   aksi hâlde tüm geçmiş yevmiye sessizce kayardı → **409**.
8. 🔴 **R3 — `Tür` (`account_type`) ile `Durum` (`is_active`) AYRI ŞEYLERDİR.**
   İkisi de Türkçe'de "aktif" okunur; süzgeçlerin karışmadığı ayrı bir testle
   kilitlenir.
9. **`q` süzgecinde LIKE jokeri KAÇIRILIR** (R15): `%` yazan kullanıcı TÜM
   hesapları görmemelidir.
"""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal

from sqlalchemy import event, select

from app.modules.accounting.models import ChartAccount, ChartAccountType
from app.modules.audit.models import AuditAction, AuditLog
from tests.conftest import test_engine

_YOL = "/chart-of-accounts"


@contextmanager
def _sorgu_sayaci() -> Iterator[list[str]]:
    """Sürücüye giden HER ifadeyi toplar — N+1 iddiasının ÖLÇÜM aracı."""
    ifadeler: list[str] = []

    def kaydet(conn, cursor, statement, parameters, context, executemany) -> None:  # noqa: ANN001
        ifadeler.append(" ".join(statement.split()))

    event.listen(test_engine.sync_engine, "before_cursor_execute", kaydet)
    try:
        yield ifadeler
    finally:
        event.remove(test_engine.sync_engine, "before_cursor_execute", kaydet)


def _govde(**ek) -> dict:
    """POST gövdesi — HP:58-62'nin DÖRT çizili sütunu (K-Ş1: alan İCAT EDİLMEZ)."""
    veri = {"code": "100", "name": "Kasa", "account_type": "asset"}
    veri.update(ek)
    return veri


# --------------------------------------------------------------------------- #
# Uç 1 — GET /chart-of-accounts
# --------------------------------------------------------------------------- #


async def test_liste_zarfi_ve_turetilmis_alanlar(
    client, muhasebe_headers, hesap_fabrikasi, fis_fabrikasi
) -> None:
    """🔴 K3 + K4: satır `balance` · `class_code` · `level` taşır.

    Kasa (Aktif) 1.000,00₺ borçlanır → bakiye **+1.000,00**. Sabit `0` basan ya
    da `balance.py`yi atlayan bir uygulama bu iddiada ölür.
    """
    kasa = await hesap_fabrikasi("100", name="Kasa", account_type=ChartAccountType.asset)
    satici = await hesap_fabrikasi("320", name="Satıcılar", account_type=ChartAccountType.liability)
    await fis_fabrikasi([(kasa, "1000.00", "0.00"), (satici, "0.00", "1000.00")])

    resp = await client.get(_YOL, headers=muhasebe_headers)

    assert resp.status_code == 200, resp.text
    govde = resp.json()
    assert set(govde) == {"items", "total", "limit", "offset"}
    assert govde["total"] == 2
    assert govde["limit"] == 50
    assert govde["offset"] == 0
    satir = govde["items"][0]
    assert satir["code"] == "100"
    assert satir["account_type"] == "asset"
    assert satir["is_active"] is True
    assert satir["class_code"] == "1"
    assert satir["level"] == 2
    assert Decimal(satir["balance"]) == Decimal("1000.00")
    # Pasif hesap ALACAK bakiyesini POZİTİF gösterir (K3 işaret kuralı).
    assert Decimal(govde["items"][1]["balance"]) == Decimal("1000.00")


async def test_liste_satirsiz_hesapta_bakiye_SIFIR_basar(
    client, muhasebe_headers, hesap_fabrikasi
) -> None:
    """NULL yutması: `SUM()` NULL döner; `COALESCE` düşerse hücre BOŞ basılır."""
    await hesap_fabrikasi("100")

    resp = await client.get(_YOL, headers=muhasebe_headers)

    assert resp.status_code == 200, resp.text
    assert Decimal(resp.json()["items"][0]["balance"]) == Decimal("0")


async def test_liste_kod_ARTAN_siralanir(client, muhasebe_headers, hesap_fabrikasi) -> None:
    """Sıralama `code ASC`tir ve hiyerarşiyi kendiliğinden üretir (HP tablosu):
    `10` · `100` · `12` · `120` · `120.01`."""
    for code in ["120.01", "10", "120", "100", "12"]:
        await hesap_fabrikasi(code)

    resp = await client.get(_YOL, headers=muhasebe_headers)

    assert [s["code"] for s in resp.json()["items"]] == ["10", "100", "12", "120", "120.01"]


async def test_liste_N_ARTI_1_YAPMAZ(client, muhasebe_headers, hesap_fabrikasi) -> None:
    """1 hesaplık liste ile 20 hesaplık listenin SORGU SAYISI eşittir.

    Hesap başına bakiye sorgusu koşan bir uygulama 20 hesapta patlar; tahminle
    değil `before_cursor_execute` sayacıyla ölçülür.
    """
    await hesap_fabrikasi("100")
    with _sorgu_sayaci() as ifadeler:
        resp = await client.get(_YOL, headers=muhasebe_headers)
    assert resp.status_code == 200, resp.text
    tek = len(ifadeler)

    for n in range(20):
        await hesap_fabrikasi(f"2{n:02d}")
    with _sorgu_sayaci() as ifadeler:
        resp = await client.get(_YOL, headers=muhasebe_headers)
    assert resp.status_code == 200, resp.text
    coklu = len(ifadeler)

    assert resp.json()["total"] == 21
    assert tek == coklu, f"N+1: 1 hesap {tek}, 21 hesap {coklu} sorgu"


# --- Süzgeçler ---


async def test_q_suzgeci_KOD_ve_AD_uzerinde_arar(client, muhasebe_headers, hesap_fabrikasi) -> None:
    """HP:47 tek kutudur; yalnız adda arasaydı kod yazan kullanıcı "hesap yok"
    sanısına düşerdi."""
    await hesap_fabrikasi("100", name="Kasa")
    await hesap_fabrikasi("320", name="Satıcılar")

    kod_ile = await client.get(_YOL, params={"q": "10"}, headers=muhasebe_headers)
    ad_ile = await client.get(_YOL, params={"q": "satıcı"}, headers=muhasebe_headers)

    assert [s["code"] for s in kod_ile.json()["items"]] == ["100"]
    assert [s["code"] for s in ad_ile.json()["items"]] == ["320"]


async def test_q_suzgecinde_LIKE_jokeri_KACIRILIR(
    client, muhasebe_headers, hesap_fabrikasi
) -> None:
    """🔴 R15: `%` yazan kullanıcı TÜM hesapları görmemelidir.

    Kaçırılmazsa `%` deseni `%%%` olur ve her satır eşleşir; iddia `total == 0`
    yerine `2` görür.
    """
    await hesap_fabrikasi("100", name="Kasa")
    await hesap_fabrikasi("320", name="Satıcılar")

    resp = await client.get(_YOL, params={"q": "%"}, headers=muhasebe_headers)
    alt_cizgi = await client.get(_YOL, params={"q": "_"}, headers=muhasebe_headers)

    assert resp.json()["total"] == 0
    assert alt_cizgi.json()["total"] == 0


async def test_q_suzgecinde_yuzde_ISARETI_ADIN_ICINDE_aranabilir(
    client, muhasebe_headers, hesap_fabrikasi
) -> None:
    """Kaçırma aramayı BOZMAZ: gerçekten `%` içeren ad bulunabilir olmalıdır."""
    await hesap_fabrikasi("191", name="İndirilecek KDV %20")
    await hesap_fabrikasi("100", name="Kasa")

    resp = await client.get(_YOL, params={"q": "%20"}, headers=muhasebe_headers)

    assert [s["code"] for s in resp.json()["items"]] == ["191"]


async def test_account_type_ve_is_active_suzgecleri_AYRI_seylerdir(
    client, muhasebe_headers, hesap_fabrikasi
) -> None:
    """🔴 R3 BEKÇİSİ — `Tür`ün "Aktif"i (HP:60) ile `Durum` (HP:62) KARIŞMAZ.

    Kurulum kasıtlı olarak çaprazdır: PASİF türlü ama DURUMU açık bir hesap ve
    AKTİF türlü ama durumu KAPALI bir hesap. İki süzgeç birbirine bağlansaydı
    (ya da biri ötekinin yerine geçseydi) iddiaların ikisi de kırmızıya döner.
    """
    await hesap_fabrikasi("100", account_type=ChartAccountType.asset, is_active=False)
    await hesap_fabrikasi("320", account_type=ChartAccountType.liability, is_active=True)

    tur_ile = await client.get(_YOL, params={"account_type": "asset"}, headers=muhasebe_headers)
    durum_ile = await client.get(_YOL, params={"is_active": "true"}, headers=muhasebe_headers)

    assert [s["code"] for s in tur_ile.json()["items"]] == ["100"]
    assert [s["code"] for s in durum_ile.json()["items"]] == ["320"]


async def test_suzgec_TOTAL_a_da_uygulanir(client, muhasebe_headers, hesap_fabrikasi) -> None:
    """`total` liste ile AYNI süzgeçten geçer; ayrışsaydı hesaplar "sayfa
    dışında kalmış" gibi görünürdü."""
    await hesap_fabrikasi("100", is_active=True)
    await hesap_fabrikasi("101", is_active=False)

    resp = await client.get(_YOL, params={"is_active": "false"}, headers=muhasebe_headers)

    assert resp.json()["total"] == 1


# --- K7: sayfalama sınırları ---


async def test_limit_tavani_KIRPILMAZ_422_doner(client, muhasebe_headers) -> None:
    """K7: 200 KABUL, 201 RET. Sessiz kırpma kullanıcıya eksik veriyi "tam" diye
    gösterirdi."""
    kabul = await client.get(_YOL, params={"limit": 200}, headers=muhasebe_headers)
    ret = await client.get(_YOL, params={"limit": 201}, headers=muhasebe_headers)

    assert kabul.status_code == 200, kabul.text
    assert ret.status_code == 422


async def test_limit_ve_offset_alt_sinirlari(client, muhasebe_headers) -> None:
    async def _kod(**params) -> int:
        return (await client.get(_YOL, params=params, headers=muhasebe_headers)).status_code

    assert await _kod(limit=0) == 422
    assert await _kod(offset=-1) == 422
    assert await _kod(offset=0) == 200


async def test_sayfalama_calisir(client, muhasebe_headers, hesap_fabrikasi) -> None:
    for code in ["100", "101", "102"]:
        await hesap_fabrikasi(code)

    resp = await client.get(_YOL, params={"limit": 2, "offset": 2}, headers=muhasebe_headers)

    govde = resp.json()
    assert govde["total"] == 3
    assert [s["code"] for s in govde["items"]] == ["102"]


# --- Yetki ---


async def test_liste_pm_okur_yetkisiz_403(
    client, pm_headers, yetkisiz_headers, hesap_fabrikasi
) -> None:
    await hesap_fabrikasi("100")

    assert (await client.get(_YOL, headers=pm_headers)).status_code == 200
    assert (await client.get(_YOL, headers=yetkisiz_headers)).status_code == 403


async def test_liste_okuma_denetim_satiri_YAZMAZ(
    client, muhasebe_headers, seeded_db, hesap_fabrikasi
) -> None:
    """WORKFLOW kuralı: `GET` uçları `record_audit` ÇAĞIRMAZ."""
    await hesap_fabrikasi("100")
    once = len((await seeded_db.execute(select(AuditLog))).scalars().all())

    await client.get(_YOL, headers=muhasebe_headers)

    sonra = len((await seeded_db.execute(select(AuditLog))).scalars().all())
    assert once == sonra


# --------------------------------------------------------------------------- #
# Uç 2 — POST /chart-of-accounts
# --------------------------------------------------------------------------- #


async def test_olustur_201_doner_ve_turev_alanlari_hesaplar(
    client, muhasebe_headers, seeded_db
) -> None:
    resp = await client.post(_YOL, json=_govde(code="120.01"), headers=muhasebe_headers)

    assert resp.status_code == 201, resp.text
    govde = resp.json()
    assert govde["code"] == "120.01"
    assert govde["class_code"] == "1"
    assert govde["level"] == 3
    assert Decimal(govde["balance"]) == Decimal("0")
    assert govde["is_active"] is True
    kayit = (
        await seeded_db.execute(select(ChartAccount).where(ChartAccount.code == "120.01"))
    ).scalar_one()
    assert kayit.name == "Kasa"


async def test_olustur_denetim_satiri_yazar_ve_TUTAR_ICERMEZ(
    client, muhasebe_headers, seeded_db
) -> None:
    """Yeni `AuditAction` üyesi AÇILMAZ (`create` kullanılır); ayrım metindedir.
    🔴 Tutar/bakiye metne GİRMEZ (HZ-1 kanonu)."""
    await client.post(_YOL, json=_govde(), headers=muhasebe_headers)

    kayitlar = (
        (await seeded_db.execute(select(AuditLog).where(AuditLog.action == AuditAction.create)))
        .scalars()
        .all()
    )
    metinler = [k.detail for k in kayitlar if "100" in (k.detail or "")]
    assert metinler, "hesap oluşturma denetim satırı yazılmadı"
    assert "Kasa" in metinler[0]
    assert "₺" not in metinler[0]


async def test_olustur_ayni_kod_409(client, muhasebe_headers, hesap_fabrikasi) -> None:
    """`uq_chart_of_accounts_code` servis katmanında ÖNCE yakalanır: aynı kod iki
    kez açılsaydı yevmiye satırları iki karta bölünür ve bakiye ikiye ayrılırdı."""
    await hesap_fabrikasi("100")

    resp = await client.post(_YOL, json=_govde(code="100"), headers=muhasebe_headers)

    assert resp.status_code == 409, resp.text
    assert "Veri bütünlüğü" not in resp.json()["detail"]


async def test_olustur_gecersiz_kod_422(client, muhasebe_headers) -> None:
    """🔴 Üçüncü kırılım ve sınıf kodu ŞEMADA reddedilir (DB CHECK son savunma)."""
    for kod in ["120.01.001", "1", "0120", "1200", "12.01"]:
        resp = await client.post(_YOL, json=_govde(code=kod), headers=muhasebe_headers)
        assert resp.status_code == 422, f"{kod} kabul edildi: {resp.text}"


async def test_olustur_ALTINCI_tur_reddedilir(client, muhasebe_headers) -> None:
    """K5 (MT-1'de DARALTILDI): enum hâlâ KAPALI bir kümedir.

    🔑 `equity` MT-1/KK-1 ile AÇILDI (kullanıcı kararı, 2026-08-16) — Bilanço
    `III. ÖZKAYNAKLAR` bölümü dört üyeyle ifade edilemiyordu; bugün **201**
    döner (aşağıdaki iddia). Küme yine de kapalıdır: `contra` bir TÜR değil
    `is_contra` bayrağıdır, nazım/maliyet hesaplarının hiçbir ekranda karşılığı
    yoktur."""
    kabul = await client.post(
        _YOL, json=_govde(code="500", account_type="equity"), headers=muhasebe_headers
    )
    assert kabul.status_code == 201, kabul.text
    assert kabul.json()["account_type"] == "equity"

    for yasak in ("memorandum", "cost", "contra", "other", "Aktif"):
        resp = await client.post(
            _YOL, json=_govde(code="501", account_type=yasak), headers=muhasebe_headers
        )
        assert resp.status_code == 422, f"{yasak} kabul edildi: {resp.text}"


async def test_olustur_TUREV_alan_govdede_422(client, muhasebe_headers) -> None:
    """🔴 `balance`/`class_code`/`level` gövdeden GELEMEZ.

    `extra="forbid"` olmasaydı Pydantic onları SESSİZCE atardı; istemci
    gönderdiği bakiyenin yazıldığını sanır, ekranda formülün ürettiği başka bir
    sayı görürdü.
    """
    turevler = [("balance", "500.00"), ("class_code", "9"), ("level", 1), ("id", str(uuid.uuid4()))]
    for alan, deger in turevler:
        resp = await client.post(_YOL, json=_govde(**{alan: deger}), headers=muhasebe_headers)
        assert resp.status_code == 422, f"{alan} sessizce yutuldu: {resp.text}"


async def test_olustur_yetki_full_gerektirir(client, pm_headers) -> None:
    """PM okur ama YAZAMAZ (`accounting=_V`)."""
    resp = await client.post(_YOL, json=_govde(), headers=pm_headers)
    assert resp.status_code == 403


async def test_FIS_SATIRI_OLAN_hesabin_altina_cocuk_acmak_409(
    client, muhasebe_headers, hesap_fabrikasi, fis_fabrikasi
) -> None:
    """🔴 K-Ş3 (§11) — yaprak kuralının TERS YÖNÜ.

    `120`e fiş satırı atıldıktan sonra `120.01` açmak, yaprak kuralını GEÇMİŞE
    DÖNÜK delerdi: `120`in bakiyesi hem kendi satırından hem çocuğunun
    satırından gelir ve MU-2 mizanı ÇİFT SAYARDI.
    """
    ebeveyn = await hesap_fabrikasi("120", account_type=ChartAccountType.asset)
    karsi = await hesap_fabrikasi("320", account_type=ChartAccountType.liability)
    await fis_fabrikasi([(ebeveyn, "500.00", "0.00"), (karsi, "0.00", "500.00")])

    resp = await client.post(_YOL, json=_govde(code="120.01"), headers=muhasebe_headers)

    assert resp.status_code == 409, resp.text


async def test_fis_satiri_OLMAYAN_hesabin_altina_cocuk_acilabilir(
    client, muhasebe_headers, hesap_fabrikasi
) -> None:
    """Kapı yalnız SATIRI OLAN ebeveyni kapatır; boş ebeveyn altına açmak
    normal iştir (aksi hâlde hesap planı hiç derinleşemezdi)."""
    await hesap_fabrikasi("120")

    resp = await client.post(_YOL, json=_govde(code="120.01"), headers=muhasebe_headers)

    assert resp.status_code == 201, resp.text


async def test_ebeveyni_HIC_OLMAYAN_kod_acilabilir(client, muhasebe_headers) -> None:
    """Ebeveyn kaydı ZORUNLU DEĞİLDİR: `NNN.NN` alt hesap `e5f6a7b8c9d0`
    tohumunda hiç yazılmaz (K2) ve test ortamı migration koşturmadığı için
    (`conftest.py` yalnız `create_all` yapar) `120` ana hesabı da yoktur —
    kullanıcı doğrudan `120.01` girebilir (R14). Zorunlu kılınsaydı hiçbir
    mockup'ın istemediği bir sıralama dayatılırdı."""
    resp = await client.post(_YOL, json=_govde(code="120.01"), headers=muhasebe_headers)
    assert resp.status_code == 201, resp.text


# --------------------------------------------------------------------------- #
# Uç 3 — GET /chart-of-accounts/{id}
# --------------------------------------------------------------------------- #


async def test_detay_bakiyeyi_liste_ile_AYNI_kaynaktan_alir(
    client, muhasebe_headers, hesap_fabrikasi, fis_fabrikasi
) -> None:
    kasa = await hesap_fabrikasi("100", account_type=ChartAccountType.asset)
    karsi = await hesap_fabrikasi("320", account_type=ChartAccountType.liability)
    await fis_fabrikasi([(kasa, "250.50", "0.00"), (karsi, "0.00", "250.50")])

    detay = await client.get(f"{_YOL}/{kasa.id}", headers=muhasebe_headers)
    liste = await client.get(_YOL, params={"q": "100"}, headers=muhasebe_headers)

    assert detay.status_code == 200, detay.text
    assert Decimal(detay.json()["balance"]) == Decimal("250.50")
    assert detay.json()["balance"] == liste.json()["items"][0]["balance"]


async def test_detay_olmayan_kimlik_404(client, muhasebe_headers) -> None:
    resp = await client.get(f"{_YOL}/{uuid.uuid4()}", headers=muhasebe_headers)
    assert resp.status_code == 404


# --------------------------------------------------------------------------- #
# Uç 4 — PATCH /chart-of-accounts/{id}
# --------------------------------------------------------------------------- #


async def test_patch_kismi_govde_diger_alanlari_EZMEZ(
    client, muhasebe_headers, hesap_fabrikasi, seeded_db
) -> None:
    """`exclude_unset` ŞARTTIR: yalnız adı düzelten bir istek türü ve durumu
    SESSİZCE ezmemelidir."""
    hesap = await hesap_fabrikasi(
        "320", name="Satıcılar", account_type=ChartAccountType.liability, is_active=False
    )

    resp = await client.patch(
        f"{_YOL}/{hesap.id}", json={"name": "Ticari Borçlar"}, headers=muhasebe_headers
    )

    assert resp.status_code == 200, resp.text
    govde = resp.json()
    assert govde["name"] == "Ticari Borçlar"
    assert govde["account_type"] == "liability"
    assert govde["is_active"] is False


async def test_patch_is_active_KALDIRMA_yoludur(
    client, muhasebe_headers, hesap_fabrikasi, fis_fabrikasi
) -> None:
    """Fiş satırı olan hesap SİLİNEMEZ; kaldırma yolu `is_active=false`tur."""
    hesap = await hesap_fabrikasi("100")
    karsi = await hesap_fabrikasi("320", account_type=ChartAccountType.liability)
    await fis_fabrikasi([(hesap, "10.00", "0.00"), (karsi, "0.00", "10.00")])

    resp = await client.patch(
        f"{_YOL}/{hesap.id}", json={"is_active": False}, headers=muhasebe_headers
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["is_active"] is False


async def test_patch_kod_degisimi_SATIRSIZ_hesapta_serbesttir(
    client, muhasebe_headers, hesap_fabrikasi
) -> None:
    hesap = await hesap_fabrikasi("100")

    resp = await client.patch(f"{_YOL}/{hesap.id}", json={"code": "101"}, headers=muhasebe_headers)

    assert resp.status_code == 200, resp.text
    assert resp.json()["code"] == "101"


async def test_patch_kod_degisimi_FIS_SATIRI_OLAN_hesapta_409(
    client, muhasebe_headers, hesap_fabrikasi, fis_fabrikasi
) -> None:
    """🔴 Aksi hâlde TÜM geçmiş yevmiye sessizce kayardı: satırlar `account_id`
    ile bağlıdır ama defter ve mizan KODU basar."""
    hesap = await hesap_fabrikasi("100")
    karsi = await hesap_fabrikasi("320", account_type=ChartAccountType.liability)
    await fis_fabrikasi([(hesap, "10.00", "0.00"), (karsi, "0.00", "10.00")])

    resp = await client.patch(f"{_YOL}/{hesap.id}", json={"code": "101"}, headers=muhasebe_headers)

    assert resp.status_code == 409, resp.text


async def test_patch_AYNI_kodu_yeniden_gondermek_satirli_hesapta_da_gecer(
    client, muhasebe_headers, hesap_fabrikasi, fis_fabrikasi
) -> None:
    """Kapı DEĞİŞİME bakar, gönderilmiş olmaya değil; aksi hâlde kullanıcı adı
    düzeltirken formun taşıdığı kodu geri gönderdiği için 409 alırdı."""
    hesap = await hesap_fabrikasi("100")
    karsi = await hesap_fabrikasi("320", account_type=ChartAccountType.liability)
    await fis_fabrikasi([(hesap, "10.00", "0.00"), (karsi, "0.00", "10.00")])

    resp = await client.patch(
        f"{_YOL}/{hesap.id}", json={"code": "100", "name": "Merkez Kasa"}, headers=muhasebe_headers
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "Merkez Kasa"


async def test_patch_baska_hesabin_kodu_409(client, muhasebe_headers, hesap_fabrikasi) -> None:
    await hesap_fabrikasi("100")
    hedef = await hesap_fabrikasi("101")

    resp = await client.patch(f"{_YOL}/{hedef.id}", json={"code": "100"}, headers=muhasebe_headers)

    assert resp.status_code == 409, resp.text


async def test_patch_kodu_SATIRLI_ebeveynin_altina_tasimak_409(
    client, muhasebe_headers, hesap_fabrikasi, fis_fabrikasi
) -> None:
    """K-Ş3 PATCH yolunda da geçerlidir: kural yalnız POST'ta olsaydı aynı
    delik `code` düzeltmesiyle açılırdı."""
    ebeveyn = await hesap_fabrikasi("120")
    karsi = await hesap_fabrikasi("320", account_type=ChartAccountType.liability)
    await fis_fabrikasi([(ebeveyn, "500.00", "0.00"), (karsi, "0.00", "500.00")])
    tasinacak = await hesap_fabrikasi("153.01")

    resp = await client.patch(
        f"{_YOL}/{tasinacak.id}", json={"code": "120.01"}, headers=muhasebe_headers
    )

    assert resp.status_code == 409, resp.text


async def test_patch_TUREV_alan_govdede_422(client, muhasebe_headers, hesap_fabrikasi) -> None:
    hesap = await hesap_fabrikasi("100")

    resp = await client.patch(
        f"{_YOL}/{hesap.id}", json={"balance": "999.00"}, headers=muhasebe_headers
    )

    assert resp.status_code == 422


async def test_patch_olmayan_kimlik_404(client, muhasebe_headers) -> None:
    resp = await client.patch(
        f"{_YOL}/{uuid.uuid4()}", json={"name": "X"}, headers=muhasebe_headers
    )
    assert resp.status_code == 404


async def test_patch_yetki_full_gerektirir(client, pm_headers, hesap_fabrikasi) -> None:
    hesap = await hesap_fabrikasi("100")
    resp = await client.patch(f"{_YOL}/{hesap.id}", json={"name": "X"}, headers=pm_headers)
    assert resp.status_code == 403


async def test_patch_denetim_satiri_yazar(
    client, muhasebe_headers, hesap_fabrikasi, seeded_db
) -> None:
    """Metin GÜNCELLENMİŞ değerlerle kurulur; yoksa satır neyin ne olduğunu
    anlatmaz."""
    hesap = await hesap_fabrikasi("100", name="Kasa")

    await client.patch(f"{_YOL}/{hesap.id}", json={"name": "Merkez Kasa"}, headers=muhasebe_headers)

    kayitlar = (
        (await seeded_db.execute(select(AuditLog).where(AuditLog.action == AuditAction.update)))
        .scalars()
        .all()
    )
    assert any("Merkez Kasa" in (k.detail or "") for k in kayitlar)


# --------------------------------------------------------------------------- #
# Uç 5 — DELETE /chart-of-accounts/{id}
# --------------------------------------------------------------------------- #


async def test_silme_YALNIZ_admin_204(client, admin_headers, hesap_fabrikasi, seeded_db) -> None:
    hesap = await hesap_fabrikasi("100")

    resp = await client.delete(f"{_YOL}/{hesap.id}", headers=admin_headers)

    assert resp.status_code == 204, resp.text
    assert resp.content == b""
    kalan = (
        await seeded_db.execute(select(ChartAccount).where(ChartAccount.id == hesap.id))
    ).scalar_one_or_none()
    assert kalan is None


async def test_silme_full_seviyesinde_403_ama_ayni_kullanici_PATCH_gecer(
    client, muhasebe_headers, hesap_fabrikasi
) -> None:
    """🔴 Ön koşullu test: 403 YETKİ SEVİYESİNDEN gelir, kaydın erişilemezliğinden
    değil. `full` silmeyi KAPSAMAZ (repo kanonu)."""
    hesap = await hesap_fabrikasi("100")

    patch = await client.patch(f"{_YOL}/{hesap.id}", json={"name": "X"}, headers=muhasebe_headers)
    silme = await client.delete(f"{_YOL}/{hesap.id}", headers=muhasebe_headers)

    assert patch.status_code == 200, patch.text
    assert silme.status_code == 403


async def test_silme_FIS_SATIRI_olan_hesapta_409(
    client, admin_headers, hesap_fabrikasi, fis_fabrikasi
) -> None:
    """Ham FK RESTRICT ihlalinin 500'ü (ya da ayrımsız "Veri bütünlüğü hatası")
    kullanıcıya SIZMAZ — denetim SERVİSTEDİR."""
    hesap = await hesap_fabrikasi("100")
    karsi = await hesap_fabrikasi("320", account_type=ChartAccountType.liability)
    await fis_fabrikasi([(hesap, "10.00", "0.00"), (karsi, "0.00", "10.00")])

    resp = await client.delete(f"{_YOL}/{hesap.id}", headers=admin_headers)

    assert resp.status_code == 409, resp.text
    assert "Veri bütünlüğü" not in resp.json()["detail"]


async def test_silme_ALT_HESABI_olan_hesapta_409(client, admin_headers, hesap_fabrikasi) -> None:
    """Ebeveyn silinseydi `120.01` sahipsiz kalır ve hiyerarşi (kodun içinde
    taşındığı için) sessizce kopardı."""
    ebeveyn = await hesap_fabrikasi("120")
    await hesap_fabrikasi("120.01")

    resp = await client.delete(f"{_YOL}/{ebeveyn.id}", headers=admin_headers)

    assert resp.status_code == 409, resp.text


async def test_silme_TORUNU_olan_grubu_da_409(client, admin_headers, hesap_fabrikasi) -> None:
    """Önek TORUNLARI da kapsar: çocuğu silinmiş ama torunu duran bir grup
    "yapraksız" sayılmamalıdır."""
    grup = await hesap_fabrikasi("12")
    await hesap_fabrikasi("120.01")

    resp = await client.delete(f"{_YOL}/{grup.id}", headers=admin_headers)

    assert resp.status_code == 409, resp.text


async def test_silme_olmayan_kimlik_404(client, admin_headers) -> None:
    resp = await client.delete(f"{_YOL}/{uuid.uuid4()}", headers=admin_headers)
    assert resp.status_code == 404


async def test_silme_denetim_satiri_KAYIT_YOK_OLMADAN_ONCE_kurulur(
    client, admin_headers, hesap_fabrikasi, seeded_db
) -> None:
    hesap = await hesap_fabrikasi("100", name="Kasa")

    resp = await client.delete(f"{_YOL}/{hesap.id}", headers=admin_headers)

    assert resp.status_code == 204, resp.text
    kayitlar = (
        (await seeded_db.execute(select(AuditLog).where(AuditLog.action == AuditAction.delete)))
        .scalars()
        .all()
    )
    assert any("Kasa" in (k.detail or "") for k in kayitlar)


# --------------------------------------------------------------------------- #
# Rota sırası (R11) — bugün literal yol YOKTUR, bekçi ileride korur
# --------------------------------------------------------------------------- #


async def test_rota_sirasi_chart_of_accounts_literal_yol_YOKTUR(client, muhasebe_headers) -> None:
    """`/chart-of-accounts/{account_id}` UUID rotasıyla çakışacak iki segmentli
    LİTERAL bir yol bu dilimde YOKTUR; eklenecek olan HER biri onun ÜSTÜNE
    konmalıdır (MK-2 dersi). Bekçi: literal bir segment bugün 422 verir.
    """
    resp = await client.get(f"{_YOL}/summary", headers=muhasebe_headers)
    assert resp.status_code == 422
