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


class CustomerValidationError(DomainError):
    """Alıcı (müşteri) tip/kimlik kuralı ihlali (P8 spec §2) — 422.

    `UnitValidationError` deseninin aynısı: DB `CHECK` ile zorlanamayan
    (`person` -> TCKN, `company` -> VKN) ve zorlansa bile kullanıcıya Türkçe
    mesaj veremeyecek kural, tek yazma yolunda servis korkuluğuyla tutulur.
    Pydantic'te DEĞİL: PATCH kısmi gövde gönderir, kural ancak DB'deki kayıtla
    birleştirilmiş değerler üzerinde anlamlıdır.
    """


class PersonnelValidationError(DomainError):
    """Personel kaynak/taşeron uyuşmazlığı (puantaj spec §2) — 422.

    `CustomerValidationError` deseninin aynısı: DB `CHECK`
    (`ck_personnel_subcontractor_only_for_subcontractor_source`) VARDIR ama ihlali
    409 "Veri bütünlüğü hatası" verirdi; kullanıcı hangi alanı düzelteceğini
    öğrenemezdi. Servis korkuluğu DB'ye düşmeden Türkçe 422 atar, CHECK ikinci
    katman olarak kalır. Pydantic'te DEĞİL: PATCH kısmi gövde gönderir, kural
    ancak DB'deki kayıtla birleştirilmiş değerler üzerinde anlamlıdır.
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


class DocumentValidationError(DomainError):
    """Belge/klasör kapsam kuralı ihlali (belge çekirdeği spec §2, §3) — 422.

    `UnitValidationError`/`CustomerValidationError` deseninin aynısı: DB ile
    zorlanamayan (klasörün `site_id`/`parent_id`sinin AYNI kapsamda olması)
    kurallar tek yazma yolunda servis korkuluğuyla tutulur. 404 DEĞİL: istenen
    kaynak projedir, `site_id`/`parent_id` gövdedeki düzeltilebilir ALAN
    DEĞERLERİDİR; 404 verilseydi ekran "proje yok" ile "şantiye başka projede"yi
    ayırt edemezdi.
    """


class ProcurementValidationError(DomainError):
    """Satınalma iş kuralı ihlali (SA spec §3) — 422.

    `DocumentValidationError`/`PersonnelValidationError` deseninin aynısı: DB
    `CHECK` ile zorlanamayan ya da zorlansa bile kullanıcıya Türkçe mesaj
    veremeyecek kurallar tek yazma yolunda servis korkuluğuyla tutulur. İki
    kullanıcısı vardır:

    * `submit` engelleri — TASLAK-FARKINDALIKLI zorunluluklar (`validation.
      submit_blockers`); taslakta gevşek, onaya gönderirken sıkı. Tüm engeller
      TEK gövdede birleşir, çünkü uzun bir formda eksikleri birer birer
      keşfettirmek kabul edilemez.
    * teklifin nakliye kuralı — PATCH kısmi gövde gönderir, kural ancak
      DB'deki kayıtla BİRLEŞTİRİLMİŞ değerler üzerinde anlamlıdır; bu yüzden
      Pydantic'te değil serviste koşar.

    404 DEĞİL: istenen kaynak vardır ve görünür, ihlal eden şey düzeltilebilir
    ALAN DEĞERLERİDİR. 409 da DEĞİL: engel kaydın DURUMU değil İÇERİĞİDİR.
    """


class ApprovalNotAllowedError(DomainError):
    """Onay YETKİSİ tutar eşiğini karşılamıyor (SA spec §3, §7 S2) — 403.

    `DeleteNotAllowedError`in kardeşi ve aynı sebeple ondan AYRI: ikisi de
    yetki engelidir ama biri silmeye, öteki onaya bakar; tek sınıfta
    toplanırlarsa mesajlar da tek yerde toplanır ve "silme yetkiniz yok"
    cümlesi bir onay ucundan dönerdi.

    409 DEĞİL: kayıt DOĞRU durumdadır (`pending_approval`), engelleyen şey
    AKTÖRÜN SEVİYESİDİR — başka bir kullanıcı aynı anda onaylayabilir. 422 da
    değildir: gövdede düzeltilecek bir alan yoktur.
    """


class PayrollValidationError(DomainError):
    """Bordro para kuralı ihlali (İK-3 spec §6/1, §6/3) — 422.

    `ProcurementValidationError`/`PersonnelValidationError` deseninin aynısı ve
    aynı sebeple onlardan AYRI: DB `CHECK` ile zorlanamayan kurallar tek yazma
    yolunda servis korkuluğuyla tutulur. İki kullanıcısı vardır:

    * **S3 invariantı** (`banka + elden = net`) — DB CHECK'i OLAMAZ çünkü üç
      kolonun da NULL olabildiği `uncomputed` durumda CHECK ya S4'ü kırar ya da
      hiçbir şey zorlamaz (`payroll/models.py` gerekçesi). Ayrıca ihlali
      409/500 olarak dönmek kullanıcıya hangi kuruşun kaydığını söylemezdi.
    * **fail-closed hesap engelleri** — oran seti yokken brüt override'ı,
      neti hesaplanmamış satırda bölüşüm.

    409 DEĞİL: kayıt DOĞRU durumdadır (`pending`), engelleyen şey GÖVDEDEKİ
    düzeltilebilir alan değerleridir. 404 da değildir: satır vardır ve görünür.
    """


class EquipmentValidationError(DomainError):
    """Makine & ekipman iş kuralı ihlali (MK-1 spec §3) — 422.

    `PayrollValidationError`/`ProcurementValidationError` deseninin aynısı ve
    aynı sebeple onlardan AYRI: DB `CHECK` ile zorlanamayan ya da zorlansa bile
    kullanıcıya Türkçe mesaj veremeyecek kurallar tek yazma yolunda servis
    korkuluğuyla tutulur. Kullanıcıları:

    * **K2 — koşullu zorunluluk** (`ownership == owned` iken `purchase_amount`).
      CHECK OLAMAZ: kural kısmi PATCH'te ancak DB'deki kayıtla BİRLEŞTİRİLMİŞ
      değerler üzerinde anlamlıdır.
    * (T4) K11 `hours` sunucu hesabının gövde kuralları ve K12 günlük tavan.

    404 DEĞİL: kayıt vardır ve görünür, ihlal eden şey düzeltilebilir ALAN
    DEĞERLERİDİR. 409 da DEĞİL: engel kaydın DURUMU değil İÇERİĞİDİR.
    """


class InvoicingValidationError(DomainError):
    """Fatura gövde kuralı ihlali (FAT-1 spec §2, §5) — 422.

    `EquipmentValidationError`/`ProcurementValidationError` deseninin aynısı ve
    aynı sebeple onlardan AYRI: DB `CHECK` ile zorlanamayan ya da zorlansa bile
    kullanıcıya Türkçe mesaj veremeyecek kurallar tek yazma yolunda servis
    korkuluğuyla tutulur. Kullanıcıları:

    * **`ck_invoices_single_party` / `ck_invoices_single_source`** — CHECK'ler
      VARDIR (T1) ama ihlalleri 409 "Veri bütünlüğü hatası" olarak dönerdi ve
      kullanıcı hangi iki alanı birden doldurduğunu öğrenemezdi. DB SON
      savunmadır; kullanıcıya 500/409 gitmez.
    * **numaranın sahibi** (§4/S5): giden faturada istemci numara gönderemez,
      gelen faturada göndermek ZORUNDADIR.
    * **kesinti oranları toplamı** (`validation.body_blockers`): %100'ü aşan
      toplam `tax_base`i negatife düşürür ve DB CHECK'i ancak KDV'den sonra,
      okunamaz bir hatayla yakalardı.
    * **gelen faturada PATCH kapsamı**: satıcının belgesinin tutarı bizim
      düzeltebileceğimiz bir alan değildir.

    404 DEĞİL: kayıt vardır ve görünür, ihlal eden şey düzeltilebilir ALAN
    DEĞERLERİDİR. 409 da DEĞİL: engel kaydın DURUMU değil İÇERİĞİDİR.
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
