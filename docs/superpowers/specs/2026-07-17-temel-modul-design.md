# FİİL Yapı ERP — Alt-Proje 1: Temel Modül (v1)

**Tarih:** 2026-07-17
**Durum:** Onaylanmış tasarım
**Kapsam:** Giriş, kullanıcı/rol/izin yönetimi, ayarlar, denetim günlüğü, gösterge paneli kabuğu, uygulama kabuğu, tasarım token katmanı

---

## 1. Amaç ve bağlam

`projedesign/` klasöründeki 68 HTML mockup'tan bir inşaat ERP'si kuruyoruz. Mockup'lar statik: JS mantığı yok, veri tamamen kurgu, backend yok. Tasarım referansı olarak kanon, uygulama olarak sıfır.

Sistem sıfırdan yazılıyor. Önceki bir uygulama (`insaat-old`) mevcut ve canlıda, ancak **kodu taşınmıyor** — bilinçli karar.

68 ekran tek bir spec'e sığmaz. İş, bağımlılık yönüne göre sıralı alt-projelere bölündü. Bu spec **yalnızca Alt-Proje 1'i (Temel)** tanımlar.

### Alt-proje haritası

| # | Alt-proje | İçerik | Durum |
|---|---|---|---|
| **1** | **Temel** | Giriş, Kullanıcılar, Rol Yönetimi, İzin Matrisi, Şirket Bilgileri, Denetim Günlüğü, Görünüm, Bildirimler, Gösterge Paneli, uygulama kabuğu, token katmanı | **bu spec** |
| 2 | Proje & Şantiye | Projeler, Proje Detay, Şantiye Detay, İş Kalemleri (WBS), Proje Takvimi | sonra |
| 3 | Sözleşme & Hakediş | İşveren/taşeron sözleşmeleri, poz dağılımı, hakediş oluşturma/özeti | sonra |
| 4 | Saha & İK | Şantiye Günlüğü, Puantaj, Personel, Bordro, SGK | sonra |
| 5 | Stok & Satınalma | Stok & Depo, Tedarikçi, Teklif, Sipariş | sonra |
| 6 | Mali | Muhasebe, Hazine, Mali Tablolar, Çek/Ödeme | sonra |
| 7 | Ekler | Makine & Ekipman, Belge Arşivi, Raporlar, Onay Kutusu, AI Chat, Yedekleme, Entegrasyonlar | sonra |

**Temel'in birinci olma gerekçesi:** diğer 6 alt-projenin tamamı giriş, rol/izin ve uygulama kabuğunun üstüne oturur. İzin matrisindeki 13 modül satırı gelecek modüllerin sözleşmesidir; her yeni modül kendi satırını doldurup aynı yetki kapısına bağlanır.

---

## 2. Alınan kararlar

| Konu | Karar | Gerekçe |
|---|---|---|
| Backend | Sıfırdan FastAPI + PostgreSQL | Kullanıcı kararı; eski kod taşınmıyor |
| Supabase | **Kullanılmıyor** | Özel izin matrisi + RLS = çifte yetki kaynağı; Alembic ile Supabase migration akışı çakışır |
| Veritabanı | Lokal Docker Postgres, canlı ortam sonra | — |
| Auth | FastAPI'de JWT (access + refresh), argon2 parola özeti | Tek yetki kaynağı |
| İzin modeli | İki eksen (seviye + kapsam), DB'den yönetilir | Mockup'taki matrisin birebir karşılığı |
| Çok şirketlilik | **Yok.** Tek şirket, `company_id` yok | Kullanıcı kararı — bkz. §9 Kabul edilen ödünçler |
| Frontend | Next.js App Router; httpOnly cookie + BFF proxy; TanStack Query | Token JS'e değmez; yoğun etkileşimli ERP tablolarına uygun |
| Tasarım dili | Açık tema — kökteki 68 mockup | 68 ekranın tamamı bu dilde; `uploads/` koyu teması kullanılmıyor |
| Ekran hedefi | Masaüstü (≥1280px) | Mockup'larda responsive yok; mobil tasarımı kullanıcı sonra verecek |
| Repo | `insaat/backend` + `insaat/frontend`, **ayrı git depoları** | Kullanıcı kararı |
| Repo sözleşmesi | OpenAPI → TypeScript tip üretimi | Ayrı repolarda tip güvenliğinin tek sağlam yolu |

---

## 3. Mimari

### 3.1 Repo yapısı

İki bağımsız git deposu, `insaat/` çalışma klasörü altında:

```
insaat/
├── projedesign/          referans mockup'lar (repo değil, dokunulmuyor)
├── backend/              git repo — FastAPI + Postgres
│   ├── app/
│   │   ├── main.py
│   │   ├── core/         config, db, security, deps, permissions
│   │   └── modules/
│   │       ├── auth/     oturum
│   │       ├── users/
│   │       ├── roles/    roller + izin matrisi
│   │       ├── company/
│   │       ├── audit/
│   │       ├── settings/ görünüm + bildirim tercihleri
│   │       ├── projects/ v1: minimal, salt okuma
│   │       └── dashboard/
│   ├── alembic/
│   ├── tests/
│   ├── docs/             ← bu spec (kanonik)
│   └── docker-compose.yml
└── frontend/             git repo — Next.js
    ├── src/
    │   ├── app/          App Router
    │   ├── components/
    │   ├── hooks/
    │   ├── lib/
    │   └── styles/tokens.css
    └── docs/             frontend uygulama planı
```

Her backend modülü aynı iskeleti izler — `router.py` (HTTP), `service.py` (iş kuralı), `repository.py` (veri erişimi), `schemas.py` (Pydantic), `models.py` (SQLAlchemy). Dosyalar tek işli ve küçük; bir modül tek bir subagent tarafından baştan sona götürülebilir.

### 3.2 Stack

**Backend:** FastAPI · SQLAlchemy 2.0 · Alembic · Pydantic v2 · argon2 (parola) · PyJWT · pytest + httpx
**Frontend:** Next.js (App Router) · React · TanStack Query · React Hook Form + Zod · Vitest + Testing Library · Playwright

### 3.3 Katmanlar arası sözleşme

FastAPI OpenAPI şemasını üretir; frontend ondan TypeScript tiplerini türetir. Backend bir alan değiştirdiğinde frontend derleme hatası verir — çalışma zamanında sürpriz olmaz. Tip üretimi frontend CI'ında koşar.

### 3.4 Oturum akışı (BFF)

```
Tarayıcı → Next.js Route Handler → FastAPI
```

1. Kullanıcı giriş formunu gönderir → Next.js `/api/auth/login` route handler'ı.
2. Route handler FastAPI `/auth/login`'i çağırır, JWT alır.
3. Route handler JWT'yi **httpOnly + Secure + SameSite=Lax** cookie'ye yazar. Tarayıcı JavaScript'i token'ı hiç görmez.
4. Sonraki istekler Next.js proxy'sinden geçer; proxy cookie'den token'ı okuyup `Authorization` başlığına koyar.
5. Next.js middleware korumalı rotaları oturumsuz erişime kapatır.

Access token kısa ömürlü, refresh token uzun ömürlü ve ayrı httpOnly cookie'de. Yenileme proxy katmanında şeffaf yapılır.

---

## 4. Veri modeli (v1)

### 4.1 Tablolar

**`users`**

| Alan | Tip | Not |
|---|---|---|
| `id` | UUID PK | |
| `email` | text, unique | giriş kimliği |
| `password_hash` | text | argon2 |
| `full_name` | text | "Ahmet Yılmaz" |
| `title` | text | "Patron · FİİL Yapı" — mockup'taki alt başlık |
| `role_id` | FK → `roles` | tek rol (mockup'ta kullanıcı başına tek rol) |
| `status` | enum | `active` · `on_leave` · `passive` (mockup: Aktif · İzinde) |
| `last_login_at` | timestamptz, null | |
| `created_at` / `updated_at` | timestamptz | |

Avatar baş harfleri (`AY`) `full_name`'den türetilir, saklanmaz.

**`roles`**

| Alan | Tip | Not |
|---|---|---|
| `id` | UUID PK | |
| `key` | text, unique | `system_admin`, `patron`, `site_chief`, `accounting`, `project_manager`, `procurement` |
| `name` | text | "Sistem Yöneticisi" |
| `emoji` | text | 🛡️ 👔 👷 📒 🏗 🛒 |
| `description` | text | rol kartındaki açıklama |
| `is_system` | bool | true → silinemez, adı değiştirilemez |

**`modules`** — izin matrisinin satırları (seed, sabit)

| Alan | Tip | Not |
|---|---|---|
| `id` | UUID PK | |
| `key` | text, unique | `dashboard`, `approvals`, … |
| `name` | text | "Gösterge Paneli" |
| `group` | enum | `GENEL` · `SAHA` · `STOK_SATINALMA` · `MALI` · `SISTEM` |
| `sort_order` | int | matristeki sıra |

**`role_permissions`** — matrisin kalbi

| Alan | Tip | Not |
|---|---|---|
| `role_id` | FK → `roles` | |
| `module_id` | FK → `modules` | |
| `access_level` | enum | bkz. §5 |
| `scope` | enum | bkz. §5 |
| | | UNIQUE(`role_id`, `module_id`) |

**`projects`** — v1'de minimal, salt okuma

| Alan | Tip | Not |
|---|---|---|
| `id` | UUID PK | |
| `code` | text, unique | |
| `name` | text | "Güneşkent A-Blok" |
| `status` | enum | `active` · `on_hold` · `completed` |
| `budget` | numeric(18,2) | |
| `progress_pct` | numeric(5,2) | |

v1'de yazma ucu yok. Alt-proje 2 bu tabloyu genişletir. Gerekçe: hem `user_project_access` hem dashboard proje kartları buna muhtaç.

**`user_project_access`**

| Alan | Tip | Not |
|---|---|---|
| `user_id` | FK → `users` | |
| `project_id` | FK → `projects`, null | null + `all_projects=true` → tüm projeler |
| `all_projects` | bool | mockup: "Tüm Projeler" |

**`company`** — tek satırlık tablo (CHECK ile tek satır zorlanır)

Firma adı, vergi no, vergi dairesi, ticaret sicil no, KEP adresi, telefon, e-posta, web sitesi, adres, logo yolu, marka rengi (`#2563eb`), GİB entegrasyon kodu, e-arşiv portalı, varsayılan KDV oranı, otomatik e-fatura (bool).

**`audit_log`**

| Alan | Tip | Not |
|---|---|---|
| `id` | UUID PK | |
| `occurred_at` | timestamptz | |
| `actor_user_id` | FK → `users`, null | null → aktör "Sistem" |
| `action` | enum | `login` · `create` · `update` · `delete` · `approve` · `backup` |
| `detail` | text | "Hakediş #47 onaylandı · ₺1.240.000" |
| `ip_address` | inet, null | sistem işlemlerinde null |

**`user_preferences`** — kullanıcı başına tek satır

Arayüz dili (`tr`/`en`), para birimi (`TRY`/`USD`/`EUR`), tarih formatı, arayüz yoğunluğu (`comfortable`/`normal`/`compact`), tema (`light` — v1'de tek geçerli değer), vurgu rengi.

**`notification_prefs`**

| Alan | Tip | Not |
|---|---|---|
| `user_id` | FK → `users` | |
| `event_key` | text | `progress_payment_created`, `vat_due_soon`, … |
| `email` / `in_app` / `sms` | bool | üç kanal |
| | | UNIQUE(`user_id`, `event_key`) |

---

## 5. İzin modeli

Mockup'taki matris hücreleri iki ekseni karıştırıyor. Model bunu ayırır:

```
access_level:  none · view · draft · request · approve · full
scope:         all · own · project · finance · stock · limited
```

Bir hücre = `(access_level, scope)` ikilisi. Mockup'taki etiket bundan **türetilir**:

| Mockup etiketi | access_level | scope |
|---|---|---|
| `✓ Tam` | `full` | `all` |
| `—` | `none` | `all` (anlamsız, yok sayılır) |
| `Görüntüle` | `view` | `all` |
| `Sınırlı` | `view` | `limited` |
| `Mali` | `view` | `finance` |
| `Kendi` | `view` | `own` |
| `Proje` | `view` | `project` |
| `Stok` | `view` | `stock` |
| `Taslak` | `draft` | `project` |
| `Talep` | `request` | `all` |
| `Onay` | `approve` | `all` |

Seviyeler sıralıdır: `none < view < draft < request < approve < full`. `require_permission(module, min_level)` bu sıraya göre karşılaştırır.

### 5.1 Modüller (13 satır, seed)

| Grup | Modül anahtarı | Ad |
|---|---|---|
| GENEL | `dashboard` | Gösterge Paneli |
| GENEL | `approvals` | Onay Kutusu |
| SAHA | `site_diary` | Günlük Kayıt |
| SAHA | `timesheet` | Puantaj |
| SAHA | `personnel` | Personel |
| SAHA | `payroll` | Bordro |
| STOK_SATINALMA | `inventory` | Stok & Depo |
| STOK_SATINALMA | `procurement` | Satınalma & Teklif |
| MALI | `progress_payments` | Hakedişler |
| MALI | `accounting` | Muhasebe |
| MALI | `treasury` | Hazine |
| SISTEM | `settings` | Ayarlar |
| SISTEM | `user_management` | Kullanıcı & Rol Yönetimi |

### 5.2 Seed matrisi (6 rol × 13 modül)

`Ayarlar - İzin Matrisi.dc.html` kanon kabul edilir.

| Modül | Sys.Yön. | Patron | Şantiye Şefi | Muhasebe | PM | Satınalma |
|---|---|---|---|---|---|---|
| Gösterge Paneli | Tam | Tam | Sınırlı | Mali | Tam | — |
| Onay Kutusu | Tam | Tam | Kendi | Mali | Proje | Stok |
| Günlük Kayıt | Tam | Tam | Tam | — | Görüntüle | — |
| Puantaj | Tam | Tam | Tam | Görüntüle | — | — |
| Personel | Tam | Tam | Görüntüle | Tam | Görüntüle | — |
| Bordro | Tam | Tam | — | Tam | — | — |
| Stok & Depo | Tam | Tam | Görüntüle | — | Görüntüle | Tam |
| Satınalma & Teklif | Tam | Tam | Talep | — | Onay | Tam |
| Hakedişler | Tam | Tam | Taslak | Onay | Onay | — |
| Muhasebe | Tam | Tam | — | Tam | Görüntüle | — |
| Hazine | Tam | Tam | — | Tam | Görüntüle | — |
| Ayarlar | Tam | — | — | — | — | — |
| Kullanıcı & Rol Yönetimi | Tam | — | — | — | — | — |

**Çözülen çelişki:** `Ayarlar.dc.html` özet matrisinde Patron'un Ayarlar erişimi `✓`, `İzin Matrisi.dc.html`'de `—`. İkincisi kanon — `Rol Yönetimi.dc.html`'deki "Patron: tüm modüller · tüm projeler (**ayarlar hariç**)" açıklamasıyla tutarlı olan o.

### 5.3 Uygulama

Tek bir kapı, her uçta:

```python
@router.post(
    "/progress-payments",
    dependencies=[require_permission("progress_payments", AccessLevel.DRAFT)],
)
```

Yetki kontrolü modüllere dağıtılmaz. `scope` uygulaması sorgu katmanında yapılır: `own` → yalnızca aktörün kayıtları, `project` → `user_project_access`'teki projeler, `finance`/`stock` → modüle özgü kısıt.

`is_system` rollerin izinleri düzenlenebilir **değildir**; Sistem Yöneticisi her zaman tam erişimlidir (kilitlenme koruması).

---

## 6. Frontend

### 6.1 Token katmanı

Mockup'larda `:root` yok, Tailwind yok, CSS değişkeni yok — 68 dosyaya dağılmış literal hex'ler ve inline style'lar var. İlk iş tek bir `tokens.css` yazmak. Bileşenler yalnızca token kullanır; çıplak hex yasak.

**Renkler:** birincil `#2563eb` (hover `#1d4ed8`); zemin `#f0f4f8`; yüzey `#ffffff`; ikincil yüzey `#f8fafc`; kenarlık `#e2e8f0`; ayırıcı `#f1f5f9`; metin `#1e293b` / `#475569` / `#64748b` / `#94a3b8`; başarı `#16a34a`; uyarı `#f59e0b`; hata `#ef4444`; nötr `#64748b`.

**Tipografi:** Inter (300–700) UI; JetBrains Mono (400/600/**700**) sayısal veri. Ölçek: sayfa başlığı 26/700 (ls −0.5px), bölüm başlığı 16/600, gövde 13/400, küçük 11/400, tablo başlığı 11/600 uppercase (ls 0.8px), sayısal 22/700 Mono.

**Radius:** 6 · 8 (standart) · 10 · 14 (kart). **Gölge:** kart `0 1px 4px rgba(0,0,0,0.06)`; topbar `0 1px 3px rgba(0,0,0,0.06)`; focus ring `0 0 0 3px rgba(37,99,235,0.1)`.

**Hareket:** `fadeUp` (opacity + translateY(8px), 0.4s ease) ana içerikte; geçişler 0.15s.

**Sabitlenen tutarsızlıklar** (mockup'ın kopyala-yapıştır kalıntıları, kasıtlı tasarım değil):

- Kart gölgesi `.06` vs `.07` → **`.06`**
- Sidebar `220px` vs `200px` → **`220px`**
- Bölüm başlığı ağırlığı 600 vs 700 → **600**
- Label rengi `#475569` vs `#374151` → **`#475569`**
- Kırmızı zemin 4 varyant → **`#fee2e2`**
- Alert sol kenarı `3px` vs `4px` → **`4px`**

**Düzeltilen hata:** JetBrains Mono 700 font linkinde yüklü değil ama KPI'larda kullanılıyor (tarayıcı sahte kalın üretiyor) → link'e 700 eklenir.

### 6.2 Bileşen sırası

`tokens.css` → primitive'ler → kabuk → ekranlar.

**Primitive'ler:** Buton (4 boyut × 7 varyant: birincil, ikincil, açık mavi, başarı, tehlike, uyarı, ghost) · Input (normal/focus/error/success/disabled, sol-sağ ikon, para) · Select · Checkbox/Radio · Toggle · Badge (durum pill, sayı, rol etiketi) · Alert (4 tip + sol-kenar varyantı) · Kart.

**Kabuk:** Topbar (52px sabit, logo 220px bloğu, proje seçici, bildirim, avatar) · Sidebar (220px sabit, FİİL AI kartı, 4 grup, sticky kullanıcı bloğu).

**Sistemde tanımsız, ekranlardan türetilecekler:** KPI kartı, tablo, modal, progress bar, breadcrumb, avatar, sparkline/alan grafiği, durum noktası. Bunlar için ilgili ekran dosyaları (`Ekran 1`, `Onay Kutusu.dc.html`) kanon.

**Not:** `Tasarım Sistemi.dc.html`'deki `fiil-*` sınıfları hiçbir ekranda kullanılmıyor (ölü kod), ama input/select davranışının tek yazılı spesifikasyonu — kaynak alınır, sınıf adları taşınmaz.

### 6.3 Ekranlar

**Giriş:** iki panel (sol 420px mavi gradient marka paneli, sağ form). E-posta, şifre (göster/gizle), "30 gün beni hatırla". Self-signup yok. **Şirket seçici kaldırılır** (tek şirket). Demo hesap blokları geliştirme ortamında kalır, canlıda gizlenir.

**Gösterge Paneli:** kabuk + gerçek proje kartları (`projects` tablosundan) + veri kaynağı olmayan kartlarda dürüst boş durum. Bkz. §7.

**Ayarlar:** kendi sol menüsü olan ayrı bir bölüm — Kullanıcılar (tablo + ekle/düzenle), Rol Yönetimi (master-detail, özel rol oluşturma, sistem rolü kilidi), İzin Matrisi (13×6 düzenlenebilir ızgara), Şirket Bilgileri (4 kart + logo yükleme), Görünüm, Bildirimler, Denetim Günlüğü (filtre + Excel).

---

## 7. Gösterge Paneli: boş durum stratejisi

Mockup'taki dashboard'ın gösterdiği verilerin çoğu v1'de mevcut değil:

| Kart | Veri kaynağı | v1 durumu |
|---|---|---|
| Proje kartları (4) | `projects` | **Gerçek** |
| Portföy · Toplam Hakediş + 6 aylık grafik | Alt-proje 3 | Boş durum |
| Tahsil Edilecek | Alt-proje 6 | Boş durum |
| Ortalama Marj | Alt-proje 3 + 6 | Boş durum |
| Onay Bekleyenler | Alt-proje 7 | Boş durum |
| Risk & Uyarılar | Alt-proje 2/3/5 | Boş durum |

Karar: **kabuk gerçek, veri dürüst.** Layout, KPI kartı, grafik bileşeni, sidebar/topbar tam yazılır; veri kaynağı olmayan kartlar "Henüz hakediş verisi yok" gibi açık boş durum gösterir. Sahte/seed rakam **kullanılmaz** — hangi sayının gerçek olduğu belirsizleşir.

Bu boş durumlar geçici bir kusur değil: gerçek uygulamada da yeni kurulan bir şirkette o kartlar boş olacak. Alt-projeler geldikçe her kart sırayla canlanır.

---

## 8. Fazlar

### Backend

| Faz | İçerik |
|---|---|
| B0 | İskelet: FastAPI, config, Postgres (docker-compose), Alembic, sağlık ucu, CI |
| B1 | Auth: `users`+`roles`, argon2, JWT access/refresh, `login`/`logout`/`refresh`/`me` |
| B2 | İzin modeli: `modules`+`role_permissions`, `require_permission`, 6×13 seed |
| B3 | Kullanıcı yönetimi + `user_project_access` + minimal `projects` |
| B4 | Şirket bilgileri + tercihler (görünüm, bildirim) |
| B5 | Denetim günlüğü: otomatik yakalama + filtre + Excel dışa aktarım |
| B6 | Dashboard uçları: proje kartları + boş durum KPI'ları |

### Frontend

| Faz | İçerik | Bağımlı |
|---|---|---|
| F0 | Next.js iskelet, `tokens.css`, fontlar, OpenAPI→TS tip üretimi, CI | — |
| F1 | Primitive'ler | F0 |
| F2 | Giriş + BFF route handler + httpOnly cookie + middleware koruma | B1, F1 |
| F3 | Kabuk: Topbar, Sidebar, layout | F1 |
| F4 | Ayarlar: Kullanıcılar, Rol Yönetimi, İzin Matrisi | B3, F3 |
| F5 | Ayarlar: Şirket, Görünüm, Bildirimler, Denetim Günlüğü | B4, B5 |
| F6 | Gösterge Paneli | B6 |

B0 + F0 paralel başlar. Backend önden gider, frontend bir faz arkadan takip eder. Her faz tek bir subagent'a verilebilecek büyüklüktedir.

**En kritik faz B2.** Yanlış kurulursa 6 alt-projenin tamamı yanlış temele oturur. Tabloları küçük, sonuçları en ağır iş budur; ayrı ve dikkatli bir faz olarak ayrılmıştır.

---

## 9. Kabul edilen ödünçler

Bilinçli kararlar; sonuçları biliniyor.

1. **Çok şirketlilik yok.** Giriş ekranındaki şirket seçici kaldırıldı. İkinci şirket gerektiği gün tüm tablolara ve tüm sorgulara geriye dönük `company_id` eklemek gerekecek — pahalı bir refactor. Kullanıcı bu maliyeti kabul etti.
2. **Responsive yok.** Hedef ≥1280px. Mockup'larda hiç `@media` yok; mobil tasarımını kullanıcı sonra verecek. Alt-proje 4 (saha/puantaj) gerçek mobil ihtiyacının doğduğu yer.
3. **Koyu tema yok.** Görünüm ayarlarındaki Koyu/Sistem seçenekleri görünür ama pasif.
4. **Bildirim gönderimi yok.** Tercih ekranı ve tercihlerin kaydı v1'de; gerçek e-posta/SMS gönderimi kanal entegrasyonu gerektirir, alt-proje 7'ye kalır.
5. **Yedekleme sayfası v1 dışı.** Uygulama özelliği değil, altyapı işi (S3, cron, geri yükleme). Arkasında gerçek sistem olmadan yapmak sahte olur.
6. **Entegrasyonlar v1 dışı.** GİB, Logo, SGK, WhatsApp — hepsi dış servis; v1'de bağlanacak bir şey yok.
7. **Kullanıcı başına tek rol.** Mockup böyle gösteriyor. Çoklu rol gerekirse `users.role_id` bir ara tabloya dönüşür.

---

## 10. Doğrulama

Her faz şu kapılardan geçmeden bitmiş sayılmaz:

1. **TDD** — kırmızı → yeşil → refactor. Backend pytest + httpx; frontend Vitest + Testing Library.
2. **%80 kapsam** — faz sonunda ölçülür.
3. **Kod incelemesi** — `fastapi-reviewer` / `react-reviewer`; auth ve izin fazlarında ayrıca `security-reviewer`.
4. **Görsel doğrulama** — Playwright ile 1280/1440'ta ekran görüntüsü, mockup ile karşılaştırma. Göz kararı değil, kanıt.
5. **E2E** — kritik akış: giriş → yetkiye göre sidebar → izin matrisi düzenle → kaydet → denetim günlüğünde görün.

### Negatif izin testleri (zorunlu)

Her rol için **erişemez** testleri yazılır: "Şantiye Şefi hakediş onaylayamaz", "Patron ayarlara giremez", "Muhasebe kullanıcı silemez". ERP'de asıl tehlike, bir rolün yapamaması gereken şeyi yapabilmesidir; pozitif testler bunu yakalamaz.

Kapsam: her (rol, modül, izin verilmeyen eylem) üçlüsü için en az bir test. 6 rol × 13 modül matrisi bu testlerin kaynağıdır.

---

## 11. Açık sorular

Yok. Tüm mimari kararlar alındı; kalan detaylar uygulama planına aittir.
