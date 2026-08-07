# TB3 — Borç Paketi (uygulama planı)

Spec: `../specs/2026-08-07-tb3-borc-paketi-design.md` · Ön şart: kullanıcı kapsam onayı.
Dal: `chore/tb3-borc-paketi` (GÜNCEL main'den) · Her task = tek subagent + commit · TDD ·
DB komutları HEP override'lı · **migration ÜRETİLMEZ** (`git status` kanıtı) · **ARA REVIEW YOK**.

## T1 — A: work_category snapshot (TDD)
- Taşeron hakediş liste + detay şemalarına `work_category` (mevcut sözleşme JOIN'inden; kolon YOK).
- N+1 yok kanıtı; mevcut testler değişmeden yeşil.

## T2 — B: U1 sayfalama (TDD)
- `limit` (varsayılan 50, tavan 200) + `offset` + `total`; hakediş liste deseniyle aynı biçim.
- Geriye uyum testi: parametresiz çağrı eski öğe alanlarını birebir korur + `total` döner.

## T3 — C: BOQ grup silme (TDD)
- `DELETE /boq/groups/{id}`: boş grup 204 · dolu grup 409 (`RelatedRecordsExist`) · izin `boq:admin` ·
  IDOR 404 · audit olayı (`AuditAction` + `messages.py` birlikte).

## T4 — Kapanış + FINAL REVIEW (Opus)
- Tüm paket + ruff (tüm repo) + `alembic check` temiz + migration üretilmedi kanıtı.
- openapi üret → DEVİR KURALI: frontend checkout main'de+temiz DEĞİLSE (F-PT çalışıyor olabilir)
  KOPYALAMA, rapor et — devir sonraki frontend diliminin T1'ine kalır.
- Review odağı: geriye uyum, JOIN doğruluğu, silme kapısı. `ROADMAP-BACKEND.md` (3 borç satırı kapanır)
  + `ARCHITECTURE-BACKEND.md` güncellenir, commit. Push/PR/merge/deploy kullanıcıda.
