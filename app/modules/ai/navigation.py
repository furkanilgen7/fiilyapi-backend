"""`navigate_to` hedefleri — **KAPALI ENUM** (S22).

Parametre serbest `str` DEĞİLDİR. Serbest olsaydı model bir URL uydurabilir ve
ekranda "Stok girişi" yazarken altta `/ayarlar/izin-matrisi` durabilirdi
(kimlik avı / confused deputy).

🔴 **URL BURADA KURULMAZ.** Backend yalnız **ekran anahtarı** döner; URL'i
frontend kurar. Gerekçe ölçüldü: `routes.ts` **AYRI BİR GİT DEPOSUNDADIR**,
yani hedeflerin `routes.ts`ten "türetilmesi" imkânsızdır — türetme iddiası
girdilerdeki çelişkilerden biriydi ve ölçümle kesildi. Sözleşme repo sınırını
geçmez: backend anahtar konuşur, frontend yol.

🔴 **Hiçbir değer taşıyan sorgu parametresi ve hiçbir `/approve`, `/submit`,
`/mark-paid` yüzeyi bu listeye giremez** — bekçisi `test_ai0b_navigation.py`.
"""

from __future__ import annotations

import enum


class EkranAnahtari(str, enum.Enum):
    """AI'ın kullanıcıyı yönlendirebileceği ekranlar.

    Yalnız **okuma/liste** ekranları. Bir eylem yüzeyi (onayla, gönder, ödendi
    işaretle) buraya eklenirse `navigate_to` vekâleten yazma aracına dönüşür.
    """

    gosterge_paneli = "gosterge_paneli"
    onay_kutusu = "onay_kutusu"
    projeler = "projeler"
    santiyeler = "santiyeler"
    puantaj = "puantaj"
    santiye_gunlugu = "santiye_gunlugu"
    stok = "stok"
    hakedisler = "hakedisler"
    faturalar = "faturalar"
    hazine = "hazine"
    muhasebe = "muhasebe"
    makineler = "makineler"
    belgeler = "belgeler"
    ayarlar = "ayarlar"


#: Ekranın kullanıcıya gösterilecek Türkçe adı. Küme eşitliği bekçilidir:
#: enum'a üye eklenip buraya eklenmezse test kırmızı olur.
EKRAN_ADLARI: dict[EkranAnahtari, str] = {
    EkranAnahtari.gosterge_paneli: "Gösterge Paneli",
    EkranAnahtari.onay_kutusu: "Onay Kutusu",
    EkranAnahtari.projeler: "Projeler",
    EkranAnahtari.santiyeler: "Şantiyeler",
    EkranAnahtari.puantaj: "Puantaj",
    EkranAnahtari.santiye_gunlugu: "Şantiye Günlüğü",
    EkranAnahtari.stok: "Stok",
    EkranAnahtari.hakedisler: "Hakedişler",
    EkranAnahtari.faturalar: "Fatura Yönetimi",
    EkranAnahtari.hazine: "Hazine",
    EkranAnahtari.muhasebe: "Muhasebe",
    EkranAnahtari.makineler: "Makine & Ekipman",
    EkranAnahtari.belgeler: "Belgeler",
    EkranAnahtari.ayarlar: "Ayarlar",
}
