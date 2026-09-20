"""AI sunucuları MASKELENMİŞ alanı ekrana `None` diye BASMAZ.

## Ölçülmüş kusur (2026-09-20)

`accounting` rolü tohumda `boq = view/finance` taşır; `finance` OPERASYONEL
kovayı gizler ve `BoqItemResponse.quantity` `Gorunurluk.operasyonel` etiketlidir.
Maske AI okuma düzleminde de KOŞAR — ölçüldü: AI araçları servisi değil UCU sarar
ve `kapsam_rotasi` sarmalayıcısı ile `kapsam_kapisi` köprüsü o hatta da gelir
(`tests/modules/ai/test_p8_kapsam_maskesi.py`).

Dolayısıyla muhasebe rolünde `quantity` `None` gelir ve sunucu şunu yapıyordu:

    rozet_metni=f"{k.get('quantity')} {k.get('unit')}"

`f"{None}"` **"None"**tur. Yani sohbet kartındaki her poz satırının rozetinde
harfi harfine **"None m³"** yazıyordu.

## Neden rozet BASILMAZ (boş metin ya da "0" değil)

Kardeş alanın kanonu aynı dosyada yazılı: `VarlikKalemi.doluluk_yuzde` için
*"`None` ise çubuk ÇİZİLMEZ — 0 yazmak 'stok bitti' demektir ve bu uydurulmuş
bir olgu olurdu."* Rozet de bir OLGU taşır; bilinmeyen bir olguyu "—" ya da "0"
diye basmak, gizlenmiş bir metrajı veri gibi göstermek olurdu. Rozet alanı zaten
`str | None`dır ve `None` "rozet yok" demektir — yeni bir hâl icat edilmez.
"""

import dataclasses

from app.modules.ai.presenters_ai2bd import _is_kalemleri


def _veri(quantity: str | None) -> dict:
    return {
        "gruplar": [
            {
                "name": "TOPRAK VE TEMEL İŞLERİ",
                "items": [
                    {
                        "code": "01.001",
                        "description": "Kazı (Makine ile)",
                        "quantity": quantity,
                        "unit": "m³",
                    }
                ],
            }
        ],
        "grand_total": "347200.00",
        "kalem_sayisi": 1,
        "gerceklesen_toplam": "0",
    }


def _kalem(bloklar):
    liste = next(b for b in bloklar if getattr(b, "kalemler", None))
    return liste.kalemler[0]


def test_MASKELI_metraj_rozete_None_diye_BASILMAZ() -> None:
    kalem = _kalem(_is_kalemleri(_veri(None)))

    assert kalem.rozet_metni is None, f"maskelenmiş metraj rozete sızdı: {kalem.rozet_metni!r}"


def test_MASKELI_metraj_hicbir_metne_None_SIZDIRMAZ() -> None:
    """🔴 Yalnız rozete bakmak DAR olurdu: aynı sözlük alt metne ya da başlığa da
    girebilir. İddia BLOĞUN TAMAMI üzerinedir."""

    # 🔴 `vars()` KULLANILMAZ: bloklar `slots=True` dataclass'tir ve `__dict__`
    #    taşımazlar (ölçüldü — ilk hâli `TypeError` verdi). `asdict` ayrıca iç
    #    içe kalemlere de iner, yani iddia gerçekten BLOĞUN TAMAMI üzerinedir.
    def _metinler(deger) -> list[str]:
        if isinstance(deger, str):
            return [deger]
        if isinstance(deger, dict):
            return [m for v in deger.values() for m in _metinler(v)]
        if isinstance(deger, (list, tuple)):
            return [m for v in deger for m in _metinler(v)]
        return []

    metinler = [
        m for blok in _is_kalemleri(_veri(None)) for m in _metinler(dataclasses.asdict(blok))
    ]

    assert not [m for m in metinler if "None" in m], f"'None' metni sızdı: {metinler}"


def test_POZITIF_KONTROL_gercek_metraj_rozete_AYNEN_gecer() -> None:
    """🔴 Bu olmadan üstteki testler "rozeti hiç basma" hâlinde de yeşil kalırdı."""
    kalem = _kalem(_is_kalemleri(_veri("1240.000")))

    assert kalem.rozet_metni == "1240.000 m³"
