# Backend B5 — Denetim Günlüğü Uygulama Planı

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sistemdeki tüm anlamlı yazma işlemlerini değiştirilemez bir `audit_log` tablosuna kaydeden servis-katmanı altyapısını kurmak; B1–B4'ün tüm yazma noktalarını bu altyapıya bağlamak; filtrelenebilir/sayfalanabilir bir okuma ucu ile Excel dışa aktarım ucunu açmak. Frontend F5'in Denetim Günlüğü ekranı bu fazdan beslenecek.

**Architecture:** Yeni `app/modules/audit/` modülü mevcut `models · schemas · repository · service · router` iskeletini izler. Yakalama **jenerik değil, açık**: her yazma noktası `record_audit(...)` çağırıp Türkçe detay metnini çağrı noktasında üretir. Çağrılar **router katmanında** yapılır (orada `Request` ve `current_user` vardır); servis fonksiyonları HTTP'den bağımsız kalır. Audit satırı `session.add()` ile aynı request-session'a eklenir, ayrı commit YOK — `get_db` bağımlılığı commit'i sahiplendiği için atomiklik doğal olarak sağlanır. Okuma/export uçları `settings ≥ view` kapısıyla korunur (seed'de yalnızca Sistem Yöneticisi).

**Tech Stack:** Python 3.13 · FastAPI · SQLAlchemy 2.0 (async, asyncpg) · Alembic · Pydantic v2 · openpyxl (yeni) · pytest + pytest-asyncio + httpx

**Spec:** `docs/superpowers/specs/2026-07-19-backend-b5-denetim-gunlugu-design.md` (birincil) ve `docs/superpowers/specs/2026-07-17-temel-modul-design.md` (§4 `audit_log`, §8 B5, §10 doğrulama). Çelişki hâlinde kaynak spec kazanır.

**Mockup:** `../projedesign/Ayarlar - Denetim Günlüğü.dc.html` — sütun başlıkları, filtre presetleri ve Excel sütunları buradan alınır; uydurulmaz.

---

## Global Constraints

- **Repo:** Tüm yollar `/Users/furkanilgen/Documents/Projeler/insaat/backend` köküne göreli. Frontend ayrı repo — bu planda ona dokunulmaz.
- **Yürütme ortamı:** PATH'te `python` YOK. Her komutta `.venv/bin/python`, `.venv/bin/pytest`, `.venv/bin/alembic`, `.venv/bin/ruff` kullan. DB Railway'de (bulut); testler uzak DB'ye bağlandığı için yavaştır — her task'ta yalnızca FOCUSED testler, tam suite yalnızca Task 7'de.
- **Dil:** Kod/değişken/fonksiyon adları İngilizce; kullanıcıya ve denetim günlüğüne dönen metinler Türkçe. Commit mesajlarında Türkçe diakritik kullanma ("denetim gunlugu").
- **Değiştirilemezlik (KRİTİK):** `audit_log` için UPDATE/DELETE ucu, servis fonksiyonu veya repository yardımcısı YAZILMAZ. Yalnızca insert (servis üzerinden) + select. Bu kural bir görüş değil, fazın varlık sebebidir.
- **Atomiklik (KRİTİK):** `record_audit` **asla commit etmez**, `session.flush()` bile çağırmaz. Yalnızca `session.add()`. Ayrı transaction/`begin_nested` kullanma. İşlem rollback olursa audit de yazılmaz — bilinçli seçim.
- **Çağrı katmanı:** `record_audit` çağrıları **router**'da yapılır. Servis/repository katmanına audit sızdırma; servis imzalarına `request`/`ip` parametresi ekleme.
- **Kapsam dışı:** `PUT /settings/preferences` ve `PUT /settings/notifications` audit ÜRETMEZ (self-service, düşük değer/yüksek gürültü). Başarısız login audit'e yazılmaz. `approve`/`backup` enum değerleri tanımlanır ama bu fazda üretici uç yoktur.
- **Migration:** Tek additive migration. `down_revision` = **uygulama anındaki head** — B5'ten hemen önce `invoicing` (14. izin modülü) migration'ı eklendi, dolayısıyla `6c98d5b8b142` DEĞİL. Task 1'de `.venv/bin/alembic heads` ile doğrula. Yeni PG enum tipi `audit_action` `downgrade()` içinde AÇIKÇA düşürülür (`sa.Enum(name="audit_action").drop(op.get_bind(), checkfirst=True)`).
- **Yetki:** `role.key` üzerinden, ASLA `role.name`. Okuma + export uçlarının ikisi de `require_permission("settings", AccessLevel.view)`.
- **Yanıt gövdesi:** Audit yanıtlarında parola, hash, token yer almaz. `detail` metinlerine parola/token/gizli değer YAZILMAZ — "parola sıfırlandı" yazılır, parolanın kendisi asla.
- **Dosya boyutu:** Tek dosya 400 satırı geçmemeli.
- **Test:** Her task TDD — önce başarısız test, sonra minimal implementasyon. Faz sonunda kapsam ≥ %80, `ruff check` + `ruff format --check` temiz.
- **Commit:** Her task sonunda tek commit, `<type>: <açıklama>` formatı. Branch: `feat/b5-denetim-gunlugu` (Task 1'de oluşturulur). **Push, PR ve deploy kullanıcının kararıdır — ajan push etmez.**

---

## File Structure

| Dosya | Sorumluluk |
|---|---|
| `app/modules/audit/__init__.py` | Boş paket işareti. |
| `app/modules/audit/models.py` | `AuditAction` StrEnum + `AuditLog` modeli (3 indeks). |
| `app/modules/audit/schemas.py` | `AuditActorRead`, `AuditItem`, `AuditListResponse`. |
| `app/modules/audit/service.py` | `record_audit(...)` — tek sorumluluk, commit etmez. |
| `app/modules/audit/messages.py` | Detay metni üreticileri (Türkçe, tek yerde). |
| `app/modules/audit/repository.py` | Filtreli/sayfalı liste + toplam sayım + actor join. |
| `app/modules/audit/export.py` | openpyxl workbook üretimi — saf fonksiyon, HTTP bilmez. |
| `app/modules/audit/router.py` | `GET /audit-log`, `GET /audit-log/export.xlsx`. |
| `app/core/ratelimit.py` | `_client_ip` → `client_ip` olarak dışa açılır (davranış birebir korunur). |
| `app/main.py` | `audit_router` kaydı. |
| `alembic/env.py`, `tests/conftest.py` | `audit` model import'u (create_all + autogenerate için). |
| `alembic/versions/<rev>_audit_log_tablosu.py` | `audit_log` tablosu + `audit_action` enum + 3 indeks. |
| `pyproject.toml` | `dependencies`'e `openpyxl>=3.1`. |
| `app/modules/{auth,users,roles,company}/router.py` | `record_audit` çağrıları (davranış-korur ek). |
| `tests/modules/test_audit_service.py` | `record_audit` birim + atomiklik (Task 1). |
| `tests/modules/test_audit_capture_users.py` | auth + users yakalama (Task 2). |
| `tests/modules/test_audit_capture_roles_company.py` | roles + company yakalama (Task 3). |
| `tests/modules/test_audit_api.py` | Okuma ucu: filtre/sayfalama/sıralama/yetki (Task 4). |
| `tests/modules/test_audit_export.py` | Excel export (Task 5). |

---

## Task 1: Şema temeli — model + migration + `record_audit`

**Files:**
- Create: `app/modules/audit/__init__.py`, `models.py`, `service.py`, `messages.py`
- Modify: `alembic/env.py`, `tests/conftest.py`, `app/core/ratelimit.py`
- Create: `alembic/versions/<yeni>_audit_log_tablosu.py`
- Create: `tests/modules/test_audit_service.py`

**Step 1 — branch:**
```bash
git checkout -b feat/b5-denetim-gunlugu
.venv/bin/alembic heads   # down_revision'ı BURADAN al, varsayma
```

**Step 2 — RED:** `tests/modules/test_audit_service.py`
- `test_record_audit_satiri_ayni_session_a_eklenir` — `record_audit(session, action=AuditAction.login, detail="Sisteme giriş yapıldı", actor_user_id=user.id, ip_address="203.0.113.7")` sonrası **commit etmeden** `session` üzerinden select edildiğinde satır görünür (autoflush).
- `test_record_audit_commit_etmez` — çağrı sonrası `session.in_transaction()` hâlâ True; `rollback()` sonrası satır YOK. (Atomiklik kanıtı — bu testin geçmesi fazın en kritik güvencesi.)
- `test_record_audit_actor_ve_ip_null_olabilir` — ikisi de None → satır yazılır, alanlar null.
- `client_ip` yeniden adlandırmasının davranışı bozmadığı: mevcut `tests/modules/test_auth_ratelimit.py` yeni ada göre güncellenir, XFF ilk-girdi davranışı aynı kalır.

Çalıştır → başarısız olmalı (modül yok).

**Step 3 — GREEN:** `app/modules/audit/models.py`
```python
class AuditAction(StrEnum):
    login = "login"
    create = "create"
    update = "update"
    delete = "delete"
    approve = "approve"
    backup = "backup"
```
`AuditLog`: `id` UUID PK (`uuid4` default) · `occurred_at` timestamptz server default `now()` · `actor_user_id` FK→`users.id` nullable (**`ondelete` kararı:** kullanıcı silinince audit satırı silinmemeli → `ON DELETE SET NULL`; aktör "Sistem"e düşer. `ON DELETE CASCADE` denetim izini yok eder, KULLANMA) · `action` `sa.Enum(AuditAction, name="audit_action")` · `detail` Text NOT NULL · `ip_address` `INET` nullable.
İndeksler: `ix_audit_log_occurred_at` (DESC), `ix_audit_log_actor_user_id`, `ix_audit_log_action`.

`app/modules/audit/service.py`:
```python
async def record_audit(
    session: AsyncSession,
    *,
    action: AuditAction,
    detail: str,
    actor_user_id: uuid.UUID | None = None,
    ip_address: str | None = None,
) -> None:
    """Denetim satırını request-session'a ekler. COMMIT ETMEZ (bkz. plan §Atomiklik)."""
    session.add(
        AuditLog(
            action=action,
            detail=detail,
            actor_user_id=actor_user_id,
            ip_address=ip_address,
        )
    )
```

`app/core/ratelimit.py`: `_client_ip` → `client_ip` (public). Takma ad BIRAKMA; çağrı yerlerini ve testini güncelle. Davranış birebir korunur.

**Step 4 — Migration:** additive; `audit_log` tablosu + `audit_action` enum + 3 indeks. `downgrade()` tabloyu düşürür ve enum tipini açıkça drop eder.

**Step 5 — Doğrulama:**
```bash
.venv/bin/alembic upgrade head && .venv/bin/alembic downgrade -1 && .venv/bin/alembic upgrade head
.venv/bin/pytest tests/modules/test_audit_service.py tests/modules/test_auth_ratelimit.py -q
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```
Postgres'te up/down/up gerçekten çalıştırılmadan bu task bitmiş sayılmaz.

**Commit:** `feat: audit_log tablosu + record_audit altyapisi`

---

## Task 2: Yakalama — auth login + users uçları

**Files:** Modify `app/modules/auth/router.py`, `app/modules/users/router.py`, `app/modules/audit/messages.py` · Create `tests/modules/test_audit_capture_users.py`

**Step 1 — RED:** Her uç için "işlem sonrası **tam olarak bir** audit satırı, doğru `action`, beklenen detay çekirdeği, doğru aktör ve IP" testi:

| Uç | action | detay çekirdeği |
|---|---|---|
| `POST /auth/login` (başarılı) | `login` | "Sisteme giriş yapıldı" |
| `POST /auth/login` (başarısız) | — | **satır oluşmaz** (negatif test, zorunlu) |
| `POST /users` | `create` | "Kullanıcı oluşturuldu: {ad} · {rol adı}" |
| `PATCH /users/{id}` | `update` | "Kullanıcı güncellendi: {ad}" |
| `PATCH /users/{id}/password` | `update` | "Kullanıcı parolası sıfırlandı: {ad}" — **parolanın kendisi metinde geçmemeli** (açık assert) |
| `DELETE /users/{id}` | `delete` | "Kullanıcı silindi: {ad}" |
| `PUT /users/{id}/project-access` | `update` | "Proje erişimi güncellendi: {ad}" |

Ayrıca: `GET` uçları audit üretmez; yetkisiz istek (403) audit üretmez.

**Step 2 — GREEN:**
- `messages.py` içinde üreticiler: `user_created(name, role_name)`, `user_updated(name)`, `password_reset(name)`, `user_deleted(name)`, `project_access_updated(name)`, `LOGIN_DETAIL = "Sisteme giriş yapıldı"`. Metinler tek yerde; router'lara string gömme.
- Router'lara `request: Request` parametresi eklenir (yoksa) ve işlem başarılı döndükten SONRA `await record_audit(...)` çağrılır. Aktör: `current_user.id` (login'de kimliği doğrulanan kullanıcı). IP: `client_ip(request)`.
- **DELETE dikkat:** silinen kullanıcının adı silme işleminden ÖNCE okunmalı; sonra okunursa satır yok. `service.delete_user` değiştirilmeden router'da önce `repository.get_user` ile ad alınır.
- **`PATCH /users/{id}` dikkat:** detayda değişen alanlar özetlenebilir ama şart değil; ad yeterli.
- `POST /users` ve `PATCH /users/{id}/password` uçlarında `current_user` bağımlılığı yoksa eklenir (parola sıfırlama ucunda şu an yok — aktörsüz audit satırı yazma).

**Step 3 — Doğrulama:** `.venv/bin/pytest tests/modules/test_audit_capture_users.py tests/modules/test_users_api.py tests/modules/test_auth*.py -q` + ruff.

**Commit:** `feat: auth ve kullanici uclarinda denetim kaydi`

---

## Task 3: Yakalama — roles + company uçları

**Files:** Modify `app/modules/roles/router.py`, `app/modules/company/router.py`, `messages.py` · Create `tests/modules/test_audit_capture_roles_company.py`

| Uç | action | detay çekirdeği |
|---|---|---|
| `POST /roles` | `create` | "Özel rol oluşturuldu: {ad}" |
| `PATCH /roles/{id}` | `update` | "Rol yeniden adlandırıldı: {eski} → {yeni}" |
| `DELETE /roles/{id}` | `delete` | "Rol silindi: {ad}" |
| `PUT /roles/{id}/permissions/{module_key}` | `update` | "İzin değişti: {rol adı} · {modül adı} → {seviye}" |
| `PUT /company` | `update` | "Şirket bilgileri güncellendi" |
| `POST /company/logo` | `update` | "Şirket logosu güncellendi" |
| `DELETE /company/logo` | `update` | "Şirket logosu kaldırıldı" |

**Dikkat noktaları:**
- Rename ve delete'te **eski değer işlemden önce** okunur (Task 2'deki DELETE dersiyle aynı).
- İzin değişikliğinde modül **adı** (`module.name`, ör. "Fatura Yönetimi") kullanılır, `module_key` değil — mockup dili insan-okur.
- Kilitlenme koruması nedeniyle reddedilen (403/409) izin değişikliği audit üretmez → negatif test yaz.
- `PUT /settings/*` uçlarının audit ÜRETMEDİĞİ açıkça test edilir (kapsam-dışı kuralının regresyon kilidi).

**Commit:** `feat: rol ve sirket uclarinda denetim kaydi`

---

## Task 4: Okuma ucu — `GET /audit-log`

**Files:** Create `app/modules/audit/schemas.py`, `repository.py`, `router.py` · Modify `app/main.py` · Create `tests/modules/test_audit_api.py`

**Sözleşme (frontend F5 buna göre yazılıyor — DEĞİŞTİRME):**
```
GET /audit-log?actor_user_id=&action=&date_from=&date_to=&limit=50&offset=0
200 → {
  "items": [{
    "id": "uuid",
    "occurred_at": "2026-07-25T09:14:00Z",
    "action": "login",
    "detail": "Sisteme giriş yapıldı",
    "ip_address": "192.168.1.100" | null,
    "actor": {"id": "uuid", "full_name": "Ahmet Yılmaz", "role_name": "Patron"} | null
  }],
  "total": 128, "limit": 50, "offset": 0
}
```
- Sıralama `occurred_at DESC`. `limit` `Query(ge=1, le=200)` default 50; `offset` `Query(ge=0)` default 0 (`UserListResponse` deseniyle birebir).
- Filtreler opsiyonel ve AND'lenir. `date_from`/`date_to` dahil-aralık (`>=` / `<=`).
- `actor` null → frontend "Sistem" gösterir; `ip_address` null → "—". **Sunum kararı frontend'in**, backend null döner.
- Yetki: `dependencies=[require_permission("settings", AccessLevel.view)]`.

**RED testleri:** filtre matrisi (actor / action / tarih aralığı / kombinasyon), sayfalama (`total` filtreden etkilenir, `limit/offset` yanıtta yankılanır), sıralama DESC, actor null yolu (kullanıcı silinmiş), **yetki: patron dahil `settings < view` olan her rol → 403; Sistem Yöneticisi → 200** (negatif izin testi zorunlu), geçersiz `action` → 422.

**N+1 uyarısı:** `actor` alanı için `selectinload`/`join` kullan; satır başına ayrı sorgu ÇIKMAMALI.

**Commit:** `feat: denetim gunlugu okuma ucu (filtre + sayfalama)`

---

## Task 5: Excel dışa aktarım — `GET /audit-log/export.xlsx`

**Files:** Create `app/modules/audit/export.py` · Modify `router.py`, `pyproject.toml`, `requirements.txt` · Create `tests/modules/test_audit_export.py`

- `pyproject.toml` `dependencies`'e `openpyxl>=3.1`; `requirements.txt` senkron tutulur (Docker build bu dosyayı kullanıyorsa). Saf-wheel, Docker-safe.
- `export.py`: `build_audit_workbook(rows) -> BytesIO` — saf fonksiyon, `Request`/`Response` bilmez.
- Sütunlar **mockup başlıklarıyla birebir**: `Zaman · Kullanıcı · İşlem · Detay · IP Adresi`.
- **FLOAT-YASAK (B4 dersi):** tüm hücreler string yazılır; openpyxl'in sessiz tip dönüşümüne alan bırakılmaz. Zaman `dd.MM.yyyy HH:mm` biçiminde string.
- Aynı filtre parametreleri geçerli; `limit`/`offset` YOK — tüm eşleşen kayıtlar.
- `Content-Disposition: attachment; filename="denetim-gunlugu.xlsx"`, MIME `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`.
- Yetki Task 4 ile aynı.

**RED testleri:** başlık satırı birebir; hücrelerin `str` oluşu; filtrenin export'a uygulanışı (filtreli export ≠ tüm kayıtlar); MIME + Content-Disposition; boş sonuç → yalnızca başlık satırı olan geçerli dosya (0 satır patlamaz).

**Sınır notu:** Kayıt sayısı büyüdüğünde export tüm satırları belleğe alır. v1'de kabul (tablo yeni, hacim düşük); üst sınır gerekirse Task 7'de takip maddesi olarak yazılır — sessizce kırpma YAPMA.

**Commit:** `feat: denetim gunlugu excel disa aktarim`

---

## Task 6: OpenAPI + frontend sözleşmesi

**Files:** `openapi.json` üretimi

- Uygulamadan güncel OpenAPI üretilir. **Açık nokta:** `backend/openapi.json` şu an untracked ve bayat; ya güncellenip izlenir hale getirilir ya da `.gitignore`'a alınıp üretim komutu README'ye yazılır. Uygulayan ajan bu kararı TEK BAŞINA VERMEZ, kullanıcıya sorar.
- Yeni iki ucun şemada göründüğü doğrulanır (`/audit-log`, `/audit-log/export.xlsx`).
- Frontend `pnpm gen:api` girdisi bu dosyadır; F5 ekranı bunu bekliyor.

**Commit:** `chore: openapi semasini b5 uclariyla guncelle`

---

## Task 7: Faz kapanışı

- [ ] Tam suite: `.venv/bin/pytest -q` — tamamı yeşil, sayıyı raporla.
- [ ] Kapsam: `.venv/bin/pytest --cov=app --cov-report=term-missing` → ≥ %80; `app/modules/audit/**` için eksik satırlar gözden geçirilir.
- [ ] `.venv/bin/ruff check .` + `.venv/bin/ruff format --check .` temiz.
- [ ] Migration ampirik doğrulama tekrarı: `upgrade head` → `downgrade` → `upgrade head`.
- [ ] `fastapi-reviewer` incelemesi; auth/izin dokunuşu olduğu için ayrıca `security-reviewer`. CRITICAL/HIGH bulgular kapatılmadan faz bitmez.
- [ ] Değiştirilemezlik denetimi: `grep -rn "AuditLog" app/` çıktısında insert + select dışında kullanım YOK.
- [ ] Kapsam-dışı kuralı hâlâ geçerli: `PUT /settings/*` audit üretmiyor.
- [ ] Takip maddeleri (engellemez) dokümante edilir: export üst sınırı, başarısız login güvenlik olayı, XFF sahteciliği ödüncü.

**Commit:** `test: b5 faz kapanisi - kapsam ve inceleme duzeltmeleri`

### Kapanış sonucu (uygulandı)

- Tam suite: **271 test yeşil**. Kapsam **%86** (eşik %80). `app/modules/audit/**` %90–100.
  Kapsam raporunda "eksik" görünen satırlar (`repository.py:101`, `router.py:88-89, 110-111`)
  **yanlış negatiftir**: `coverage.py` izleyicisi SQLAlchemy'nin greenlet bağlamı değişiminden
  sonra `await`'i izleyen satırları kaydedemiyor. O satırların çalıştığı testlerle kanıtlı
  (`test_audit_api` `total`/`limit`/`offset` alanlarını, `test_audit_export` dosya gövdesini
  doğruluyor). Aynı etki `users/roles/company` router'larının düşük yüzdelerinde de var.
- Migration temiz PG 18 veritabanında ampirik doğrulandı: `upgrade head` → `downgrade -1`
  (tablo + `audit_action` enum tipi düşer) → `upgrade head` (3 indeks geri gelir).
  `alembic check` → "No new upgrade operations detected" (model/migration ayrışması yok).
- Değiştirilemezlik denetimi: `grep -rn "AuditLog" app/` yalnızca modelin tanımı,
  `service.py`'deki tek INSERT ve `repository.py`'deki SELECT'leri gösteriyor. UPDATE/DELETE yok.
- Kapsam-dışı kuralı regresyon kilidiyle korunuyor (`test_tercih_uclari_denetim_satiri_yazmaz`).

### İnceleme bulgusu — kapatıldı

- **HIGH — geçersiz IP asıl işlemi düşürüyordu.** `ip_address` kolonu `INET`; `client_ip()`
  ise `X-Forwarded-For`'un ilk girdisini (istemci kontrolünde) ya da istemci yoksa
  `"anonymous"` sabitini döndürüyor. Geçersiz metin insert'i `DataError` ile düşürüyor ve
  audit satırı asıl işlemle aynı transaction'da olduğu için **işlemin kendisi geri
  alınıyordu** (ör. `X-Forwarded-For: not-an-ip` başlıklı bir login/kullanıcı oluşturma
  isteği). `record_audit` artık değeri `ipaddress.ip_address()` ile normalize ediyor;
  geçersizse alan `NULL` yazılıyor, işlem korunuyor (`test_record_audit_gecersiz_ip_null_yazilir`,
  `test_record_audit_ipv6_ve_bosluklu_ip_kabul_edilir`).

### Takip maddeleri (engellemez)

1. ~~**Excel'de saat dilimi (MEDIUM).**~~ **KAPANDI** (`fix: denetim gunlugu saat dilimi
   Europe/Istanbul`). Karar: kullanıcıya dönük **tüm** zamanlar `Europe/Istanbul`. Export
   `occurred_at`'i `to_display()` ile TR'ye çevirip `dd.MM.yyyy HH:mm` yazıyor; ekranla Excel
   artık aynı saati gösteriyor.
2. ~~**Tarih filtresi de UTC (MEDIUM).**~~ **KAPANDI** (aynı commit). `date_from`/`date_to`
   artık TR gün sınırlarına açılıp (`day_start_utc`/`day_end_utc`) UTC'ye çevrilerek
   karşılaştırılıyor; sınırlar yine **dahil**. Saat dilimi adı tek yerde:
   `settings.display_timezone` → `app/core/timezone.py` (`zoneinfo`, sabit ofset varsayımı yok).
3. **Export üst sınırı yok (MEDIUM).** `limit=None` ile tüm eşleşen satırlar belleğe alınıp
   tek xlsx'e yazılıyor. Tablo büyüdüğünde bellek/süre riski; `settings ≥ view` olan her
   kullanıcı tetikleyebilir. Sessiz kırpma yerine ya üst sınır + açık uyarı ya da streaming
   gerekir.
4. **Başarısız login güvenlik olayı (MEDIUM).** Şu an yalnızca başarılı girişler yazılıyor.
   Kaba-kuvvet tespiti için ayrı bir güvenlik-olayı kanalı (veya `login_failed` action)
   değerlendirilmeli — gürültü/değer dengesi bilinçli olarak v1'de dışarıda bırakıldı.
5. **XFF sahteciliği (MEDIUM).** `client_ip()` proxy zincirini doğrulamıyor; istemci
   `X-Forwarded-For` ile denetim kaydına **istediği geçerli IP'yi** yazdırabilir. Railway
   arkasında güvenilir proxy sayısı bilinerek sağdan n'inci girdi alınmalı.
6. **`q` uzunluk sınırı yok (LOW).** Çok uzun arama terimi iki `ILIKE` taramasını
   pahalılaştırır; `Query(max_length=…)` ucuz bir korkuluk olur. (Joker karakter escape'i
   `_escape_like` ile zaten yapılıyor.)
7. **Türkçe `İ/I` ILIKE sınırı (LOW).** Postgres `ILIKE` Türkçe nokta-sız/noktalı `i`
   eşlemesini yapmaz: "ilyas" araması "İlyas" kaydını bulmaz. Gerekirse `citext` veya
   `lower(... COLLATE "tr-TR")` tabanlı bir çözüm.
8. **Audit uçlarında hız sınırı yok (LOW).** Özellikle export pahalı; `settings ≥ view`
   kapısı var ama ek bir limit savunma-derinliği sağlar.
9. **Küçük ek sorgular (LOW).** `users`/`roles` router'larında detay metni için işlem
   sonrası `get_user`/`get_role`/`get_module` okumaları var (istek başına 1-2 ek sorgu,
   döngü içinde değil — N+1 değil). Okuma ucunda N+1 yok: aktör ve rol tek `outerjoin`
   sorgusunda geliyor.

---

## Bağımlılık ve sıra notları

- **Öncesi:** `invoicing` (14. izin modülü) migration'ı B5'ten önce head'e girer. B5 migration'ının `down_revision`'ı odur.
- **Sonrası:** F5 (frontend Denetim Günlüğü) yalnızca Task 4'ün sözleşmesine bağımlıdır; Task 4 biter bitmez frontend paralel ilerleyebilir. Task 5 (export) frontend'in "Excel'e Aktar" butonunu açar.
- **Alt-Proje 1'in kalanı:** B6 (dashboard uçları) → F6 (Gösterge Paneli). B5 bunların önkoşulu değildir; istenirse paralel yürütülebilir.

## Self-Review Notu (plan yazarından)

- Spec'in 13 yazma noktasının tamamı Task 2 ve 3'e dağıtıldı: users 5 + auth 1 = 6 (Task 2), roles 4 + company 3 = 7 (Task 3). Toplam 13, eksik yok.
- Spec'in "hariç" listesi (tercih uçları, başarısız login) **pozitif değil negatif testle** kilitlendi — sessizce genişlemeye karşı.
- Spec'te belirsiz bırakılan iki nokta plan seviyesinde karara bağlandı ve gerekçelendirildi: (1) FK `ON DELETE SET NULL` (denetim izi kullanıcı silinince kaybolmamalı), (2) `_client_ip` için takma ad bırakılmaması (iki isimli tek fonksiyon karışıklık üretir).
- Karar verilMEYEN tek nokta `openapi.json`'ın izlenip izlenmeyeceği (Task 6) — bilinçli olarak kullanıcıya bırakıldı, ajan varsayım yapmayacak.
