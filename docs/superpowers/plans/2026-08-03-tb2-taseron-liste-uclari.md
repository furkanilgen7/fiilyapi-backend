# TB2 — Taşeron Liste Uçları (uygulama planı)

Spec: `../specs/2026-08-03-tb2-taseron-liste-uclari-design.md` · Ön şart: kullanıcı kapsam onayı.
Dal: `chore/tb2-taseron-liste-uclari` (GÜNCEL main'den — SD merge'li, head `b5c6d7e8f9a0`).
Her task = tek subagent + commit · TDD · DB komutları HEP override'lı · **migration ÜRETİLMEZ**
(`git status` ile kanıtlanır; `alembic check` temiz kalır).

## T1 — U1: sözleşme liste ucu (TDD)
- `GET /subcontractor-contracts` + filtreler + arama; işveren `/contracts` liste deseninden.
- IDOR: görünmeyen proje sözleşmesi listede YOK (test); boş filtre = tüm görünür projeler.
- Sıralama deterministik (ör. contract_no, id) — sayfalama YOK (mevcut liste uçları desenine uygun).

## T2 — U2: hakediş listesi + summary'ye site_id (TDD)
- Sözleşme join'li filtre; `site_id=NULL` sözleşmelerin hakedişleri filtreli sorguda GELMEZ (test).
- Geriye uyum: parametresiz çağrı birebir eski davranış (mevcut testler değişmeden yeşil).

## T3 — Kapanış + FINAL REVIEW (Opus)
- Tüm paket + ruff (tüm repo) + `alembic check` temiz + migration üretilmedi kanıtı.
- openapi üret; **frontend'e kopyalama YENİ KURALLA:** kopyadan önce frontend checkout'unun `main`'de
  ve ağacının TEMİZ olduğunu doğrula — değilse KOPYALAMA, rapor et (SD'de yaşanan yanlış-dal kazasının
  kuralı). Kopyalandıysa notu yaz: `gen:api` frontend main'de ayrı commit'le koşulacak.
- Review odağı: IDOR, geriye uyum, join doğruluğu. `ROADMAP-BACKEND.md` (F-TH'den açılan iki pending'in
  backend ayağı kapandı notu) + `ARCHITECTURE-BACKEND.md` (§2 uç sayıları) güncellenir, commit.
  Push/PR/merge/deploy kullanıcıda.
