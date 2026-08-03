"""FINAL REVIEW (T5) sondası — sil + yeniden adlandır aynı istekte.

`UQ (site_id, kind, section_id, label)` yüzünden: gövde bir satırı silerken
BAŞKA bir satırı silinen satırın etiketine taşırsa, ORM'in UPDATE'i DELETE'ten
ÖNCE flush edilirse geçici olarak İKİ satır aynı etiketi taşır ve kısıt patlar.
Izgara ekranında satır yeniden adlandırma + silme tek "Kaydet"te olur (P97).
"""

from tests.site_planning.conftest import rows_url


async def test_silinen_satirin_etiketine_yeniden_adlandirma(
    client, santiye, bolum, sef_headers, satir_fabrikasi
):
    eski = await satir_fabrikasi(santiye, "Kalıpçı", section=bolum, sort_order=1)
    yeni = await satir_fabrikasi(santiye, "Demirci", section=bolum, sort_order=2)

    # "Kalıpçı" satırı gövdede YOK (silinir); "Demirci" onun etiketini alır.
    resp = await client.put(
        rows_url(santiye.id),
        headers=sef_headers,
        json={
            "rows": [
                {
                    "id": str(yeni.id),
                    "kind": "crew",
                    "section_id": str(bolum.id),
                    "label": "Kalıpçı",
                    "planned_worker_count": None,
                    "sort_order": 1,
                }
            ]
        },
    )

    assert resp.status_code == 200, resp.text
    kalanlar = resp.json()["rows"]
    assert [r["label"] for r in kalanlar] == ["Kalıpçı"]
    assert kalanlar[0]["id"] == str(yeni.id)
    assert str(eski.id) not in {r["id"] for r in kalanlar}


async def test_iki_satirin_etiketi_takas_edilir(
    client, santiye, bolum, sef_headers, satir_fabrikasi
):
    """Aynı sınıfın ikinci vakası: silme yok, iki etiket yer değiştiriyor.

    Ertelenmiş kısıt olmadan UPDATE'lerin ilki anında çakışırdı.
    """
    birinci = await satir_fabrikasi(santiye, "Kalıpçı", section=bolum, sort_order=1)
    ikinci = await satir_fabrikasi(santiye, "Demirci", section=bolum, sort_order=2)

    def govde(row_id, label, sort_order):
        return {
            "id": str(row_id),
            "kind": "crew",
            "section_id": str(bolum.id),
            "label": label,
            "planned_worker_count": None,
            "sort_order": sort_order,
        }

    resp = await client.put(
        rows_url(santiye.id),
        headers=sef_headers,
        json={"rows": [govde(birinci.id, "Demirci", 1), govde(ikinci.id, "Kalıpçı", 2)]},
    )

    assert resp.status_code == 200, resp.text
    etiketler = {r["id"]: r["label"] for r in resp.json()["rows"]}
    assert etiketler[str(birinci.id)] == "Demirci"
    assert etiketler[str(ikinci.id)] == "Kalıpçı"
