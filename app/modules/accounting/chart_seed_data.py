"""Tekdüzen Hesap Planı (TDHP) tohum verisi — MU-SEED T1, **SAF LİSTE**.

`roles/seed_data.py` emsali: bu dosya yalnız VERİYİ taşır. Yükleyici
(`seed_chart_of_accounts()`) T2'de, migration kopyası T3'te yazılır; T5 iki
katmanın BİREBİR aynı olduğunu iddia eden testi yazar — bu yüzden satırlar
makine tarafından karşılaştırılabilir (`frozen dataclass`) tutulur.

## K2 — KAPSAM: yalnız `NN` (grup) ve `NNN` (ana hesap)

🔴 `NNN.NN` alt hesap **YAZILMAZ**. Migration ham SQL'dir ve servis kapısını
atlar; bir alt hesap tohumlansaydı `_assert_parent_has_no_lines` kuralı
delinir, üstündeki ana hesap sessizce fiş satırı kabul eder hâle gelirdi.
Alt hesabı kullanıcı UI'dan açar.

## K3 — HARİTA KAPSAMI: hiçbir grup YEDEĞE düşmez

Tohumlanan her grup `statement_map` içinde **AÇIK BİR ANAHTARDIR** — ya
`BALANCE_SHEET_GROUPS` (10–58) ya `CASH_FLOW_GROUPS` (sınıf 6/7 → 60–79).
Bu yüzden şunlar **TOHUMLANMAZ**:

* **`59`** — `EXCLUDED_BALANCE_SHEET_GROUPS`. Kapanış hesabıdır; üründe kapanış
  akışı yoktur ve `Dönem Net Kârı` zaten `6xx`/`7xx`ten türer (çift sayım).
* 🔴 **`69`** — aynı ailenin GELİR TABLOSU tarafı (şef kararı, T2). Haritada
  açık anahtarı vardır (`CASH_FLOW_GROUPS["69"]`) ama `690`/`692` bir KAPANIŞ
  AKTARIM hesabıdır: `period_profit()` sınıf 6/7'yi `Σ(alacak − borç)` ile
  sayar, bu hesaplara fiş atılırsa dönem kârı İKİ KEZ sayılır. Kapanış akışı
  olmayan bir üründe zaten kullanılamazlar → kazanç yok, sessiz para hatası
  riski var.
* **Sınıf 8 ve 9** — haritada hiç yoktur, `_UNMAPPED_LINES` yedeğine düşerlerdi.
* **`14`, `16`, `20`, `21`, `31`, `41`, `45`, `46`, `51`, `53`, `55`, `56`** —
  `GROUP_SOURCE_NOTES` bunlar için *"TDHP'de kullanılmayan grup"* diyor. Harita
  bütünlüğü (10–58 aralığında delik bırakmamak) için orada dururlar; gerçek bir
  TDHP grubu DEĞİLLERDİR, dolayısıyla hesap planına kayıt olarak girmezler.

`other_current_assets` gibi bir "Diğer …" kalemine düşmek MEŞRUDUR — yasak olan
YEDEĞE (haritada anahtarı olmayan gruba) düşmektir.

## K4 🔴 — `is_contra` HESAP HESAP, ELLE

Kural tek cümledir: `is_contra=True` ⇔ hesabın **doğal bakiye yönü**
(`SIGN`: `asset`/`expense` = +1 borç · `liability`/`revenue`/`equity` = −1
alacak), düştüğü **bilanço kaleminin tarafının TERSİ** ise.

`(-)` son ekinden TÜRETİLMEZ. İki kanonik karşı örnek:

* `257 Birikmiş Amortismanlar (-)` → `liability` (alacak yönlü) ama **AKTİF**
  taraftaki `Maddi Duran Varlıklar (net)` kalemine düşer → **`is_contra=True`**.
* `501 Ödenmemiş Sermaye (-)` → `equity` + **`is_contra=False`**. PASİF tarafta
  kalır; borç bakiyesi `SIGN[equity] = −1` ile zaten düşer. 🔴 Ölçülmüş kanıt:
  kontra işaretlenirse `Sermaye` kalemi 6.000 yerine **14.000** çıkıyor.
  `580 Geçmiş Yıllar Zararları (-)` aynı gerekçeyle `False`.

Deseni iki cümlede: **kontra-AKTİF** hesap (aktif tarafta alacak bakiyeli) →
`liability` + `True`; **kontra-PASİF** hesap (pasif tarafta borç bakiyeli) →
`asset` + `True`.

🔴 **Sınıf 6/7'nin TAMAMI `is_contra=False`.** Bilanço gövdesine hiç girmezler
(`balance_sheet_line_for` `None` döner) ve `period_profit()` ne türü ne kontrayı
okur — ham `alacak − borç` niceliğiyle çalışır. `610 Satıştan İadeler (-)` bile
`False`.

## K5 🔴 — Sınıf 6/7'de tür SINIFTAN TÜRETİLEMEZ

SINIF 6 hem geliri (`60x`, `64x`, `67x`) hem gideri (`62x`, `63x`, `65x`,
`66x`, `68x`) taşır. Her hesabın türü tek tek yazılır ve **doğal bakiye
yönünü** söyler: borç yönlü → `expense`, alacak yönlü → `revenue`. Bu yüzden
`61x` (satış indirimleri) `expense`, `7x1` yansıtma hesapları `revenue`dır.
Rozet bir aile etiketi değil, YÖN bildirimidir.

## İsimler

Mockup (`projedesign/Muhasebe - Hesap Planı.dc.html`) bir hesabı çiziyorsa
**mockup adı BİREBİR kazanır** (`254 Taşıt Araçları`, `360 Ödenecek Vergi ve
Fonlar`, `760 Pazarlama Giderleri` …). Kalanında standart TDHP adları.
`(-)` ADIN parçasıdır ve korunur.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounting.models import ChartAccount, ChartAccountType

__all__ = ["CHART_ACCOUNTS", "ChartSeedAccount", "seed_chart_of_accounts"]


@dataclass(frozen=True, slots=True)
class ChartSeedAccount:
    """Tek bir tohum satırı — kod / ad / tür / kontra dörtlüsü.

    `frozen`: T5 iki katmanı (servis tohumu ↔ migration) küme olarak
    karşılaştıracak; donmuş dataclass hem hashlenebilir hem eşitlik
    karşılaştırılabilirdir. Alan sırası migration'daki sütun sırasıdır.
    """

    code: str
    name: str
    account_type: ChartAccountType
    is_contra: bool = False


_A = ChartSeedAccount
_T = ChartAccountType

#: 🔴 TEK KAYNAK. Grup satırları (`NN`) ve ana hesaplar (`NNN`) AYNI listede,
#: KOD SIRASINDA. T2 servisi ve T3 migration'ı bu sırayı birebir kullanır.
CHART_ACCOUNTS: tuple[ChartSeedAccount, ...] = (
    # ===================================================================== #
    # SINIF 1 — DÖNEN VARLIKLAR  (tümü bilanço AKTİF tarafı)
    # ===================================================================== #
    _A("10", "Hazır Değerler", _T.asset),
    _A("100", "Kasa", _T.asset),  # mockup HP
    _A("101", "Alınan Çekler", _T.asset),  # mockup HP
    _A("102", "Bankalar", _T.asset),  # mockup HP
    # kontra: alacak yönlü, AKTİF `Kasa ve Bankalar` kalemine düşer → ters
    _A("103", "Verilen Çekler ve Ödeme Emirleri (-)", _T.liability, True),
    _A("108", "Diğer Hazır Değerler", _T.asset),
    _A("11", "Menkul Kıymetler", _T.asset),
    _A("110", "Hisse Senetleri", _T.asset),
    _A("111", "Özel Kesim Tahvil, Senet ve Bonoları", _T.asset),
    _A("112", "Kamu Kesimi Tahvil, Senet ve Bonoları", _T.asset),
    _A("118", "Diğer Menkul Kıymetler", _T.asset),
    # kontra: değer düşüklüğü karşılığı alacak yönlü, AKTİF kaleme düşer → ters
    _A("119", "Menkul Kıymetler Değer Düşüklüğü Karşılığı (-)", _T.liability, True),
    _A("12", "Ticari Alacaklar", _T.asset),
    _A("120", "Alıcılar", _T.asset),  # mockup HP
    _A("121", "Alacak Senetleri", _T.asset),
    # kontra: reeskont alacak yönlü, AKTİF `Ticari Alacaklar` kalemine düşer → ters
    _A("122", "Alacak Senetleri Reeskontu (-)", _T.liability, True),
    # kontra: kazanılmamış faiz alacak yönlü, AKTİF kaleme düşer → ters
    _A("124", "Kazanılmamış Finansal Kiralama Faiz Gelirleri (-)", _T.liability, True),
    _A("126", "Verilen Depozito ve Teminatlar", _T.asset),
    _A("127", "Diğer Ticari Alacaklar", _T.asset),  # mockup HP
    _A("128", "Şüpheli Ticari Alacaklar", _T.asset),
    # kontra: karşılık alacak yönlü, AKTİF `Ticari Alacaklar` kalemine düşer → ters
    _A("129", "Şüpheli Ticari Alacaklar Karşılığı (-)", _T.liability, True),
    _A("13", "Diğer Alacaklar", _T.asset),
    _A("131", "Ortaklardan Alacaklar", _T.asset),
    _A("132", "İştiraklerden Alacaklar", _T.asset),
    _A("133", "Bağlı Ortaklıklardan Alacaklar", _T.asset),
    _A("135", "Personelden Alacaklar", _T.asset),
    _A("136", "Diğer Çeşitli Alacaklar", _T.asset),
    # kontra: reeskont alacak yönlü, AKTİF `Diğer Dönen Varlıklar` kalemine düşer
    _A("137", "Diğer Alacak Senetleri Reeskontu (-)", _T.liability, True),
    _A("138", "Şüpheli Diğer Alacaklar", _T.asset),
    # kontra: karşılık alacak yönlü, AKTİF kaleme düşer → ters
    _A("139", "Şüpheli Diğer Alacaklar Karşılığı (-)", _T.liability, True),
    _A("15", "Stoklar", _T.asset),
    _A("150", "İlk Madde ve Malzeme", _T.asset),  # mockup HP
    _A("151", "Yarı Mamuller - Üretim", _T.asset),
    _A("152", "Mamuller", _T.asset),
    _A("153", "Ticari Mallar", _T.asset),
    _A("157", "Diğer Stoklar", _T.asset),
    # kontra: karşılık alacak yönlü, AKTİF `Stoklar` kalemine düşer → ters
    _A("158", "Stok Değer Düşüklüğü Karşılığı (-)", _T.liability, True),
    _A("159", "Verilen Sipariş Avansları", _T.asset),
    _A("17", "Yıllara Yaygın İnşaat ve Onarım Maliyetleri", _T.asset),
    _A("170", "Yıllara Yaygın İnşaat ve Onarım Maliyetleri", _T.asset),
    _A("178", "Yıllara Yaygın İnşaat Enflasyon Düzeltme Hesabı", _T.asset),
    _A("179", "Taşeronlara Verilen Avanslar", _T.asset),
    _A("18", "Gelecek Aylara Ait Giderler ve Gelir Tahakkukları", _T.asset),
    _A("180", "Gelecek Aylara Ait Giderler", _T.asset),
    _A("181", "Gelir Tahakkukları", _T.asset),
    _A("19", "Diğer Dönen Varlıklar", _T.asset),
    _A("190", "Devreden KDV", _T.asset),
    _A("191", "İndirilecek KDV", _T.asset),  # mockup HP
    _A("192", "Diğer KDV", _T.asset),
    _A("193", "Peşin Ödenen Vergiler ve Fonlar", _T.asset),
    _A("195", "İş Avansları", _T.asset),
    _A("196", "Personel Avansları", _T.asset),
    _A("197", "Sayım ve Tesellüm Noksanları", _T.asset),
    _A("198", "Diğer Çeşitli Dönen Varlıklar", _T.asset),
    # kontra: karşılık alacak yönlü, AKTİF `Diğer Dönen Varlıklar` kalemine düşer
    _A("199", "Diğer Dönen Varlıklar Karşılığı (-)", _T.liability, True),
    # ===================================================================== #
    # SINIF 2 — DURAN VARLIKLAR  (tümü bilanço AKTİF tarafı)
    # ===================================================================== #
    _A("22", "Ticari Alacaklar", _T.asset),
    _A("220", "Alıcılar", _T.asset),
    _A("221", "Alacak Senetleri", _T.asset),
    # kontra: reeskont alacak yönlü, AKTİF `Diğer Duran Varlıklar` kalemine düşer
    _A("222", "Alacak Senetleri Reeskontu (-)", _T.liability, True),
    # kontra: kazanılmamış faiz alacak yönlü, AKTİF kaleme düşer → ters
    _A("224", "Kazanılmamış Finansal Kiralama Faiz Gelirleri (-)", _T.liability, True),
    _A("226", "Verilen Depozito ve Teminatlar", _T.asset),
    # kontra: karşılık alacak yönlü, AKTİF kaleme düşer → ters
    _A("229", "Şüpheli Alacaklar Karşılığı (-)", _T.liability, True),
    _A("23", "Diğer Alacaklar", _T.asset),
    _A("231", "Ortaklardan Alacaklar", _T.asset),
    _A("232", "İştiraklerden Alacaklar", _T.asset),
    _A("233", "Bağlı Ortaklıklardan Alacaklar", _T.asset),
    _A("235", "Personelden Alacaklar", _T.asset),
    _A("236", "Diğer Çeşitli Alacaklar", _T.asset),
    # kontra: reeskont alacak yönlü, AKTİF kaleme düşer → ters
    _A("237", "Diğer Alacak Senetleri Reeskontu (-)", _T.liability, True),
    _A("238", "Şüpheli Diğer Alacaklar", _T.asset),
    # kontra: karşılık alacak yönlü, AKTİF kaleme düşer → ters
    _A("239", "Şüpheli Diğer Alacaklar Karşılığı (-)", _T.liability, True),
    _A("24", "Mali Duran Varlıklar", _T.asset),
    _A("240", "Bağlı Menkul Kıymetler", _T.asset),
    # kontra: karşılık alacak yönlü, AKTİF kaleme düşer → ters
    _A("241", "Bağlı Menkul Kıymetler Değer Düşüklüğü Karşılığı (-)", _T.liability, True),
    _A("242", "İştirakler", _T.asset),
    # kontra: taahhüt alacak yönlü, AKTİF kaleme düşer → ters
    _A("243", "İştiraklere Sermaye Taahhütleri (-)", _T.liability, True),
    # kontra: karşılık alacak yönlü, AKTİF kaleme düşer → ters
    _A("244", "İştirakler Sermaye Payları Değer Düşüklüğü Karşılığı (-)", _T.liability, True),
    _A("245", "Bağlı Ortaklıklar", _T.asset),
    # kontra: taahhüt alacak yönlü, AKTİF kaleme düşer → ters
    _A("246", "Bağlı Ortaklıklara Sermaye Taahhütleri (-)", _T.liability, True),
    # kontra: karşılık alacak yönlü, AKTİF kaleme düşer → ters
    _A(
        "247",
        "Bağlı Ortaklıklar Sermaye Payları Değer Düşüklüğü Karşılığı (-)",
        _T.liability,
        True,
    ),
    _A("248", "Diğer Mali Duran Varlıklar", _T.asset),
    # kontra: karşılık alacak yönlü, AKTİF kaleme düşer → ters
    _A("249", "Diğer Mali Duran Varlıklar Karşılığı (-)", _T.liability, True),
    _A("25", "Maddi Duran Varlıklar", _T.asset),
    _A("250", "Arazi ve Arsalar", _T.asset),
    _A("251", "Yeraltı ve Yerüstü Düzenleri", _T.asset),
    _A("252", "Binalar", _T.asset),  # mockup HP
    _A("253", "Tesis, Makine ve Cihazlar", _T.asset),
    _A("254", "Taşıt Araçları", _T.asset),  # mockup HP
    _A("255", "Demirbaşlar", _T.asset),
    _A("256", "Diğer Maddi Duran Varlıklar", _T.asset),
    # 🔑 KANONİK ÖRNEK — kontra: `liability` (alacak yönlü) ama AKTİF taraftaki
    # `Maddi Duran Varlıklar (net)` kalemine düşer → taraf TERS → True.
    _A("257", "Birikmiş Amortismanlar (-)", _T.liability, True),  # mockup HP
    _A("258", "Yapılmakta Olan Yatırımlar", _T.asset),
    _A("259", "Verilen Avanslar", _T.asset),
    _A("26", "Maddi Olmayan Duran Varlıklar", _T.asset),
    _A("260", "Haklar", _T.asset),
    _A("261", "Şerefiye", _T.asset),
    _A("262", "Kuruluş ve Örgütlenme Giderleri", _T.asset),
    _A("263", "Araştırma ve Geliştirme Giderleri", _T.asset),
    _A("264", "Özel Maliyetler", _T.asset),
    _A("267", "Diğer Maddi Olmayan Duran Varlıklar", _T.asset),
    # kontra: amortisman alacak yönlü, AKTİF `Diğer Duran Varlıklar` kalemine düşer
    _A("268", "Birikmiş Amortismanlar (-)", _T.liability, True),
    _A("269", "Verilen Avanslar", _T.asset),
    _A("27", "Özel Tükenmeye Tabi Varlıklar", _T.asset),
    _A("271", "Arama Giderleri", _T.asset),
    _A("272", "Hazırlık ve Geliştirme Giderleri", _T.asset),
    _A("277", "Diğer Özel Tükenmeye Tabi Varlıklar", _T.asset),
    # kontra: tükenme payı alacak yönlü, AKTİF kaleme düşer → ters
    _A("278", "Birikmiş Tükenme Payları (-)", _T.liability, True),
    _A("279", "Verilen Avanslar", _T.asset),
    _A("28", "Gelecek Yıllara Ait Giderler ve Gelir Tahakkukları", _T.asset),
    _A("280", "Gelecek Yıllara Ait Giderler", _T.asset),
    _A("281", "Gelir Tahakkukları", _T.asset),
    _A("29", "Diğer Duran Varlıklar", _T.asset),
    _A("291", "Gelecek Yıllarda İndirilecek KDV", _T.asset),
    _A("292", "Diğer KDV", _T.asset),
    _A("293", "Gelecek Yıllar İhtiyacı Stoklar", _T.asset),
    _A("294", "Elden Çıkarılacak Stoklar ve Maddi Duran Varlıklar", _T.asset),
    _A("295", "Peşin Ödenen Vergiler ve Fonlar", _T.asset),
    _A("297", "Diğer Çeşitli Duran Varlıklar", _T.asset),
    # kontra: karşılık alacak yönlü, AKTİF `Diğer Duran Varlıklar` kalemine düşer
    _A("298", "Stok Değer Düşüklüğü Karşılığı (-)", _T.liability, True),
    # kontra: amortisman alacak yönlü, AKTİF kaleme düşer → ters
    _A("299", "Birikmiş Amortismanlar (-)", _T.liability, True),
    # ===================================================================== #
    # SINIF 3 — KISA VADELİ YÜKÜMLÜLÜKLER  (tümü bilanço PASİF tarafı)
    # ===================================================================== #
    _A("30", "Mali Borçlar", _T.liability),
    _A("300", "Banka Kredileri", _T.liability),
    _A("301", "Finansal Kiralama İşlemlerinden Borçlar", _T.liability),
    # kontra: ertelenmiş maliyet BORÇ yönlü (`asset`), PASİF kaleme düşer → ters
    _A("302", "Ertelenmiş Finansal Kiralama Borçlanma Maliyetleri (-)", _T.asset, True),
    _A("303", "Uzun Vadeli Kredilerin Anapara Taksitleri ve Faizleri", _T.liability),
    _A("304", "Tahvil Anapara Borç, Taksit ve Faizleri", _T.liability),
    _A("305", "Çıkarılmış Bonolar ve Senetler", _T.liability),
    _A("306", "Çıkarılmış Diğer Menkul Kıymetler", _T.liability),
    # kontra: ihraç farkı BORÇ yönlü (`asset`), PASİF kaleme düşer → ters
    _A("308", "Menkul Kıymetler İhraç Farkı (-)", _T.asset, True),
    _A("309", "Diğer Mali Borçlar", _T.liability),
    _A("32", "Ticari Borçlar", _T.liability),
    _A("320", "Satıcılar", _T.liability),  # mockup HP
    _A("321", "Borç Senetleri", _T.liability),
    # 🔑 kontra: reeskont BORÇ yönlü (`asset`), PASİF `Ticari Borçlar` kalemine
    # düşer → taraf TERS → True.
    _A("322", "Borç Senetleri Reeskontu (-)", _T.asset, True),
    _A("326", "Alınan Depozito ve Teminatlar", _T.liability),
    _A("329", "Diğer Ticari Borçlar", _T.liability),
    _A("33", "Diğer Borçlar", _T.liability),
    _A("331", "Ortaklara Borçlar", _T.liability),
    _A("332", "İştiraklere Borçlar", _T.liability),
    _A("333", "Bağlı Ortaklıklara Borçlar", _T.liability),
    _A("335", "Personele Borçlar", _T.liability),
    _A("336", "Diğer Çeşitli Borçlar", _T.liability),
    # kontra: reeskont BORÇ yönlü (`asset`), PASİF kaleme düşer → ters
    _A("337", "Diğer Borç Senetleri Reeskontu (-)", _T.asset, True),
    _A("34", "Alınan Avanslar", _T.liability),
    _A("340", "Alınan Sipariş Avansları", _T.liability),
    _A("349", "Alınan Diğer Avanslar", _T.liability),
    _A("35", "Yıllara Yaygın İnşaat ve Onarım Hakedişleri", _T.liability),
    _A("350", "Yıllara Yaygın İnşaat ve Onarım Hakediş Bedelleri", _T.liability),
    _A("358", "Yıllara Yaygın İnşaat Enflasyon Düzeltme Hesabı", _T.liability),
    _A("36", "Ödenecek Vergi ve Diğer Yükümlülükler", _T.liability),
    _A("360", "Ödenecek Vergi ve Fonlar", _T.liability),  # mockup HP
    _A("361", "Ödenecek Sosyal Güvenlik Kesintileri", _T.liability),
    _A(
        "368",
        "Vadesi Geçmiş, Ertelenmiş veya Taksitlendirilmiş Vergi ve Diğer Yükümlülükler",
        _T.liability,
    ),
    _A("369", "Ödenecek Diğer Yükümlülükler", _T.liability),
    _A("37", "Borç ve Gider Karşılıkları", _T.liability),
    _A("370", "Dönem Kârı Vergi ve Diğer Yasal Yükümlülük Karşılıkları", _T.liability),
    # kontra: peşin ödenen vergi BORÇ yönlü (`asset`), PASİF kaleme düşer → ters
    _A("371", "Dönem Kârının Peşin Ödenen Vergi ve Diğer Yükümlülükleri (-)", _T.asset, True),
    _A("372", "Kıdem Tazminatı Karşılığı", _T.liability),
    _A("373", "Maliyet Giderleri Karşılığı", _T.liability),
    _A("379", "Diğer Borç ve Gider Karşılıkları", _T.liability),
    _A("38", "Gelecek Aylara Ait Gelirler ve Gider Tahakkukları", _T.liability),
    _A("380", "Gelecek Aylara Ait Gelirler", _T.liability),
    _A("381", "Gider Tahakkukları", _T.liability),
    _A("39", "Diğer Kısa Vadeli Yabancı Kaynaklar", _T.liability),
    _A("391", "Hesaplanan KDV", _T.liability),  # mockup HP
    _A("392", "Diğer KDV", _T.liability),
    _A("393", "Merkez ve Şubeler Cari Hesabı", _T.liability),
    _A("397", "Sayım ve Tesellüm Fazlaları", _T.liability),
    _A("399", "Diğer Çeşitli Yabancı Kaynaklar", _T.liability),
    # ===================================================================== #
    # SINIF 4 — UZUN VADELİ YÜKÜMLÜLÜKLER  (tümü bilanço PASİF tarafı)
    # ===================================================================== #
    _A("40", "Mali Borçlar", _T.liability),
    _A("400", "Banka Kredileri", _T.liability),
    _A("401", "Finansal Kiralama İşlemlerinden Borçlar", _T.liability),
    # kontra: ertelenmiş maliyet BORÇ yönlü (`asset`), PASİF kaleme düşer → ters
    _A("402", "Ertelenmiş Finansal Kiralama Borçlanma Maliyetleri (-)", _T.asset, True),
    _A("405", "Çıkarılmış Tahviller", _T.liability),
    _A("407", "Çıkarılmış Diğer Menkul Kıymetler", _T.liability),
    # kontra: ihraç farkı BORÇ yönlü (`asset`), PASİF kaleme düşer → ters
    _A("408", "Menkul Kıymetler İhraç Farkı (-)", _T.asset, True),
    _A("409", "Diğer Mali Borçlar", _T.liability),
    _A("42", "Ticari Borçlar", _T.liability),
    _A("420", "Satıcılar", _T.liability),
    _A("421", "Borç Senetleri", _T.liability),
    # 🔑 kontra: reeskont BORÇ yönlü (`asset`), PASİF `Uzun Vadeli Krediler`
    # kalemine düşer → taraf TERS → True.
    _A("422", "Borç Senetleri Reeskontu (-)", _T.asset, True),
    _A("426", "Alınan Depozito ve Teminatlar", _T.liability),
    _A("429", "Diğer Ticari Borçlar", _T.liability),
    _A("43", "Diğer Borçlar", _T.liability),
    _A("431", "Ortaklara Borçlar", _T.liability),
    _A("432", "İştiraklere Borçlar", _T.liability),
    _A("433", "Bağlı Ortaklıklara Borçlar", _T.liability),
    _A("436", "Diğer Çeşitli Borçlar", _T.liability),
    # kontra: reeskont BORÇ yönlü (`asset`), PASİF kaleme düşer → ters
    _A("437", "Diğer Borç Senetleri Reeskontu (-)", _T.asset, True),
    _A("438", "Kamuya Olan Ertelenmiş veya Taksitlendirilmiş Borçlar", _T.liability),
    _A("44", "Alınan Avanslar", _T.liability),
    _A("440", "Alınan Sipariş Avansları", _T.liability),
    _A("449", "Alınan Diğer Avanslar", _T.liability),
    _A("47", "Borç ve Gider Karşılıkları", _T.liability),
    _A("472", "Kıdem Tazminatı Karşılığı", _T.liability),
    _A("479", "Diğer Borç ve Gider Karşılıkları", _T.liability),
    _A("48", "Gelecek Yıllara Ait Gelirler ve Gider Tahakkukları", _T.liability),
    _A("480", "Gelecek Yıllara Ait Gelirler", _T.liability),
    _A("481", "Gider Tahakkukları", _T.liability),
    _A("49", "Diğer Uzun Vadeli Yabancı Kaynaklar", _T.liability),
    _A("492", "Gelecek Yıllara Ertelenmiş veya Terkin Edilecek KDV", _T.liability),
    _A("493", "Tesise Katılma Payları", _T.liability),
    _A("499", "Diğer Çeşitli Uzun Vadeli Yabancı Kaynaklar", _T.liability),
    # ===================================================================== #
    # SINIF 5 — ÖZKAYNAKLAR  (🔴 `59` TOHUMLANMAZ — kapanış hesabı, K3)
    # ===================================================================== #
    _A("50", "Ödenmiş Sermaye", _T.equity),
    _A("500", "Sermaye", _T.equity),
    # 🔑 KANONİK KARŞI ÖRNEK — `(-)` var ama KONTRA DEĞİL: `equity` PASİF tarafta
    # kalır ve borç bakiyesi `SIGN[equity] = −1` ile zaten DÜŞER. Kontra
    # işaretlenseydi `Sermaye` kalemi 6.000 yerine 14.000 çıkardı (ölçüldü).
    _A("501", "Ödenmemiş Sermaye (-)", _T.equity, False),
    _A("52", "Sermaye Yedekleri", _T.equity),
    _A("520", "Hisse Senetleri İhraç Primleri", _T.equity),
    _A("521", "Hisse Senedi İptal Kârları", _T.equity),
    _A("522", "Maddi Duran Varlık Yeniden Değerleme Artışları", _T.equity),
    _A("523", "İştirakler Yeniden Değerleme Artışları", _T.equity),
    _A("529", "Diğer Sermaye Yedekleri", _T.equity),
    _A("54", "Kâr Yedekleri", _T.equity),
    _A("540", "Yasal Yedekler", _T.equity),
    _A("541", "Statü Yedekleri", _T.equity),
    _A("542", "Olağanüstü Yedekler", _T.equity),
    _A("548", "Diğer Kâr Yedekleri", _T.equity),
    _A("549", "Özel Fonlar", _T.equity),
    _A("57", "Geçmiş Yıllar Kârları", _T.equity),
    _A("570", "Geçmiş Yıllar Kârları", _T.equity),
    _A("58", "Geçmiş Yıllar Zararları (-)", _T.equity),
    # `501` ile aynı gerekçe: PASİF tarafta kalır, borç bakiyesi zaten düşer.
    _A("580", "Geçmiş Yıllar Zararları (-)", _T.equity, False),
    # ===================================================================== #
    # SINIF 6 — GELİR TABLOSU HESAPLARI
    # 🔴 K5: tür SINIFTAN türetilemez — 6 hem geliri hem gideri taşır.
    # 🔴 K4: bu sınıfın TAMAMI `is_contra=False` (bilanço gövdesine girmez;
    #        `period_profit()` ne türü ne kontrayı okur).
    # ===================================================================== #
    _A("60", "Brüt Satışlar", _T.revenue),
    _A("600", "Yurt İçi Satışlar", _T.revenue),  # mockup HP
    _A("601", "Yurt Dışı Satışlar", _T.revenue),
    _A("602", "Diğer Gelirler", _T.revenue),
    _A("61", "Satış İndirimleri (-)", _T.expense),
    _A("610", "Satıştan İadeler (-)", _T.expense),  # `(-)` var, kontra YOK (K4)
    _A("611", "Satış İskontoları (-)", _T.expense),
    _A("612", "Diğer İndirimler (-)", _T.expense),
    _A("62", "Satışların Maliyeti", _T.expense),
    _A("620", "Satılan Mamuller Maliyeti (-)", _T.expense),
    _A("621", "Satılan Ticari Mallar Maliyeti (-)", _T.expense),
    _A("622", "Satılan Hizmet Maliyeti (-)", _T.expense),
    _A("623", "Diğer Satışların Maliyeti (-)", _T.expense),
    _A("63", "Faaliyet Giderleri", _T.expense),
    _A("630", "Araştırma ve Geliştirme Giderleri (-)", _T.expense),
    _A("631", "Pazarlama, Satış ve Dağıtım Giderleri (-)", _T.expense),
    _A("632", "Genel Yönetim Giderleri (-)", _T.expense),
    _A("64", "Diğer Faaliyetlerden Olağan Gelir ve Kârlar", _T.revenue),
    _A("640", "İştiraklerden Temettü Gelirleri", _T.revenue),
    _A("641", "Bağlı Ortaklıklardan Temettü Gelirleri", _T.revenue),
    _A("642", "Faiz Gelirleri", _T.revenue),
    _A("643", "Komisyon Gelirleri", _T.revenue),
    _A("644", "Konusu Kalmayan Karşılıklar", _T.revenue),
    _A("645", "Menkul Kıymet Satış Kârları", _T.revenue),
    _A("646", "Kambiyo Kârları", _T.revenue),
    _A("647", "Reeskont Faiz Gelirleri", _T.revenue),
    _A("649", "Diğer Olağan Gelir ve Kârlar", _T.revenue),
    _A("65", "Diğer Faaliyetlerden Olağan Gider ve Zararlar", _T.expense),
    _A("653", "Komisyon Giderleri (-)", _T.expense),
    _A("654", "Karşılık Giderleri (-)", _T.expense),
    _A("655", "Menkul Kıymet Satış Zararları (-)", _T.expense),
    _A("656", "Kambiyo Zararları (-)", _T.expense),
    _A("657", "Reeskont Faiz Giderleri (-)", _T.expense),
    _A("659", "Diğer Gider ve Zararlar (-)", _T.expense),
    _A("66", "Finansman Giderleri", _T.expense),
    _A("660", "Kısa Vadeli Borçlanma Giderleri (-)", _T.expense),
    _A("661", "Uzun Vadeli Borçlanma Giderleri (-)", _T.expense),
    _A("67", "Olağandışı Gelir ve Kârlar", _T.revenue),
    _A("671", "Önceki Dönem Gelir ve Kârları", _T.revenue),
    _A("679", "Diğer Olağandışı Gelir ve Kârlar", _T.revenue),
    _A("68", "Olağandışı Gider ve Zararlar", _T.expense),
    _A("680", "Çalışmayan Kısım Gider ve Zararları (-)", _T.expense),
    _A("681", "Önceki Dönem Gider ve Zararları (-)", _T.expense),
    _A("689", "Diğer Olağandışı Gider ve Zararlar (-)", _T.expense),
    # 🔴 ŞEF KARARI (T2) — GRUP `69` TOHUMLANMAZ (`690`/`691`/`692` dâhil).
    # `59`un dışlanma gerekçesinin GELİR TABLOSU tarafıdır: `period_profit()`
    # sınıf 6/7'yi `Σ(alacak − borç)` ile sayar ve `690`/`692` bir KAPANIŞ
    # AKTARIM hesabıdır — fiş atılırsa dönem kârı İKİ KEZ sayılır. Üründe
    # kapanış akışı YOKTUR (`statement_map.py:222`), dolayısıyla bu hesaplar
    # zaten kullanılamaz: dâhil etmenin kazancı yok, sessiz para hatası riski
    # var. Kullanıcı gerçekten kapanış yapacaksa kartı UI'dan kendi açar.
    # ===================================================================== #
    # SINIF 7 — MALİYET HESAPLARI (7/A + 7/B)
    # 🔴 K4: tamamı `is_contra=False`. Tür = DOĞAL BAKİYE YÖNÜ; yansıtma
    #        hesapları (`7x1`, `798`) alacak yönlüdür → `revenue`.
    # ===================================================================== #
    _A("70", "Maliyet Muhasebesi Bağlantı Hesapları", _T.expense),
    _A("700", "Maliyet Muhasebesi Bağlantı Hesabı", _T.expense),
    _A("701", "Maliyet Muhasebesi Yansıtma Hesabı", _T.revenue),
    _A("71", "Direkt İlk Madde ve Malzeme Giderleri", _T.expense),
    _A("710", "Direkt İlk Madde ve Malzeme Giderleri", _T.expense),
    _A("711", "Direkt İlk Madde ve Malzeme Yansıtma Hesabı", _T.revenue),
    _A("712", "Direkt İlk Madde ve Malzeme Fiyat Farkı", _T.expense),
    _A("713", "Direkt İlk Madde ve Malzeme Miktar Farkı", _T.expense),
    _A("72", "Direkt İşçilik Giderleri", _T.expense),
    _A("720", "Direkt İşçilik Giderleri", _T.expense),
    _A("721", "Direkt İşçilik Giderleri Yansıtma Hesabı", _T.revenue),
    _A("722", "Direkt İşçilik Ücret Farkları", _T.expense),
    _A("723", "Direkt İşçilik Süre (Zaman) Farkları", _T.expense),
    _A("73", "Genel Üretim Giderleri", _T.expense),
    _A("730", "Genel Üretim Giderleri", _T.expense),  # mockup HP
    _A("731", "Genel Üretim Giderleri Yansıtma Hesabı", _T.revenue),
    _A("732", "Genel Üretim Giderleri Bütçe Farkları", _T.expense),
    _A("733", "Genel Üretim Giderleri Verimlilik Farkları", _T.expense),
    _A("734", "Genel Üretim Giderleri Kapasite Farkları", _T.expense),
    _A("74", "Hizmet Üretim Maliyeti", _T.expense),
    _A("740", "Hizmet Üretim Maliyeti", _T.expense),
    _A("741", "Hizmet Üretim Maliyeti Yansıtma Hesabı", _T.revenue),
    _A("742", "Hizmet Üretim Maliyeti Fark Hesapları", _T.expense),
    _A("75", "Araştırma ve Geliştirme Giderleri", _T.expense),
    _A("750", "Araştırma ve Geliştirme Giderleri", _T.expense),
    _A("751", "Araştırma ve Geliştirme Giderleri Yansıtma Hesabı", _T.revenue),
    _A("752", "Araştırma ve Geliştirme Gider Farkları", _T.expense),
    _A("76", "Pazarlama, Satış ve Dağıtım Giderleri", _T.expense),
    _A("760", "Pazarlama Giderleri", _T.expense),  # mockup HP
    _A("761", "Pazarlama, Satış ve Dağıtım Giderleri Yansıtma Hesabı", _T.revenue),
    _A("762", "Pazarlama, Satış ve Dağıtım Giderleri Fark Hesabı", _T.expense),
    _A("77", "Genel Yönetim Giderleri", _T.expense),
    _A("770", "Genel Yönetim Giderleri", _T.expense),
    _A("771", "Genel Yönetim Giderleri Yansıtma Hesabı", _T.revenue),
    _A("772", "Genel Yönetim Gider Farkları", _T.expense),
    _A("78", "Finansman Giderleri", _T.expense),
    _A("780", "Finansman Giderleri", _T.expense),
    _A("781", "Finansman Giderleri Yansıtma Hesabı", _T.revenue),
    _A("782", "Finansman Giderleri Fark Hesabı", _T.expense),
    _A("79", "Gider Çeşitleri", _T.expense),
    _A("790", "İlk Madde ve Malzeme Giderleri", _T.expense),
    _A("791", "İşçi Ücret ve Giderleri", _T.expense),
    _A("792", "Memur Ücret ve Giderleri", _T.expense),
    _A("793", "Dışarıdan Sağlanan Fayda ve Hizmetler", _T.expense),
    _A("794", "Çeşitli Giderler", _T.expense),
    _A("795", "Vergi, Resim ve Harçlar", _T.expense),
    _A("796", "Amortismanlar ve Tükenme Payları", _T.expense),
    _A("797", "Finansman Giderleri", _T.expense),
    _A("798", "Gider Çeşitleri Yansıtma Hesabı", _T.revenue),
    _A("799", "Üretim Maliyet Hesabı", _T.expense),
)


async def seed_chart_of_accounts(session: AsyncSession) -> None:
    """`CHART_ACCOUNTS`u `chart_of_accounts` tablosuna yükler — idempotent.

    🔴 **BU FONKSİYON HİÇBİR YERDEN ÇAĞRILMAZ ve bu bir eksiklik DEĞİL.**
    Tohumun canlıdaki mekanizması MIGRATION'dır (`Dockerfile:22` açılışta
    `alembic upgrade head` koşar). Bu katman migration verisinin **ölçülebilir
    İKİZİDİR**: `tests/conftest.py:57-61` şemayı `Base.metadata.create_all` ile
    kurar ve **`alembic upgrade` KOŞMAZ** — tek katmanlı bir migration normal
    suite'te tamamen bekçisiz kalırdı. T5 iki katmanın birebir aynı olduğunu
    iddia eder.

    🔴 **Kimse bunu `lifespan`a bağlamasın.** `lifespan` testlerde HİÇ koşmaz
    (`conftest.py:106` `ASGITransport(app=app)`) ve hataları yutulur
    (`main.py:61-66`) → tohum sessizce hiç yazılmamış olabilir ve bunu hiçbir
    test göremezdi.

    🔴 **K6 — İDEMPOTENS: `ON CONFLICT (code) DO NOTHING`.** Çakışma hedefi
    `uq_chart_of_accounts_code`. `DO UPDATE` yazılsaydı, kullanıcının kendi
    açtığı `100` kartının adı/türü/kontrası her tohum koşusunda TDHP
    varsayılanına geri döner, kullanıcı emeği yok olurdu. Emsal:
    `periods_service.lock_period` (UPSERT-SONRA-KİLİTLE).

    Tek toplu INSERT'tir: satır başına bir gidiş-dönüş 316 tur ederdi.
    `id` burada ÜRETİLİR — Core INSERT'te ORM örneği yoktur, kolon
    varsayılanına güvenmek yerine açıkça yazmak migration kopyasıyla (T3, ham
    SQL) aynı biçimi korur.
    """
    await session.execute(
        pg_insert(ChartAccount)
        .values(
            [
                {
                    "id": uuid.uuid4(),
                    "code": row.code,
                    "name": row.name,
                    "account_type": row.account_type,
                    "is_contra": row.is_contra,
                }
                for row in CHART_ACCOUNTS
            ]
        )
        .on_conflict_do_nothing(index_elements=["code"])
    )
    await session.flush()
