#!/usr/bin/env python3
"""Print the current NBA season string (e.g. 2026-27).

October-December belong to the season starting that year;
January-September belong to the season that started the prior year.
"""

import datetime


def current_season(today: datetime.date) -> str:
    start_year = today.year if today.month >= 10 else today.year - 1
    return f"{start_year}-{str(start_year + 1)[-2:]}"


if __name__ == "__main__":
    print(current_season(datetime.date.today()))
