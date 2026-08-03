# TB2 — Taşeron Sözleşme Liste Ucu + Hakediş site_id Filtresi (backend spec)

Tarih: 2026-08-03 · Durum: **ONAYLANDI (2026-08-03)** — kapsam kullanıcı onaylı ("TB2 okey").
Kaynak: F-TH diliminde ortaya çıkan iki boşluk (kullanıcıya sunuldu, geçici istemci çözümleri onaylandı):
1. Taşeron sözleşmesi LİSTE ucu yok (`GET /subcontractor-contracts/{id}` tekil; liste yok) — F-TH seçim
   adımı hakedişlerden türetiyor, **hiç hakedişi olmayan sözleşmeye ilk hakediş açılamıyor**.
2. `GET /subcontractor-progress-payments` yalnız `project_id` filtreli — şantiye sekmesi N+1 ile süzüyor.

## 1. Kapsam (additive; migration YOK; davranış değişikliği YOK)
- **U1 — `GET /subcontractor-contracts`** (`contracts:view`): filtreler `project_id` · `site_id` ·
  `status` · `q` (taşeron adı/sözleşme no araması). Yanıt: seçim adımının ihtiyacı olan alanlar
  (id, contract_no, subcontractor_name, work_category, project_id+adı, site_id+adı, status, is_draft).
  IDOR: `visible_projects` süzgeci; görünmeyen projelerin sözleşmeleri listelenmez.
- **U2 — `GET /subcontractor-progress-payments`'a `site_id` parametresi:** sözleşme üzerinden join
  (`contract.site_id = :site_id`). `site_id=NULL` sözleşmelerin hakedişleri bu filtreyle GELMEZ
  (SD S5 tek-anlamlılık kararıyla tutarlı). Summary ucuna da aynı filtre eklenir (şantiye KPI'ları için).

## 2. Kapsam DIŞI
SD-2 damga borcu (ayrı dilim) · sözleşme CRUD/ekranları (P5-frontend) · yeni izin/modül/kolon YOK.

## 3. Kabul
- Yeni parametreler openapi'de; eski çağrılar (parametresiz) birebir aynı davranır (geriye uyum testi).
- IDOR testleri U1 için işveren liste deseninden; U2 için site filtresi + görünürlük birlikte.
- Frontend takibi (F-TH kapanışından sonra ayrı mini görev): `useSubcontractorContractOptions` U1'e,
  `useSiteSubcontractorPayments` U2'ye geçer; N+1 ve "ilk hakediş açılamıyor" sınırları kapanır.
