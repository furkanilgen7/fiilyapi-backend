"""HZ-1 T3 — banka hesabı uçları (spec §4, uçlar 1-5).

| # | Uç | İzin |
|---|---|---|
| 1 | `GET /bank-accounts` | `view` |
| 2 | `POST /bank-accounts` | `full` |
| 3 | `GET /bank-accounts/{id}` | `view` |
| 4 | `PATCH /bank-accounts/{id}` | `full` |
| 5 | `DELETE /bank-accounts/{id}` | **`admin`** |

## Bu dosyanın kilitlediği kararlar

1. **`balance` TÜRETİLİR** (K2) ve uçtan görünür. Saklanmadığı için hiçbir kolon
   onu doğrulamaz: uçtan okunan sayının `opening_balance ± Σ payments` olduğunu
   kanıtlayan tek şey buradaki iddialardır. `balance.py` çağrısı düşürülüp yerine
   `opening_balance` basılsaydı ödemesiz hesap testleri YİNE geçerdi — bu yüzden
   ödemeli hesap testi ZORUNLUDUR.
2. **Liste N+1 YAPMAZ.** 1 hesap ile 20 hesabın sorgu sayısı `before_cursor_execute`
   sayacıyla KARŞILAŞTIRILIR (T2/`test_hz1_balance` emsali) — tahmine dayanmaz.
3. **`limit` tavanı KIRPILMAZ, 422'dir** (TB3 kanonu).
4. **`DELETE` yalnız `admin`**; `full` (muhasebe) 403 alır — ön koşullu testtir:
   aynı kullanıcı PATCH'i GEÇER, yani 403 yetki seviyesinden gelir, hesabın
   erişilemezliğinden değil.
5. **Ödemesi olan hesap 409** ve bu SERVİS kararıdır: ham FK ihlalinin 500'ü (ya
   da `IntegrityError` handler'ının "Veri bütünlüğü hatası" 409'u) kullanıcıya
   SIZMAZ. ⚠️ SQLSTATE'e dayanan iddia YAZILMAZ (yerel PG18 / CI PG16 farkı).
6. **Kısmi UNIQUE:** iki Kasa NULL IBAN'la açılabilir; aynı IBAN 409'dur ve
   BOŞLUK/HARF farkı bu kapıyı ATLATAMAZ (normalize edilir).
7. **`ck_bank_accounts_cash_has_name` servis katmanında 422** ile ÖNCE yakalanır;
   PATCH yolunda da (tipi `cash`e çevirip adı boş bırakmak) geçerlidir.
8. **Görünmeyen/olmayan kayıt 404** — K3 gereği "görünmeyen" hâli yoktur, hesap
   şirket genelidir; 404 yalnız var olmayan kimlik içindir.
"""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal

from sqlalchemy import event, select

from app.modules.audit.models import AuditAction, AuditLog
from app.modules.invoicing.models import InvoiceDirection
from app.modules.treasury.models import BankAccount, BankAccountType
from tests.conftest import test_engine

_YOL = "/bank-accounts"


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


def _kasa(**ek) -> dict:
    govde = {"bank_name": "Merkez", "account_type": "cash", "display_name": "Merkez Kasa"}
    govde.update(ek)
    return govde


# --------------------------------------------------------------------------- #
# Uç 1 — GET /bank-accounts
# --------------------------------------------------------------------------- #


async def test_liste_zarfi_ve_turetilmis_bakiye(
    client, muhasebe_headers, hesap_fabrikasi, odeme_fabrikasi
) -> None:
    """🔴 K2: `balance` = `opening_balance` + tahsilat − ödeme.

    Hesap açılışta 1.000,00₺; giden faturaya 250,00₺ tahsilat (GİRİŞ), gelen
    faturaya 100,00₺ ödeme (ÇIKIŞ) → 1.150,00₺. `opening_balance` basan bir
    uygulama 1.000,00 döner ve bu iddia ölür.
    """
    hesap = await hesap_fabrikasi(opening_balance="1000.00")
    await odeme_fabrikasi(hesap, "250.00", InvoiceDirection.outgoing)
    await odeme_fabrikasi(hesap, "100.00", InvoiceDirection.incoming)

    resp = await client.get(_YOL, headers=muhasebe_headers)
    assert resp.status_code == 200, resp.text
    govde = resp.json()
    assert set(govde) == {"items", "total", "limit", "offset"}
    assert govde["total"] == 1
    assert govde["limit"] == 50
    assert govde["offset"] == 0
    (satir,) = govde["items"]
    assert satir["id"] == str(hesap.id)
    assert Decimal(satir["balance"]) == Decimal("1150.00")
    assert Decimal(satir["opening_balance"]) == Decimal("1000.00")


async def test_liste_odemesiz_hesapta_bakiye_acilis_bakiyesidir(
    client, muhasebe_headers, hesap_fabrikasi
) -> None:
    """NULL yutması: `SUM()` NULL döner; `coalesce` düşerse bakiye BOŞ basılır."""
    await hesap_fabrikasi(opening_balance="500.00")
    resp = await client.get(_YOL, headers=muhasebe_headers)
    assert resp.status_code == 200, resp.text
    assert Decimal(resp.json()["items"][0]["balance"]) == Decimal("500.00")


async def test_liste_is_active_suzgeci_total_ile_TUTARLI(
    client, muhasebe_headers, hesap_fabrikasi
) -> None:
    """Süzgeç `total`a da uygulanır: pasif hesap "sayfa dışında" bile görünmez."""
    await hesap_fabrikasi(bank_name="Aktif Bank")
    await hesap_fabrikasi(bank_name="Kapalı Bank", is_active=False)

    hepsi = await client.get(_YOL, headers=muhasebe_headers)
    assert hepsi.json()["total"] == 2

    aktif = await client.get(_YOL, headers=muhasebe_headers, params={"is_active": "true"})
    assert aktif.status_code == 200, aktif.text
    assert aktif.json()["total"] == 1
    assert aktif.json()["items"][0]["bank_name"] == "Aktif Bank"

    pasif = await client.get(_YOL, headers=muhasebe_headers, params={"is_active": "false"})
    assert pasif.json()["total"] == 1
    assert pasif.json()["items"][0]["bank_name"] == "Kapalı Bank"


async def test_liste_limit_tavani_asimi_KIRPILMAZ_422(client, muhasebe_headers) -> None:
    resp = await client.get(_YOL, headers=muhasebe_headers, params={"limit": 201})
    assert resp.status_code == 422, resp.text


async def test_liste_limit_alt_siniri_422(client, muhasebe_headers) -> None:
    resp = await client.get(_YOL, headers=muhasebe_headers, params={"limit": 0})
    assert resp.status_code == 422, resp.text


async def test_liste_negatif_offset_422(client, muhasebe_headers) -> None:
    resp = await client.get(_YOL, headers=muhasebe_headers, params={"offset": -1})
    assert resp.status_code == 422, resp.text


async def test_liste_offset_sayfalar_ve_total_TAM_sayidir(
    client, muhasebe_headers, hesap_fabrikasi
) -> None:
    for sira in range(3):
        await hesap_fabrikasi(bank_name=f"Bank {sira}")
    resp = await client.get(_YOL, headers=muhasebe_headers, params={"limit": 2, "offset": 2})
    assert resp.status_code == 200, resp.text
    govde = resp.json()
    assert govde["total"] == 3
    assert len(govde["items"]) == 1
    assert govde["offset"] == 2


async def test_liste_N_ARTI_1_YAPMAZ(
    client, muhasebe_headers, hesap_fabrikasi, odeme_fabrikasi
) -> None:
    """1 hesap ile 20 hesabın SORGU SAYISI eşit olmalıdır (T2 kanonu).

    Hesap başına `balances_for` çağıran bir uygulama 3 kartta fark ettirmez,
    20 hesapta patlar.
    """
    hesap = await hesap_fabrikasi(bank_name="Tek Bank", opening_balance="10.00")
    await odeme_fabrikasi(hesap, "5.00")
    with _sorgu_sayaci() as tek:
        resp = await client.get(_YOL, headers=muhasebe_headers)
        assert resp.status_code == 200, resp.text
    tek_sayi = len(tek)

    for sira in range(19):
        await hesap_fabrikasi(bank_name=f"Bank {sira}", opening_balance="10.00")
    with _sorgu_sayaci() as cok:
        resp = await client.get(_YOL, headers=muhasebe_headers)
        assert resp.status_code == 200, resp.text
        assert len(resp.json()["items"]) == 20

    assert len(cok) == tek_sayi, f"N+1: 1 hesapta {tek_sayi}, 20 hesapta {len(cok)} sorgu"


async def test_liste_yetkisiz_rol_403(client, yetkisiz_headers) -> None:
    resp = await client.get(_YOL, headers=yetkisiz_headers)
    assert resp.status_code == 403, resp.text


async def test_liste_kimliksiz_401(client) -> None:
    resp = await client.get(_YOL)
    assert resp.status_code == 401, resp.text


# --------------------------------------------------------------------------- #
# Uç 2 — POST /bank-accounts
# --------------------------------------------------------------------------- #


async def test_olusturma_201_ve_bakiye_acilistan(client, muhasebe_headers) -> None:
    resp = await client.post(
        _YOL,
        headers=muhasebe_headers,
        json={
            "bank_name": "Ziraat Bank",
            "account_type": "checking",
            "iban": "TR330006100519786457841326",
            "opening_balance": "2500.50",
        },
    )
    assert resp.status_code == 201, resp.text
    govde = resp.json()
    assert govde["account_type"] == "checking"
    assert govde["is_active"] is True
    assert Decimal(govde["balance"]) == Decimal("2500.50")


async def test_olusturma_denetim_satiri_yazar(
    client, muhasebe_headers, seeded_db, kullanici_kimligi
) -> None:
    """Yeni `AuditAction` üyesi AÇILMAZ (TB3/T3 kanonu): mevcut `create` + metin."""
    resp = await client.post(_YOL, headers=muhasebe_headers, json=_kasa(bank_name="Merkez Ofis"))
    assert resp.status_code == 201, resp.text
    kayitlar = (
        (await seeded_db.execute(select(AuditLog).where(AuditLog.action == AuditAction.create)))
        .scalars()
        .all()
    )
    assert any("Merkez Kasa" in (k.detail or "") for k in kayitlar), [k.detail for k in kayitlar]
    aktor = await kullanici_kimligi("muhasebe@hazine.co")
    assert all(k.actor_user_id == aktor for k in kayitlar)


async def test_olusturma_view_rolu_403(client, pm_headers) -> None:
    resp = await client.post(_YOL, headers=pm_headers, json=_kasa())
    assert resp.status_code == 403, resp.text


async def test_iki_kasa_NULL_IBAN_ile_acilabilir(client, muhasebe_headers) -> None:
    """🔴 Kısmi UNIQUE (`WHERE iban IS NOT NULL`): NULL'lar çoklanabilir.

    İndeks kısmi olmasaydı İKİNCİ kasa hiç açılamazdı — bu iddia `postgresql_where`
    kaldırıldığında KIRMIZI olur.
    """
    ilk = await client.post(_YOL, headers=muhasebe_headers, json=_kasa(display_name="Merkez Kasa"))
    assert ilk.status_code == 201, ilk.text
    ikinci = await client.post(
        _YOL, headers=muhasebe_headers, json=_kasa(display_name="Şantiye Kasası")
    )
    assert ikinci.status_code == 201, ikinci.text
    assert ilk.json()["iban"] is None and ikinci.json()["iban"] is None


async def test_ayni_IBAN_409(client, muhasebe_headers) -> None:
    govde = {
        "bank_name": "İş Bank",
        "account_type": "checking",
        "iban": "TR120006400000112345678901",
    }
    assert (await client.post(_YOL, headers=muhasebe_headers, json=govde)).status_code == 201
    resp = await client.post(_YOL, headers=muhasebe_headers, json=govde)
    assert resp.status_code == 409, resp.text
    assert "Veri bütünlüğü hatası" not in resp.json()["detail"]


async def test_IBAN_bosluk_ve_harf_farki_kapiyi_ATLATAMAZ_409(client, muhasebe_headers) -> None:
    """Normalize edilmeseydi `TR12 0006…` ile `TR120006…` İKİ AYRI hesap olurdu
    ve tekillik kuralı sessizce anlamsızlaşırdı."""
    assert (
        await client.post(
            _YOL,
            headers=muhasebe_headers,
            json={
                "bank_name": "İş Bank",
                "account_type": "checking",
                "iban": "TR120006400000112345678901",
            },
        )
    ).status_code == 201
    resp = await client.post(
        _YOL,
        headers=muhasebe_headers,
        json={
            "bank_name": "İş Bank",
            "account_type": "checking",
            "iban": "tr12 0006 4000 0011 2345 6789 01",
        },
    )
    assert resp.status_code == 409, resp.text


async def test_IBAN_bosluklu_girilse_de_SIKISTIRILMIS_saklanir(client, muhasebe_headers) -> None:
    resp = await client.post(
        _YOL,
        headers=muhasebe_headers,
        json={
            "bank_name": "Yapı Kredi",
            "account_type": "checking",
            "iban": "tr98 0006 4000 0011 2345 6789 02",
        },
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["iban"] == "TR980006400000112345678902"


async def test_kasa_adsiz_422_ve_kayit_ACILMAZ(client, muhasebe_headers, seeded_db) -> None:
    """🔴 `ck_bank_accounts_cash_has_name` SERVİSTE önce yakalanır.

    DB CHECK'ine düşseydi kullanıcı 409 "Veri bütünlüğü hatası" alır ve HANGİ
    alanı doldurması gerektiğini öğrenemezdi.
    """
    resp = await client.post(
        _YOL, headers=muhasebe_headers, json={"bank_name": "Merkez", "account_type": "cash"}
    )
    assert resp.status_code == 422, resp.text
    assert (await seeded_db.execute(select(BankAccount))).scalars().all() == []


async def test_kasa_bos_isimli_422(client, muhasebe_headers) -> None:
    resp = await client.post(
        _YOL,
        headers=muhasebe_headers,
        json={"bank_name": "Merkez", "account_type": "cash", "display_name": "   "},
    )
    assert resp.status_code == 422, resp.text


async def test_vadesiz_hesap_adsiz_acilabilir(client, muhasebe_headers) -> None:
    """Kural YALNIZ `cash` içindir: vadesizde banka adı zaten basılır."""
    resp = await client.post(
        _YOL,
        headers=muhasebe_headers,
        json={"bank_name": "Ziraat Bank", "account_type": "checking"},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["display_name"] is None


async def test_govdede_TURETILMIS_ve_bilinmeyen_alanlar_422(client, muhasebe_headers) -> None:
    """`balance` TÜREVDİR: sessizce yok sayılsaydı istemci gönderdiği bakiyenin
    yazıldığını sanırdı."""
    for alan, deger in (("balance", "999.00"), ("id", str(uuid.uuid4())), ("bilinmeyen", "x")):
        resp = await client.post(_YOL, headers=muhasebe_headers, json=_kasa(**{alan: deger}))
        assert resp.status_code == 422, f"{alan} sessizce yok sayıldı: {resp.text}"


async def test_gecersiz_hesap_tipi_422(client, muhasebe_headers) -> None:
    """🔴 K1: `savings`/`credit`/`pos` İCAT EDİLMEZ — kapalı küme ikidir."""
    resp = await client.post(
        _YOL, headers=muhasebe_headers, json={"bank_name": "X Bank", "account_type": "savings"}
    )
    assert resp.status_code == 422, resp.text


# --------------------------------------------------------------------------- #
# Uç 3 — GET /bank-accounts/{id}
# --------------------------------------------------------------------------- #


async def test_detay_turetilmis_bakiye_ile_doner(
    client, pm_headers, hesap_fabrikasi, odeme_fabrikasi
) -> None:
    hesap = await hesap_fabrikasi(opening_balance="100.00")
    await odeme_fabrikasi(hesap, "40.00", InvoiceDirection.incoming)
    resp = await client.get(f"{_YOL}/{hesap.id}", headers=pm_headers)
    assert resp.status_code == 200, resp.text
    assert Decimal(resp.json()["balance"]) == Decimal("60.00")


async def test_detay_olmayan_kayit_404(client, muhasebe_headers) -> None:
    resp = await client.get(f"{_YOL}/{uuid.uuid4()}", headers=muhasebe_headers)
    assert resp.status_code == 404, resp.text


async def test_detay_yetkisiz_rol_403(client, yetkisiz_headers, hesap_fabrikasi) -> None:
    hesap = await hesap_fabrikasi()
    resp = await client.get(f"{_YOL}/{hesap.id}", headers=yetkisiz_headers)
    assert resp.status_code == 403, resp.text


# --------------------------------------------------------------------------- #
# Uç 4 — PATCH /bank-accounts/{id}
# --------------------------------------------------------------------------- #


async def test_patch_acilis_bakiyesi_degisince_bakiye_YENIDEN_turetilir(
    client, muhasebe_headers, hesap_fabrikasi, odeme_fabrikasi
) -> None:
    """Elle düzeltme meşrudur (spec §4 md.4) ve bakiye kendiliğinden yenilenir."""
    hesap = await hesap_fabrikasi(opening_balance="100.00")
    await odeme_fabrikasi(hesap, "25.00", InvoiceDirection.outgoing)
    resp = await client.patch(
        f"{_YOL}/{hesap.id}", headers=muhasebe_headers, json={"opening_balance": "300.00"}
    )
    assert resp.status_code == 200, resp.text
    assert Decimal(resp.json()["balance"]) == Decimal("325.00")


async def test_patch_pasiflestirme(client, muhasebe_headers, hesap_fabrikasi) -> None:
    hesap = await hesap_fabrikasi()
    resp = await client.patch(
        f"{_YOL}/{hesap.id}", headers=muhasebe_headers, json={"is_active": False}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["is_active"] is False


async def test_patch_tipi_kasaya_cevirip_adi_BOS_birakmak_422(
    client, muhasebe_headers, hesap_fabrikasi
) -> None:
    """🔴 Kural BİRLEŞİK değerler üzerinde koşar: kullanıcı yalnız `account_type`
    gönderse bile kayıttaki `display_name` NULL'dır ve kasa adsız kalırdı."""
    hesap = await hesap_fabrikasi(account_type=BankAccountType.checking, display_name=None)
    resp = await client.patch(
        f"{_YOL}/{hesap.id}", headers=muhasebe_headers, json={"account_type": "cash"}
    )
    assert resp.status_code == 422, resp.text


async def test_patch_tipi_kasaya_cevirirken_ad_verilirse_gecer(
    client, muhasebe_headers, hesap_fabrikasi
) -> None:
    hesap = await hesap_fabrikasi(account_type=BankAccountType.checking, display_name=None)
    resp = await client.patch(
        f"{_YOL}/{hesap.id}",
        headers=muhasebe_headers,
        json={"account_type": "cash", "display_name": "Şantiye Kasası"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["display_name"] == "Şantiye Kasası"


async def test_patch_kasanin_adini_NULL_yapmak_422(
    client, muhasebe_headers, hesap_fabrikasi
) -> None:
    hesap = await hesap_fabrikasi(
        account_type=BankAccountType.cash, iban=None, display_name="Merkez Kasa"
    )
    resp = await client.patch(
        f"{_YOL}/{hesap.id}", headers=muhasebe_headers, json={"display_name": None}
    )
    assert resp.status_code == 422, resp.text


async def test_patch_baska_hesabin_IBANI_409(client, muhasebe_headers, hesap_fabrikasi) -> None:
    await hesap_fabrikasi(iban="TR120006400000112345678901")
    hedef = await hesap_fabrikasi(iban="TR120006400000112345678902")
    resp = await client.patch(
        f"{_YOL}/{hedef.id}",
        headers=muhasebe_headers,
        json={"iban": "TR120006400000112345678901"},
    )
    assert resp.status_code == 409, resp.text


async def test_patch_KENDI_ibanini_yeniden_gondermek_200(
    client, muhasebe_headers, hesap_fabrikasi
) -> None:
    """Tekillik denetimi KAYDIN KENDİSİNİ dışlamalıdır; dışlamasaydı kullanıcı
    yalnızca banka adını düzeltirken 409 alırdı."""
    hesap = await hesap_fabrikasi(iban="TR120006400000112345678903")
    resp = await client.patch(
        f"{_YOL}/{hesap.id}",
        headers=muhasebe_headers,
        json={"iban": "TR120006400000112345678903", "bank_name": "Yapı Kredi"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["bank_name"] == "Yapı Kredi"


async def test_patch_bos_govde_kaydi_BOZMAZ(client, muhasebe_headers, hesap_fabrikasi) -> None:
    hesap = await hesap_fabrikasi(bank_name="Ziraat Bank", opening_balance="7.00")
    resp = await client.patch(f"{_YOL}/{hesap.id}", headers=muhasebe_headers, json={})
    assert resp.status_code == 200, resp.text
    assert resp.json()["bank_name"] == "Ziraat Bank"
    assert Decimal(resp.json()["opening_balance"]) == Decimal("7.00")


async def test_patch_olmayan_kayit_404(client, muhasebe_headers) -> None:
    resp = await client.patch(
        f"{_YOL}/{uuid.uuid4()}", headers=muhasebe_headers, json={"bank_name": "X"}
    )
    assert resp.status_code == 404, resp.text


async def test_patch_view_rolu_403(client, pm_headers, hesap_fabrikasi) -> None:
    hesap = await hesap_fabrikasi()
    resp = await client.patch(
        f"{_YOL}/{hesap.id}", headers=pm_headers, json={"bank_name": "X Bank"}
    )
    assert resp.status_code == 403, resp.text


async def test_patch_denetim_satiri_yazar(
    client, muhasebe_headers, hesap_fabrikasi, seeded_db
) -> None:
    hesap = await hesap_fabrikasi(bank_name="Ziraat Bank")
    resp = await client.patch(
        f"{_YOL}/{hesap.id}", headers=muhasebe_headers, json={"bank_name": "Yapı Kredi"}
    )
    assert resp.status_code == 200, resp.text
    kayitlar = (
        (await seeded_db.execute(select(AuditLog).where(AuditLog.action == AuditAction.update)))
        .scalars()
        .all()
    )
    assert any("Yapı Kredi" in (k.detail or "") for k in kayitlar), [k.detail for k in kayitlar]


# --------------------------------------------------------------------------- #
# Uç 5 — DELETE /bank-accounts/{id}
# --------------------------------------------------------------------------- #


async def test_delete_admin_204(client, admin_headers, hesap_fabrikasi, seeded_db) -> None:
    hesap = await hesap_fabrikasi()
    resp = await client.delete(f"{_YOL}/{hesap.id}", headers=admin_headers)
    assert resp.status_code == 204, resp.text
    assert (await seeded_db.execute(select(BankAccount))).scalars().all() == []


async def test_delete_FULL_rolu_403_ama_ayni_kullanici_PATCH_gecer(
    client, muhasebe_headers, hesap_fabrikasi
) -> None:
    """🔴 Ön koşullu test: `full` silmeyi KAPSAMAZ (repo kanonu).

    Aynı başlıkla PATCH'in geçtiği ÖNCE gösterilir; yoksa 403 "muhasebe bu
    hesabı hiç göremiyor" diye de okunabilirdi ve iddia hiçbir şey kanıtlamazdı.
    """
    hesap = await hesap_fabrikasi()
    on_kosul = await client.patch(
        f"{_YOL}/{hesap.id}", headers=muhasebe_headers, json={"bank_name": "Yapı Kredi"}
    )
    assert on_kosul.status_code == 200, on_kosul.text

    resp = await client.delete(f"{_YOL}/{hesap.id}", headers=muhasebe_headers)
    assert resp.status_code == 403, resp.text


async def test_delete_odemesi_olan_hesap_409_ve_HAM_hata_SIZMAZ(
    client, admin_headers, hesap_fabrikasi, odeme_fabrikasi, seeded_db
) -> None:
    """🔴 FK RESTRICT'in servis karşılığı: 500 de "Veri bütünlüğü hatası" da DEĞİL.

    ⚠️ SQLSTATE'e dayanan bir iddia YAZILMAZ (yerel PG18 / CI PG16 farkı) — bu
    yüzden denetim servis düzeyindedir ve test yalnız DAVRANIŞA bakar.
    """
    hesap = await hesap_fabrikasi()
    await odeme_fabrikasi(hesap, "50.00")
    resp = await client.delete(f"{_YOL}/{hesap.id}", headers=admin_headers)
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"] != "Veri bütünlüğü hatası"
    assert (await seeded_db.execute(select(BankAccount))).scalars().all() != []


async def test_delete_olmayan_kayit_404(client, admin_headers) -> None:
    resp = await client.delete(f"{_YOL}/{uuid.uuid4()}", headers=admin_headers)
    assert resp.status_code == 404, resp.text


async def test_delete_denetim_satiri_yazar(
    client, admin_headers, hesap_fabrikasi, seeded_db
) -> None:
    """Metin silmeden ÖNCE kurulur — sonra kurulsaydı ad okunamazdı."""
    hesap = await hesap_fabrikasi(bank_name="Ziraat Bank", display_name="Vadesiz TL")
    resp = await client.delete(f"{_YOL}/{hesap.id}", headers=admin_headers)
    assert resp.status_code == 204, resp.text
    kayitlar = (
        (await seeded_db.execute(select(AuditLog).where(AuditLog.action == AuditAction.delete)))
        .scalars()
        .all()
    )
    assert any("Vadesiz TL" in (k.detail or "") for k in kayitlar), [k.detail for k in kayitlar]
