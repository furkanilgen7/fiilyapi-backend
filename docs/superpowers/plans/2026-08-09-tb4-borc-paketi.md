# TB4 — Borç Paketi (backend plan)

Tarih: 2026-08-09 · Spec: `../specs/2026-08-09-tb4-borc-paketi-design.md` (ONAYLI) ·
Dal: `feat/tb4-borc-paketi` (güncel main'den — `69e4aff` P10 merge'i dahil) ·
Task başına TEK subagent, her task sonunda commit. **Hedef SIFIR migration** — `alembic/` diff'i
boş kalmalı (T4'te `git diff main..HEAD -- alembic/` boş kanıtı; migration ihtiyacı doğarsa DUR).

## T1 — B1 · SD-2 sunucu-tarafı `diary` damgası (TDD)
- İKİ ailede (`progress_payments` + `subcontractor_progress_payments`) `PUT lines`:
  satırın miktarı, hakedişin dönemine ait **submitted** günlüklerin poz-bazlı toplamıyla
  karşılaştırılır → birebir eşitse `quantity_source=diary`, değilse `manual`. Her PUT'ta
  yeniden türetilir. Gövdeden `quantity_source` KABUL EDİLMEZ (mevcut bilinçli kural sürer).
- Köprü: satır↔günlük pozu eşlemesi mevcut "günlükten doldur" öneri uçlarının köprü mantığıyla
  AYNI kaynaktan (kopyalanmaz — ortak yardımcıya çıkarılır). Köprüsüz satır → `manual`.
- Testler: eşit→diary · farklı→manual · taslak günlük sayılmaz · köprüsüz→manual · ikinci PUT'ta
  damga tazelenir · gövdeden damga sızdırma denemesi etkisiz. İki aile için ayrı test dosyası.
- Mutasyon denetimi.

## T2 — B2 · dağıtım "kalan" tek kaynağa (TDD)
- İki tanım bulunur (aşım kontrolü kümesi vs "kalan" göstergesi kümesi), tek fonksiyona indirilir;
  **aşım kontrolünün kümesi otorite**. Davranış değişikliği beklenmez — mevcut testler DEĞİŞMEDEN
  yeşil kalmalı; ayrışma üretmeye çalışan yeni test + mutasyon kanıtı (tek kaynağı bozunca iki
  yüzey birden kırmızı).

## T3 — B3 · işveren kalemi → ayna BOQ senkronu (TDD)
- İşveren kalemi PATCH'inde (`unit_price`/`code`) dağıtılmış ayna BOQ satırlarının İLGİLİ alanları
  senkron tazelenir; MİKTARLARA DOKUNULMAZ. `FOR UPDATE` (TB1'in `lock_employer_items` deseni
  zaten var — yeniden kullan). Audit: mevcut update olayının detayına "N BOQ satırı tazelendi";
  yeni `AuditAction` YOK.
- Testler: fiyat değişimi BOQ satırına yansır · kod değişimi yansır · miktar korunur ·
  dağıtımsız kalemde hiçbir BOQ satırına dokunulmaz · başka projenin satırı etkilenmez (kapsam).
- Mutasyon denetimi.

## T4 — B4 küçükler + kapanış + FINAL REVIEW (Opus)
- `test_concurrency.py` seed-commit sızıntısı: fixture commit'siz; `modules/` testlerinden ÖNCE
  koşsa da yeşil kaldığının kanıtı (izole koşu sırası denemesi).
- Metin tavanı: sınırsız `description`/serbest metin alanlarına (boq + contracts aileleri) 2000 —
  `DESCRIPTION_MAX_LENGTH` tek-kaynak (BC emsali); 2000/2001 sınır testleri; kolon tipi DEĞİŞMEZ.
- Kapanış: tüm paket + ruff tüm repo + `alembic check` + `git diff main..HEAD -- alembic/` BOŞ.
- FINAL REVIEW odağı: damganın istekten sızdırılamazlığı · köprü mantığının öneri uçlarıyla tek
  kaynaklılığı (kopya = bulgu) · B2 tek-kaynak · B3 kapsam sınırı · kalıcı karar taraması
  (naming_convention dokunuşu / yeni migration / yeni AuditAction = bulgu). Bulgular kapatılır.
- `openapi.json` üret → DEVİR KURALI: frontend main'de+temiz DEĞİLSE KOPYALAMA, rapor
  (F-BC kapanış zincirinde — muhtemelen devir YAPILMAZ; borç P10+TB4 birikir, sonraki frontend T1'i).
- `ARCHITECTURE-BACKEND.md` + `ROADMAP-BACKEND.md` güncelle (§3'te üç borç satırı kapanır), commit.
