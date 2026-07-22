"""Product-level configuration shared by the API and data tooling."""

from datetime import date

# This is intentionally operator-controlled rather than derived from the calendar.
# An NBA season becomes the default only after its complete dataset has passed the
# official verification and guarded production-promotion workflow.
DEFAULT_SEASON = "2025-26"

# First calendar day after 2026 All-Star weekend. Regular-season games resume
# later that week, so this cleanly separates the two in-season phases.
ALL_STAR_BREAK_END = {DEFAULT_SEASON: date(2026, 2, 16)}
