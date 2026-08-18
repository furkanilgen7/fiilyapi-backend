"""FIN-1 — cek & senet portfoyu (E10 `Cek & Odeme` ekrani).

Paket, tek dosyaya YIGILMADAN acildi (gorev emri tuzak listesi): `sites/
service.py` 1087 ve `personnel/service.py` 1124 satirla 800 tavanini ZATEN
asmis durumda ve ikisi de "sonra boleriz" diye baslamisti.

| dosya | sorumluluk |
|---|---|
| `derive.py` | K2/K8'in TUREV katmani — `is_due` + ay penceresi (TEK kaynak) |
| `transitions.py` | K2 gecis TABLOSU + terminal koruma + `direction` uyumu |
| `schemas.py` | Pydantic govde/yanit uclusu |
| `repository.py` | yalniz SQL — karar yok, kapsam kararini `service` verir |
| `summary.py` | K8'in dort KPI karti |
| `service.py` | is kurallari: CRUD + gecis + kapsam |
| `router.py` | yedi uc + izin kapilari |
"""
