# RAG Service

基于 FastAPI 的 RAG（Retrieval-Augmented Generation）服务，包含知识库（KnowledgeBase）和记忆库（MemoryBank）两种向量存储。项目支持 Qdrant 向量库、Embedding 服务、Rerank 服务及 BEIR 数据集评测。

## 目录结构

- `main.py` - 启动 RAG API 服务
- `mcp_svr.py` - 启动 MCP Server
- `conf/conf.yaml` - 服务配置
- `engine/` - 核心业务逻辑：知识库、记忆库、管道、chunker
- `eval/` - 评测与数据集导入工具
- `vector_store/qdrant.py` - Qdrant 封装
- `scripts/run.sh` - 统一启动/停止/状态管理脚本
- `data/` - 评测结果与生成文件输出目录
- `models/` - 本地模型文件

## 快速开始

### 1. 安装依赖

```bash
cd /home/dfg/rag
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

> 项目依赖定义在 `pyproject.toml`，包括 `fastapi`、`qdrant-client`、`httpx`、`beir`、`matplotlib` 等。

### 2. 启动服务

使用项目自带管理脚本：

```bash
cd /home/dfg/rag
./scripts/run.sh start
```

可选参数：

- `./scripts/run.sh start api`：仅启动 API 服务及依赖服务
- `./scripts/run.sh start mcp`：仅启动 MCP 服务及依赖服务
- `./scripts/run.sh stop`：停止所有服务
- `./scripts/run.sh status`：查看各服务运行状态

### 3. API 地址

- RAG API: `http://localhost:8001`
- MCP Server: `http://localhost:9000`
- Embedding 服务: `http://localhost:8002`
- Rerank 服务: `http://localhost:8003`

## 使用说明

### 创建/列出知识库

- 创建 collection：

```bash
curl -X POST http://localhost:8001/knowledge \
  -H "Content-Type: application/json" \
  -d '{"name":"scifact","enabled":true,"hybrid":true}'
```

- 列出 collection：

```bash
curl http://localhost:8001/knowledge
```

### 导入文档 / BEIR 数据集

直接调用导入脚本：

```bash
cd /home/dfg
source rag/.venv/bin/activate
python -m rag.eval.ingest <source-path> -c <collection>
```

导入 BEIR 数据集：

```bash
python -m rag.eval.ingest --dataset-name scifact -c scifact
```

### 检索查询

发送 search 请求：

```bash
curl -X POST http://localhost:8001/knowledge/search \
  -H "Content-Type: application/json" \
  -d '{
    "collection": "scifact",
    "queries": ["your query text"],
    "top_k": 10,
    "threshold": 0.0,
    "search_type": "dense",
    "rerank": false
  }'
```

## 评测

当前项目支持 BEIR 评测流程。示例：

```bash
cd /home/dfg
source rag/.venv/bin/activate
python -m rag.eval eval --dataset-name scifact --collection scifact
```

这会生成 JSON 报告文件到 `rag/data/`，默认文件名类似：

- `scifact_scifact_dense_no_rerank_<timestamp>.json`
- `scifact_scifact_dense_rerank_<timestamp>.json`
- `scifact_scifact_hybrid_no_rerank_<timestamp>.json`
- `scifact_scifact_hybrid_rerank_<timestamp>.json`

### 绘图

评测完成后，可使用 plot 功能生成对比图：

```bash
cd /home/dfg
source rag/.venv/bin/activate
python -m rag.eval plot /home/dfg/rag/data/<report1>.json /home/dfg/rag/data/<report2>.json ...
```

生成的 PNG 文件会保存到 `rag/data/`。

## 运行环境

- Python 3.11+
- Qdrant (通过 Docker 启动)
- 本地模型文件存放在 `models/`

## 注意事项

- `python -m rag.eval` 需要从父目录运行或确保 `PYTHONPATH` 包含 `/home/dfg`。
- Qdrant collection 在服务端实际存储时使用命名空间前缀，例如 `KnowledgeBase.scifact`。
- 如果在 `ingest` 时出现 404 或 `collection doesn't exist`，可能是 RAG 服务内存状态与 Qdrant 实际状态不同步，建议重启 RAG 服务后重新导入。

## 开发

项目已配置 `README.md` 为 `pyproject.toml` 的默认 README 文件。可通过 `pytest` 执行开发测试，`ruff` 进行静态检查。

```bash
source .venv/bin/activate
pytest
ruff check .
```
