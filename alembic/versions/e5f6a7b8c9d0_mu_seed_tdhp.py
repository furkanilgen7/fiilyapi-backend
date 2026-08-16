"""mu seed tdhp hesap plani tohumu

MU-SEED T3 — Tekduzen Hesap Plani (TDHP) tohumu: 56 grup (`NN`) + 260 ana hesap
(`NNN`) = **316 satir**, 34'u kontra.

🔴 **BU MIGRATION CANLIDA ACILISTA KOSAR.** `Dockerfile:22`
`alembic upgrade head && uvicorn …` calistirir; burada patlayan bir satir `&&`yi
kisa devre yaptirir ve uvicorn HIC BASLAMAZ (**tam kesinti**). Her adim buna
gore yazilmistir: INSERT idempotenttir, downgrade veri kapilidir.

🔴 **K1 — VERI KOPYALANIR, UYGULAMA KODU IMPORT EDILMEZ.** Bu migration
`app.modules.accounting.chart_seed_data`i kasitli olarak import ETMEZ:
uygulanmis bir migration DONMUS olmalidir, uygulama kodu zamanla degisir.
Asagidaki `SEED_ACCOUNTS` demeti `CHART_ACCOUNTS`tan satir satir birebir
kopyalanmistir (kod · ad · tur · kontra). Emsal: `a477fdf00fdf:23-26`.
T5 iki katmanin BIREBIR ayni oldugunu iddia eden testi yazar.

🔴 **K6 — IDEMPOTENS.** `ON CONFLICT (code) DO NOTHING`
(`uq_chart_of_accounts_code`). Kullanici `100`u kendi actiysa USTUNE YAZILMAZ;
`DO UPDATE` yazilsaydi kullanicinin duzelttigi ad/tur/kontra her kosuda TDHP
varsayilanina donerdi. Ayrica yarim kalmis bir deploy'dan sonra ikinci
`upgrade` PATLAMAZ — bu yalniz canlida hayat kurtarir.
`op.bulk_insert` bunu YAPAMAZ (ON CONFLICT uretmez), bu yuzden
`postgresql.insert(...).on_conflict_do_nothing(...)` elle kosulur.

🔴 **K7 — DOWNGRADE VERI KAPILIDIR, KORU KORUNE SILMEZ.** `journal_lines.
account_id` **RESTRICT**tir: fis satiri olan bir hesabin silinmesi ham bir FK
hatasi verir ve migration YARIM kalirdi. Bu yuzden downgrade ONCE sorar; tohum
kodlarindan herhangi birine fis satiri varsa `RuntimeError` ile DURUR ve semayi
BOZMADAN birakir (yarim downgrade daha kotudur). `a477fdf00fdf`in kapisiz
`DELETE FROM roles` supurmesi burada YANLISTIR: yalniz tohum kodlari silinir,
kullanicinin kendi actigi hicbir hesaba dokunulmaz.

🔴 `chart_account_type` tipi ZATEN VARDIR (`d5e6f7a8b9c0` + `c8d9e0f1a2b3`);
`create_type=False` olmasaydi migration tipi yeniden yaratmaya kalkar ve
"type already exists" ile patlardi.

`id` migration'in KENDISI uretir — kolonun sunucu varsayilani YOKTUR
(`a477fdf00fdf` deseni). `is_active`/`created_at`/`updated_at` sunucu
varsayilanina birakilir.

Elle yazilmistir (autogenerate DEGIL) — repo deseni.

Revision ID: e5f6a7b8c9d0
Revises: d3e4f5a6b7c8
Create Date: 2026-08-16

"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e5f6a7b8c9d0"
down_revision: str | Sequence[str] | None = "d3e4f5a6b7c8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

chart_of_accounts_table = sa.table(
    "chart_of_accounts",
    sa.column("id", postgresql.UUID(as_uuid=True)),
    sa.column("code", sa.String),
    sa.column("name", sa.String),
    # 🔴 `create_type=False`: tip zaten var, migration onu YARATMAYA KALKMAZ.
    sa.column(
        "account_type",
        postgresql.ENUM(
            "asset",
            "liability",
            "revenue",
            "expense",
            "equity",
            name="chart_account_type",
            create_type=False,
        ),
    ),
    sa.column("is_contra", sa.Boolean),
)

#: 🔴 DONMUS KOPYA — `chart_seed_data.CHART_ACCOUNTS` ile birebir ayni sira ve
#: icerik: (kod, ad, tur, kontra). 316 satir · 34 kontra.
SEED_ACCOUNTS: tuple[tuple[str, str, str, bool], ...] = (
    ("10", "Hazır Değerler", "asset", False),
    ("100", "Kasa", "asset", False),
    ("101", "Alınan Çekler", "asset", False),
    ("102", "Bankalar", "asset", False),
    ("103", "Verilen Çekler ve Ödeme Emirleri (-)", "liability", True),
    ("108", "Diğer Hazır Değerler", "asset", False),
    ("11", "Menkul Kıymetler", "asset", False),
    ("110", "Hisse Senetleri", "asset", False),
    ("111", "Özel Kesim Tahvil, Senet ve Bonoları", "asset", False),
    ("112", "Kamu Kesimi Tahvil, Senet ve Bonoları", "asset", False),
    ("118", "Diğer Menkul Kıymetler", "asset", False),
    ("119", "Menkul Kıymetler Değer Düşüklüğü Karşılığı (-)", "liability", True),
    ("12", "Ticari Alacaklar", "asset", False),
    ("120", "Alıcılar", "asset", False),
    ("121", "Alacak Senetleri", "asset", False),
    ("122", "Alacak Senetleri Reeskontu (-)", "liability", True),
    ("124", "Kazanılmamış Finansal Kiralama Faiz Gelirleri (-)", "liability", True),
    ("126", "Verilen Depozito ve Teminatlar", "asset", False),
    ("127", "Diğer Ticari Alacaklar", "asset", False),
    ("128", "Şüpheli Ticari Alacaklar", "asset", False),
    ("129", "Şüpheli Ticari Alacaklar Karşılığı (-)", "liability", True),
    ("13", "Diğer Alacaklar", "asset", False),
    ("131", "Ortaklardan Alacaklar", "asset", False),
    ("132", "İştiraklerden Alacaklar", "asset", False),
    ("133", "Bağlı Ortaklıklardan Alacaklar", "asset", False),
    ("135", "Personelden Alacaklar", "asset", False),
    ("136", "Diğer Çeşitli Alacaklar", "asset", False),
    ("137", "Diğer Alacak Senetleri Reeskontu (-)", "liability", True),
    ("138", "Şüpheli Diğer Alacaklar", "asset", False),
    ("139", "Şüpheli Diğer Alacaklar Karşılığı (-)", "liability", True),
    ("15", "Stoklar", "asset", False),
    ("150", "İlk Madde ve Malzeme", "asset", False),
    ("151", "Yarı Mamuller - Üretim", "asset", False),
    ("152", "Mamuller", "asset", False),
    ("153", "Ticari Mallar", "asset", False),
    ("157", "Diğer Stoklar", "asset", False),
    ("158", "Stok Değer Düşüklüğü Karşılığı (-)", "liability", True),
    ("159", "Verilen Sipariş Avansları", "asset", False),
    ("17", "Yıllara Yaygın İnşaat ve Onarım Maliyetleri", "asset", False),
    ("170", "Yıllara Yaygın İnşaat ve Onarım Maliyetleri", "asset", False),
    ("178", "Yıllara Yaygın İnşaat Enflasyon Düzeltme Hesabı", "asset", False),
    ("179", "Taşeronlara Verilen Avanslar", "asset", False),
    ("18", "Gelecek Aylara Ait Giderler ve Gelir Tahakkukları", "asset", False),
    ("180", "Gelecek Aylara Ait Giderler", "asset", False),
    ("181", "Gelir Tahakkukları", "asset", False),
    ("19", "Diğer Dönen Varlıklar", "asset", False),
    ("190", "Devreden KDV", "asset", False),
    ("191", "İndirilecek KDV", "asset", False),
    ("192", "Diğer KDV", "asset", False),
    ("193", "Peşin Ödenen Vergiler ve Fonlar", "asset", False),
    ("195", "İş Avansları", "asset", False),
    ("196", "Personel Avansları", "asset", False),
    ("197", "Sayım ve Tesellüm Noksanları", "asset", False),
    ("198", "Diğer Çeşitli Dönen Varlıklar", "asset", False),
    ("199", "Diğer Dönen Varlıklar Karşılığı (-)", "liability", True),
    ("22", "Ticari Alacaklar", "asset", False),
    ("220", "Alıcılar", "asset", False),
    ("221", "Alacak Senetleri", "asset", False),
    ("222", "Alacak Senetleri Reeskontu (-)", "liability", True),
    ("224", "Kazanılmamış Finansal Kiralama Faiz Gelirleri (-)", "liability", True),
    ("226", "Verilen Depozito ve Teminatlar", "asset", False),
    ("229", "Şüpheli Alacaklar Karşılığı (-)", "liability", True),
    ("23", "Diğer Alacaklar", "asset", False),
    ("231", "Ortaklardan Alacaklar", "asset", False),
    ("232", "İştiraklerden Alacaklar", "asset", False),
    ("233", "Bağlı Ortaklıklardan Alacaklar", "asset", False),
    ("235", "Personelden Alacaklar", "asset", False),
    ("236", "Diğer Çeşitli Alacaklar", "asset", False),
    ("237", "Diğer Alacak Senetleri Reeskontu (-)", "liability", True),
    ("238", "Şüpheli Diğer Alacaklar", "asset", False),
    ("239", "Şüpheli Diğer Alacaklar Karşılığı (-)", "liability", True),
    ("24", "Mali Duran Varlıklar", "asset", False),
    ("240", "Bağlı Menkul Kıymetler", "asset", False),
    ("241", "Bağlı Menkul Kıymetler Değer Düşüklüğü Karşılığı (-)", "liability", True),
    ("242", "İştirakler", "asset", False),
    ("243", "İştiraklere Sermaye Taahhütleri (-)", "liability", True),
    ("244", "İştirakler Sermaye Payları Değer Düşüklüğü Karşılığı (-)", "liability", True),
    ("245", "Bağlı Ortaklıklar", "asset", False),
    ("246", "Bağlı Ortaklıklara Sermaye Taahhütleri (-)", "liability", True),
    ("247", "Bağlı Ortaklıklar Sermaye Payları Değer Düşüklüğü Karşılığı (-)", "liability", True),
    ("248", "Diğer Mali Duran Varlıklar", "asset", False),
    ("249", "Diğer Mali Duran Varlıklar Karşılığı (-)", "liability", True),
    ("25", "Maddi Duran Varlıklar", "asset", False),
    ("250", "Arazi ve Arsalar", "asset", False),
    ("251", "Yeraltı ve Yerüstü Düzenleri", "asset", False),
    ("252", "Binalar", "asset", False),
    ("253", "Tesis, Makine ve Cihazlar", "asset", False),
    ("254", "Taşıt Araçları", "asset", False),
    ("255", "Demirbaşlar", "asset", False),
    ("256", "Diğer Maddi Duran Varlıklar", "asset", False),
    ("257", "Birikmiş Amortismanlar (-)", "liability", True),
    ("258", "Yapılmakta Olan Yatırımlar", "asset", False),
    ("259", "Verilen Avanslar", "asset", False),
    ("26", "Maddi Olmayan Duran Varlıklar", "asset", False),
    ("260", "Haklar", "asset", False),
    ("261", "Şerefiye", "asset", False),
    ("262", "Kuruluş ve Örgütlenme Giderleri", "asset", False),
    ("263", "Araştırma ve Geliştirme Giderleri", "asset", False),
    ("264", "Özel Maliyetler", "asset", False),
    ("267", "Diğer Maddi Olmayan Duran Varlıklar", "asset", False),
    ("268", "Birikmiş Amortismanlar (-)", "liability", True),
    ("269", "Verilen Avanslar", "asset", False),
    ("27", "Özel Tükenmeye Tabi Varlıklar", "asset", False),
    ("271", "Arama Giderleri", "asset", False),
    ("272", "Hazırlık ve Geliştirme Giderleri", "asset", False),
    ("277", "Diğer Özel Tükenmeye Tabi Varlıklar", "asset", False),
    ("278", "Birikmiş Tükenme Payları (-)", "liability", True),
    ("279", "Verilen Avanslar", "asset", False),
    ("28", "Gelecek Yıllara Ait Giderler ve Gelir Tahakkukları", "asset", False),
    ("280", "Gelecek Yıllara Ait Giderler", "asset", False),
    ("281", "Gelir Tahakkukları", "asset", False),
    ("29", "Diğer Duran Varlıklar", "asset", False),
    ("291", "Gelecek Yıllarda İndirilecek KDV", "asset", False),
    ("292", "Diğer KDV", "asset", False),
    ("293", "Gelecek Yıllar İhtiyacı Stoklar", "asset", False),
    ("294", "Elden Çıkarılacak Stoklar ve Maddi Duran Varlıklar", "asset", False),
    ("295", "Peşin Ödenen Vergiler ve Fonlar", "asset", False),
    ("297", "Diğer Çeşitli Duran Varlıklar", "asset", False),
    ("298", "Stok Değer Düşüklüğü Karşılığı (-)", "liability", True),
    ("299", "Birikmiş Amortismanlar (-)", "liability", True),
    ("30", "Mali Borçlar", "liability", False),
    ("300", "Banka Kredileri", "liability", False),
    ("301", "Finansal Kiralama İşlemlerinden Borçlar", "liability", False),
    ("302", "Ertelenmiş Finansal Kiralama Borçlanma Maliyetleri (-)", "asset", True),
    ("303", "Uzun Vadeli Kredilerin Anapara Taksitleri ve Faizleri", "liability", False),
    ("304", "Tahvil Anapara Borç, Taksit ve Faizleri", "liability", False),
    ("305", "Çıkarılmış Bonolar ve Senetler", "liability", False),
    ("306", "Çıkarılmış Diğer Menkul Kıymetler", "liability", False),
    ("308", "Menkul Kıymetler İhraç Farkı (-)", "asset", True),
    ("309", "Diğer Mali Borçlar", "liability", False),
    ("32", "Ticari Borçlar", "liability", False),
    ("320", "Satıcılar", "liability", False),
    ("321", "Borç Senetleri", "liability", False),
    ("322", "Borç Senetleri Reeskontu (-)", "asset", True),
    ("326", "Alınan Depozito ve Teminatlar", "liability", False),
    ("329", "Diğer Ticari Borçlar", "liability", False),
    ("33", "Diğer Borçlar", "liability", False),
    ("331", "Ortaklara Borçlar", "liability", False),
    ("332", "İştiraklere Borçlar", "liability", False),
    ("333", "Bağlı Ortaklıklara Borçlar", "liability", False),
    ("335", "Personele Borçlar", "liability", False),
    ("336", "Diğer Çeşitli Borçlar", "liability", False),
    ("337", "Diğer Borç Senetleri Reeskontu (-)", "asset", True),
    ("34", "Alınan Avanslar", "liability", False),
    ("340", "Alınan Sipariş Avansları", "liability", False),
    ("349", "Alınan Diğer Avanslar", "liability", False),
    ("35", "Yıllara Yaygın İnşaat ve Onarım Hakedişleri", "liability", False),
    ("350", "Yıllara Yaygın İnşaat ve Onarım Hakediş Bedelleri", "liability", False),
    ("358", "Yıllara Yaygın İnşaat Enflasyon Düzeltme Hesabı", "liability", False),
    ("36", "Ödenecek Vergi ve Diğer Yükümlülükler", "liability", False),
    ("360", "Ödenecek Vergi ve Fonlar", "liability", False),
    ("361", "Ödenecek Sosyal Güvenlik Kesintileri", "liability", False),
    (
        "368",
        "Vadesi Geçmiş, Ertelenmiş veya Taksitlendirilmiş Vergi ve Diğer Yükümlülükler",
        "liability",
        False,
    ),
    ("369", "Ödenecek Diğer Yükümlülükler", "liability", False),
    ("37", "Borç ve Gider Karşılıkları", "liability", False),
    ("370", "Dönem Kârı Vergi ve Diğer Yasal Yükümlülük Karşılıkları", "liability", False),
    ("371", "Dönem Kârının Peşin Ödenen Vergi ve Diğer Yükümlülükleri (-)", "asset", True),
    ("372", "Kıdem Tazminatı Karşılığı", "liability", False),
    ("373", "Maliyet Giderleri Karşılığı", "liability", False),
    ("379", "Diğer Borç ve Gider Karşılıkları", "liability", False),
    ("38", "Gelecek Aylara Ait Gelirler ve Gider Tahakkukları", "liability", False),
    ("380", "Gelecek Aylara Ait Gelirler", "liability", False),
    ("381", "Gider Tahakkukları", "liability", False),
    ("39", "Diğer Kısa Vadeli Yabancı Kaynaklar", "liability", False),
    ("391", "Hesaplanan KDV", "liability", False),
    ("392", "Diğer KDV", "liability", False),
    ("393", "Merkez ve Şubeler Cari Hesabı", "liability", False),
    ("397", "Sayım ve Tesellüm Fazlaları", "liability", False),
    ("399", "Diğer Çeşitli Yabancı Kaynaklar", "liability", False),
    ("40", "Mali Borçlar", "liability", False),
    ("400", "Banka Kredileri", "liability", False),
    ("401", "Finansal Kiralama İşlemlerinden Borçlar", "liability", False),
    ("402", "Ertelenmiş Finansal Kiralama Borçlanma Maliyetleri (-)", "asset", True),
    ("405", "Çıkarılmış Tahviller", "liability", False),
    ("407", "Çıkarılmış Diğer Menkul Kıymetler", "liability", False),
    ("408", "Menkul Kıymetler İhraç Farkı (-)", "asset", True),
    ("409", "Diğer Mali Borçlar", "liability", False),
    ("42", "Ticari Borçlar", "liability", False),
    ("420", "Satıcılar", "liability", False),
    ("421", "Borç Senetleri", "liability", False),
    ("422", "Borç Senetleri Reeskontu (-)", "asset", True),
    ("426", "Alınan Depozito ve Teminatlar", "liability", False),
    ("429", "Diğer Ticari Borçlar", "liability", False),
    ("43", "Diğer Borçlar", "liability", False),
    ("431", "Ortaklara Borçlar", "liability", False),
    ("432", "İştiraklere Borçlar", "liability", False),
    ("433", "Bağlı Ortaklıklara Borçlar", "liability", False),
    ("436", "Diğer Çeşitli Borçlar", "liability", False),
    ("437", "Diğer Borç Senetleri Reeskontu (-)", "asset", True),
    ("438", "Kamuya Olan Ertelenmiş veya Taksitlendirilmiş Borçlar", "liability", False),
    ("44", "Alınan Avanslar", "liability", False),
    ("440", "Alınan Sipariş Avansları", "liability", False),
    ("449", "Alınan Diğer Avanslar", "liability", False),
    ("47", "Borç ve Gider Karşılıkları", "liability", False),
    ("472", "Kıdem Tazminatı Karşılığı", "liability", False),
    ("479", "Diğer Borç ve Gider Karşılıkları", "liability", False),
    ("48", "Gelecek Yıllara Ait Gelirler ve Gider Tahakkukları", "liability", False),
    ("480", "Gelecek Yıllara Ait Gelirler", "liability", False),
    ("481", "Gider Tahakkukları", "liability", False),
    ("49", "Diğer Uzun Vadeli Yabancı Kaynaklar", "liability", False),
    ("492", "Gelecek Yıllara Ertelenmiş veya Terkin Edilecek KDV", "liability", False),
    ("493", "Tesise Katılma Payları", "liability", False),
    ("499", "Diğer Çeşitli Uzun Vadeli Yabancı Kaynaklar", "liability", False),
    ("50", "Ödenmiş Sermaye", "equity", False),
    ("500", "Sermaye", "equity", False),
    ("501", "Ödenmemiş Sermaye (-)", "equity", False),
    ("52", "Sermaye Yedekleri", "equity", False),
    ("520", "Hisse Senetleri İhraç Primleri", "equity", False),
    ("521", "Hisse Senedi İptal Kârları", "equity", False),
    ("522", "Maddi Duran Varlık Yeniden Değerleme Artışları", "equity", False),
    ("523", "İştirakler Yeniden Değerleme Artışları", "equity", False),
    ("529", "Diğer Sermaye Yedekleri", "equity", False),
    ("54", "Kâr Yedekleri", "equity", False),
    ("540", "Yasal Yedekler", "equity", False),
    ("541", "Statü Yedekleri", "equity", False),
    ("542", "Olağanüstü Yedekler", "equity", False),
    ("548", "Diğer Kâr Yedekleri", "equity", False),
    ("549", "Özel Fonlar", "equity", False),
    ("57", "Geçmiş Yıllar Kârları", "equity", False),
    ("570", "Geçmiş Yıllar Kârları", "equity", False),
    ("58", "Geçmiş Yıllar Zararları (-)", "equity", False),
    ("580", "Geçmiş Yıllar Zararları (-)", "equity", False),
    ("60", "Brüt Satışlar", "revenue", False),
    ("600", "Yurt İçi Satışlar", "revenue", False),
    ("601", "Yurt Dışı Satışlar", "revenue", False),
    ("602", "Diğer Gelirler", "revenue", False),
    ("61", "Satış İndirimleri (-)", "expense", False),
    ("610", "Satıştan İadeler (-)", "expense", False),
    ("611", "Satış İskontoları (-)", "expense", False),
    ("612", "Diğer İndirimler (-)", "expense", False),
    ("62", "Satışların Maliyeti", "expense", False),
    ("620", "Satılan Mamuller Maliyeti (-)", "expense", False),
    ("621", "Satılan Ticari Mallar Maliyeti (-)", "expense", False),
    ("622", "Satılan Hizmet Maliyeti (-)", "expense", False),
    ("623", "Diğer Satışların Maliyeti (-)", "expense", False),
    ("63", "Faaliyet Giderleri", "expense", False),
    ("630", "Araştırma ve Geliştirme Giderleri (-)", "expense", False),
    ("631", "Pazarlama, Satış ve Dağıtım Giderleri (-)", "expense", False),
    ("632", "Genel Yönetim Giderleri (-)", "expense", False),
    ("64", "Diğer Faaliyetlerden Olağan Gelir ve Kârlar", "revenue", False),
    ("640", "İştiraklerden Temettü Gelirleri", "revenue", False),
    ("641", "Bağlı Ortaklıklardan Temettü Gelirleri", "revenue", False),
    ("642", "Faiz Gelirleri", "revenue", False),
    ("643", "Komisyon Gelirleri", "revenue", False),
    ("644", "Konusu Kalmayan Karşılıklar", "revenue", False),
    ("645", "Menkul Kıymet Satış Kârları", "revenue", False),
    ("646", "Kambiyo Kârları", "revenue", False),
    ("647", "Reeskont Faiz Gelirleri", "revenue", False),
    ("649", "Diğer Olağan Gelir ve Kârlar", "revenue", False),
    ("65", "Diğer Faaliyetlerden Olağan Gider ve Zararlar", "expense", False),
    ("653", "Komisyon Giderleri (-)", "expense", False),
    ("654", "Karşılık Giderleri (-)", "expense", False),
    ("655", "Menkul Kıymet Satış Zararları (-)", "expense", False),
    ("656", "Kambiyo Zararları (-)", "expense", False),
    ("657", "Reeskont Faiz Giderleri (-)", "expense", False),
    ("659", "Diğer Gider ve Zararlar (-)", "expense", False),
    ("66", "Finansman Giderleri", "expense", False),
    ("660", "Kısa Vadeli Borçlanma Giderleri (-)", "expense", False),
    ("661", "Uzun Vadeli Borçlanma Giderleri (-)", "expense", False),
    ("67", "Olağandışı Gelir ve Kârlar", "revenue", False),
    ("671", "Önceki Dönem Gelir ve Kârları", "revenue", False),
    ("679", "Diğer Olağandışı Gelir ve Kârlar", "revenue", False),
    ("68", "Olağandışı Gider ve Zararlar", "expense", False),
    ("680", "Çalışmayan Kısım Gider ve Zararları (-)", "expense", False),
    ("681", "Önceki Dönem Gider ve Zararları (-)", "expense", False),
    ("689", "Diğer Olağandışı Gider ve Zararlar (-)", "expense", False),
    ("70", "Maliyet Muhasebesi Bağlantı Hesapları", "expense", False),
    ("700", "Maliyet Muhasebesi Bağlantı Hesabı", "expense", False),
    ("701", "Maliyet Muhasebesi Yansıtma Hesabı", "revenue", False),
    ("71", "Direkt İlk Madde ve Malzeme Giderleri", "expense", False),
    ("710", "Direkt İlk Madde ve Malzeme Giderleri", "expense", False),
    ("711", "Direkt İlk Madde ve Malzeme Yansıtma Hesabı", "revenue", False),
    ("712", "Direkt İlk Madde ve Malzeme Fiyat Farkı", "expense", False),
    ("713", "Direkt İlk Madde ve Malzeme Miktar Farkı", "expense", False),
    ("72", "Direkt İşçilik Giderleri", "expense", False),
    ("720", "Direkt İşçilik Giderleri", "expense", False),
    ("721", "Direkt İşçilik Giderleri Yansıtma Hesabı", "revenue", False),
    ("722", "Direkt İşçilik Ücret Farkları", "expense", False),
    ("723", "Direkt İşçilik Süre (Zaman) Farkları", "expense", False),
    ("73", "Genel Üretim Giderleri", "expense", False),
    ("730", "Genel Üretim Giderleri", "expense", False),
    ("731", "Genel Üretim Giderleri Yansıtma Hesabı", "revenue", False),
    ("732", "Genel Üretim Giderleri Bütçe Farkları", "expense", False),
    ("733", "Genel Üretim Giderleri Verimlilik Farkları", "expense", False),
    ("734", "Genel Üretim Giderleri Kapasite Farkları", "expense", False),
    ("74", "Hizmet Üretim Maliyeti", "expense", False),
    ("740", "Hizmet Üretim Maliyeti", "expense", False),
    ("741", "Hizmet Üretim Maliyeti Yansıtma Hesabı", "revenue", False),
    ("742", "Hizmet Üretim Maliyeti Fark Hesapları", "expense", False),
    ("75", "Araştırma ve Geliştirme Giderleri", "expense", False),
    ("750", "Araştırma ve Geliştirme Giderleri", "expense", False),
    ("751", "Araştırma ve Geliştirme Giderleri Yansıtma Hesabı", "revenue", False),
    ("752", "Araştırma ve Geliştirme Gider Farkları", "expense", False),
    ("76", "Pazarlama, Satış ve Dağıtım Giderleri", "expense", False),
    ("760", "Pazarlama Giderleri", "expense", False),
    ("761", "Pazarlama, Satış ve Dağıtım Giderleri Yansıtma Hesabı", "revenue", False),
    ("762", "Pazarlama, Satış ve Dağıtım Giderleri Fark Hesabı", "expense", False),
    ("77", "Genel Yönetim Giderleri", "expense", False),
    ("770", "Genel Yönetim Giderleri", "expense", False),
    ("771", "Genel Yönetim Giderleri Yansıtma Hesabı", "revenue", False),
    ("772", "Genel Yönetim Gider Farkları", "expense", False),
    ("78", "Finansman Giderleri", "expense", False),
    ("780", "Finansman Giderleri", "expense", False),
    ("781", "Finansman Giderleri Yansıtma Hesabı", "revenue", False),
    ("782", "Finansman Giderleri Fark Hesabı", "expense", False),
    ("79", "Gider Çeşitleri", "expense", False),
    ("790", "İlk Madde ve Malzeme Giderleri", "expense", False),
    ("791", "İşçi Ücret ve Giderleri", "expense", False),
    ("792", "Memur Ücret ve Giderleri", "expense", False),
    ("793", "Dışarıdan Sağlanan Fayda ve Hizmetler", "expense", False),
    ("794", "Çeşitli Giderler", "expense", False),
    ("795", "Vergi, Resim ve Harçlar", "expense", False),
    ("796", "Amortismanlar ve Tükenme Payları", "expense", False),
    ("797", "Finansman Giderleri", "expense", False),
    ("798", "Gider Çeşitleri Yansıtma Hesabı", "revenue", False),
    ("799", "Üretim Maliyet Hesabı", "expense", False),
)


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    bind.execute(
        postgresql.insert(chart_of_accounts_table)
        .values(
            [
                {
                    "id": uuid.uuid4(),
                    "code": code,
                    "name": name,
                    "account_type": account_type,
                    "is_contra": is_contra,
                }
                for code, name, account_type, is_contra in SEED_ACCOUNTS
            ]
        )
        .on_conflict_do_nothing(index_elements=["code"])
    )


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()
    kodlar = [code for code, _name, _tur, _kontra in SEED_ACCOUNTS]

    # 🔴 VERI KAPISI — fis satiri tasiyan tohum hesabi varsa DUR.
    #    `journal_lines.account_id` RESTRICT'tir; korukorune DELETE ham bir FK
    #    hatasi verir ve migration yarim kalir. Ustelik silinen satir
    #    kullanicinin KENDI duzelttigi kart olabilirdi.
    kullanilan = bind.execute(
        sa.text(
            "SELECT c.code, count(*) AS satir "
            "FROM journal_lines l "
            "JOIN chart_of_accounts c ON c.id = l.account_id "
            "WHERE c.code = ANY(:kodlar) "
            "GROUP BY c.code ORDER BY c.code"
        ),
        {"kodlar": kodlar},
    ).all()
    if kullanilan:
        ornek = ", ".join(f"{code} ({satir} satir)" for code, satir in kullanilan[:10])
        toplam_satir = sum(satir for _code, satir in kullanilan)
        raise RuntimeError(
            f"downgrade durduruldu: {len(kullanilan)} tohum hesabinda toplam "
            f"{toplam_satir} yevmiye satiri var — {ornek}"
            + (" …" if len(kullanilan) > 10 else "")
            + ". Bu hesaplar silinemez (journal_lines.account_id RESTRICT). "
            "Once ilgili fisler elle silinmeli ya da satirlar baska bir hesaba "
            "tasinmalidir; ardindan downgrade tekrar kosulabilir. Sema "
            "BOZULMADAN birakildi."
        )

    # Yalniz TOHUM kodlari silinir — kullanicinin kendi actigi hesaplar kalir.
    bind.execute(
        sa.text("DELETE FROM chart_of_accounts WHERE code = ANY(:kodlar)"),
        {"kodlar": kodlar},
    )
