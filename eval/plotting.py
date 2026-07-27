"""绘图工具：根据 JSON 评测报告生成 PNG。"""

import json
import logging

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np

logger = logging.getLogger(__name__)

METRICS = ["NDCG@10", "Recall@10", "MRR@10", "MAP@10"]
COLORS = ["#4C72B0", "#55A868", "#C44E52", "#8172B2"]


def _load(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def _label(r: dict) -> str:
    col = r.get("collection", "")
    st = r["search_type"]
    rr = "+Rerank" if r.get("rerank") else ""
    return f"{col}/{st}{rr}" if col else f"{st}{rr}"


def _png(path: str) -> str:
    return path.rsplit(".", 1)[0] + ".png"


def plot(json_path: str) -> str:
    """读取单个 JSON 报告，在同目录生成柱状图 PNG。"""
    r = _load(json_path)
    values = [r["metrics"].get(k, 0) for k in METRICS]

    fig, ax = plt.subplots(figsize=(6, 4))
    bars = ax.bar(METRICS, values, color=COLORS, width=0.5)
    for bar, v in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.01,
                f"{v:.4f}", ha="center", va="bottom", fontsize=9)

    ax.set_title(f"{r['dataset']} | {_label(r)}")
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("Score")
    ax.yaxis.set_major_formatter(ticker.PercentFormatter(1.0))

    path = _png(json_path)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    logger.info("Saved: %s", path)
    return path


def plot_comparison(json_paths: list[str]) -> str:
    """读取多个 JSON，生成分组对比图。自动处理同 collection/跨 collection 场景。"""
    reports = [_load(p) for p in json_paths]
    metric_names = ["NDCG@10", "Recall@10", "MRR@10"]
    n_metrics = len(metric_names)
    n_groups = len(reports)

    fig, ax = plt.subplots(figsize=(max(7, n_groups * 1.8), 5))
    x = np.arange(n_metrics)
    width = 0.75 / n_groups

    for i, r in enumerate(reports):
        values = [r["metrics"].get(m, 0) for m in metric_names]
        offset = (i - (n_groups - 1) / 2) * width
        bars = ax.bar(x + offset, values, width,
                      label=_label(r), color=COLORS[i % len(COLORS)])
        for bar, v in zip(bars, values):
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.01,
                    f"{v:.4f}", ha="center", va="bottom",
                    fontsize=7, rotation=90)

    ax.set_xticks(x)
    ax.set_xticklabels(metric_names)
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("Score")
    ax.yaxis.set_major_formatter(ticker.PercentFormatter(1.0))
    ax.set_title(f"{reports[0]['dataset']} | Comparison")
    ax.legend(loc="lower right", fontsize=8)

    path = _png(json_paths[0]).replace(".png", "_cmp.png")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    logger.info("Saved: %s", path)
    return path
