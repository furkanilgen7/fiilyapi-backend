"""Şantiye planlama korkulukları ve Türkçe hata metinleri (planlama spec §3).

`site_diary/guards.py` deseninin birebiri: metinler TEK yerde durur, router'a ya
da servise gömülü string YAZILMAZ.

`sites` modülünün "bulunamadı" cümlesi KOPYALANMAZ, İMPORT edilir: plan ucu
görünmeyen bir şantiye için `sites` ucundan FARKLI bir cümle dönerse, elinde bir
UUID olan kullanıcı iki uç arasındaki farktan kaydın var olduğunu çıkarabilir.
"""

from app.modules.sites.guards import SITE_MISSING

__all__ = ["SITE_MISSING", "WEEK_START_NOT_MONDAY"]

# 422 — `week_start` haftanın Pazartesi'si DEĞİL. Sessizce Pazartesi'ye
# kaydırmak, ekranın istediğinden BAŞKA bir haftayı gösterdiğini fark
# edemeyeceği anlamına gelirdi; hafta gezinme okları (P103-105) da yanlış
# çıpadan ilerlerdi. Aynı gerekçe yazma uçlarında (T3) daha da ağırdır:
# kaydırılmış bir hafta, kullanıcının görmediği bir haftanın hücrelerini
# DEĞİŞTİRME semantiğiyle süpürürdü.
WEEK_START_NOT_MONDAY = "Hafta başlangıcı Pazartesi olmalıdır"
