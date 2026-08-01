# P6 — Bölüm Detay + Form - Bölüm Ekle (backend spec)

Tarih: 2026-08-02 · Durum: **ONAYLANDI (2026-08-02)** — §7'nin TÜM soruları önerildiği gibi onaylandı:
S1 `on_hold` eklenir · S2 elle `budget_amount` kolonu açılır · S3 taşeron+makine pending ·
S4 bağımlılık/milestone/Gantt → P11 · S5 tamamlanan-kalem placeholder.
Mockup'lar: `projedesign/Bölüm Detay.dc.html` · `projedesign/Form - Bolum Ekle.dc.html`
Mevcut model: `app/modules/sites/models.py:203-257` (`sections`) · şemalar: `sites/schemas.py`

## 1. Kapsam
Bölüm Detay ekranının veri uçları + `Form - Bolum Ekle`nin istediği alanların `sections`'a eklenmesi.
İzin modülü **`sites`** (yeni modül açılmaz). BOQ-bölüm bağı **AÇILMAZ** (kalıcı karar 1).

## 2. Mevcut durum (özet)
`sections`: id, site_id, code, name, status(planned/active/completed), manager_user_id+manager_name,
start_date, end_date, sort_order, created/updated_at. `budget` bilinçli YOK (model yorumu: BOQ türevi).
`SectionResponse` yer tutucuları: `progress_pct`, `boq_item_count`, `budget`, `worker_count`.

## 3. Yeni kolonlar (hepsi nullable — taslak mantığı, kalıcı karar 4)
| Kolon | Tip | Mockup satırı | Not |
|---|---|---|---|
| `section_type` | Enum `section_type` (foundation_infra, structural, finishing, facade_roof, mep, landscape, handover) | Form 70 | etiketler: Temel & Altyapı / Kaba İnşaat / İnce İşler / Cephe & Çatı / Mekanik-Elektrik / Peyzaj / Teslimat & Kabul |
| `description` | Text | Form 74-75 | Açıklama / Kapsam |
| `deputy_manager_user_id` | UUID FK→users SET NULL | Form 84 | Yardımcı Sorumlu (izinli personel atanabilir — kalıcı karar 5) |
| `deputy_manager_name` | String(200) | Form 84 | manager_name deseniyle snapshot |
| `planned_worker_count` | Integer CHECK ≥0 | Form 85 | `sites.planned_worker_count` deseni |
| `is_draft` | Boolean NOT NULL default false | Form 242 "Taslak Kaydet" | taslak desteği sections'a genişler |

## 4. Enum değişikliği
`section_status`'a **`on_hold`** ("Beklemede", Form 71) eklenir — **§7 S1 onayına bağlı**.
`ALTER TYPE ... ADD VALUE`; downgrade'de enum yeniden yaratılır (Postgres kısıtı).

## 5. Uçlar
| Uç | İzin | İçerik |
|---|---|---|
| `GET /sections/{section_id}` (YENİ) | `sites:view` | tüm kolonlar + yer tutucular; IDOR: `visible_projects`, görünmeyen → 404 |
| `PATCH /sections/{section_id}` (GENİŞLER) | `sites:full` | yeni kolonlar `SectionUpdate`'e |
| `POST /sites/{site_id}/sections` (GENİŞLER) | `sites:full` | yeni kolonlar + `is_draft`; zorunluluklar yalnız taslak-dışı |
| `DELETE` | değişmez (`sites:admin`) | |
Audit: `AuditAction` + `messages.py` güncellenir. `code` boşsa otomatik `BLM-NN`
(şantiye `_next_site_code` desenine paralel; mevcut servis davranışı task'ta doğrulanır).

## 6. Bu dilimde BASILMAYANLAR (pending / başka dilim)
- **"Bölüme Atanacak İş Kalemleri" kartı (Form 131-211) BASILMAZ** — kalıcı karar 1 (BOQ-bölüm bağı
  kapalı); Detay'daki İş Kalemleri sekmesi/tablosu da aynı. Bağlar dilimi geldiğinde açılır.
- Hero KPI'ları (`progress_pct`, `budget`, `worker_count`, "Gerçekleşen") → placeholder deseni sürer.
- Sekmeler: İşçiler&Puantaj → puantaj · Malzeme → stok · Hakediş → progress_payments · Günlük → site_diary.
- Bölüm Belgeleri (Form 214-233) → belge çekirdeği (kalıcı karar 8, `pending_module: "documents"`).
- Görevli Taşeronlar / Kullanılacak Makineler (Form 88-98) → §7 S3.
- Bağımlılık + Milestone + "Gantt'a ekle" (Form 115-123, 237) → §7 S4.
- "3 gecikme riski" — bilinçli yok (mevcut şema yorumu korunur).

## 7. AÇIK SORULAR (kullanıcı cevabı ŞART)
- **S1 — "Beklemede":** `on_hold` enum'a eklensin mi? Önerim: evet.
- **S2 — Bölüm Bedeli (Form 110, zorunlu ₺):** Model "BOQ türevi" der ama bağ kapalı — türetilemez.
  (a) elle `budget_amount` kolonu (bağ gelince türeve çevrilir) · (b) placeholder kalsın, form basmasın.
  Önerim: **(a)**.
- **S3 — Taşeron + makine atamaları:** eşleme tabloları yok. Önerim: ikisi de pending (taşeron →
  taşeron hakediş dilimi, makine → makine modülü).
- **S4 — Bağımlılık/milestone/Gantt bayrağı:** P11'e ertelensin mi? Önerim: evet, kolon açılmaz.
- **S5 — "İş Kalemleri 16/26"daki 16 (tamamlanan):** placeholder mı kalsın? Önerim: evet.
