"""绘图工具：单组柱状图 + 多组对比图。"""

import logging
from datetime import datetime

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np

from ..core import auto_path

logger = logging.getLogger(__name__)


def plot_single(report: dict, label: str) -> str:
    """为单组评测结果生成指标柱状图，返回保存路径。"""
    metrics = report["metrics"]
    keys = ["NDCG@10", "Recall@10", "MRR@10", "MAP@10"]
    values = [metrics.get(k, 0) for k in keys]

    fig, ax = plt.subplots(figsize=(6, 4))
    colors = ["#4C72B0", "#55A868", "#C44E52", "#8172B2"]
    bars = ax.bar(keys, values, color=colors, width=0.5)

    for bar, v in zip(bars, values):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 0.01,
            f"{v:.4f}",
            ha="center",
            va="bottom",
            fontsize=9,
        )

    ax.set_ylim(0, 1.05)
    ax.set_ylabel("Score")
    ax.set_title(
        f"{report['dataset']} | {report['search_type']}"
        f"{' + Rerank' if report['rerank'] else ''}"
    )
    ax.yaxis.set_major_formatter(ticker.PercentFormatter(1.0))

    path = auto_path(f"data/{label}.png")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    logger.info("Chart saved: %s", path)
    return path


def plot_comparison(reports: list[dict], dataset_name: str) -> str:
    """多组评测汇总对比图，返回保存路径。"""
    metric_names = ["NDCG@10", "Recall@10", "MRR@10"]
    n_metrics = len(metric_names)
    n_groups = len(reports)

    fig, ax = plt.subplots(figsize=(8, 5))
    x = np.arange(n_metrics)
    width = 0.8 / n_groups
    colors = ["#4C72B0", "#55A868", "#C44E52", "#8172B2"]

    for i, report in enumerate(reports):
        values = [report["metrics"].get(m, 0) for m in metric_names]
        label = f"{report['search_type']}{'+Rerank' if report['rerank'] else ''}"
        offset = (i - (n_groups - 1) / 2) * width
        bars = ax.bar(x + offset, values, width, label=label, color=colors[i])
        for bar, v in zip(bars, values):
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height() + 0.01,
                f"{v:.4f}",
                ha="center",
                va="bottom",
                fontsize=7,
                rotation=90,
            )

    ax.set_xticks(x)
    ax.set_xticklabels(metric_names)
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("Score")
    ax.set_title(f"{dataset_name} | Strategy Comparison")
    ax.yaxis.set_major_formatter(ticker.PercentFormatter(1.0))
    ax.legend(loc="lower right", fontsize=8)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = auto_path(f"data/{dataset_name}_comparison_{ts}.png")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    logger.info("Comparison chart saved: %s", path)
    return path
