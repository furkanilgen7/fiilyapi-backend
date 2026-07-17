import uuid
from dataclasses import dataclass

from app.core.access import AccessLevel, can_delete


@dataclass
class FakeRecord:
    created_by: uuid.UUID
    is_draft: bool


def test_admin_can_delete_anything():
    record = FakeRecord(created_by=uuid.uuid4(), is_draft=False)
    assert can_delete(uuid.uuid4(), AccessLevel.admin, record) is True


def test_full_cannot_delete_finalised_record():
    """Spec §5.0: full silmeyi kapsamaz."""
    actor = uuid.uuid4()
    record = FakeRecord(created_by=actor, is_draft=False)
    assert can_delete(actor, AccessLevel.full, record) is False


def test_owner_can_delete_own_draft():
    actor = uuid.uuid4()
    record = FakeRecord(created_by=actor, is_draft=True)
    assert can_delete(actor, AccessLevel.draft, record) is True


def test_owner_cannot_delete_own_finalised_record():
    """Onaylanmış kayıt, oluşturanı tarafından bile silinemez."""
    actor = uuid.uuid4()
    record = FakeRecord(created_by=actor, is_draft=False)
    assert can_delete(actor, AccessLevel.draft, record) is False


def test_user_cannot_delete_someone_elses_draft():
    record = FakeRecord(created_by=uuid.uuid4(), is_draft=True)
    assert can_delete(uuid.uuid4(), AccessLevel.draft, record) is False


def test_view_level_cannot_delete_even_own_draft():
    """Taslak istisnası en az draft seviyesi ister."""
    actor = uuid.uuid4()
    record = FakeRecord(created_by=actor, is_draft=True)
    assert can_delete(actor, AccessLevel.view, record) is False
