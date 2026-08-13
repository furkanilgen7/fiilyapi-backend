"""Bordro şemaları — İK-3 T2'de YALNIZ `compute` çıktısı.

Dönem/satır okuma şemaları T3'ün işidir ve buraya SPEKÜLATİF olarak açılmaz
(YAGNI): açılsaydı henüz varlığı olmayan uçların sözleşmesi openapi'ye sızardı.
"""

from pydantic import BaseModel, Field


class PayrollComputeResult(BaseModel):
    """`POST /payroll/periods/{id}/compute` özeti — **sessiz atlama YOKTUR**.

    Atlanan satırlar sayıyla raporlanır (WORKFLOW §3): kullanıcı "hesapladım"
    yanıtını alıp elle düzelttiği satırın niçin değişmediğini merak etmemelidir.
    İki atlama sebebi AYRI sayılır çünkü anlamları farklıdır — biri kullanıcının
    kendi düzeltmesidir (K3/S6), diğeri ödeme izidir (S5).
    """

    created: int = Field(description="Yeni açılan satır sayısı")
    updated: int = Field(description="Yeniden hesaplanıp güncellenen satır sayısı")
    skipped_overridden: int = Field(
        description="Elle düzeltildiği için KORUNAN satır sayısı (S6)",
    )
    skipped_approved: int = Field(
        description="Onaylı/ödenmiş olduğu için KORUNAN satır sayısı (S5)",
    )
