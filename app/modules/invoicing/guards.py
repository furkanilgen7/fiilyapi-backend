"""Fatura korkulukları ve Türkçe hata metinleri (FAT-1 spec §6, §7).

`procurement/guards.py` deseninin kardeşi: hata SINIFLARI `app/core/errors.py`de,
METİNLER burada TEK kopya sabit olarak durur; router'a ya da servise gömülü
string YAZILMAZ. (Durum makinesinin iki metni `transitions.py`de kalır — orası
geçişin tek kaynağıdır ve metni oradan ayırmak kuralı ikiye bölerdi.)

## Hangi kural hangi koda düşer (ST §4b kanonu)

| Durum | Kod | Sınıf |
|---|---|---|
| Görünmeyen ya da var olmayan fatura | 404 | `NotFoundError` |
| Gövdedeki proje/şantiye/taraf/kaynak referansı görünmüyor ya da yok | 404 | `NotFoundError` |
| Biçim ihlali (uzunluk, ölçek, `limit` tavanı, gönderilemez alan) | 422 | Pydantic |
| Alanlar-arası kural (tek taraf/kaynak · numara sahibi · oran) | 422 | `InvoicingValidationError` |
| Düzenleme/silmeye kapalı DURUM | 409 | `ConflictError` |
| Aynı yönde aynı fatura numarası | 409 | `DuplicateError` |

**Kanon tek cümledir:** *görünmez/yok VARLIK referansı = 404 · biçim/kural
ihlali = 422.* Durum çakışması 409'dur, 403 DEĞİL: kullanıcının yetkisi VARDIR,
engelleyen şey kaydın DURUMUDUR.
"""

PERMISSION_MODULE = "invoicing"
"""Spec §6: izin anahtarı seed'de ZATEN vardı ("Fatura Yönetimi", grup MALI,
`sort_order: 13`) — **yeni izin modülü AÇILMAZ, izin migration'ı YOKTUR.**

Matris satırı `"invoicing": [_A, _F, _N, _N, _N, _F, _V, _N]`, yani kapılar:
* okuma (`view`)  → PM · muhasebe · patron · sysadmin
* yazma (`full`)  → muhasebe · patron · sysadmin (**PM yazamaz**)
* silme (`admin`) → YALNIZ sysadmin — `full` silmeyi KAPSAMAZ (repo kanonu)

Sabit `service.py`de DEĞİL burada durur (`procurement.guards` emsali): hem
router hem servis hem testler ona ihtiyaç duyar ve `repository → service`
ithalatı ileride döngüye girebilirdi.
"""

__all__ = [
    "INCOMING_PATCHABLE_FIELDS",
    "INCOMING_PATCH_FIELDS_LIMITED",
    "INVOICE_DUPLICATE_NO",
    "INVOICE_MISSING",
    "INVOICE_NO_AMBIGUOUS",
    "INVOICE_PARTY_INVALID",
    "INVOICE_PROJECT_INVALID",
    "INVOICE_SITE_INVALID",
    "INVOICE_SOURCE_INVALID",
    "PERMISSION_MODULE",
    "SINGLE_PARTY_ONLY",
    "SINGLE_SOURCE_ONLY",
]

# 404 — görünmeyen fatura ile var olmayan fatura AYNI gövdeyi alır. 403
# verilseydi elinde kimlik olan kullanıcı kaydın var olduğunu öğrenirdi.
INVOICE_MISSING = "Fatura bulunamadı"

#: URL-4 — `invoice_no` ŞİRKET GENELİ TEKİL DEĞİLDİR: `uq_invoices_no_direction`
#: (`direction`, `invoice_no`) yalnız YÖN BAŞINA tekilliği zorlar, yani aynı
#: numara bir GELEN ve bir GİDEN faturada aynı anda bulunabilir. Böyle bir
#: numarayla gelen istekte SESSİZCE BİRİ SEÇİLMEZ (yönetim kararı 2026-09-05):
#: kullanıcı hangi faturayı açtığını bilemezdi ve seçim, satır sırası gibi
#: TANIMSIZ bir şeye bağlı olurdu.
INVOICE_NO_AMBIGUOUS = (
    "Bu fatura numarası hem gelen hem giden faturada kayıtlı — "
    "faturayı listeden ya da kimliğiyle açın"
)

# 404 — gövdedeki `project_id` görünmüyor ya da hiç yok. İki durum AYNI cümleyi
# alır; ayrı cümleler kimliğin varlığını ele verirdi.
INVOICE_PROJECT_INVALID = "Seçilen proje bulunamadı"

# 404 — `site_id` yok, görünmüyor YA DA faturanın projesine ait değil. Üçüncü
# dal da aynı cümleyi alır: başka projenin şantiyesi bu fatura için "yok"tur.
INVOICE_SITE_INVALID = "Seçilen şantiye bulunamadı"

# 404 — dört taraf kartından (işveren · alıcı · tedarikçi · taşeron) verilen
# kimlik katalogda YOK. Metin HANGİ alanın hatalı olduğunu söylemez: en fazla
# biri dolu olabildiği için zaten tektir ve kimlik sızdırmaz.
INVOICE_PARTY_INVALID = "Seçilen cari kart bulunamadı"

# 404 — dört kaynak kaydından (hakediş · taşeron hakedişi · makine kira
# hakedişi · sipariş) verilen kimlik yok YA DA projesi görünmüyor. Bu, gövde
# içi varlık referansının IDOR ayağıdır (ST kanonu) — 403 DEĞİL.
INVOICE_SOURCE_INVALID = "Seçilen kaynak kayıt bulunamadı"

# 422 — `ck_invoices_single_party` servis katmanında ÖNCE yakalanır. DB CHECK'i
# son savunmadır; ihlali 409 "Veri bütünlüğü hatası" olarak dönerdi ve kullanıcı
# hangi iki alanı birden doldurduğunu öğrenemezdi.
SINGLE_PARTY_ONLY = "Faturaya yalnızca bir taraf kartı bağlanabilir"

# 422 — `ck_invoices_single_source`un aynısı. Kaynak izi tektir: bir fatura hem
# hakedişten hem siparişten doğamaz, doğsaydı tutarın dayanağı belirsizleşirdi.
SINGLE_SOURCE_ONLY = "Faturaya yalnızca bir kaynak kayıt bağlanabilir"

#: Gelen faturada PATCH'in dokunabildiği ALANLAR — spec §7 md.5.
#: Gelen fatura SATICININ belgesidir: tutarını, tarafını ya da kalemini biz
#: düzeltemeyiz (K7 snapshot'ı da bunu gerektirir). Düzeltilebilen tek şey BİZE
#: ait olan üç alandır: vade, ödeme şekli ve iç not.
INCOMING_PATCHABLE_FIELDS = frozenset({"note", "due_date", "payment_method"})

# 422 — yukarıdaki kümenin dışında bir alan gelen faturada gönderildi.
INCOMING_PATCH_FIELDS_LIMITED = (
    "Gelen faturada yalnızca vade tarihi, ödeme şekli ve not düzeltilebilir"
)

# 409 — `uq_invoices_no_direction`. Tekillik YÖN İÇİNDEDİR: satıcının `FIL…`
# serisi bizim numaramızı bloklamaz. Servis IntegrityError'a düşmeden ÖNCE açık
# bir SELECT ile bunu fırlatır ki kullanıcı Türkçe ve alanına özel mesaj alsın.
INVOICE_DUPLICATE_NO = "Bu fatura numarası bu yönde zaten kayıtlı"
