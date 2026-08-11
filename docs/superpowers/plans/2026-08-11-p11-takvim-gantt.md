# P11 — Proje Takvimi / Gantt (backend plan)

Tarih: 2026-08-11 · Spec: `../specs/2026-08-11-p11-takvim-gantt-design.md` (ONAYLI) ·
Dal: `feat/p11-takvim-gantt` (güncel main'den — `f843c2f` TB4 merge'i dahil) · Task başına TEK subagent.

## T1 — Migration + modeller
- `sections.depends_on_section_id` (self-FK, nullable, SET NULL, indeks) + **`section_milestones`**
  tablosu (id · section_id CASCADE · title String(200) · milestone_date Date · sort_order).
  Ebeveyn: **`c9d0e1f2a3b4`** (`alembic heads` TEK head doğrula; farklıysa DUR). Enum yok, izin
  migration'ı yok. `alembic/env.py` importu (TB1 kuralı — yeni models dosyası açılırsa).
- Tur upgrade→downgrade→upgrade temiz; migration testi açık revizyon id.

## T2 — Bölüm gövdesi genişlemesi (TDD)
- `POST/PATCH sections`: `depends_on_section_id` (aynı ŞANTİYE 422 · self/döngü 422 — zincir
  yürüyerek; görünmez öncül 404-eşdeğeri davranış IDOR'la tutarlı) + `milestones` listesi
  id-korunumlu birleştirme (P9 emsali; bilinmeyen/yabancı id 422).
- Okuma yanıtlarına `depends_on_section_id` + `milestones` (additive). Tarih kısıtı ZORLANMAZ (S3).
- Bölüm silme: milestone CASCADE + bağımlı SET NULL testleri. Mutasyon denetimi.

## T3 — `GET /projects/timeline` (TDD)
- Portföy verisi: görünür projeler → proje satırı (ad/start/end/sözleşme bedeli/durum) + bölümler
  (ad/tarihler/status/sort_order/depends_on) + milestone'lar + `today` (`core.timezone`).
- İlerleme %'si YOK (S1 — pending zarfla da dönülmez, alan hiç açılmaz; frontend durum renginden
  çizer). HAM veri, ay/zoom parametresi YOK (S4). Deterministik sıra; N+1 ölçüm testi (TB3 sayaç).
- `projects:view` · IDOR (görünmez proje yanıtta yok — testli).

## T4 — Kapanış + FINAL REVIEW (Opus)
- Tüm paket + ruff tüm repo + `alembic check` + migration turu + tek head.
- Review odağı: döngü tespiti sağlamlığı (uzun zincir + iki yönlü) · kimlik korunumu · IDOR ·
  kalıcı karar taraması (progress_pct kolonu / include_in_timeline / tarih zorlaması / ayrı milestone
  CRUD ucu / gecikme-kritik yol alanı = bulgu). Bulgular kapatılır.
- `openapi.json` üret → DEVİR KURALI: frontend F-P10 dalında olacak — muhtemelen KOPYALANMAZ, rapor
  (P11 şeması sonraki devire biner).
- `ARCHITECTURE-BACKEND.md` + `ROADMAP-BACKEND.md` güncelle, commit.
