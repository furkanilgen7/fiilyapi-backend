# İK-2 — İzin Yönetimi (backend spec)

Tarih: 2026-08-12 · Durum: **ONAYLANDI (hızlandırılmış düzen — kararlar §5'te yönetimce bağlı)**
Mockup: `İK - İzin Yönetimi.dc.html` (**İZ**, 176). Bağlam: İK-1 CANLIDA (`personnel` +
`hire_date`/`is_active`); izin bakiyesi personele bağlanır. Kapsam DIŞI: bordro/SGK (İK-3) ·
"Onay Kutusu" genel ekranı (izin onayı BU dilimde satır-içi ✓/✗ ile) · devreden-yanma job'u
(bildirim altyapısı yok — durum türevi yeter).

## 1. Şema (tek migration)

- **`leave_types`** katalog (İZ B): `name` (Yıllık/Hastalık/Mazeret) · `deducts_from_annual` bool
  (Yıllık=true; Hastalık/Mazeret=false — İZ 87 "Rapor", yıllık haktan düşmez) · `is_paid` bool ·
  `requires_document` bool (Hastalık→rapor, İZ 88) · `color` · `sort_order`. **SEED 3 tip**; katalog
  CRUD ucu AÇILMAZ (ayarlar dilimi).
- **`leave_requests`**: `personnel_id` CASCADE · `leave_type_id` FK RESTRICT · `start_date` ·
  `end_date` · `days` (KOLON — iş günü hesabı §5 K2; server hesaplar, istemci gönderemez) ·
  `note` Text(2000) · `document_id` FK→documents SET NULL nullable (İZ 88 "rapor ekli"; BC-2 pilotu
  emsali İK-1) · `status` enum `leave_status(pending, approved, rejected)` · `decided_by`/`decided_at`/
  `reject_reason` · audit.
- **`leave_balances`** (İZ D, yıl bazlı — devreden MANUEL): `personnel_id` CASCADE · `year` ·
  `carried_over` Numeric (İZ 137 "Devreden"; önceki yıldan taşınan, elle girilir — otomatik devir
  job'u İK-3) · UQ (personnel_id, year). **`annual_entitlement` KOLON DEĞİL** — kıdemden TÜREV
  (§5 K1). `used`/`remaining`/`usage_pct` de TÜREV.

## 2. Türev hesaplar (kolon yok)

- **Yıllık hak** = kıdemden (4857): `hire_date`→yıl bazında kıdem; <1 yıl → **hak yok** (İZ 163
  "1 yıl dolunca") · 1-5 yıl → 14 · 5-15 → 20 · >15 → 26. Tek kaynak sabit tablo.
- **Kullanılan** = o yılın `approved` izinlerinin `days` toplamı (yalnız `deducts_from_annual` tipler —
  hastalık/mazeret düşmez).
- **Kalan** = hak + `carried_over` − kullanılan (İZ formülü doğrulandı: 14+3−6=11 ✓).
- **Hak aşımı** (İZ 98-99 onay engeli): talebin `days`ı > o an kalan hak ise `approve` **REDDEDİLİR
  (409)** — yalnız `deducts_from_annual` tiplerde. **NULL-eşik kanonu:** kalan hak NULL/0 (kıdem<1)
  ise onay ENGELLİ (fail-closed). Red her zaman serbest.

## 3. Uçlar (~10; izin `personnel` modülü)

`GET/POST /leave-requests` (POST: kişi kendi/İK adına; `days` sunucu hesaplar; çakışan onaylı izinle
üst üste binme 409 §5 K3) · `PATCH /leave-requests/{id}` (yalnız pending) · `DELETE` (pending, sahibi
ya da admin) · `POST .../{id}/approve` + `.../{id}/reject` (reject `reason` zorunlu — TH emsali;
hak aşımında approve 409) · `GET /leave-requests?status=&personnel_id=&project_id=` (İZ talep tablosu;
TB3 sayfalama) · `GET/PUT /leave-balances/{personnel_id}/{year}` (PUT yalnız `carried_over` — manuel
devreden) · **`GET /hr/leaves/summary`** (İZ 5 KPI: bekleyen/bugün-izinli/ay-kullanılan/toplam-borç/
devreden-risk + bakiye tablosu) — N+1 ölçümlü.

## 4. Kapsam dışı / pending

Çok-aşamalı onay MOTORU AÇILMAZ (İZ 57 "şef→İK" akış METNİ; satır-içi tek ✓ = tek onay adımı — SA
onay-motoru kararı emsali) · otomatik devreden-devir + yanma bildirimi (İK-3) · ücretsiz izin tipi
(mockup'ta yok) · "+ İzin Talebi" formu ekranı frontend işi (backend uç hazır) · "Bugün İzinli"/
"Toplam Borç" gibi KPI'lar summary türevi.

## 5. Yönetimin bağladığı kararlar

K1 `annual_entitlement` kolon DEĞİL, kıdemden türev (4857 kademeleri tek kaynak sabit) — `carried_over`
manuel kolon, gerisi türev · K2 `days` SUNUCU hesabı (iş günü mü takvim günü mü: **takvim günü**,
başlangıç-bitiş dahil; hafta sonu/tatil çıkarma İK-3 — mockup 5 gün=04-08 Ağu dahil, takvim doğrular) ·
K3 aynı personelin ÇAKIŞAN onaylı izniyle üst üste binen yeni talep `approve`ta 409 (çift izin engeli) ·
K4 onay TEK adım (rol kapısı: `personnel` full+; şef→İK akışı metin) · K5 hak aşımı approve'ta 409 +
NULL/0 kalan fail-closed · K6 BC-2: rapor belgesi `documents` arşivine, `document_id` SET NULL ·
K7 kapanış — **PRODUCTION MERGE/DEPLOY İNSAN ONAYLI** (güvenlik olayı sonrası; şef PR+CI'a kadar
gider, merge+deploy için kullanıcıya sorar) · canlı YAZMA smoke YOK.

## 6. Test odakları

Kıdem→hak kademe sınırları (0/1/5/15 yıl) · kalan formülü + hastalık/mazeret düşmez · hak aşımı 409 +
NULL fail-closed · çakışan izin 409 · `days` sunucu hesabı (istemci gönderemez) · reject reason zorunlu ·
BC IDOR (görünmez document_id → 404) · onay tek-adım rol kapısı · IDOR · N+1 · migration turu.
