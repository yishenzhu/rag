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
CMP_METRICS = ["NDCG@10", "Recall@10", "MRR@10"]
COLORS = ["#4C72B0", "#55A868", "#C44E52", "#8172B2"]
DPI = 150


def plot(json_paths) -> str:
    """根据 JSON 评测报告生成柱状图 PNG。

    单个路径：单报告柱状图（4 个指标）。
    多个路径：分组对比柱状图（3 个指标 × N 份报告）。
    """
    if isinstance(json_paths, str):
        json_paths = [json_paths]
    reports = [json.load(open(p)) for p in json_paths]
    if len(reports) == 1:
        return _plot_single(reports[0], json_paths[0])
    return _plot_comparison(reports, json_paths)


def _plot_single(r: dict, json_path: str) -> str:
    values = [r["metrics"].get(k, 0) for k in METRICS]
    fig, ax = plt.subplots(figsize=(6, 4))
    bars = ax.bar(METRICS, values, color=COLORS, width=0.5)
    ax.bar_label(bars, labels=[f"{v:.4f}" for v in values], fontsize=9, padding=2)
    ax.set_title(f"{r['dataset']} | {_label(r)}")
    return _finish(fig, ax, json_path.rsplit(".", 1)[0] + ".png")


def _plot_comparison(reports: list[dict], json_paths: list[str]) -> str:
    n_groups = len(reports)
    fig, ax = plt.subplots(figsize=(max(7, n_groups * 1.8), 5))
    x = np.arange(len(CMP_METRICS))
    width = 0.75 / n_groups

    for i, r in enumerate(reports):
        values = [r["metrics"].get(m, 0) for m in CMP_METRICS]
        offset = (i - (n_groups - 1) / 2) * width
        bars = ax.bar(x + offset, values, width,
                      label=_label(r), color=COLORS[i % len(COLORS)])
        ax.bar_label(bars, labels=[f"{v:.4f}" for v in values],
                     fontsize=7, rotation=90, padding=2)

    ax.set_xticks(x)
    ax.set_xticklabels(CMP_METRICS)
    ax.set_title(f"{reports[0]['dataset']} | Comparison")
    ax.legend(loc="lower right", fontsize=8)
    return _finish(fig, ax, json_paths[0].rsplit(".", 1)[0] + "_cmp.png")


def _label(r: dict) -> str:
    col = r.get("collection", "")
    st = r["search_type"]
    rr = "+Rerank" if r.get("rerank") else ""
    return f"{col}/{st}{rr}" if col else f"{st}{rr}"


def _finish(fig, ax, path: str) -> str:
    """统一收尾：坐标轴样式 + 保存。"""
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("Score")
    ax.yaxis.set_major_formatter(ticker.PercentFormatter(1.0))
    fig.tight_layout()
    fig.savefig(path, dpi=DPI)
    plt.close(fig)
    logger.info("Saved: %s", path)
    return path
