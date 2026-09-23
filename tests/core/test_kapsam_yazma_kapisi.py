"""MASKELEYEN kapsamlı aktör, maskeli bir routerda YAZAMAZ — istek sınırında 403.

## Hangi iddia ölçüldü ve ne çıktı

2026-09-20 devrinde şu iddia geldi:

> `PATCH /boq/items/{id}` açık `null` metrajı SORGUSUZ kabul ediyor. Savunmanın
> TAMAMI frontend'deki `maskesiz()` — yani API'ye doğrudan istek atan biri
> maskelenmiş alanı `null`a yazabiliyor.

*"Savunmanın tamamı frontend"* cümlesi koda karşı ölçüldü ve **YANLIŞ** çıktı.
Sunucuda İKİ bağımsız kapı zaten vardı:

1. `app/modules/roles/service.py::update_permission` — maskeleyen bir kapsamın
   (`limited`/`finance`) `draft` ve üstü bir seviyeyle AYNI HÜCREDE bulunmasını
   reddeder. Gerekçesi orada yazılı: maskelenen değer forma/hesaba düşerdi.
2. Maskeli yazma uçlarının hepsi `full`/`admin` ister; matristeki kısıtlı
   kapsamlı hücrelerin hepsi `view`dır.

## 🔴 Ama iki kapı da YAPILANDIRMA ZAMANINDADIR — istek yolunda HİÇBİR ŞEY YOKTU

`update_permission` yalnız YAZILIRKEN bakar. Şu üç yoldan biriyle hücre o frenin
arkasından geçerse istek yolu itirazsız kabul ederdi:

* doğrudan SQL / veri taşıma / tohum düzeltmesi,
* freni 2026-09-19'dan ÖNCE yazılmış bir kalıntı satır,
* `require_permission`ı `full` yerine `draft`a alan yeni bir uç — o hâlde
  "kısıtlı kapsam yazma seviyesi taşımaz" kuralı aynı kalır ama kapı alçalır.

Bu dosya üçüncü katmanı ekler ve o katman **istek sınırındadır**: kapsamı bir
kovayı GİZLEYEN aktör, maskeli routerın güvenli olmayan (GET/HEAD/OPTIONS dışı)
hiçbir ucuna giremez. Böylece invariant, yazıldığı yerde değil UYGULANDIĞI yerde
de durur.

## Neden ALAN ALAN değil, UCUN TAMAMI

Alan düzeyinde bir bekçi (yalnız gizlenen kovadaki alanların gövdede geçmesini
yasaklamak) daha cerrahi GÖRÜNÜR ama üç yerden sızar: (a) istek şemaları
etiketli DEĞİLDİR ve etiketlemek ikinci bir kova kopyası yaratır — iki kopya
zamanla ayrışır; (b) gövdesini kendi üreten uçlar (çok parçalı yükleme, ham
`dict`) alan bilgisi taşımaz; (c) alan adı eşleştirmesi bu depoda zaten
çürütülmüş bir tekniktir (*"etiketli alan doğru kovada olduğunu kanıtlamaz"*).

Ucun tamamını kapatmak YAPISALDIR ve `roles/service.py`nin verdiği kararla
BİREBİR aynı şeyi söyler — o karar zaten *"kısıtlı kapsamlı hücre yazma seviyesi
TAŞIYAMAZ"* der. Burada yeni bir ürün kararı alınmıyor; alınmış karar istek
yolunda da uygulanıyor.

🔴 **Bugün hiçbir ATANABİLİR yapılandırma bu kapıya çarpmaz** (ölçüldü: tohumda
kısıtlı kapsamlı 18 hücrenin 18'i de `view`, ve `update_permission` başkasını
yazdırmaz). Yani bu bir davranış değişikliği DEĞİL, bir fail-closed sınırdır.

## Açık `null` politikası BURADA ÇÖZÜLMEDİ — ve bu bilinçli

İddianın birinci cümlesi ("açık `null` sorgusuz kabul ediliyor") DOĞRUDUR ve
maskeden BAĞIMSIZ bir kusur ailesini ortaya çıkardı: maskeli yazma yüzeyinde 50
alan, NOT NULL bir kolona açık `null` yazmaya çalışabiliyor. Ama deponun bu
soruya **İKİ yazılı ve ÇELİŞEN cevabı** var (422 reddi vs "gönderilmedi sayılır",
ikincisi yayımlanmış OpenAPI sözleşmesinde). Hangisinin kanon olduğu bir API
POLİTİKASI kararıdır → `KARARLAR-BEKLEYEN.md` §2.
"""

from decimal import Decimal

import pytest

from app.core.access import AccessLevel, Scope

from ..modules._boq import _auth, _group, _item, _login_with_access, _set_permission, _site


@pytest.fixture
async def boq_kalemi(db_session, project_factory):
    project = await project_factory("KAPSAM-YAZMA")
    site = await _site(db_session, project, code="A-YAZ")
    group = await _group(db_session, site)
    item = await _item(
        db_session, site, group, quantity=Decimal("1240.000"), unit_price=Decimal("280.00")
    )
    return site, item


async def _aktor(
    client,
    db_session,
    user_factory,
    kapsam: Scope,
    eposta: str,
    seviye: AccessLevel = AccessLevel.full,
) -> dict[str, str]:
    """`project_manager` + `boq = (seviye, kapsam)`.

    🔴 `seviye` PARAMETRE: silme ucu `admin` ister ve `full` ile çağrılsaydı 403
    SEVİYE kapısından gelirdi — test yeşil görünür, ölçmek istediği KAPSAM
    kapısını hiç denemezdi. (Bu, bu depoda ölçülmüş bir sahte-yeşil hâlidir:
    "403 testi kapının SEVİYESİNİ ölçmez".)

    🔴 İzin satırı DOĞRUDAN yazılır (`_set_permission`), `update_permission`
    ÜZERİNDEN DEĞİL: servis freni tam olarak bu bileşimi reddeder. Ölçülmek
    istenen şey zaten *"fren atlanmış olsaydı istek yolu ne yapardı"*dır; frenin
    kendi bekçisi ayrı dosyadadır (`test_role_service.py`).
    """
    token = await _login_with_access(client, db_session, user_factory, "project_manager", eposta)
    await _set_permission(db_session, "project_manager", "boq", seviye, kapsam)
    return _auth(token)


@pytest.mark.parametrize("kapsam", [Scope.limited, Scope.finance])
async def test_MASKELEYEN_kapsam_PATCH_ucunde_403_alir(
    client, db_session, user_factory, boq_kalemi, kapsam
):
    """İKİ kapsam da ölçülür: yalnız `limited`e bakan bir bekçi, `finance`
    aktörün metrajı ezmesini kaçırırdı (maske simetriktir, kapı da öyle olmalı).
    """
    _site_, item = boq_kalemi
    basliklar = await _aktor(client, db_session, user_factory, kapsam, f"{kapsam.value}@yaz.co")

    resp = await client.patch(
        f"/boq/items/{item.id}", json={"quantity": "1.000"}, headers=basliklar
    )

    assert resp.status_code == 403, (
        f"Kapsamı `{kapsam.value}` olan aktör maskeli bir routerda YAZDI: {resp.text}"
    )


async def test_MASKELEYEN_kapsam_DELETE_ucunde_de_403_alir(
    client, db_session, user_factory, boq_kalemi
):
    """🔴 204 DELETE'in gövdesi yoktur, yani MASKE orada anlamsızdır — ama KAPI
    anlamlıdır: göremediği bir kalemi silmek, göremediği bir alanı ezmekten daha
    ağırdır. Yalnız gövdeli uçlara bakan bir bekçi bunu kaçırırdı."""
    _site_, item = boq_kalemi
    basliklar = await _aktor(
        client, db_session, user_factory, Scope.limited, "sil@yaz.co", AccessLevel.admin
    )

    resp = await client.delete(f"/boq/items/{item.id}", headers=basliklar)

    assert resp.status_code == 403, f"maskeli kapsam SİLDİ: {resp.text}"


async def test_POZITIF_KONTROL_ALL_kapsamda_ayni_PATCH_gecer(
    client, db_session, user_factory, boq_kalemi
):
    """🔴 Bu olmadan üstteki testler *"her şeyi reddet"* hâlinde de yeşil kalırdı."""
    _site_, item = boq_kalemi
    basliklar = await _aktor(client, db_session, user_factory, Scope.all, "all@yaz.co")

    resp = await client.patch(
        f"/boq/items/{item.id}", json={"quantity": "1.000"}, headers=basliklar
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["quantity"] == "1.000"


async def test_POZITIF_KONTROL_maskeli_kapsam_OKUMAYA_devam_eder(
    client, db_session, user_factory, boq_kalemi
):
    """🔴 Kapı YAZMAYA özeldir. Okumayı da kapatan bir uygulama, maskenin bütün
    varlık sebebini (*"göster ama parayı gizle"*) yok ederdi — ve bu test onu
    çakar."""
    site, _item = boq_kalemi
    basliklar = await _aktor(client, db_session, user_factory, Scope.limited, "oku@yaz.co")

    resp = await client.get(f"/sites/{site.id}/boq", headers=basliklar)

    assert resp.status_code == 200, resp.text
    kalem = resp.json()["groups"][0]["items"][0]
    assert kalem["unit_price"] is None, "maske koşmadı"
    assert kalem["quantity"] == "1240.000", "okuma kapatıldı ya da fazla maskelendi"
