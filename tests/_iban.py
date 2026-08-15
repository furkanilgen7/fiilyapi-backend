"""Testler için SENTETİK ama GEÇERLİ TR IBAN üreteci (`tests/_time.py` kardeşi).

## Neden var

Fixture'lar IBAN'ları sayaçtan üretiyordu (`f"TR{n:024d}"` → `TR000…001`). Bu
değerler ISO 13616 mod-97 sağlamasını GEÇMEZ. Doğrudan model kurulumunda pydantic
koşmadığı için testler yeşil kalıyordu, ama fixture'ın ürettiği veri gerçek
sistemde ASLA var olamayacak bir veriydi — ve aynı sabitler uç gövdelerine
kopyalandığında (`TR120006400000112345678901`) kusur görünmez hâle geliyordu.

Üreteç sağlama hanesini HESAPLAR, sabit listeden seçmez: fixture N tane farklı
hesap isteyebilir ve elle hesaplanmış dört-beş sabit bunu karşılamaz.

⚠️ Değerler tümüyle sentetiktir; gerçek banka verisi DEĞİLDİR.
"""

#: TR IBAN'ı 26 hanedir: `TR` + 2 sağlama + 22 hane BBAN (ISO 13616).
_TR_BBAN_UZUNLUK = 22


def _mod97(iban: str) -> int:
    dondurulmus = iban[4:] + iban[:4]
    return int("".join(str(int(karakter, 36)) for karakter in dondurulmus)) % 97


def tr_iban(sira: int) -> str:
    """`sira` numarasından TÜRETİLMİŞ, mod-97'yi GEÇEN 26 haneli TR IBAN'ı.

    Sağlama hanesi `app/core/iban.py`den BAĞIMSIZ hesaplanır (aynı ISO 7064
    tanımının ikinci uygulaması): üreteç doğrulayıcıyı çağırsaydı, doğrulayıcı
    bozulduğunda fixture da onunla birlikte bozulur ve testler bunu göremezdi.
    """
    bban = f"{sira:0{_TR_BBAN_UZUNLUK}d}"
    # ISO 7064: sağlama haneleri `00` konur, kalan hesaplanır, `98 - kalan`
    # alınır. Sonuç SIFIR DOLGULUDUR — tek haneli bir sağlama uzunluğu 25'e
    # düşürür ve üretilen değer TR uzunluk kapısına takılırdı.
    saglama = 98 - _mod97(f"TR00{bban}")
    return f"TR{saglama:02d}{bban}"
