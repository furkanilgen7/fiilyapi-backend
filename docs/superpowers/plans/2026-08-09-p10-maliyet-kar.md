# P10 — Maliyet/Kâr (backend plan)

Tarih: 2026-08-09 · Spec: `../specs/2026-08-09-p10-maliyet-kar-design.md` (ONAYLI) ·
Dal: `feat/p10-maliyet-kar` (güncel main'den) · Task başına TEK subagent, her task sonunda commit.
**Migration YOK** — dilim boyunca `alembic/` diff'i BOŞ kalmalı (TB2 emsali; T4'te `git diff main..HEAD
-- alembic/` boş kanıtı).

## T1 — Maliyet çekirdeği (TDD)
- `projects/costs.py` (yeni servis dosyası): taşeron hakediş toplamları (approved+paid BRÜT = harcanan ·
  paid = ödenen · approved = bekleyen; draft/submitted/rejected GİRMEZ) · arsa maliyeti kuralı
  (kendi yatırım `land_cost`, kat karşılığı 0, taahhüt None) · toplam bütçe maliyeti (4 kalem + arsa) ·
  tip-bazlı kâr/marj türevleri (spec §2 formülleri, mockup sayılarıyla birebir senaryolu testler:
  KY 18,4M/%38,2 · KK 12,8M/%42,1).
- Sıfıra bölme korkulukları (`_average` emsali): payda 0/None → `None`, 0 basılmaz.
- Mutasyon denetimi.

## T2 — `GET /projects/{id}/costs` (TDD)
- KY kartlarının yanıtı: maliyet kırılımı (arsa · inşaat harcanan/bütçe · pending 3 kalem
  `pending_module` ile) + kâr projeksiyonu bloğu + taşeron maliyet tablosu (sözleşme/ödenen/bekleyen
  satırları + tfoot toplamı — mevcut sözleşme+hakediş verisinden JOIN, N+1 yok).
- İzin `projects:view` · IDOR `visible_projects` → 404 · tek gidiş-dönüş hedefi.

## T3 — Yer tutucular gerçeğe (TDD)
- Proje kart/listesi: `construction_cost`/`estimated_profit`/`margin`/`our_share_value` —
  **zarf İÇİNDE** (`MetricPlaceholder.available=true` + `value`, `pending_module=null`). Tip DEĞİŞMEZ
  (E4 kartları canlıda). Zarf sözleşme testi: `available=true` ⇒ `pending_module is None`.
- `units`: `unit_cost` (bütçe bazlı m² dağıtımı; m²'siz → zarf `available=false` kalır) +
  `expected_profit` (liste fiyatı − maliyet).
- `sales`: "Bu Satıştan Kâr" + marj (satış bedeli − ünite maliyeti).
- Liste uçlarında N+1 ölçüm testi (TB3 `before_cursor_execute` sayaç emsali: proje sayısından
  bağımsız sorgu sayısı).
- Mutasyon denetimi.

## T4 — Kapanış + FINAL REVIEW (Opus)
- Tüm paket: pytest (override'lı) + ruff tüm repo + `alembic check` + `git diff main..HEAD -- alembic/`
  BOŞ kanıtı (migration yasağı).
- Review odağı: hesap formüllerinin spec §2 ile birebirliği · durum süzgeci (rejected sızıntısı = bulgu) ·
  zarf sözleşmesi · N+1 · kalıcı karar taraması (elle maliyet girişi / yeni tablo / E1 ortalama marj /
  şantiye brüt marj dokunuşu = bulgu). Bulgular kapatılır.
- `openapi.json` üret → DEVİR KURALI (WORKFLOW §4): frontend checkout main'de+temiz DEĞİLSE KOPYALAMA,
  rapor et (F-P5 merge olduysa main temiz olabilir — kontrol et).
- `ARCHITECTURE-BACKEND.md` + `ROADMAP-BACKEND.md` güncelle (MetricPlaceholder borcunun kapandığı
  notu dahil), commit.
