# Belge Çekirdeği — documents (uygulama planı)

Spec: `../specs/2026-08-03-belge-cekirdegi-design.md` · Ön şart: spec §7 sorularının kullanıcı cevabı.
Dal: `feat/belge-cekirdegi` (GÜNCEL main'den; `alembic heads` TEK head doğrulanır — F-SD frontend dilimi
paralel çalışıyor olabilir, backend'de çakışma beklenmez). Her task = tek subagent + commit · TDD ·
DB komutları HEP override'lı (WORKFLOW §4) · **ARA REVIEW YOK** (WORKFLOW §2).

## T1 — Migration + modeller + izin modülü
- 3 tablo (`document_folders`, `documents`, `document_blobs`) — blob AYRI tabloda (liste sorguları
  künyeye dokunur, kanıt: liste testinde blob tablosuna SELECT atılmadığı doğrulanır).
- S2: `documents` izin modülü (20., grup MALI) — seed_data + migration + matris testi ÜÇÜ BİRLİKTE
  (`test_seed_migration_matches_seed_data` tuzağı). Config: `DOCUMENT_MAX_BYTES` (50MB) +
  `ALLOWED_DOCUMENT_EXTENSIONS`.
- upgrade→downgrade→upgrade turu temiz.

## T2 — StorageBackend soyutlaması + klasör uçları (TDD)
- `StorageBackend` arayüzü (put/stream/delete) + `DbStorageBackend` v1; servis yalnız arayüzü görür
  (testte sahte backend ile kanıtlanır — R2/S3 geçişinin tek sınıf olduğunun garantisi).
- Klasör CRUD: liste (proje/şantiye kapsamlı) · POST · PATCH(ad) · DELETE (yalnız boş; admin) ·
  UQ çakışması 409 · IDOR.

## T3 — Belge uçları (TDD)
- `POST /documents` multipart: boyut sınırı 413/422 · uzantı beyaz listesi 422 · künye+blob atomik
  yazım · audit.
- `GET /documents` (filtreler + `q` ad/açıklama araması + Son Eklenenler sıralaması) — blob'a
  DOKUNMADAN (sorgu kanıtı).
- `GET /{id}/download` **StreamingResponse** (48MB'lık dosya tam-bellek okunmaz — bellek testi/kanıtı) +
  doğru Content-Type/Disposition · `PATCH` (ad/açıklama/klasör taşıma — taşımada kapsam uyumu doğrulanır:
  klasörün project/site'ı belgeninkiyle aynı olmalı, 422) · `DELETE` (admin; blob CASCADE).
- IDOR: tüm uçlar `visible_projects`; görünmeyen belge 404.

## T4 — Kapanış + FINAL REVIEW (Opus)
- Tüm paket + ruff (tüm repo) + `alembic check` temiz + migration turu.
- openapi üret → DEVİR KURALI (WORKFLOW §4): frontend checkout main'de+temiz mi? F-SD dilimi çalışıyorsa
  muhtemelen DEĞİL → KOPYALAMA, rapor et (devir F-SD kapanışından sonra tek seferde).
- Review odağı: IDOR · blob izolasyonu kanıtı · streaming belleği · atomiklik (künye yazıldı blob
  yazılamadı yarımlığı imkânsız mı) · beyaz liste bypass denemeleri (çift uzantı, MIME sahteciliği) ·
  kalıcı karar taraması (thumbnail/versiyon/onay/slot sızıntısı = bulgu).
- `ARCHITECTURE-BACKEND.md` + `ROADMAP-BACKEND.md` (6 `pending_module: "documents"` borcunun backend
  ayağı kapandı notu) güncellenir, commit. Push/PR/merge/deploy kullanıcıda.
