"""Personel belgesi DURUM TÜREVİ — TEK KAYNAK (İK-1 spec §2, §3, §5 K1).

Durum bir KOLON DEĞİL, `valid_until` + tip `validity_months` üzerinden HESAPLANIR.
Bu modül o hesabın TEK yeridir: T3 belge uçları da, T4 `GET /hr/documents/summary`
de AYNI fonksiyonu çağırır. İki farklı yerde "expiring eşiği kaç gün" kararı
verilirse KPI ile satır durumu ayrışır — bu yüzden eşik burada TEK sabittir.

## Kapsam: TEKİL belge → `valid` / `expiring` / `expired`

`missing` BURADA DEĞİLDİR: o "zorunlu bir tip için AKTİF personelde hiç kayıt
olmaması" TÜREVİDİR ve kişi+tip düzeyinde, kayıt YOKLUĞU üzerinden hesaplanır
(T4 summary). Tekil bir belgenin durumu asla `missing` olamaz — belge vardır.

## `valid_until` NULL kararı (spec §5 K1, yönetimce bağlı)

* `valid_until` NULL + tip süresiz (`validity_months` NULL) → `valid` (süresiz belge).
* `valid_until` NULL + tip süreli (`validity_months` DOLU) → yine `valid`: kullanıcı
  henüz geçerlilik tarihini girmemiştir, süre takibi BAŞLAMAMIŞTIR. `expiring`/
  `expired` DEĞİL — eldeki tek olgu "tarih yok"tur ve bir tarih uydurmak (ör.
  `issued_at + validity_months`) kullanıcının girmediği bir sınırı ona dayatırdı.

`validity_months` bugün için durum SONUCUNU değiştirmez (yalnız `valid_until`
girilir); parametre response'a tip künyesini taşımak ve ileride türetilmiş
`valid_until` gerekirse tek yerde durması için imzada TUTULUR.
"""

from datetime import date

EXPIRING_THRESHOLD_DAYS = 30
"""`expiring` penceresi (spec §2/§3): bugün ≤ `valid_until` ≤ bugün+30 → yaklaşıyor.

30 DAHİL, 31 HARİÇ (sınır testli). Eşik TEK yerdedir: KPI, satır rozeti ve
summary aynı sayıyı okur; iki kopya olsaydı ekranın iki köşesi farklı sayardı.
"""

STATUS_VALID = "valid"
STATUS_EXPIRING = "expiring"
STATUS_EXPIRED = "expired"


def derive_document_status(
    valid_until: date | None,
    validity_months: int | None,
    *,
    today: date,
) -> str:
    """Bir belgenin durumunu döndürür (`valid`/`expiring`/`expired`).

    `today` ENJEKTE EDİLİR (servis `date.today()` verir, test sabit tarih verir):
    saat farkına bağlı bir testin gece yarısı kırılmaması için sınır günleri
    deterministik olmalıdır.

    Sıra önemlidir — önce "tarih yok", sonra "geçmiş", sonra "yaklaşan":
    * `valid_until` NULL → `valid` (spec §5 K1 kararı; süre takibi başlamamıştır).
    * `valid_until` < bugün → `expired`.
    * bugün ≤ `valid_until` ≤ bugün + 30 gün → `expiring` (30 dahil, 31 hariç).
    * aksi hâlde → `valid`.
    """
    if valid_until is None:
        return STATUS_VALID
    if valid_until < today:
        return STATUS_EXPIRED
    if (valid_until - today).days <= EXPIRING_THRESHOLD_DAYS:
        return STATUS_EXPIRING
    return STATUS_VALID


def days_until(valid_until: date | None, *, today: date) -> int | None:
    """`valid_until`e kalan gün (negatif = geçmiş); tarih yoksa None.

    Türev alan; response'un `days_left`i buradan gelir ki hesap tek yerde dursun.
    """
    if valid_until is None:
        return None
    return (valid_until - today).days
