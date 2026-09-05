"""Optional diagnostic figures for paired station evaluations."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import numpy as np
import pandas as pd


def create_evaluation_figures(
    matched: pd.DataFrame, variables: Iterable[str], case_name: str, output_dir: str | Path
) -> list[Path]:
    """Create one paired scatter plot and one mean time-series plot per variable."""

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    products: list[Path] = []
    for variable in variables:
        obs_col, model_col = f"obs_{variable}", f"model_{variable}"
        if obs_col not in matched or model_col not in matched:
            continue
        paired = matched[["time", obs_col, model_col]].dropna()
        if paired.empty:
            continue
        fig, ax = plt.subplots(figsize=(5.2, 5.0))
        ax.scatter(paired[obs_col], paired[model_col], s=9, alpha=0.45)
        low = float(np.nanmin(paired[[obs_col, model_col]].to_numpy()))
        high = float(np.nanmax(paired[[obs_col, model_col]].to_numpy()))
        ax.plot([low, high], [low, high], color="black", linewidth=1)
        ax.set(xlabel="Observation", ylabel="WRF", title=f"{case_name}: {variable}")
        fig.tight_layout()
        path = root / f"scatter_{variable}.png"
        fig.savefig(path, dpi=180)
        plt.close(fig)
        products.append(path)

        means = paired.groupby("time")[[obs_col, model_col]].mean()
        fig, ax = plt.subplots(figsize=(8.0, 3.5))
        ax.plot(means.index, means[obs_col], label="Observation", linewidth=1.2)
        ax.plot(means.index, means[model_col], label="WRF", linewidth=1.2)
        ax.set(ylabel=variable, title=f"{case_name}: station mean")
        ax.legend(frameon=False)
        fig.autofmt_xdate()
        fig.tight_layout()
        path = root / f"timeseries_{variable}.png"
        fig.savefig(path, dpi=180)
        plt.close(fig)
        products.append(path)
    return products
