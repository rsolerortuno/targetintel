import pandas as pd


def minmax_scale(series: pd.Series) -> pd.Series:
    """
    Min-max scale a pandas Series from 0 to 1.
    """
    min_value = series.min()
    max_value = series.max()

    if max_value == min_value:
        return series * 0

    return (series - min_value) / (max_value - min_value)


def add_initial_target_score(df: pd.DataFrame) -> pd.DataFrame:
    """
    First MVP target score.

    Version 0.1 only uses Open Targets evidence.
    Later versions will add DepMap, single-cell, spatial,
    survival, tractability, and LLM evidence.
    """
    df = df.copy()

    df["opentargets_score_scaled"] = minmax_scale(df["opentargets_score"])
    df["final_score"] = df["opentargets_score_scaled"] * 100

    df = df.sort_values("final_score", ascending=False)

    return df
