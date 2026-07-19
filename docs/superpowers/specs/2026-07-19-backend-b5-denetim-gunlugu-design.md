# FİİL Yapı ERP — Backend B5: Denetim Günlüğü — Tasarım

**Tarih:** 2026-07-19
**Alt-Proje:** 1 (Temel) · **Faz:** B5
**Bağımlılık:** B1-B4 (main'de + canlı). Sonraki: F5 (Ayarlar frontend) bu faza bağımlı.
**Kaynak spec:** `docs/superpowers/specs/2026-07-17-temel-modul-design.md` (§ `audit_log` tablosu, §8 Fazlar)
**Mockup:** `../projedesign/Ayarlar - Denetim Günlüğü.dc.html`

---

## 1. Amaç ve kapsam

Sistemdeki tüm anlamlı yazma işlemlerini (giriş, oluşturma, güncelleme, silme, onay,
yedekleme) değiştirilemez bir denetim günlüğüne kaydetmek; bu günlüğü filtrelenebilir bir
liste ucu ve Excel dışa aktarımı ile sunmak.

**Kapsam içi:** `audit_log` tablosu + migration; servis-katmanı kayıt altyapısı
(`record_audit`); tüm mevcut B1-B4 yazma noktalarının bağlanması; filtreli okuma ucu;
Excel export ucu; yetki kapısı; testler.

**Kapsam dışı:** gerçek yedekleme/onay üreticileri (Alt-Proje 7 / sonraki fazlar — enum
değerleri hazır tutulur, üretici uç yok); tercih değişikliklerinin (görünüm/bildirim,
self-service, düşük değer/yüksek gürültü) kaydı; audit satırı silme/arşivleme/purge
(v1'de kayıtlar süresiz saklanır).

---

## 2. Kararlar (kullanıcı onaylı)

1. **Yakalama = servis-katmanı açık kaydı.** Jenerik middleware / ORM event listener
   yerine, her anlamlı yazma noktası `record_audit(...)` çağırır ve **zengin, domaine özel
   Türkçe `detail` metnini çağrı noktasında** yazar. Gerekçe: mockup "Kullanıcı rolü
   değiştirildi: Kadir Arslan → PM", "Hakediş #47 onaylandı · ₺1.240.000" gibi metinler
   istiyor; jenerik yakalama bunları üretemez.
2. **Kapsam = tüm B1-B4 yazma noktaları.** Altyapı + login, kullanıcı CRUD+parola,
   rol oluştur/rename/sil, izin matrisi değişikliği, şirket güncelleme+logo. Böylece ekran
   ilk günden gerçek veriyle dolu. Tercih değişiklikleri hariç.
3. **Atomiklik = aynı transaction.** Audit satırı asıl işlemle **aynı commit'te** yazılır.
   İşlem geri alınırsa audit de yazılmaz; audit yazıldıysa işlem kesin oldu. Denetim izinde
   boşluk/hayalet kayıt olmaz.

**Mimari teyit:** `app/core/db.py` içinde commit'i **`get_db` bağımlılığı sahiplenir**
(temiz çıkışta tek `session.commit()`, hata olursa rollback). Servisler yalnızca
`session.add()` yapar. Dolayısıyla `record_audit` satırı aynı request-session'a
`add` edildiğinde asıl işlemle otomatik aynı commit'e girer — atomiklik doğal olarak
sağlanır, ek commit/transaction yönetimi gerekmez.

---

## 3. Veri modeli — `audit_log`

Kaynak spec'teki şema birebir uygulanır.

| Alan | Tip | Not |
|---|---|---|
| `id` | UUID PK | `uuid4` default |
| `occurred_at` | timestamptz | server default `now()` |
| `actor_user_id` | FK → `users.id`, **nullable** | null → aktör "Sistem" |
| `action` | enum `audit_action` | `login·create·update·delete·approve·backup` |
| `detail` | text, NOT NULL | insan-dostu Türkçe açıklama |
| `ip_address` | inet, nullable | sistem işlemlerinde / IP alınamazsa null |

**Migration:** yeni revizyon, `down_revision = 6c98d5b8b142` (B4 head). PG `audit_action`
enum tipi oluşturulur. Additive — canlı oturumları etkilemez.

**İndeksler:**
- `ix_audit_log_occurred_at` (`occurred_at DESC`) — varsayılan sıralama.
- `ix_audit_log_actor_user_id` — aktör filtresi.
- `ix_audit_log_action` — işlem filtresi.

**Değiştirilemezlik:** modelde ve router'da hiçbir UPDATE/DELETE ucu yoktur. Yalnızca
insert (servis üzerinden) ve select.

---

## 4. Yakalama altyapısı — `app/modules/audit/`

Modül iskeleti diğer modüllerin desenini izler (`models.py`, `repository.py`,
`service.py`, `schemas.py`, `router.py`).

- **`models.py`** — `AuditLog` SQLAlchemy modeli; `AuditAction` StrEnum
  (proje UP042 istisnasıyla StrEnum kullanır).
- **`service.py`** — `record_audit(session, *, action, detail, actor_user_id=None,
  ip_address=None) -> None`. Yeni `AuditLog` örneğini `session.add()` eder; **commit
  ETMEZ** (request-session ile birlikte commit = atomik). İş kuralı yok, saf kayıt.
- **`repository.py`** — okuma sorguları: filtreli+sayfalı liste (`occurred_at DESC`),
  toplam sayım, `actor` (User+Role) join'i. Filtreler: `actor_user_id`, `action`,
  `date_from`, `date_to` (hepsi opsiyonel, AND'lenir).
- **IP çıkarımı** — `app/core/ratelimit.py:_client_ip` (XFF-aware; Railway proxy arkasında
  `X-Forwarded-For`'un ilk girdisi, yoksa `request.client.host`) yeniden kullanılır.
  Ortak kullanım için gerekirse `app/core`'a taşınabilir/paylaşılabilir; davranış birebir
  korunur.

**Çağrı deseni:** `record_audit` çağrıları **router katmanında** yapılır (orada `Request`
ve `current_user` mevcut). Router aktör id'sini, IP'yi ve Türkçe detay metnini üretip
servise/`record_audit`'e geçer. Servis fonksiyonları HTTP'den bağımsız kalır. Detay metni
kısa bir yardımcıyla (ör. `app/modules/audit/messages.py`) tutarlı biçimde üretilebilir,
ama zorunlu değil.

---

## 5. Bağlanacak yazma noktaları (tüm B1-B4)

| Uç | action | Örnek `detail` |
|---|---|---|
| `POST /auth/login` (yalnız başarılı) | `login` | "Sisteme giriş yapıldı" |
| `POST /users` | `create` | "Kullanıcı oluşturuldu: Ahmet Yılmaz · Muhasebe" |
| `PATCH /users/{id}` | `update` | "Kullanıcı güncellendi: Ahmet Yılmaz" (değişen alanlar özetlenebilir) |
| `DELETE /users/{id}` | `delete` | "Kullanıcı silindi: Ahmet Yılmaz" |
| `PATCH /users/{id}/password` | `update` | "Kullanıcı parolası sıfırlandı: Ahmet Yılmaz" |
| `PUT /users/{id}/project-access` | `update` | "Proje erişimi güncellendi: Ahmet Yılmaz" |
| `POST /roles` | `create` | "Özel rol oluşturuldu: Depo Sorumlusu" |
| `PATCH /roles/{id}` | `update` | "Rol yeniden adlandırıldı: Depo Sorumlusu" |
| `DELETE /roles/{id}` | `delete` | "Rol silindi: Depo Sorumlusu" |
| `PUT /roles/{id}/permissions/{module_key}` | `update` | "İzin değişti: Muhasebe · Hakediş → approve" |
| `PUT /company` | `update` | "Şirket bilgileri güncellendi" |
| `POST /company/logo` | `update` | "Şirket logosu güncellendi" |
| `DELETE /company/logo` | `update` | "Şirket logosu kaldırıldı" |

**Hariç:** `PUT /settings/preferences`, `PUT /settings/notifications` (self-service,
düşük değer, yüksek gürültü). `approve`/`backup` enum'da hazır; Alt-Proje 1'de üretici
uç yok — gelecek modüller (hakediş onayı, yedekleme) kendi kayıtlarını bağlar.

> Not: detay metinlerinin tam sözcüğü uygulama sırasında netleşir; tablo örnek/niyet
> gösterir. Metinler kısa, Türkçe ve mockup diliyle tutarlı olmalı.

---

## 6. Okuma + Excel dışa aktarım

**`GET /audit-log`** — filtreli, sayfalı liste.
- Query: `actor_user_id` (uuid, ops.), `action` (enum, ops.), `date_from` (datetime, ops.),
  `date_to` (datetime, ops.), `limit` (default makul, ör. 50), `offset` (default 0).
- Yanıt: `AuditListResponse` zarfı — `items` / `total` / `limit` / `offset`
  (`UserListResponse` desenindeki gibi). Her `item`: `id`, `occurred_at`, `action`,
  `detail`, `ip_address`, `actor` (`{id, full_name, role_name}` veya null→"Sistem").
- Sıralama: `occurred_at DESC`.
- Frontend preset'leri (Son 7 Gün / Son 30 Gün / Bu Ay) `date_from`/`date_to`'ya map'ler —
  backend esnek aralık alır, preset bilmez.

**`GET /audit-log/export.xlsx`** — aynı filtre parametreleri (limit/offset hariç: tüm
eşleşen kayıtlar).
- openpyxl ile üretim (**yeni bağımlılık**: `openpyxl` → `pyproject.toml` `dependencies`;
  saf-wheel, Docker-safe).
- Sütunlar: Zaman · Kullanıcı · İşlem · Detay · IP Adresi (mockup başlıkları).
- **Tüm hücreler string** (B4 dersi: openpyxl `Decimal`'i sessizce `float`'a coerce eder;
  burada sayısal alan yok ama kural olarak metin/timestamp string yazılır — FLOAT-YASAK).
- `Content-Disposition: attachment; filename="denetim-gunlugu.xlsx"`, doğru MIME
  (`application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`).

**Yetki (her iki uç):** `settings` modülü ≥ `view` (`require_permission("settings",
AccessLevel.VIEW)`). Seed matrisinde yalnızca Sistem Yöneticisi'nde `settings=admin`;
diğer 7 rol `none` → 403. Mockup'ta Denetim Günlüğü Sistem/Ayarlar bölümünde.

---

## 7. Güvenlik ve kenar durumlar

- **Değiştirilemez:** audit satırı için UPDATE/DELETE ucu yok; yalnız insert + select.
- **Aktör null → "Sistem"**, **ip null → "—"** (sunum katmanında; DB'de null).
- **Başarısız login** audit'e yazılmaz (yalnızca başarılı `/auth/login`). Gelecekte
  başarısız giriş denemesi ayrı bir güvenlik olayı olarak ele alınabilir — v1 dışı.
- **Atomiklik riski:** audit insert asıl işlemle aynı commit'te; basit tek-satır insert
  olduğu için başarısızlık olasılığı düşük. Başarısız olursa asıl işlem de rollback olur
  (bilinçli seçim — denetim izninde boşluk olmaz).
- **Migration additive**, default'suz zorunlu alan yok (mevcut satır yok, tablo boş
  başlar) → canlı deploy güvenli, oturumlar düşmez.
- IP başlığı sahtelenebilir (XFF); v1'de kabul edilen ödünç (ratelimit ile aynı model).

---

## 8. Test stratejisi (%80+ kapsam)

- **`record_audit` birim:** satır aynı session'a eklenir; op rollback edildiğinde audit
  yazılmaz (atomiklik); actor/ip null yolları.
- **Bağlı uç başına entegrasyon:** işlem sonrası tam olarak bir audit satırı, doğru
  `action` ve beklenen `detail` çekirdeğiyle oluşur; tercih uçları audit üretmez.
- **Okuma:** filtre matrisi (actor / action / date_from-date_to / kombinasyon), sayfalama
  (limit/offset, total), sıralama (`occurred_at DESC`), actor null→"Sistem".
- **Yetki:** `settings < view` (patron dahil diğer roller) → 403; Sys.Yön → 200.
- **Excel:** doğru sütun/başlık, hücrelerin string oluşu, filtrelerin export'a uygulanışı,
  MIME + Content-Disposition.
- **Migration:** up → down → up temiz (Postgres); enum tipi oluşur/düşer.

**Kalite kapıları (kaynak spec §11):** ruff check+format temiz; %80+ kapsam;
`fastapi-reviewer` + auth/izin dokunuşu olduğu için `security-reviewer`; migration
ampirik Postgres up/down/up doğrulaması.

---

## 9. Dosya envanteri (öngörülen)

```
app/modules/audit/
  __init__.py
  models.py        # AuditLog + AuditAction enum
  schemas.py       # AuditListResponse, AuditItem, AuditActorRead
  repository.py    # filtreli/sayfalı okuma + join
  service.py       # record_audit(...)
  router.py        # GET /audit-log, GET /audit-log/export.xlsx
  export.py        # openpyxl workbook üretimi (router'dan ayrık, saf fonksiyon)
alembic/versions/<rev>_audit_log_tablosu.py
```

Mevcut modüllere dokunuş: `auth/router.py`, `users/router.py`, `roles/router.py`,
`company/router.py` içine `record_audit` çağrıları (davranış-korur ek). `pyproject.toml`
dependencies'e `openpyxl`. App başlatma `app/main.py` (veya router toplayıcı) audit
router'ını dahil eder.
