"""LiHua-World 端到端评测：LLM 生成查询 → 多次调用 RAG MCP → evidence 对齐 + LLM 评分。

用法::

    PYTHONPATH=.. python -m rag.eval.lihua -c lihua --limit 20

主要组件:

    from rag.eval.lihua import E2EConfig, E2ERunner, RetrievalAgent, Trajectory
"""

from .agent import FinalAnswer, RetrievalAgent, Trajectory
from .dataset import QuerySample, load_queries, load_sessions
from .judge import JudgeResult, judge
from .llm import LLM, LLMConfig
from .metric import aggregate, evaluate
from .runner import E2EConfig, E2ERunner

__all__ = [
    "LLM",
    "E2EConfig",
    "E2ERunner",
    "FinalAnswer",
    "JudgeResult",
    "LLMConfig",
    "QuerySample",
    "RetrievalAgent",
    "Trajectory",
    "aggregate",
    "evaluate",
    "judge",
    "load_queries",
    "load_sessions",
]
