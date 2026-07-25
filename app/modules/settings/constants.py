"""Bildirim olay katalogu. Migration'da per-user seed YOK — GET varsayilanlarla merge eder.

Yeni olay eklemek yalnizca bu listeyi genisletir; backfill gerekmez.
"""

NOTIFICATION_EVENTS: list[dict] = [
    {
        "event_key": "progress_payment_created",
        "label": "Hakedis olusturuldu",
        "email": True,
        "in_app": True,
        "sms": False,
    },
    {
        "event_key": "progress_payment_approved",
        "label": "Hakedis onaylandi",
        "email": True,
        "in_app": True,
        "sms": False,
    },
    {
        "event_key": "vat_due_soon",
        "label": "KDV odemesi yaklasiyor",
        "email": True,
        "in_app": True,
        "sms": False,
    },
    {
        "event_key": "approval_pending",
        "label": "Onay bekleyen islem",
        "email": False,
        "in_app": True,
        "sms": False,
    },
    {
        "event_key": "stock_low",
        "label": "Stok kritik seviyede",
        "email": False,
        "in_app": True,
        "sms": False,
    },
    {
        "event_key": "purchase_approval_pending",
        "label": "Satinalma onay bekliyor",
        "email": False,
        "in_app": True,
        "sms": False,
    },
    {
        "event_key": "payroll_payday",
        "label": "Bordro odeme gunu",
        "email": True,
        "in_app": True,
        "sms": False,
    },
    {
        "event_key": "daily_log_missing",
        "label": "Gunluk kayit girilmedi",
        "email": False,
        "in_app": True,
        "sms": False,
    },
    {
        "event_key": "user_added",
        "label": "Yeni kullanici eklendi",
        "email": False,
        "in_app": True,
        "sms": False,
    },
]

NOTIFICATION_EVENT_KEYS: set[str] = {event["event_key"] for event in NOTIFICATION_EVENTS}
NOTIFICATION_LABELS: dict[str, str] = {
    event["event_key"]: event["label"] for event in NOTIFICATION_EVENTS
}
