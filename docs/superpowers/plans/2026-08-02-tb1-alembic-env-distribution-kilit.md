# TB1 — Teknik Borç (uygulama planı)

Spec: `../specs/2026-08-02-tb1-alembic-env-distribution-kilit-design.md` (ONAYLI)
Dal: `chore/alembic-env-borcu` (main'den) · Her task = tek subagent + commit · DB komutları HEP override'lı.

## T1 — env.py import kapsaması (spec §1)
- Mevcut `alembic/env.py` import listesini çıkar; eksikleri (`boq`, `progress_payments` + varsa diğerleri)
  tüm-modül kapsayan açık listeye çevir; "yeni modülde buraya ekle" yorumu.
- Kanıt: `createdb tb1 && DATABASE_URL="postgresql+asyncpg://furkanilgen@localhost:5432/tb1" .venv/bin/alembic upgrade c3d4e5f6a7b8`
  → aynı override ile `alembic check` TEMİZ · `dropdb tb1` (başarısızlıkta bile).
- Migration dosyası üretilmediğini `git status` ile doğrula.
- Kabul: check temiz + tüm test paketi yeşil (env.py importları test toplamayı bozmamalı).

## T2 — Dağıtım kilidi (spec §2, TDD)
- Önce YARIŞ TESTİ yaz (iki eşzamanlı `save_distribution`; kilitsiz halde tutarsızlık/aşım üretebilen
  senaryo) → KIRMIZI gör.
- `get_contract_locked` desenine paralel kilit (`SELECT … FOR UPDATE`) ekle → YEŞİL.
- Şema/yanıt sözleşmesinin DEĞİŞMEDİĞİNİ openapi üretip karşılaştırarak kanıtla
  (`frontend/`e kopya GEREKMEZ).

## T3 — Kapanış + FINAL REVIEW (Opus)
- Tüm paket: pytest (yerel DB) + `ruff check .` + `ruff format --check .` (alembic/ dahil).
- Review odağı: env.py değişikliğinin migration ortamına yan etkisi yok mu; kilit deadlock riski
  (kilit sırası tutarlı mı); test gerçekten yarışı kanıtlıyor mu.
- `ROADMAP-BACKEND.md §3`'te iki borç satırını "kapandı (TB1)" olarak işaretle;
  `ARCHITECTURE-BACKEND.md §5`'teki "Bilinen borç" notunu düşür. Commit; push/PR kararı kullanıcıda.
