# HZ-1 — Hazine Çekirdeği (backend) · uygulama planı

Spec: `backend/docs/superpowers/specs/2026-08-14-hz1-hazine-cekirdegi-design.md`
Dal: `feat/hz1-hazine-cekirdegi` (base: `main`, **FAT-1 merge edildikten SONRA**)

TDD zorunlu: önce test, **KIRMIZI GÖR**, sonra kod. İlk koşuda yeşilse mutasyon denetimi.

---

## T1 — Model + migration · **Opus**
`treasury/models.py` (spec §2.1/§2.2) + alembic revizyonu + `alembic/env.py` + `tests/conftest.py`.

**Kabul:** iki tablo spec'le birebir (kolon/tip/nullability/FK davranışı/CHECK/kısmi UNIQUE) ·
iki enum, downgrade `DROP TYPE` yapar · migration testi **açık revizyon id'siyle**,
upgrade→downgrade→upgrade temiz, `alembic heads` **TEK** · `alembic check` temiz ·
`test_alembic_env_imports.py` yeşil.
⚠️ **Ebeveyn revizyon `alembic heads` ile OKUNUR, tahmin edilmez.**

## T2 — Bakiye çekirdeği (saf/DB-hafif) · **Opus**
`balance.py` (spec K2).

**Kabul:** bakiye = `opening_balance` + Σ(giden fatura ödemesi) − Σ(gelen fatura ödemesi) ·
`Decimal`, kayan nokta YOK · ödemesi olmayan hesap `opening_balance` döner ·
🔴 **N+1 YOK — ölçülür:** 1 hesap ile 20 hesabın sorgu sayısı EŞİT olmalı
(`before_cursor_execute` sayacı, TB3/T1 emsali) · `inventory/balance.py` deseni emsal alınır.

## T3 — Banka hesabı uçları (1-5) · **Opus**
`schemas/repository/service/router` + `main.py` kaydı.

**Kabul:** `GET` yanıtı **türetilmiş `balance`** taşır · `DELETE` yalnız `admin`, ödemesi olan hesap
**409** (FK 500'ü kullanıcıya SIZMAZ) · `full` rolü DELETE'te **403** · kısmi UNIQUE: iki Kasa
NULL IBAN ile açılabilir, aynı IBAN **409** · `ck_bank_accounts_cash_has_name` servis katmanında
**422** ile önce yakalanır · `limit` tavanı aşımı **422** (kırpma değil) · görünmeyen/olmayan → 404.

## T4 — 🔴 Ödeme uçları + KİLİT (6, 7, 8) · **Opus**
`/invoices/{id}/payments` uçları **`invoicing` router'ının İÇİNDE** (spec §5 sıra tuzağı).

**Kabul:**
- **K7 EŞİK=KİLİT:** fatura satırı `with_for_update + populate_existing`, kilit **denetimlerden
  ÖNCE**, sıra SABİT. **İKİ GERÇEK BAĞLANTIYLA** eşzamanlılık testi; **kilit kaldırılınca KIRMIZI
  olduğu KANITLANIR** — raporda kanıt istenir.
- **K6:** `Σ + yeni > total` → **422**, kuruş bazında tam karşılaştırma, tolerans YOK.
  Sınır değerleri (`= total` geçer, `total + 0.01` reddedilir) ikisi de testli.
- **K5:** `paid_amount` kolonu **YOK**; durum `Σ payments`ten türetilerek damgalanır.
  `DELETE /payments/{id}` sonrası durum **yeniden türetilir** (`collected` → `sent`'e düşer) — testli.
- Ödeme silme yalnız `admin`.
- Yeni `AuditAction` üyesi **AÇILMAZ** (TB3/T3 kanonu); ayrım `messages.*` metninden.

## T5 — Türev uçlar (9, 10) · **Opus**
`upcoming.py` + `cash_flow.py`.

**Kabul:** `days` varsayılan **7**, `ge=1 le=90`, aşım 422 · `days_remaining` **türetilir** ·
🔴 **K10: renk/aciliyet sınıfı sunucuda ÜRETİLMEZ** · **K9: bordro kaynağı UYDURULMAZ** — zarf
`source_type` taşır, bordro bugün sıfır satır üretir ve bu ROADMAP'e borç yazılır ·
`cash-flow` ay penceresi `DISPLAY_TIMEZONE`de · boş ayda seri boş, **toplamlar 0** (NULL değil).

## T6 — FINAL REVIEW (Opus) + doküman
1. **K8 sınıf araması:** ödeme türev değer değildir, donacak çarpanı yoktur — **ama fatura tarafı
   FAT-1'de donmuştu**; ödeme donmuş `total`a karşı denetleniyor mu, doğrula.
2. **🔴 ROADMAP-BACKEND §3 BAYAT BORÇ DENETİMİ** (F-TB3/T-A emsali, frontend'de 56 satırın **8'i**
   bayat çıktı): §3'teki üstü çizili OLMAYAN her satır kod gerçeğine karşı denetlenir.
   Verdict: **AÇIK** / **KAPALI (commit + `dosya:satır`)** / **KISMİ**. Kanıtsız satır AÇIK sayılmaz.
   Kapananlar `~~üstü çizili~~` + ✅ + kanıt commit'iyle işaretlenir. **Kredi gerçekten kapatan
   dilime yazılır**, HZ-1'e değil. Raporda **sayı**: kaç satır denetlendi / kaçı bayat.
3. NULL-EŞİK denetimi: her toplanabilir alanda NULL'ın yönü kararlaştırılmış ve testli mi?
4. Dosya tavanı **800 satır**.
5. Kapılar: override'lı tam pytest + `ruff check .` + `ruff format --check .` (TÜM repo).
6. `openapi.json` üretilir, **yol sayısı raporlanır** (beklenen **204**).
   🔴 **openapi DEVRİ YAPILMAZ** — frontend PR #29 o dosyalarda açık.
7. `ARCHITECTURE-BACKEND.md` + `ROADMAP-BACKEND.md` güncellenir.
   🔴 **`ARCHITECTURE.md` (repo-üstü) dosyasına DOKUNULMAZ** — yönetim günceller.
8. **K5 açık kararı** ROADMAP'e "kullanıcı dönünce doğrulanacak" olarak yazılır.

## T7 — KOŞULLU KAPANIŞ (⚡ tek paket, MERGE'E KADAR)
Koşullar: dört kapı yeşil · **Docker/PG 16 yerel CI eşdeğeri yeşil ve kanıtlı** ·
`origin/main` head'i değişmemiş · `origin/main` alembic head'i değişmemiş
→ push → PR → CI durumu raporlanır → **MERGE-HAZIR raporu, TEK rapor**, sonra DUR.

🔴 `gh pr merge` YOK · deploy YOK · canlıya giriş/yazma YOK · canlı DB'ye migration YOK.
