class DomainError(Exception):
    """Alan kuralı ihlali. Router katmanı bunu uygun HTTP koduna çevirir."""


class PermissionLockedError(DomainError):
    """system_admin rolünün izinleri değiştirilemez (kilitlenme koruması, spec §5.0)."""


class DeleteNotAllowedError(DomainError):
    """Silme koşulları sağlanmadı (spec §5.0)."""


class NotFoundError(DomainError):
    """İstenen kayıt bulunamadı — router katmanı 404'e çevirir."""
