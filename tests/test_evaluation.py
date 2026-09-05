import numpy as np
import pandas as pd
import pytest

from wrfchem_site_eval.evaluation import aggregate_time, calculate_metrics, collocate, compare_case_metrics


def test_collocation_and_metrics_use_paired_values():
    times = pd.date_range("2019-01-01", periods=3, freq="h")
    obs = pd.DataFrame({
        "station_id": ["A"] * 3, "time": times, "latitude": [10.0] * 3,
        "longitude": [100.0] * 3, "temperature": [1.0, 2.0, np.nan],
    })
    model = pd.DataFrame({
        "station_id": ["A"] * 3, "time": times, "latitude": [10.0] * 3,
        "longitude": [100.0] * 3, "inside_domain": [True] * 3,
        "temperature": [2.0, 4.0, 100.0],
    })
    paired = collocate(obs, model, ["temperature"])
    metrics = calculate_metrics(paired, ["temperature"], "CASE", include_station=False)
    row = metrics.iloc[0]
    assert row["n"] == 2
    assert row["bias"] == pytest.approx(1.5)
    assert row["rmse"] == pytest.approx(np.sqrt(2.5))
    assert row["correlation"] == pytest.approx(1.0)


def test_wind_direction_uses_circular_error():
    paired = pd.DataFrame({"obs_wind_direction": [350.0], "model_wind_direction": [10.0]})
    metrics = calculate_metrics(paired, ["wind_direction"], "CASE", include_station=False)
    assert metrics.iloc[0]["bias"] == pytest.approx(20.0)


def test_daily_aggregation_minimum_count_and_case_comparison(tmp_path):
    hourly = pd.DataFrame({
        "station_id": ["A"] * 3, "time": pd.date_range("2019-01-01", periods=3, freq="h"),
        "precipitation": [1.0, 2.0, 3.0], "temperature": [300.0, 302.0, 304.0],
    })
    daily = aggregate_time(hourly, "1D", minimum_count=3)
    assert daily.loc[0, "precipitation"] == pytest.approx(6.0)
    assert daily.loc[0, "temperature"] == pytest.approx(302.0)
    first = tmp_path / "first.csv"
    second = tmp_path / "second.csv"
    pd.DataFrame({"case": ["B"], "variable": ["pm25"]}).to_csv(first, index=False)
    pd.DataFrame({"case": ["A"], "variable": ["pm25"]}).to_csv(second, index=False)
    result = compare_case_metrics([str(first), str(second)])
    assert result["case"].tolist() == ["A", "B"]
