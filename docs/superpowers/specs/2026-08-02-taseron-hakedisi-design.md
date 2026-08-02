# Taşeron Hakedişi (backend spec)

Tarih: 2026-08-02 · Durum: **ONAYLANDI (2026-08-02)** — §8'in DÖRT sorusu da önerildiği gibi onaylandı:
S1 `subcontractor_contracts.vat_pct` default **20** (küme {1,10,20}; %18 artefakt) · S2 `section_id`
bilgi alanı (kota/hesaba girmez) · S3 kota tavanı = **sözleşme kalem miktarı** · S4 KDV tevkifatı bu
dilimde hesaba girmez (bayrak bilgi; fatura/muhasebe dilimine).
Mockup'lar: `projedesign/Ekran 2 - Taşeron Hakedişi.dc.html` (L) · `Taşeron Hakediş Oluştur.dc.html` (O)
Zemin: `subcontractor_contracts(+items)` P5'ten hazır (advance_pct=10, retainage_pct=5,
vat_withholding bayrağı, payment_period) · işveren hakediş deseni (`progress_payments`) birebir örnek ·
`calculations.py` saf fonksiyonları yeniden kullanılır · **site_diary modülü YOK** (izin anahtarı seed'de var, model yok).

## 1. Kapsam
Taşeron sözleşmesine bağlı dönemsel hakediş: iki yeni tablo + durum makinesi + hesap + liste/KPI uçları.
İzin modülü **`progress_payments`** (işveren hakedişiyle aynı ekran ailesi — yeni modül AÇILMAZ).
Ek küçük task: `index_type`/`has_price_escalation` işveren sözleşme okuma ucuna eklenir (P7 bulgusu).

## 2. Yeni tablolar (işveren deseni birebir, farklar işaretli)
### `subcontractor_progress_payments`
`id` · `contract_id` FK→subcontractor_contracts CASCADE · `project_id` (görünürlük süzgeci) ·
**`sequence_no` sözleşme kapsamlı** — UQ (contract_id, sequence_no); mockup #47/#48 sözleşme içi sayaç ·
`period_year/month` (taslakta nullable) · `description` · `status` enum `draft/pending_approval/approved/paid`
(işverenle aynı 4 durum — §5) · snapshot yüzdeler `vat_pct`/`advance_pct`/`retainage_pct` (sözleşmeden
kopyalanır; KDV kaynağı §8 S1) · `default_coefficient` Numeric(8,3) default 1 (**onaylı sapma** — aşağıda) ·
`section_id` FK→sections SET NULL nullable (§8 S2; O58 "Bölüm" seçici, NULL="Tüm Bölümler") ·
damgalar `submitted_at/approved_at/approved_by/paid_at` + `rejected_at`+`rejection_reason` (§5) ·
`created_by` RESTRICT. Tutar kolonu YOK (türev ilkesi). `is_draft` property.

### `subcontractor_progress_payment_lines`
`payment_id` CASCADE · `contract_item_id` FK→subcontractor_contract_items SET NULL · snapshot beşlisi
`code/description/unit/contract_unit_price/group_name` (grup adı `source_contract_item_id→employer_contract_groups`
zincirinden çözülür, snapshot'lanır) · `coefficient` default 1 · `quantity` ≥0 · `sort_order` ·
`quantity_source` enum(`manual`,`diary`) default `manual` (O87 "Günlük kayıttan" rozetinin altyapısı;
diary değeri site_diary dilimiyle dolar, bu dilimde HEP manual) · kısmi UQ (payment_id, contract_item_id).
**Guard:** `unit_price IS NULL` sözleşme kalemi hakedişe ALINAMAZ (422 — "girilmedi ≠ 0 TL").

## 3. Hesap (tfoot O147-163 + onaylı sapma)
`calculations.py` aynen: `line_total` (katsayılı) → brüt → `vat_amount(vat_pct)` → `advance_deduction`
(kümülatif tavanlı; tavan = sözleşme bedeli türevi = Σ kalem quantity×unit_price) → `retention_amount` →
`net_amount`. **ONAYLI SAPMA (eski karar, hafızada kayıtlı):** mockup tfoot'unda OLMAYAN **teminat
kesintisi satırı** ve **fiyat farkı katsayısı** eklenir — sapma diye geri alınmaz. Liste ekranındaki
"Net = Brüt − KDV" görünümü (L146) mockup HESAP HATASIDIR, altın sayı değildir (K5 emsali) — doğru
formül uygulanır. KDV tevkifatı (`vat_withholding`) → §8 S4.

## 4. Kota
Kümülatif tavan = **sözleşme kaleminin miktarı** (`subcontractor_contract_items.quantity`) — §8 S3.
İşveren kota mekaniği aynen: yalnız artışta kontrol, onayda kilit altında sırasız tam küme yeniden
doğrulama, `approved|paid` kümülatifi, bağı kopmuş satır kümülatiften düşer.

## 5. Durum makinesi
İşverenle birebir: `submit/approve/reject/mark-paid/unapprove` + aynı geçiş tablosu. **"Revize Gerekli"
rozeti (L177) 5. durum DEĞİL** — `reject` draft'a döndürür, `rejected_at`+`rejection_reason` damgalanır;
rozet `draft AND rejected_at IS NOT NULL` türevidir (yeniden submit'te damga temizlenir). Aynı sözleşmede
draft/pending varken yeni hakediş 409.

## 6. Uçlar (hepsi `progress_payments` izni + `visible_projects` süzgeci)
`GET /subcontractor-progress-payments` (liste; proje/dönem/durum/taşeron-arama filtreleri — L83-101) ·
`GET .../summary` (L105-122 KPI'ları) · `POST /subcontractor-contracts/{id}/progress-payments` (kalemler
sözleşmeden otomatik yüklenir — O66) · `GET/PATCH/{id}` · `PUT {id}/lines` (**DEĞİŞTİRME** semantiği) ·
`refresh-prices` · 5 durum aksiyonu · `DELETE` draft+`can_delete`. Audit tam kapsam.
**Ek task:** `GET /projects/{id}/contract` yanıtına `index_type` + `has_price_escalation` (P7 bulgusu; additive).

## 7. Pending / kapsam dışı
"Günlük kayıttan hesaplandı" önerileri → site_diary dilimi (UI'da bu dilimde her satır "Elle giriş") ·
gecikme cezası + malzeme mahsubu satırları (mockup'ta da yok) → ileri dilim · fatura/ödeme bağı →
mali dilimler · belge eki → belge çekirdeği.

## 8. AÇIK SORULAR (kullanıcı cevabı ŞART)
- **S1 — KDV oranı:** mockup çelişkili (liste %18, form %20). Önerim: taşeron sözleşmesine `vat_pct`
  kolonu (default **20**, küme {1,10,20}) + hakedişe snapshot; %18 eski oran artefaktı sayılır.
- **S2 — Bölüm bağı:** O58'de "Bölüm" seçici var; kalıcı karar 1 "bağlar sonra" der. Önerim: `section_id`
  **nullable bilgi alanı** olarak açılır (kota/dağıtım hesabına GİRMEZ, salt etiket/filtre) — mockup
  birebirlik kuralın gereği. Onay?
- **S3 — Kota tavanı:** sözleşme kalem miktarı mı (önerim), yoksa işveren poz dağıtım kotası mı?
  Önerim: **sözleşme miktarı** — taşeronun taahhüdü kendi sözleşmesidir; işveren kotasıyla çapraz kontrol
  ileride raporlama işi.
- **S4 — KDV tevkifatı:** `vat_withholding` bayrağı var ama oran/hesap yok, mockup'ta da satırı yok.
  Önerim: bu dilimde hesaba GİRMEZ (bayrak bilgi olarak kalır); tevkifat fatura/muhasebe dilimine.
