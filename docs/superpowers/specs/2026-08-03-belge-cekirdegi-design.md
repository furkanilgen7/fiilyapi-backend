# Belge Çekirdeği — documents (backend spec)

Tarih: 2026-08-03 · Durum: **ONAYLANDI (2026-08-03)** — §7'nin BEŞ sorusu da önerildiği gibi onaylandı:
S1 v1 depolama DB (ayrı blob tablosu + StreamingResponse + StorageBackend soyutlaması; R2/S3'e ileride
tek sınıfla) · S2 yeni `documents` izin modülü (20., grup MALI, §6 satırı) · S3 klasörler serbest
(otomatik seed yok) · S4 kapsam yalnız arşiv çekirdeği (form bağlama sonraki dilimler) ·
S5 50MB/dosya + geniş beyaz liste (zip+heic dahil).
Mockup'lar: `Ekran 12 - Belge Arşivi.dc.html` (E12 — global arşiv) · `Şantiye - Belgeler.dc.html` (SB —
şantiye sekmesi; en zengin kolon seti burada). Form belge alanları (şantiye 6, bölüm 3, satış 6, proje 6,
personel/makine/sözleşme) bu dilimin KAPSAMI DIŞINDA — §7 S4.
Bekleyen borç: 6 yerde `pending_module: "documents"` + 3 formda `DocumentsPlaceholderCard`.

## 1. Kapsam
Arşiv çekirdeği: klasörler + belge künyesi + ikili saklama (soyutlama katmanlı) + yükle/indir/ara/liste
uçları. Önizleme/thumbnail YOK (mockup'ta yok — yalnız emoji tip ikonu + İndir). Onay akışı YOK.
Versiyon tablosu YOK (mockup versiyon kavramını yalnız dosya ADINDA taşıyor — "Rev3"/"v4").

## 2. Yeni tablolar
### `document_folders`
`id` · `project_id` FK→projects CASCADE · `site_id` FK→sites CASCADE nullable (NULL=proje düzeyi klasör;
E12 kök=proje/şantiye) · `parent_id` self-FK SET NULL nullable (alt klasör; UI 2 seviye gösterir,
model N-seviyeyi yasaklamaz) · `name` String(150) · UQ (project_id, site_id, parent_id, name) ·
`created_by`. Kategori seti SERBEST (§7 S3) — otomatik seed YOK; E12'nin 5'li ve SB'nin 8'li listeleri
örnek veridir (adları da tutarsız: "Onay & İzinler" vs "İzin & Ruhsat").

### `documents` (künye — blob'suz; liste sorguları buna dokunur)
`id` · `folder_id` FK→document_folders SET NULL nullable · `project_id` + `site_id` (kapsam;
görünürlük süzgeci) · `filename` String(255) · `mime_type` String(100) · `size_bytes` BIGINT ·
`description` Text nullable (SB alt-satır serbest metni: "48 fotoğraf", "Aylık denetim") ·
`uploaded_by_user_id` FK→users SET NULL + `uploaded_by_name` snapshot (SB144 "Şantiye Şefi: S. Öztürk") ·
`created_at`. Versiyon/onay/etiket kolonu YOK.

### `document_blobs` (baytlar — künyeden AYRI tablo; §7 S1)
`document_id` PK/FK CASCADE · `data` BYTEA. Ayrı tablo = liste/arama sorguları blob'a asla dokunmaz,
TOAST şişmesi izole. **Depolama soyutlaması:** servis katmanında `StorageBackend` arayüzü (put/get/
delete/stream); v1 implementasyonu DB (`document_blobs`), ileride R2/S3 backend'i TEK sınıf değişimiyle
takılır (künye şeması değişmez — eski taslak kararın kendisi).

## 3. Uçlar (izin: §7 S2 `documents` modülü; `visible_projects` süzgeci; audit)
- Klasörler: `GET /projects/{id}/document-folders(?site_id=)` · `POST` · `PATCH /document-folders/{id}`
  (ad) · `DELETE` (yalnız BOŞ klasör; admin).
- Belgeler: `GET /documents?project_id=&site_id=&folder_id=&q=` (künye listesi + "Son Eklenenler" için
  `sort=created_at desc&limit=`) · `POST /documents` (multipart: dosya + folder/scope/description;
  sınırlar §7 S5; company logo yükleme deseni) · `GET /documents/{id}/download` (**StreamingResponse** —
  48MB tam-bellek okunmaz; Content-Disposition dosya adıyla) · `PATCH /documents/{id}` (ad/açıklama/
  klasör taşıma) · `DELETE /documents/{id}` (admin) — **silme UCU açılır ama ekranda BASILMAZ**
  (mockup'ta silme aksiyonu yok; mockup gelirse buton o zaman) — bilinçli karar.
- Arama `q`: yalnız dosya adı + açıklama (mockup'ta tek serbest kutu; filtre/sıralama/sayfalama YOK —
  mockup'ta da yok; `limit` yalnız Son Eklenenler için).

## 4. Sınırlar (§7 S5)
Dosya başına **50 MB** (mockup kanıtı: 48 MB ZIP) · uzantı/MIME beyaz listesi GENİŞ: pdf, doc/docx,
xls/xlsx/csv, dwg, jpg/jpeg/png/**heic**, **zip** (E12'de ZIP var; GK317 HEIC sayıyor — çelişkili GK278
dar listesi artefakt sayılır) · config'e `DOCUMENT_MAX_BYTES` + `ALLOWED_DOCUMENT_EXTENSIONS` env'leri.

## 5. Kapsam dışı / sonraki dilimler
Form belge alanlarının gerçek yüklemeye bağlanması (slot mekanizması) → her formun kendi takip dilimi ·
günlük fotoğrafları galerisi → F-SD sonrası ayrı iş (aynı çekirdeği kullanır) · thumbnail/önizleme ·
versiyon geçmişi · onay akışı · Belge Arşivi/Şantiye-Belgeler EKRANLARI → F-BC frontend dilimi.

## 6. İzin matrisi önerisi (S2 onaylanırsa seed'e girecek satır)
`documents` (20. modül, grup **MALI** — E12 sidebar'ında Mali sonunda): sysadmin `_A` · patron `_F` ·
şef `_F` · saha müh. `_F` · İK `_V` · muhasebe `_F` · PM `_V` · satınalma `_V`.

## 7. AÇIK SORULAR (kullanıcı cevabı ŞART)
- **S1 — Depolama:** v1 = DB bytea AMA ayrı `document_blobs` tablosu + StreamingResponse + 50MB sınır +
  `StorageBackend` soyutlaması (ileride R2/S3'e tek sınıfla geçiş). Önerim bu (eski taslak kararınla
  aynı). Alternatif: şimdi object storage kur (Railway'e bucket eklemek operasyonel iş — önermem).
- **S2 — İzin modülü:** yeni **`documents`** modülü (matris 19→20, grup MALI, §6 satırı). Onay?
- **S3 — Klasörler serbest:** otomatik kategori seed'i YOK; kullanıcı "+ Yeni Klasör"le açar (mockup'ın
  iki ekranı farklı listeler gösteriyor — sabit set kanıtlanamıyor). Onay?
- **S4 — Kapsam:** bu dilim yalnız ARŞİV çekirdeği; form belge alanlarının bağlanması sonraki dilimler.
  Onay?
- **S5 — Sınırlar:** 50MB/dosya + geniş beyaz liste (zip+heic dahil). Onay?
