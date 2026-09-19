"""İzin matrisi YALNIZ UYGULANAN kapsamları taşır (kullanıcı kararı 2026-09-19).

## Kusur

`Scope` enum'u DEKORATİFTİ: altı değeri vardı, matriste beşi kullanılıyordu ve
**hiçbiri hiçbir uçta okunmuyordu**. İzin Matrisi ekranı uygulanmayan bir kısıt
vaat ediyordu — ürün, tutmadığı bir sözü kullanıcıya yazılı olarak veriyordu.

## Karar

Ölçüm sonrası (2026-09-19) üç kapsam matristen DÜŞTÜ:

* **`own`** (`approvals` ×3) — uygulanması KUSUR olurdu. `GET /approvals`
  bilerek kapısızdır (kendi docstring'i matristeki `_OWN`a atıf yapar) ve
  `repository._pending_filter`in "Bekçi 5"i senin AÇTIĞIN zinciri senin onay
  kutundan ZATEN ÇIKARIR (çıkar çatışması). `created_by == aktör` süzgeci o
  bekçiyi TERS ÇEVİRİRDİ.
* **`project`** (`approvals` ×1 · `progress_payments` ×2) — FAZLALIK. Proje
  kapsamı `UserProjectAccess`ten sürülür ve iki modülde de ZATEN yürürlüktedir
  (`progress_payments/repository.py` · `approvals/repository.py`nin
  `visible_document_clause`u). İki mekanizmanın aynı kısıtı iki yerden
  söylemesi, bir gün ayrışmaları demekti.
* **`stock`** (`approvals` ×1) — onay kutusu zaten kişiseldir.

Geriye UYGULANAN iki kapsam kalır: `limited` (para alanları gizli) ve `finance`
(operasyonel detay gizli).

## 🔴 Neden SAYI değil BEKÇİ

Matristeki kapsamları elle saymak kusurun saatini ileri almaktan ibaret olurdu.
Bu bekçi, matrise UYGULANMAYAN bir kapsam ekleyeni testte durdurur ve onu
kapsamı ya GERÇEKTEN uygulamaya ya da `all` yazmaya zorlar.
"""

from app.core.access import DROPPED_SCOPES, Scope
from app.modules.roles.seed_data import MATRIX

#: Kodun GERÇEKTEN uyguladığı kapsamlar — DÜŞENLERİN TÜMLEYENİ olarak TÜRETİLİR,
#: elle YAZILMAZ. İki liste elle tutulsaydı bir gün ayrışırlar ve bu bekçi
#: ölçtüğünü sandığı şeyi ölçmeyi bırakırdı.
UYGULANAN_KAPSAMLAR = set(Scope) - DROPPED_SCOPES


def test_matris_UYGULANMAYAN_kapsam_TASIMAZ() -> None:
    """Matristeki her hücrenin kapsamı, kodun uyguladığı bir kapsam olmalıdır."""
    ihlaller = {
        modul: sorted({scope.value for _lvl, scope in hucreler} - UYGULANAN_KAPSAMLAR)
        for modul, hucreler in MATRIX.items()
        if {scope for _lvl, scope in hucreler} - UYGULANAN_KAPSAMLAR
    }
    assert not ihlaller, (
        "İzin matrisi UYGULANMAYAN kapsam taşıyor — ekran tutmadığı bir söz "
        f"veriyor. Ya kapsamı uygulayın ya `all` yazın: {ihlaller}"
    )


def test_UYGULANAN_kapsamlarin_HEPSI_matriste_KULLANILIYOR() -> None:
    """🔴 POZİTİF KONTROL — üstteki bekçi, matris TAMAMEN `all`a çökse de yeşil
    kalırdı ve o hâlde kapsam mekanizmasının tamamı ölü koda dönerdi."""
    kullanilan = {scope for hucreler in MATRIX.values() for _lvl, scope in hucreler}
    eksik = UYGULANAN_KAPSAMLAR - kullanilan
    assert not eksik, (
        f"Uygulanan kapsam matriste HİÇ kullanılmıyor: {sorted(s.value for s in eksik)}. "
        "Ya matrise ekleyin ya uygulamasını kaldırın."
    )
