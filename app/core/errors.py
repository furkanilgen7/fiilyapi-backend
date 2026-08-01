class DomainError(Exception):
    """Alan kuralı ihlali. Router katmanı bunu uygun HTTP koduna çevirir."""


class PermissionLockedError(DomainError):
    """system_admin rolünün izinleri değiştirilemez (kilitlenme koruması, spec §5.0)."""


class DeleteNotAllowedError(DomainError):
    """Silme koşulları sağlanmadı (spec §5.0)."""


class NotFoundError(DomainError):
    """İstenen kayıt bulunamadı — router katmanı 404'e çevirir."""


class ProjectTypeMismatchError(DomainError):
    """Tip uzantısı proje tipiyle uyuşmuyor (Alt-Proje 2 P1 spec §3.5) — 422."""


class ProjectValidationError(DomainError):
    """Proje oluşturma iş kuralı ihlali (spec §3.6: zorunluluk, tarih sırası, endeks) — 422.

    Pydantic alan doğrulamasının ötesinde, taslak-farkındalıklı ve alanlar-arası
    kurallar için. Mesaj Türkçe ve kullanıcıya gösterilir.
    """


class SiteValidationError(DomainError):
    """Şantiye formu iş kuralı ihlali (spec §5.1, §7.2) — 422.

    `ProjectValidationError` deseninin aynısı ve aynı ayrımı taşır: Pydantic'in
    alan doğrulamasının ötesinde, TASLAK-FARKINDALIKLI ve alanlar-arası kurallar
    için. Kural: tutarlılık kuralları her zaman, zorunluluk kuralları yalnız
    taslak-dışında koşar — böylece yarım kalmış taslak geçersiz değil yalnız
    eksik veri saklar. Mesaj Türkçe ve doğrudan kullanıcıya gösterilir.
    """


class DuplicateError(DomainError):
    """Benzersiz olması gereken bir değer zaten kayıtlı (spec §3.2) — router 409'a çevirir.

    Servis, IntegrityError'a düşmeden ÖNCE açık bir SELECT ile bunu fırlatır ki
    kullanıcıya alanına özel Türkçe mesaj verilebilsin. IntegrityError → 409 handler'ı
    yarış durumu emniyet ağı olarak KALIR.
    """


class UnitValidationError(DomainError):
    """Blok/ünite iş kuralı ihlali (Alt-Proje 2 P3 spec §4.5, §7.11) — 422.

    `BoqGroupSiteMismatchError` deseninin aynısı: DB `CHECK` ile zorlanamayan ya da
    zorlansa bile kullanıcıya Türkçe mesaj veremeyecek kurallar (şantiye sayısına
    bağlı blok ataması, `net > brüt`) tek yazma yolunda servis korkuluğuyla tutulur.
    """


class RelatedRecordsExistError(DomainError):
    """Silinmek istenen kayda bağlı alt kayıtlar var (Alt-Proje 2 P3 spec §7.9) — 409.

    `DeleteNotAllowedError` (403) YETKİ engelidir; bu ise ÇAKIŞMA'dır: kullanıcının
    yetkisi vardır ama kaydın durumu silmeye elverişli değildir. İkisini tek sınıfta
    toplamak, "yetkin yok" ile "önce alt kayıtları sil" mesajlarını aynı koda düşürür.

    Cascade'e KAYILMAZ: ünitesi olan blok silinirse 24 daire tek istekte gider ve
    geri alınamaz. DB tarafındaki `ON DELETE RESTRICT` (spec §4.2) ikinci katmandır.
    """


class BoqGroupSiteMismatchError(DomainError):
    """Poz kaleminin bağlanmak istediği grup, hedef şantiyeye ait değil

    (Alt-Proje 2 P4 spec §3.3 invariant 1, §5.4) — 422. DB'de bileşik FK
    açılmadığı için (P1 §3.5 gerekçesi) tek yazma yolunda servis korkuluğu.
    """


class ConflictError(DomainError):
    """Durum makinesi / iş kuralı çakışması — 409 (P7 hakediş spec §7, §9.2, §9.7).

    `DuplicateError`'dan (benzersizlik ihlali) kasıtlı olarak AYRI: burada
    çakışan şey bir alan değeri değil, kaydın MEVCUT DURUMU — açık hakediş
    varken ikincisinin açılamaması (D8/`OPEN_PAYMENT_EXISTS`), taslak
    dışındayken yazılamaması (`INVALID_STATUS_TRANSITION`), onaylanmış/ödenmiş
    kaydın silinememesi (`PAYMENT_NOT_DELETABLE`) gibi. `RelatedRecordsExistError`
    (bağlı alt kayıt) semantiğine de UYMADIĞI için P7 ile birlikte açılır.
    """
