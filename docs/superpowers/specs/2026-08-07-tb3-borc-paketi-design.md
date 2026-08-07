# TB3 — Borç Paketi: work_category snapshot + U1 sayfalama + BOQ grup silme (backend spec)

Tarih: 2026-08-07 · Durum: **ONAYLANDI (2026-08-07)** — kapsam kullanıcı onaylı ("TB3 okey").
Kaynak borçlar (ROADMAP §3'te kayıtlı, üçü de dilim kapanışlarında kullanıcıya duyuruldu):
1. **TB3-A:** taşeron hakediş LİSTE şemasında `work_category` yok → F-TH şantiye sekmesi U1'e ek join
   yapıyor (1+1 istek). Snapshot alan eklenince join tamamen kalkar.
2. **TB3-B:** `GET /subcontractor-contracts` (U1) sayfalamasız — 200+ sözleşmede seçim kutusu sınırsız,
   kırpılma korkuluğunun karşılığı yok.
3. **TB3-C:** `DELETE /boq/groups/{id}` ucu yok → F-SD smoke'unda boş test grubu canlıda silinemedi (405).

## Kapsam (hepsi additive; davranış değişikliği yalnız yeni yüzeylerde)
- **A:** taşeron hakediş liste öğesine `work_category` (sözleşmeden okunur — JOIN'le, YENİ KOLON AÇILMAZ;
  zaten sözleşme join'i var). Detay şemasına da eklenir (tutarlılık).
- **B:** U1'e `limit` (varsayılan 50, tavan 200) + `offset` + yanıtta `total` — işveren/taşeron hakediş
  liste desenleriyle aynı biçim. Parametresiz çağrı: varsayılan limit uygulanır ama `total` döner
  (istemci kırpılmayı görebilir). MEVCUT tüketici (F-TH seçim adımı) kırılmamalı — `total` alanı additive,
  öğe alanları aynı kalır.
- **C:** `DELETE /boq/groups/{group_id}` — **yalnız BOŞ grup** (kalemi olan grup 409 `RelatedRecordsExist`),
  izin `boq:admin` (kalıcı karar 2: silme=admin; kalem DELETE emsali). Audit olayı.
- **Migration YOK** (kolon açılmıyor). Frontend takibi ayrı mini görev (F-PT'den sonra):
  `useSiteSubcontractorPayments` join'i kalkar (A) + seçim adımına `total` korkuluğu (B).

## Kabul
Geriye uyum: mevcut testler değişmeden yeşil (B'de varsayılan limit test fikstürlerini etkilemez —
doğrulanır) · A'da N+1 yok (tek JOIN kanıtı) · C'de dolu grup 409 + boş grup 204 + IDOR 404 ·
`alembic check` temiz + migration üretilmedi kanıtı (`git status`).
