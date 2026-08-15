"""İzin türev hesapları — İK-2 spec §2, §5 K2.

`status.py`nin kardeşi: KOLON OLMAYAN her değer TEK KAYNAKTAN hesaplanır. Bu
modül saf (I/O'suz) fonksiyonlar tutar; DB'ye dokunan çakışma sorgusu
`repository.py`de, kural `service.py`dedir.

**`days` neden burada?** `LeaveRequest.days` bir KOLONdur ama SUNUCU hesabıdır
(spec §5 K2): istemci gönderemez. POST ve PATCH aynı fonksiyonu ÇAĞIRIR, formülü
KOPYALAMAZ — aksi hâlde tarih düzeltmesinde iki yol ayrışırdı.
"""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

# --- 4857 m.53 yıllık izin kademeleri (İK-2 spec §2, §5 K1) -----------------
#
# **TEK KAYNAK.** `annual_entitlement` KOLON DEĞİLDİR (K1): kolon açılırsa kıdem
# ilerlediğinde satır bayatlar ve iki gerçek kaynak doğar. Kademeler yalnız burada
# yazılıdır; servis/şema bu sayıları TEKRARLAMAZ.
#
# Sınırlar 4857 m.53 metnine göre BİLİNÇLİ olarak kapalıdır:
# * "bir yıldan **beş yıla kadar (beş dahil)**"  → tam 5 yıl **14** (20 DEĞİL),
# * "beş yıldan fazla onbeş yıldan az"           → 20,
# * "**onbeş yıl (dahil)** ve daha fazla"        → 26.
# Spec §2'nin kısaltılmış "1-5 / 5-15 / >15" yazımı bu iki uçta belirsizdi; her iki
# sınırda da yasanın DAHİL yönü seçildi ve bu yön aynı zamanda fail-closed'dur
# (sınırdaki kişiye bir üst kademe PEŞİN verilmez).
_TIER_ONE_YEARS = 1
_TIER_TWO_YEARS = 5
_TIER_THREE_YEARS = 15
_TIER_ONE_DAYS = 14
_TIER_TWO_DAYS = 20
_TIER_THREE_DAYS = 26

_MONTHS_IN_YEAR = 12


def calculate_leave_days(start_date: date, end_date: date) -> int:
    """İzin gün sayısı: **TAKVİM günü, başlangıç ve bitiş DAHİL** (spec §5 K2).

    Mockup (İZ) 04-08 Ağustos satırını "5 gün" gösterir; takvim hesabı bunu
    doğrular (08-04=4, +1 = 5). Hafta sonu/resmî tatil ÇIKARILMAZ — iş günü
    hesabı İK-3'ün işidir ve buraya sessizce eklenirse mevcut kayıtların `days`
    değeri geriye dönük anlamını değiştirirdi.

    Tek günlük izin 1'dir (0 DEĞİL) — `ck_leave_requests_days_positive` de bunu
    zorlar. Ters tarih ÇAĞIRANIN işidir (servis 422 verir): burada negatif dönmek
    yerine sessizce düzeltmek, hatalı gövdeyi geçirirdi.
    """
    return (end_date - start_date).days + 1


def leave_year(start_date: date, end_date: date) -> int:
    """Talebin sayıldığı YIL — **BAŞLANGIÇ tarihinin yılı** (İK-2 T3 kararı).

    Yıl sınırını aşan talep (31 Ara → 2 Oca) İKİYE BÖLÜNMEZ, tamamen başladığı
    yıla yazılır. Gerekçe iki katlıdır:

    * `days` TEK bir kolondur (spec §5 K2). Bölme yapılsaydı kaydın kendi `days`
      değeri ile bakiyeye giren değer AYRIŞIRDI — iki gerçek kaynak doğardı ve
      `used` toplamı hiçbir sorguyla `days` toplamına eşitlenemezdi.
    * Onay eşiği (K5) TEK bir yılın kalanına bakar. Bölünmüş talepte hangi yılın
      hakkının aşıldığı belirsizleşir; iki yılın da kalanını istemek ise mockup'ta
      olmayan bir kural uydurmak olurdu.

    `end_date` imzada DURUR ama kullanılmaz: çağıran taraf aralığı verir, kuralın
    hangi ucu seçtiği BURADA tek yerde okunur (çağıranlar `request.start_date.year`
    yazsaydı kural koda dağılır ve sessizce değiştirilebilirdi).
    """
    return start_date.year


def balance_reference_date(year: int, today: date) -> date:
    """Kıdemin ÖLÇÜLDÜĞÜ tarih: `min(bugün, yılın 31 Aralık'ı)`.

    Üç durumu tek formül kapsar ve ÜÇÜ DE fail-closed yöndedir:

    * **geçmiş yıl** → o yılın 31 Aralık'ı (yıl kapandı; kıdem yıl sonunda dondu),
    * **içinde bulunulan yıl** → BUGÜN (yıl içinde gelecek bir yıldönümünün
      getireceği üst kademe PEŞİN verilmez),
    * **gelecek yıl** → yine BUGÜN (aynı gerekçe, daha da uzak).

    `today` ENJEKTE EDİLİR (servis sınırı `timezone.today()` verir, test sabit tarih):
    kademe sınırları deterministik sınanabilsin.
    """
    return min(today, date(year, 12, 31))


def completed_service_months(hire_date: date | None, reference: date) -> int | None:
    """Referans tarihinde TAMAMLANMIŞ kıdem AYI — `hire_date` NULL ise **None**.

    🔴 None ile 0 AYNI ŞEY DEĞİLDİR (NULL-eşik kanonu): 0 "yeni işe girdi" der ve
    bir yıl sonra hak doğurur; None "veri yok" der ve onay yolunda engel üretir.
    Bu ayrım silinirse eksik veri "kıdemsiz" gibi davranır ve fark edilmez.

    Gün DÜZELTMESİ yapılır: yıldönümü GÜNÜ dolmadan o ay tamamlanmış sayılmaz
    (15 Oca girişli personel 14 Oca'da 23 ay, 15 Oca'da 24 aydır).

    Referanstan SONRAKİ işe giriş 0'a kırpılır — negatif kıdem uydurulmaz; sonuç
    yine "1 yıl dolmadı" olur (fail-closed).
    """
    if hire_date is None:
        return None
    months = (reference.year - hire_date.year) * _MONTHS_IN_YEAR + (
        reference.month - hire_date.month
    )
    if reference.day < hire_date.day:
        months -= 1
    return max(months, 0)


def _anniversary(hire_date: date, years: int) -> date:
    """İşe giriş tarihinin `years` yıl sonraki YILDÖNÜMÜ.

    29 Şubat girişi artık olmayan yılda 28 Şubat'a düşürülür — 1 Mart'a taşımak
    yıldönümünü bir gün GECİKTİRİR ve o gün başvuran kişiyi bir kademe aşağıda
    bırakırdı.
    """
    try:
        return hire_date.replace(year=hire_date.year + years)
    except ValueError:
        return hire_date.replace(year=hire_date.year + years, day=28)


def annual_entitlement(hire_date: date | None, reference: date) -> int | None:
    """4857 kademelerinden yıllık izin hakkı — **hak yoksa/bilinmiyorsa None**.

    Kademe sınırı YILDÖNÜMÜ TARİHİ ile karşılaştırılır, tamamlanmış YIL SAYISIYLA
    değil. Fark sınırda ısırır: "tam 5 yıl" ile "5 yıl 1 gün" tamamlanmış yıl
    sayısı olarak İKİSİ DE 5'tir, oysa yasa ilkine 14, ikincisine 20 gün verir.
    Yıl sayımına indirgemek 5 yıl 1 günlük personeli bir yıl boyunca 6 gün eksik
    hakla bırakırdı (`test_yillik_hak_kademe_sinirlari` bu kaymayı yakaladı).

    🔴 NULL-EŞİK KANONU (fail-closed): `hire_date` NULL ya da kıdem 1 yılı
    doldurmamışsa (İZ 163 "1 yıl dolunca hak kazanır") sonuç **None**'dur, 0
    DEĞİL. 0 döndürmek "hesap yapıldı, sonuç sıfır" der ve `remaining` 0 çıkarak
    devreden üzerinden onay yolunu açardı; None "hesaplanamadı" der ve
    `remaining_leave` ile onay kapısı bunu ENGELE çevirir.
    """
    if hire_date is None:
        return None
    if reference < _anniversary(hire_date, _TIER_ONE_YEARS):
        return None
    if reference <= _anniversary(hire_date, _TIER_TWO_YEARS):
        return _TIER_ONE_DAYS
    if reference < _anniversary(hire_date, _TIER_THREE_YEARS):
        return _TIER_TWO_DAYS
    return _TIER_THREE_DAYS


def remaining_leave(entitlement: int | None, carried_over: Decimal, used: int) -> Decimal | None:
    """Kalan = hak + devreden − kullanılan (İZ doğrulaması: 14 + 3 − 6 = 11).

    🔴 Hak None ise sonuç da **None**'dur — devreden DOLU olsa bile. `None + 3`'ü
    3 saymak, kıdemi dolmamış personele onay kapısını açardı (fail-closed).

    Sonuç NEGATİF çıkabilir ve 0'a KIRPILMAZ: elle düzeltilmiş bakiye ya da
    geçmişte onaylanmış fazla izin bir borçtur ve ekranda görünmelidir.
    """
    if entitlement is None:
        return None
    return Decimal(entitlement) + carried_over - Decimal(used)


def usage_pct(entitlement: int | None, carried_over: Decimal, used: int) -> int | None:
    """Kullanım yüzdesi (İZ ilerleme çubuğu) — tam sayıya YARIM YUKARI yuvarlanır.

    Mockup doğrulaması: 6/17 = %35.29 → **35**; 5/14 = %35.71 → **36**; 12/20 → **60**.

    Hak None ise ya da payda (hak + devreden) 0 ise **None** — yüzde TANIMSIZDIR;
    0 ya da 100 uydurmak ekranda "hiç kullanmadı" ya da "doldu" yanılsaması yaratırdı.
    """
    if entitlement is None:
        return None
    toplam = Decimal(entitlement) + carried_over
    if toplam <= 0:
        return None
    yuzde = (Decimal(used) / toplam * 100).to_integral_value(rounding=ROUND_HALF_UP)
    return int(yuzde)
