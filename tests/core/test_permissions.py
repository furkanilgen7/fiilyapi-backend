import pytest

from app.core.access import AccessLevel, satisfies


def test_levels_are_ordered():
    assert satisfies(AccessLevel.full, AccessLevel.view) is True
    assert satisfies(AccessLevel.view, AccessLevel.full) is False


def test_same_level_satisfies_itself():
    assert satisfies(AccessLevel.approve, AccessLevel.approve) is True


def test_none_satisfies_nothing_above_it():
    for required in (AccessLevel.view, AccessLevel.draft, AccessLevel.full, AccessLevel.admin):
        assert satisfies(AccessLevel.none, required) is False


def test_admin_satisfies_every_level():
    for required in AccessLevel:
        assert satisfies(AccessLevel.admin, required) is True


@pytest.mark.parametrize(
    ("actual", "required", "expected"),
    [
        (AccessLevel.draft, AccessLevel.view, True),
        (AccessLevel.request, AccessLevel.draft, True),
        (AccessLevel.approve, AccessLevel.request, True),
        (AccessLevel.full, AccessLevel.approve, True),
        (AccessLevel.admin, AccessLevel.full, True),
        (AccessLevel.full, AccessLevel.admin, False),
        (AccessLevel.approve, AccessLevel.full, False),
    ],
)
def test_level_ordering_matrix(actual, required, expected):
    assert satisfies(actual, required) is expected


def test_full_does_not_satisfy_admin():
    """Spec §5.0: full silmeyi kapsamaz — silme yalnızca admin seviyesindedir."""
    assert satisfies(AccessLevel.full, AccessLevel.admin) is False
