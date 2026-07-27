"""Pytest surface for the data-quality checks.

The checks themselves live in `db.quality_checks` because the promotion path
calls them directly, on its own connection, inside an open transaction -- a
fixture-provided connection could not see uncommitted rows. This file is one
caller of that module, not its home.

Aliased on import so pytest collects each check as a test. `__all__` is an
explicit literal so the linter does not read these as unused imports and remove
the entire suite. Requires a database holding a manifested season; see
`db/tests/conftest.py`.
"""

from db.quality_checks import (
    check_active_players_have_stats as test_active_players_have_stats,
)
from db.quality_checks import (
    check_all_teams_have_games as test_all_teams_have_games,
)
from db.quality_checks import (
    check_game_dates_are_present as test_game_dates_are_present,
)
from db.quality_checks import (
    check_game_dates_fall_within_the_season as test_game_dates_fall_within_the_season,
)
from db.quality_checks import (
    check_game_scores_match_team_stats as test_game_scores_match_team_stats,
)
from db.quality_checks import (
    check_games_not_empty as test_games_not_empty,
)
from db.quality_checks import (
    check_games_reference_valid_teams as test_games_reference_valid_teams,
)
from db.quality_checks import (
    check_manifest_digest_recorded as test_manifest_digest_recorded,
)
from db.quality_checks import (
    check_natural_keys_are_enforced_by_constraints as test_natural_keys_are_enforced_by_constraints,
)
from db.quality_checks import (
    check_player_game_stats_not_empty as test_player_game_stats_not_empty,
)
from db.quality_checks import (
    check_player_stats_reasonable_values as test_player_stats_reasonable_values,
)
from db.quality_checks import (
    check_player_stats_reference_valid_games as test_player_stats_reference_valid_games,
)
from db.quality_checks import (
    check_player_stats_reference_valid_players as test_player_stats_reference_valid_players,
)
from db.quality_checks import (
    check_players_not_empty as test_players_not_empty,
)
from db.quality_checks import (
    check_recorded_game_count_reconciles as test_recorded_game_count_reconciles,
)
from db.quality_checks import (
    check_recorded_player_count_reconciles as test_recorded_player_count_reconciles,
)
from db.quality_checks import (
    check_recorded_shot_count_reconciles as test_recorded_shot_count_reconciles,
)
from db.quality_checks import (
    check_season_row_exists as test_season_row_exists,
)
from db.quality_checks import (
    check_shooting_percentages_valid as test_shooting_percentages_valid,
)
from db.quality_checks import (
    check_shot_attempts_not_empty as test_shot_attempts_not_empty,
)
from db.quality_checks import (
    check_shot_attempts_reference_valid_games as test_shot_attempts_reference_valid_games,
)
from db.quality_checks import (
    check_shot_totals_match_player_game_stats as test_shot_totals_match_player_game_stats,
)
from db.quality_checks import (
    check_team_game_stats_not_empty as test_team_game_stats_not_empty,
)
from db.quality_checks import (
    check_teams_not_empty as test_teams_not_empty,
)
from db.quality_checks import (
    check_two_teams_per_game as test_two_teams_per_game,
)
from db.quality_checks import (
    check_verification_status_passed as test_verification_status_passed,
)

__all__ = [
    "test_active_players_have_stats",
    "test_all_teams_have_games",
    "test_game_dates_are_present",
    "test_game_dates_fall_within_the_season",
    "test_game_scores_match_team_stats",
    "test_games_not_empty",
    "test_games_reference_valid_teams",
    "test_manifest_digest_recorded",
    "test_natural_keys_are_enforced_by_constraints",
    "test_player_game_stats_not_empty",
    "test_player_stats_reasonable_values",
    "test_player_stats_reference_valid_games",
    "test_player_stats_reference_valid_players",
    "test_players_not_empty",
    "test_recorded_game_count_reconciles",
    "test_recorded_player_count_reconciles",
    "test_recorded_shot_count_reconciles",
    "test_season_row_exists",
    "test_shooting_percentages_valid",
    "test_shot_attempts_not_empty",
    "test_shot_attempts_reference_valid_games",
    "test_shot_totals_match_player_game_stats",
    "test_team_game_stats_not_empty",
    "test_teams_not_empty",
    "test_two_teams_per_game",
    "test_verification_status_passed",
]
