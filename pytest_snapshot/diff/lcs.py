"""Longest common subsequence utilities used by structural list diffing."""

from __future__ import annotations

from typing import Any


def _elements_equal(a: Any, b: Any) -> bool:
    """Return ``True`` only when two JSON values match by type and value."""
    if type(a) is not type(b):
        return False
    return a == b


def compute_lcs_indices(
    expected: list[Any],
    actual: list[Any],
) -> list[tuple[int, int]]:
    """Return index pairs for the longest common subsequence of two lists."""
    n = len(expected)
    m = len(actual)
    dp: list[list[int]] = [[0] * (m + 1) for _ in range(n + 1)]

    for i in range(1, n + 1):
        for j in range(1, m + 1):
            if _elements_equal(expected[i - 1], actual[j - 1]):
                dp[i][j] = dp[i - 1][j - 1] + 1
            else:
                dp[i][j] = max(dp[i - 1][j], dp[i][j - 1])

    result: list[tuple[int, int]] = []
    i, j = n, m

    while i > 0 and j > 0:
        if _elements_equal(expected[i - 1], actual[j - 1]):
            result.append((i - 1, j - 1))
            i -= 1
            j -= 1
        elif dp[i - 1][j] >= dp[i][j - 1]:
            i -= 1
        else:
            j -= 1

    result.reverse()
    return result
