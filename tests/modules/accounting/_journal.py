"""MU-1 T3b — yevmiye fişi uç testlerinin PAYLAŞILAN kurulumu.

Üç test dosyası (`test_mu1_journal_api` · `_state` · `_summary`) aynı gövde
kurucularını kullanır. Dosya 800 satır tavanını aşınca bölündü; yardımcılar
kopyalanmadı, buraya alındı — iki kopya olsaydı biri güncellenip öteki
kalır ve iki dosya AYNI ismi taşıyan FARKLI gövdelerle koşardı.

Hiçbir testin iddiası bu bölmeyle değişmedi.
"""

from app.modules.accounting.models import ChartAccountType

YOL = "/journal-entries"
TARIH = "2026-07-17"


def satir(account_id, debit: str = "0", credit: str = "0") -> dict:  # noqa: ANN001
    return {"account_id": str(account_id), "debit": debit, "credit": credit}


def govde(borc_hesap, alacak_hesap, tutar: str = "1000.00", **ek) -> dict:  # noqa: ANN001
    deger = {
        "entry_date": TARIH,
        "description": "Kasa tahsilatı",
        "detail_note": "Ziraat Bank · TRF-20260717",
        "lines": [
            satir(borc_hesap.id, debit=tutar),
            satir(alacak_hesap.id, credit=tutar),
        ],
    }
    deger.update(ek)
    return deger


async def iki_yaprak(hesap_fabrikasi, sira: int = 0):  # noqa: ANN001, ANN201
    """İki YAPRAK hesap — fiş satırı yalnızca çocuğu olmayana kesilebilir (§4c).

    `sira` kodları ayrıştırır: `uq_chart_of_accounts_code` tekildir ve aynı test
    içinde iki kez çağrılan bir yardımcı sessizce IntegrityError üretirdi.
    """
    kasa = await hesap_fabrikasi(f"10{sira}", name="Kasa", account_type=ChartAccountType.asset)
    saticilar = await hesap_fabrikasi(
        f"32{sira}", name="Satıcılar", account_type=ChartAccountType.liability
    )
    return kasa, saticilar


async def fis_olustur(client, headers, hesap_fabrikasi, sira: int = 0, **ek) -> dict:  # noqa: ANN001
    kasa, saticilar = await iki_yaprak(hesap_fabrikasi, sira)
    resp = await client.post(YOL, json=govde(kasa, saticilar, **ek), headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()
