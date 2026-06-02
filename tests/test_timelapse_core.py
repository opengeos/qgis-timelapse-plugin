import datetime

from timelapse.core import timelapse_core


def test_date_sequence_dekadal_uses_calendar_dekads():
    ranges = timelapse_core.date_sequence(
        start_year=2026,
        end_year=2026,
        start_date="01-01",
        end_date="01-31",
        frequency="dekadal",
        step=1,
    )

    assert ranges == [
        (
            datetime.date(2026, 1, 1),
            datetime.date(2026, 1, 10),
            "2026-01-01",
        ),
        (
            datetime.date(2026, 1, 11),
            datetime.date(2026, 1, 20),
            "2026-01-11",
        ),
        (
            datetime.date(2026, 1, 21),
            datetime.date(2026, 1, 31),
            "2026-01-21",
        ),
    ]


def test_date_sequence_dekadal_respects_step():
    ranges = timelapse_core.date_sequence(
        start_year=2026,
        end_year=2026,
        start_date="01-01",
        end_date="01-31",
        frequency="dekadal",
        step=2,
    )

    assert [label for _start, _end, label in ranges] == [
        "2026-01-01",
        "2026-01-21",
    ]


def test_date_sequence_dekadal_uses_actual_month_end():
    ranges = timelapse_core.date_sequence(
        start_year=2026,
        end_year=2026,
        start_date="02-01",
        end_date="02-28",
        frequency="dekadal",
        step=1,
    )

    assert ranges[-1] == (
        datetime.date(2026, 2, 21),
        datetime.date(2026, 2, 28),
        "2026-02-21",
    )
