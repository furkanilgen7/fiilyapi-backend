# Backend B3.5 — Üretim Sağlamlaştırma Uygulama Planı

**Goal:** Canlıya (Railway) alınan API'yi üretim güvenliği için sağlamlaştırmak: login/refresh rate-limiting, env-bazlı CORS, engine/connection timeout, ve token_version tabanlı refresh-token iptali (gerçek çıkış + parola-reset iptali).

**Architecture:** Mevcut modüler FastAPI. Çoğu değişiklik `app/core/*` (config, db, security, deps, main) + `app/modules/auth` + `app/modules/users`. Tek migration `users.token_version` kolonu ekler. Davranış-koruyucu ekler; mevcut auth akışı kırılmaz (eski token'lar `ver` yoksa 0 sayılır, backward-compatible).

**Tech Stack:** FastAPI · SQLAlchemy 2.0 async · asyncpg · Alembic · PyJWT · slowapi (yeni) · pytest.

**Spec:** `docs/superpowers/specs/2026-07-17-temel-modul-design.md` + B0-B3 backlog (ertelenen sağlamlaştırma). Yürütme: inline (executing-plans tarzı), her task TDD + focused test + commit.

## Global Constraints

- Repo: `/Users/furkanilgen/Documents/Projeler/insaat/backend`. Kod/isim İngilizce, hata mesajları Türkçe. `company_id` yok.
- `.venv/bin/python -m pytest`, `.venv/bin/ruff check .`. Migration yalnızca `TEST_DATABASE_URL`'de denenir; up/down/up doğrulanır.
- `.env` ASLA commit'lenmez. Yeni ortam değişkenleri `.env.example`'a eklenir.
- Davranış-koruyucu: mevcut 139 test yeşil kalmalı. Yeni ayarların hepsi güvenli varsayılana sahip (dev'de kırmaz).
- Config değerleri hardcode değil `Settings`'ten. Head migration şu an `e274019416f6`.

---

## Task 1: Engine/connection timeout

**Files:** `app/core/config.py`, `app/core/db.py`, `tests/core/test_db.py`

Config'e ekle: `db_connect_timeout: int = 10`, `db_command_timeout: int = 30`.
`db.py`: `build_engine(settings)` factory çıkar → `create_async_engine(settings.database_url, pool_pre_ping=True, connect_args={"timeout": settings.db_connect_timeout, "command_timeout": settings.db_command_timeout})`; `engine = build_engine(settings)`.

- [ ] **Step 1:** Test — default'lar (10/30) + `build_engine`'in `connect_args`'ı bu değerlerle kurduğunu doğrula.
- [ ] **Step 2:** Kırmızı gör.
- [ ] **Step 3:** Config + db.py uygula.
- [ ] **Step 4:** `.venv/bin/python -m pytest tests/core/test_config.py tests/core/test_db.py -q` yeşil + `import app.main` OK.
- [ ] **Step 5:** `.env.example`'a `DB_CONNECT_TIMEOUT`/`DB_COMMAND_TIMEOUT`. Commit: `feat: engine connect/command timeout (uretim saglamlastirma)`.

---

## Task 2: CORS middleware (env-bazlı allowlist)

**Files:** `app/core/config.py`, `app/main.py`, `tests/test_cors.py` (yeni)

Config: `cors_origins: str = ""` + parser property `cors_origin_list -> list[str]` (virgülle ayrılmış, boşları at). Boşsa CORS eklenmez (dev'de kırmaz).
`main.py`: liste doluysa `app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])`. **Wildcard `*` + credentials YASAK** — origins açık liste.

- [ ] **Step 1:** Test — `cors_origin_list` parser birim testi + `CORS_ORIGINS` set edilip app kurulunca izinli origin'e `access-control-allow-origin` döner, izinsize dönmez.
- [ ] **Step 2:** Kırmızı gör.
- [ ] **Step 3:** Config parser + main.py middleware uygula. Not: BFF yüzünden savunma-derinliği (spec web/security).
- [ ] **Step 4:** `.venv/bin/python -m pytest tests/test_cors.py -q` yeşil.
- [ ] **Step 5:** `.env.example`'a `CORS_ORIGINS`. Commit: `feat: env-bazli CORS allowlist`.

---

## Task 3: Login/refresh rate-limiting (slowapi)

**Files:** `pyproject.toml`, `requirements.txt`, `app/core/config.py`, `app/core/ratelimit.py` (yeni), `app/main.py`, `app/modules/auth/router.py`, `tests/modules/test_auth_ratelimit.py` (yeni)

`slowapi` ekle. `ratelimit.py`: `Limiter(key_func=_client_ip)` — `_client_ip` X-Forwarded-For'un ilk IP'sini (Railway proxy arkası), yoksa `request.client.host`. In-memory.
Config: `login_rate_limit: str = "10/minute"`, `refresh_rate_limit: str = "20/minute"`.
`main.py`: `app.state.limiter = limiter`; `RateLimitExceeded` → 429 handler (Türkçe).
`auth/router.py`: `login`/`refresh`'e `request: Request` + `@limiter.limit(...)`.

- [ ] **Step 1:** Test — küçük limit config'iyle art arda `/auth/login` 429; limit altında normal.
- [ ] **Step 2:** Kırmızı gör.
- [ ] **Step 3:** Uygula. Gerekiyorsa testler arası limiter state reset fixture'ı.
- [ ] **Step 4:** `.venv/bin/python -m pytest tests/modules/test_auth_ratelimit.py tests/modules/test_auth.py -q` yeşil.
- [ ] **Step 5:** `.env.example`'a `LOGIN_RATE_LIMIT`/`REFRESH_RATE_LIMIT`. Commit: `feat: login/refresh rate-limiting (slowapi in-memory)`.

---

## Task 4: token_version — migration + token'lara göm + doğrula

**Files:** `app/modules/users/models.py`, `alembic/versions/<rev>_users_token_version.py` (yeni), `app/core/security.py`, `app/core/deps.py`, `app/modules/auth/router.py`, `tests/core/test_security.py`, `tests/modules/test_auth.py`

Model: `token_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")`.
Migration (down_revision `e274019416f6`): `add_column("users", Column("token_version", Integer, nullable=False, server_default="0"))`; downgrade `drop_column`. Enum yok.
`security.py`: `_create_token(user_id, token_version, ...)` → payload `"ver"`. `create_access_token(user_id, token_version)`, `create_refresh_token(user_id, token_version)`. `decode_token(token, expected_type) -> DecodedToken` (frozen dataclass `user_id`, `token_version`); `ver` yoksa 0 (backward-compat).
`deps.py`: user yüklendikten sonra `decoded.token_version != user.token_version` → 401.
`auth/router.py`: login/refresh token'ları `user.token_version` ile üretir; refresh, decode edilen refresh token'ın ver'i kullanıcınınkiyle eşleşmezse 401.

- [ ] **Step 1:** Test — ver gömülüyor/decode ediliyor; ver yoksa 0; user.token_version artınca eski token get_current_user'da 401.
- [ ] **Step 2:** Kırmızı gör.
- [ ] **Step 3:** Model+migration+security+deps+router uygula. `create_*_token` çağıran her yeri (login/refresh) güncelle.
- [ ] **Step 4:** `.venv/bin/python -m pytest tests/core/test_security.py tests/modules/test_auth.py tests/core/test_require_permission.py -q` yeşil. Migration zinciri TEST DB'de up/down/up temiz.
- [ ] **Step 5:** Commit: `feat: token_version claim - token uret/dogrula`.

---

## Task 5: İptal tetikleyicileri — logout + parola-reset

**Files:** `app/modules/auth/router.py`, `app/modules/users/service.py`, `tests/modules/test_auth.py`, `tests/modules/test_users_service.py`

`logout`: `get_current_user` al, `user.token_version += 1`, flush → tüm token'lar geçersiz (gerçek çıkış). BFF access token gönderiyor; süresi dolmuşsa 401 — kabul, not düş.
`users/service.py set_user_password`: `user.token_version += 1` → hedefin token'ları geçersiz (admin reset sonrası eski oturumlar düşer).

- [ ] **Step 1:** Test — logout sonrası eski access token 401; admin parola sıfırlayınca hedefin eski token'ı 401.
- [ ] **Step 2:** Kırmızı gör.
- [ ] **Step 3:** Uygula.
- [ ] **Step 4:** `.venv/bin/python -m pytest tests/modules/test_auth.py tests/modules/test_users_service.py tests/modules/test_users_api.py -q` yeşil.
- [ ] **Step 5:** Commit: `feat: logout ve parola-reset token_version artir (gercek iptal)`.

---

## Task 6: Faz kapanışı

- [ ] Tam suite + kapsam: `.venv/bin/python -m pytest --cov=app` → yeşil, ≥%80.
- [ ] `ruff check . && ruff format --check .` temiz.
- [ ] Migration zinciri boş TEST DB'de `upgrade head` + `downgrade base && upgrade head` temiz.
- [ ] `security-reviewer` + `fastapi-reviewer` (branch diff) → CRITICAL/HIGH yok.
- [ ] `.env.example` tüm yeni değişkenleri içeriyor. Railway deploy notu.
- [ ] Commit: `chore: B3.5 faz kapanisi`.

## Faz sonu kabul kriterleri
- [ ] Rate-limit: login/refresh aşımında 429.
- [ ] CORS: yalnızca allowlist; wildcard+credentials yok.
- [ ] Engine connect/command timeout aktif.
- [ ] token_version: logout ve parola-reset mevcut token'ları geçersiz kılıyor; eski (ver'siz) token'lar 0 sayılıp çalışıyor.
- [ ] 139+ test yeşil, kapsam ≥%80, migration temiz, incelemede CRITICAL/HIGH yok.
- [ ] Deploy notu: Railway'de `CORS_ORIGINS`, `JWT_SECRET`, rate-limit/timeout env'leri.
