# B4 — Şirket Bilgileri + Kullanıcı Tercihleri (Tasarım)

**Tarih:** 2026-07-18
**Modül:** Temel · B4 (spec §8 backlog)
**Bağımlılık:** B0–B3 (auth + izin matrisi + kullanıcı/proje/rol yönetimi) — tamamlandı, canlıda.
**Tüketici:** Frontend F5 Ayarlar (Şirket Bilgileri, Görünüm, Bildirimler).

---

## 1. Amaç & kapsam

Spec §4.1'deki üç tabloyu (`company`, `user_preferences`, `notification_prefs`) hayata geçirir
ve bunları besleyen uçları sağlar:

- **Şirket Bilgileri:** tek şirket (çok-şirketlilik YOK, `company_id` YOK). Okuma + güncelleme +
  logo yükleme. Güncelleme `settings` modülü ile kapılı (seed'de yalnızca `system_admin`).
- **Görünüm (preferences):** kullanıcı başına, self-service (yalnızca `get_current_user`).
  Her kullanıcı yalnızca kendi tercihini okur/yazar.
- **Bildirimler (notification_prefs):** kullanıcı başına kanal tercihleri (email/in_app/sms),
  self-service.

### Kapsam DIŞI (spec §9 kabul edilen ödünçler)

- Koyu tema yok — `theme` DB enum'unda `dark`/`system` bulunur ama v1 yazma şeması yalnızca
  `light` kabul eder (aksi 422). Frontend'de Koyu/Sistem seçenekleri görünür ama pasiftir.
- Bildirim gönderimi yok — tercih ekranı ve kaydı v1'de; gerçek e-posta/SMS gönderimi
  alt-proje 7'ye kalır.
- Çok-şirketlilik yok — `company_id` hiçbir tabloya eklenmez.

---

## 2. Modüller & dosya yapısı

Spec dosya yapısına birebir iki yeni modül. Her biri standart iskelet
(`models · schemas · repository · service · router`). Router'lar `app/main.py`'de kaydedilir.

```
app/modules/
├── company/
│   ├── __init__.py
│   ├── models.py        # Company (bytea logo dahil)
│   ├── schemas.py       # CompanyRead, CompanyUpdate, CompanyLogoMeta
│   ├── repository.py    # get_singleton, update, set_logo, clear_logo
│   ├── service.py       # ensure/get/update + logo doğrulama
│   └── router.py        # GET/PUT /company, POST/GET/DELETE /company/logo
└── settings/
    ├── __init__.py
    ├── constants.py     # NOTIFICATION_EVENTS kataloğu
    ├── models.py        # UserPreferences, NotificationPref
    ├── schemas.py       # PreferencesRead/Update, NotificationPrefRead/Update
    ├── repository.py    # get/upsert preferences + notification prefs
    ├── service.py       # default merge + theme guard
    └── router.py        # GET/PUT /settings/preferences, /settings/notifications
```

---

## 3. Veri modeli (1 additive migration)

Migration tek dosya; 3 tablo + enum'lar. Additive ve geriye dönük uyumlu (canlıda güvenli).
Enum'lar downgrade'de açıkça düşürülür: `sa.Enum(name=...).drop(op.get_bind(), checkfirst=True)`.

### `company` — tek satır

Tekillik `only_row bool NOT NULL DEFAULT true` + `UNIQUE(only_row)` + `CHECK (only_row IS TRUE)`
ile zorlanır (en fazla bir satır).

| Alan | Tip | Not |
|---|---|---|
| `id` | UUID PK | |
| `only_row` | bool | tekillik koruması, hep true |
| `name` | text null | firma adı |
| `tax_number` | text null | vergi no |
| `tax_office` | text null | vergi dairesi |
| `trade_registry_no` | text null | ticaret sicil no |
| `kep_address` | text null | KEP adresi |
| `phone` | text null | |
| `email` | text null | |
| `website` | text null | |
| `address` | text null | |
| `logo_data` | bytea null | logo ikili verisi (DB'de) |
| `logo_content_type` | text null | `image/png` vb. |
| `logo_filename` | text null | |
| `brand_color` | text NOT NULL default `#2563eb` | marka rengi (hex) |
| `gib_integration_code` | text null | GİB entegrasyon kodu |
| `earsiv_portal` | text null | e-arşiv portalı |
| `default_vat_rate` | numeric(5,2) NOT NULL default 20.00 | varsayılan KDV oranı |
| `auto_einvoice` | bool NOT NULL default false | otomatik e-fatura |
| `created_at`/`updated_at` | timestamptz | |

`bootstrap.ensure_company()` başlangıçta boş tek satırı garanti eder (`ensure_first_admin` deseni).
Böylece `GET /company` daima 200 döner.

### `user_preferences` — kullanıcı başına tek satır

| Alan | Tip | Not |
|---|---|---|
| `user_id` | UUID PK, FK → `users` | |
| `locale` | enum(`tr`,`en`) default `tr` | arayüz dili |
| `currency` | enum(`TRY`,`USD`,`EUR`) default `TRY` | para birimi |
| `date_format` | text default `DD.MM.YYYY` | tarih formatı |
| `density` | enum(`comfortable`,`normal`,`compact`) default `normal` | arayüz yoğunluğu |
| `theme` | enum(`light`,`dark`,`system`) default `light` | v1 yalnızca `light` yazılabilir |
| `accent_color` | text default `#2563eb` | vurgu rengi (hex) |
| `created_at`/`updated_at` | timestamptz | |

`GET` satır yoksa varsayılanları döner (kalıcılaştırmaz); `PUT` upsert eder.

### `notification_prefs`

| Alan | Tip | Not |
|---|---|---|
| `id` | UUID PK | |
| `user_id` | FK → `users` | |
| `event_key` | text | katalog anahtarı |
| `email` | bool | |
| `in_app` | bool | |
| `sms` | bool | |
| | | UNIQUE(`user_id`, `event_key`) |

Kanonik olay listesi kod sabiti `NOTIFICATION_EVENTS` (event_key + Türkçe etiket + kanal
varsayılanları). `GET` saklı satırları varsayılanlarla **merge** eder; `PUT` gelen seti upsert
eder. Migration'da per-user seed YOK — yeni olay eklemek backfill gerektirmez.

Başlangıç kataloğu (örnek, kod sabitinde nihai hâli):
`progress_payment_created`, `vat_due_soon`, `approval_pending`, `stock_low`, `user_added`.

---

## 4. Uçlar, doğrulama & hata durumları

### Company

| Uç | Yetki | Davranış |
|---|---|---|
| `GET /company` | `get_current_user` | Company alanları (logo bytes HARİÇ) + `has_logo: bool` + `logo_url: "/company/logo"`. Daima 200. |
| `PUT /company` | `require_permission("settings", full)` | Kısmi güncelleme (tüm alanlar opsiyonel). Doğrulama: `email` format, `brand_color` hex `#RRGGBB`, `default_vat_rate` 0–100. |
| `POST /company/logo` | `require_permission("settings", full)` | multipart `file`. content_type ∈ config listesi (`image/png,image/jpeg,image/svg+xml,image/webp`). Boyut ≤ `LOGO_MAX_BYTES` (def 1 MB). Aşım → 413, geçersiz tip → 422 (Türkçe). |
| `GET /company/logo` | `get_current_user` | Logo yoksa 404 ("Logo yüklenmemiş"); varsa doğru `Content-Type` ile ikili yanıt. |
| `DELETE /company/logo` | `require_permission("settings", full)` | Logo alanlarını null'lar → 204. |

### Settings (self-service — hepsi `get_current_user`, daima kendi `user.id`)

| Uç | Davranış |
|---|---|
| `GET /settings/preferences` | Satır varsa döner; yoksa varsayılanlar (kalıcılaştırmaz). |
| `PUT /settings/preferences` | Upsert. `theme` yalnızca `light` (aksi 422: "Koyu tema henüz aktif değil"). `locale/currency/density` enum dışı → 422. `accent_color` hex doğrulama. |
| `GET /settings/notifications` | Katalog × saklı satırlar merge → `[{event_key, label, email, in_app, sms}]`. |
| `PUT /settings/notifications` | Gövde olay listesi. Bilinmeyen `event_key` → 422. Her olayı upsert. |

**Genel kurallar:** Yanıt gövdesinde parola/hash/token yok. Config değerleri
`app/core/config.py` Settings'ten: `LOGO_MAX_BYTES`, `ALLOWED_LOGO_CONTENT_TYPES`,
`DEFAULT_BRAND_COLOR`, `DEFAULT_ACCENT_COLOR`, `DEFAULT_VAT_RATE`. Kod/isim İngilizce,
kullanıcı hata mesajları Türkçe. Yetki `role.key` üzerinden; `require_permission` tek kapı.

---

## 5. Faz & test planı (task-task TDD)

Her task: önce başarısız test → asgari uygulama → yeşil → refactor → commit. Railway uzak DB
yavaş olduğundan her task'ta yalnızca FOCUSED testler; tam suite faz sonunda bir kez.

**B4.1 — Şema & migration.** 3 model + enum'lar + tek migration. TEST_DATABASE_URL'de
`upgrade head → downgrade base → upgrade head` doğrula. `bootstrap.ensure_company()`.
*Kabul:* migration ileri/geri temiz, enum'lar downgrade'de düşer, tek-satır CHECK tutuyor.

**B4.2 — Company okuma/yazma.** repository/service/schemas/router.
*Testler:* GET (bootstrap satırı), PUT kısmi güncelleme, yetkisiz PUT → 403, hex/email/vat → 422.

**B4.3 — Company logo.** POST/GET/DELETE.
*Testler:* yükle→getir round-trip, geçersiz content_type → 422, boyut aşımı → 413, logo yokken
GET → 404, yetkisiz yükleme → 403.

**B4.4 — Preferences (self-service).**
*Testler:* GET default (satır yok), PUT upsert, `theme=dark` → 422, enum dışı → 422, kullanıcı
yalnızca kendi kaydını görür/yazar.

**B4.5 — Notifications (self-service).**
*Testler:* GET merge (boş → tüm katalog varsayılanla), PUT upsert, bilinmeyen event_key → 422,
kullanıcı izolasyonu.

**Faz sonu:** tam suite bir kez, `ruff` temiz, kapsam ≥ %85. Kritik uçlarda
`security-reviewer` + `fastapi-reviewer` (CRITICAL/HIGH kalmaz). Ayrı branch
`feat/b4-company-settings`, her task commit. Merge/deploy kullanıcıya sorulur.

---

## 6. Global kısıtlar (B0–B3 ile aynı)

- Çok-şirketlilik YOK (`company_id` yok). Kod/isim İngilizce, hata mesajları Türkçe.
- Yetki `role.key` üzerinden, ASLA `role.name`. `require_permission` tek yetki kapısı;
  saf domain `app/core/access.py`, kapı `app/core/permissions.py`.
- Yanıt gövdesinde parola/hash/token yok. Config değerleri hardcode değil, Settings'ten.
- Migration'lar additive + geriye dönük uyumlu (canlıda güvenli). Migration ASLA dev DB'de
  denenmez; TEST_DATABASE_URL kullanılır.
- Her task TDD + commit. Faz sonu inceleme; merge/deploy kullanıcı onayıyla.

---

## 7. Frontend hatırlatması

B4 bitince OpenAPI'ye yeni uçlar eklendiği için: `openapi.json` üret + frontend'de
`pnpm gen:api`. F5 Ayarlar ekranları (Şirket Bilgileri / Görünüm / Bildirimler) bu uçları tüketir.
