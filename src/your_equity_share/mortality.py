"""How long a household can expect to live, from the table inside Choi's model.

Choi, Liu and Liu fitted their discount rates on the 2019 United States life
table, so wherever this project needs a lifetime it reads the same table: one
mortality throughout the model rather than one inside the coefficients and
another beside them.

The figures are the expectation of life column, e_x, of National Center for
Health Statistics, United States Life Tables, 2019, National Vital Statistics
Reports 70(19), Table 1, total population. Its probabilities of dying are the
ones Choi's appendix uses, checked to the sixth decimal against the copy the
full life-cycle solver was validated with.

Used by the Italian variant to say when a household's funds are sold: Italian
law taxes an accumulating fund only on sale, and treats death as a sale, so the
tax can be put off at most for the rest of a life. See taxes.py.
"""

from __future__ import annotations

__all__ = ["LIFE_EXPECTANCY_2019", "remaining_life_expectancy"]

# Remaining years of life at each age from 0 to 100; the last is 100 and over.
LIFE_EXPECTANCY_2019 = (
    78.8, 78.3, 77.3, 76.3, 75.4, 74.4, 73.4, 72.4, 71.4, 70.4,  # ages 0 to 9
    69.4, 68.4, 67.4, 66.4, 65.4, 64.5, 63.5, 62.5, 61.5, 60.6,  # ages 10 to 19
    59.6, 58.6, 57.7, 56.7, 55.8, 54.9, 53.9, 53.0, 52.0, 51.1,  # ages 20 to 29
    50.2, 49.2, 48.3, 47.4, 46.4, 45.5, 44.6, 43.7, 42.7, 41.8,  # ages 30 to 39
    40.9, 40.0, 39.1, 38.1, 37.2, 36.3, 35.4, 34.5, 33.6, 32.7,  # ages 40 to 49
    31.8, 31.0, 30.1, 29.2, 28.4, 27.5, 26.7, 25.9, 25.1, 24.3,  # ages 50 to 59
    23.5, 22.7, 21.9, 21.1, 20.4, 19.6, 18.8, 18.1, 17.3, 16.6,  # ages 60 to 69
    15.9, 15.2, 14.5, 13.8, 13.1, 12.4, 11.8, 11.1, 10.5, 9.9,  # ages 70 to 79
    9.3, 8.7, 8.2, 7.7, 7.2, 6.7, 6.2, 5.8, 5.4, 5.0,  # ages 80 to 89
    4.6, 4.3, 4.0, 3.7, 3.4, 3.2, 3.0, 2.8, 2.6, 2.4,  # ages 90 to 99
    2.2,  # 100 and over
)


def remaining_life_expectancy(age: int) -> float:
    """Expected remaining years of life at a whole age, from the 2019 table."""
    if age < 0:
        raise ValueError(f"age must not be negative, got {age}")
    return LIFE_EXPECTANCY_2019[min(int(age), 100)]
