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
`/mark-paid` yüzeyi bu listeye giremez** — bekçisi
`test_ai2bd_araclar.py::test_NAV_*`.

🔴 **DÜZELTİLDİ (AI-2b/2d).** Bu satır VAR OLMAYAN bir `test_ai0b_navigation.py`yi
gösteriyordu ve aşağıdaki `EKRAN_ADLARI` yorumu *"Küme eşitliği bekçilidir"*
diyordu; ölçüldü: **`EKRAN_ADLARI`ya dokunan hiçbir test yoktu.** Eksik bir
etiket derleme hatası DEĞİL, `handlers.navigate_to` içinde çalışma anı
`KeyError`ı (yani 500) üretirdi. Bekçi bu dilimde YAZILDI ve mutasyonla
kanıtlandı; yorum artık doğrudur.
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
    #: Kapalı yönetim kararı (AI-2b): `taseron_hakedisleri` aracının kaynak/aksiyon
    #: bloğu bu ekrana bağlanır. `hakedisler` İŞVEREN tarafıdır ve ikisi ayrı
    #: ekrandır — tek anahtara indirmek kullanıcıyı yanlış listeye götürürdü.
    taseron_hakedisleri = "taseron_hakedisleri"
    ayarlar = "ayarlar"


#: Ekranın kullanıcıya gösterilecek Türkçe adı.
#:
#: 🔴 Küme eşitliği ARTIK GERÇEKTEN bekçilidir
#: (`test_ai2bd_araclar.py::test_NAV_EKRAN_ADLARI_enum_ile_KUME_ESITTIR`).
#: Bu cümle AI-2b'ye kadar YALANDI: ölçüldü, hiçbir test bu sözlüğe
#: dokunmuyordu ve eksik bir etiket `navigate_to` çağrıldığında **çalışma anı
#: 500** üretirdi.
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
    EkranAnahtari.taseron_hakedisleri: "Taşeron Hakedişleri",
    EkranAnahtari.ayarlar: "Ayarlar",
}
