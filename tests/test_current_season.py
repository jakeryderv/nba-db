"""Season-string date math for the scheduled refresh."""

import datetime

from current_season import current_season


def test_october_starts_new_season():
    assert current_season(datetime.date(2026, 10, 1)) == "2026-27"


def test_december_is_same_season():
    assert current_season(datetime.date(2026, 12, 31)) == "2026-27"


def test_january_belongs_to_prior_year_season():
    assert current_season(datetime.date(2027, 1, 1)) == "2026-27"


def test_june_finals_still_prior_year_season():
    assert current_season(datetime.date(2027, 6, 15)) == "2026-27"


def test_offseason_maps_to_completed_season():
    assert current_season(datetime.date(2026, 7, 20)) == "2025-26"


def test_september_is_still_prior_season():
    assert current_season(datetime.date(2026, 9, 30)) == "2025-26"


def test_century_boundary_formatting():
    assert current_season(datetime.date(1999, 11, 1)) == "1999-00"
