# ESA DocIR、RAG 与 mm 统一环境安装指南

本文整合当前 ESA 仓库中 DocIR、RAG（Retrieval-Augmented Generation）和 mm
（多模态附件摄取）的环境安装、配置、数据准备、启动与验证流程。

本文按以下优先级确定安装流程：

- 第一优先级——当前代码和契约：`requirements*.txt`、`.env.example`、
  `backend/core/utils/config.py`、`backend/agent/mm/config.py`、CLI 的真实参数；
- 第二优先级——当前状态的只读验证：模块 import、`pip check`、测试、模型 revision、
  manifest 和服务健康检查；
- 第三优先级——经验证的现场经验：用于识别已经成功过的组合、代理问题和运维坑，
  但不把一次性的操作记录当成安装脚本。

现场记录可能包含失败尝试、为当时网络临时增加的绕路、后来被代码替代的主机路径，
也可能遗漏后续人工命令。本文只吸收经当前代码和当前状态仍能成立的结论。环境快照
仅用于审计和版本比对，不应跨机器盲目执行 `pip install -r`。

## 1. 三个模块的关系

```text
源文件（PDF / DOCX / PPTX / XLSX / 图片）
                    │
                    ▼
             MinerU 独立环境
                    │
                    ▼
                  DocIR
                    │
             ┌──────┴─────────┐
             ▼                ▼
      ChunkCollection      mm 视觉增强
             │                │
             ▼                ├─ 短文档：直接上下文
      Embedding + Qdrant       └─ 长文档：进程内附件 RAG
             │
             ▼
     Retrieval + Evidence
             │
             ▼
        ESA Agent / B1 / B2
```

建议使用两个隔离的 Python 环境：

| 环境 | 用途 | 主要组件 |
| --- | --- | --- |
| `esa-rag` | 推荐的 DocIR/RAG/mm 模块环境；参考部署使用此名称 | PyTorch、Transformers、sentence-transformers、HTTPX |
| `esa-mineru` | 文档解析子进程 | `mineru[all]==3.4.4` 及其 OCR/VLM 依赖 |
| 完整 ESA 应用环境（可选） | 启动 WebAPI、Agent 和 vLLM 生成模型 | `requirements.txt` 中的完整依赖 |

MinerU 单独隔离是必要的：它的 Torch、Transformers、OCR 和视觉依赖较多，和 ESA
主环境混装容易发生版本覆盖。

## 2. 前置条件

推荐基础条件：

- Linux；
- Python 3.10 或 3.11；当前模块环境已验证 3.11.15，CI 使用 3.10；
- Git；
- 至少 20 GB 可用磁盘，真实模型和语料较多时需要更多空间；
- 构建正式 RAG 时需要可访问的 Qdrant；
- 使用本地 Transformers/vLLM 模型时需要兼容的 NVIDIA 驱动和 CUDA；
- 使用 Docker 启动 Qdrant 时需要 Docker Engine。

先进入仓库根目录，并用一个与机器无关的变量表示路径：

```bash
cd /path/to/esa
export ESA_WORKSPACE="$PWD"
```

模型、索引、数据库、日志、`artifacts/` 和 `runtime/` 都是本地运行数据，不应提交
到 Git。

## 3. 安装或复用 `esa-rag` 环境

### 3.1 当前推荐的模块环境

下面是根据当前模块 import、CLI 和测试收敛后的最小流程，不要求复刻历史命令顺序：

```bash
conda create -n esa-rag python=3.11 -y
conda activate esa-rag
python -m pip install --upgrade pip setuptools wheel

python -m pip install \
  "pydantic>=2,<3" \
  pypdf \
  huggingface_hub \
  safetensors \
  httpx

python -m pip install torch \
  --index-url https://download.pytorch.org/whl/cu128

python -m pip install transformers sentence-transformers
python -m pip install pytest
python -m pip check
```

PyTorch wheel 必须根据目标驱动/CUDA 选择；上面的 cu128 是参考部署验证过的选择，
不是所有机器的固定要求。使用 `ALL_PROXY=socks...` 时再安装 `httpx[socks]`：

```bash
python -m pip install "httpx[socks]"
```

### 3.2 参考部署的实测状态

2026-08-11 按当前 checkout 重新只读检查，而不是仅引用历史，得到：

| 项目 | 当前只读检查结果 |
| --- | --- |
| Python | 3.11.15 |
| Torch | 2.11.0+cu128 |
| CUDA runtime | 12.8 |
| GPU | 当前受限执行环境不可见；既有部署验证曾确认 RTX 4090 D 可用 |
| Transformers | 5.14.1 |
| sentence-transformers | 5.7.0 |
| Pydantic | 2.13.4 |
| pypdf | 6.15.0 |
| HTTPX | 0.28.1 |

该环境未安装 vLLM、Pillow、pillow-heif 或 pypdfium2，但当前 DocIR/RAG/mm 模块均可
import，模块测试结果为 `184 passed, 35 skipped`；skip 来自未随仓库提供的外部语料和
评测 artifacts，不是 import 失败。这说明上述缺失包不是当前模块回归路径的统一硬前提；
完整 WebAPI 或额外图像处理需要时，再按对应功能安装，不要为“看起来完整”无条件
堆入最小环境。

如果正在复用已有服务器环境，先检查现有环境，不要重复覆盖安装：

```bash
conda activate esa-rag
python --version
python -m pip check
python - <<'PY'
import torch
import transformers

print("torch:", torch.__version__)
print("cuda runtime:", torch.version.cuda)
print("cuda available:", torch.cuda.is_available())
print("gpu:", torch.cuda.get_device_name(0) if torch.cuda.is_available() else None)
print("transformers:", transformers.__version__)
PY
hf version
```

只有依赖检查或模块 import 表明确实缺包时，才进行增量安装。不要用当前仓库的完整
`requirements.txt` 无条件覆盖这套已经验证的轻量 RAG 环境，因为它还会引入完整 Agent
和固定的 `vllm==0.24.0`。

### 3.3 CI/CPU 测试环境

CI 不安装 vLLM/CUDA 运行栈，而使用：

```bash
python -m pip install -r requirements-dev.txt
python -m ruff check .
python -m mypy
python -m pytest
```

外部语料、真实模型或 GPU 不存在时，对应测试会明确 skip；不要伪造 manifest 或真实
检索结果来消除 skip。

需要记录一次已验证环境时，可以生成只读快照：

```bash
python -m pip freeze | sort > /path/to/operations-record/esa-environment.lock.txt
python -m pip check
```

快照应同时记录 Python、驱动和 CUDA 信息，并由运维保管；不要因为仓库中存在历史
lock 快照，就跨机器盲目复现其中的 CUDA wheel 组合。

### 3.4 完整 ESA 应用环境（可选）

需要启动 WebAPI、Agent 和主生成模型时，建议另建完整环境，或在确认兼容性后扩展
`esa-rag`：

```bash
conda create -n esa-app python=3.10 -y
conda activate esa-app
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt
python -m pip check
```

`requirements.txt` 当前包含 `vllm==0.24.0`。安装前应核对它和目标 CUDA、Torch 以及
Python 的兼容关系；这个完整应用环境不是上面已验证的 `esa-rag` 精确组合。

## 4. 安装 MinerU 独立环境

当前 DocIR 回归夹具观测于 MinerU 3.4.x，推荐固定 `3.4.4`：

```bash
conda create -n esa-mineru python=3.11 -y
conda activate esa-mineru
python -m pip install --upgrade pip uv
uv pip install "mineru[all]==3.4.4"
mineru --version
```

当前只读检查确认该环境仍为 Python 3.11.15、MinerU 3.4.4，且 `pip check` 通过。
服务器上应先复用并检查：

```bash
conda activate esa-mineru
python --version
python -m pip check
mineru --version
```

然后回到 RAG 环境，并把实际 MinerU 可执行文件告诉仓库包装脚本：

```bash
conda activate esa-rag
export MINERU_BIN="$(conda run -n esa-mineru which mineru)"
"$ESA_WORKSPACE/bin/run-mineru" --version
```

也可以直接配置绝对可执行文件路径，但不要把某台主机的 Conda 路径写回仓库。中国
网络环境若使用 MinerU 支持的 ModelScope 模型源，可在运行前设置：

```bash
export MINERU_MODEL_SOURCE=modelscope
```

无桌面的计算节点若在导入 OpenCV 时提示 `libGL.so.1`、`libGLX.so.0` 或
`libGLdispatch.so.0` 缺失，可把平台已有的兼容动态库目录以冒号分隔写入
`MINERU_LIBRARY_PATH`。`bin/run-mineru` 只会为 MinerU 子进程追加该路径，不会污染
ESA 主模型的动态库环境。模型缓存和 MinerU 配置也建议放进被忽略的 `runtime/`：

```bash
export MINERU_TOOLS_CONFIG_JSON="$ESA_WORKSPACE/runtime/mineru.json"
export HF_HOME="$ESA_WORKSPACE/runtime/huggingface-mineru"
export MINERU_MODEL_SOURCE=huggingface
mineru-models-download -s huggingface -m pipeline
```

六卡部署中，MinerU 和长附件 Embedding 应与正式 RAG Embedding 共用第六张卡；在后端
只暴露“主模型四卡 + 第六张卡”时，对应逻辑设备是 `cuda:4`。不要把 MinerU 默认的
`cuda` 留在逻辑 `cuda:0`，否则会和主模型抢显存。

首次解析时 MinerU 可能下载自己的模型。MinerU 模型、RAG Embedding 模型、可选
Reranker 和 mm VLM 是不同组件，不能互相替代。

支持的 DocIR/mm 输入扩展名包括：

- 文档：`.pdf`、`.docx`、`.pptx`、`.xlsx`；
- 图片：`.png`、`.jpg`、`.jpeg`、`.webp`、`.bmp`、`.gif`、`.tif`、`.tiff`。

## 5. 准备模型

### 5.1 正式 RAG 必需模型

当前冻结 RAG 使用：

- Embedding：`Qwen/Qwen3-Embedding-4B`；
- 向量维度：2560；
- 正式检索：dense-only；
- Reranker：默认关闭。

参考部署已通过 `hf cache verify --fail-on-missing-files` 校验以下模型 revision：

| 模型 | 已验证完整 revision |
| --- | --- |
| `Qwen/Qwen3-Embedding-4B` | `5cf2132abc99cad020ac570b19d031efec650f2b` |
| `Qwen/Qwen3-Reranker-4B` | `22e683669bc0f0bd69640a1354a6d0aebcfeede5` |

正式 dense-only 运行只需要 Embedding；Reranker 权重是现有实验资产，不代表正式默认
已经启用 Reranker。

Transformers 可以直接使用 Hub ID，也可以使用本地固定 revision 的模型目录。离线
部署建议先下载到仓库外部：

```bash
export ESA_MODEL_ROOT=/path/to/model-storage
mkdir -p "$ESA_MODEL_ROOT"
export ESA_EMBEDDING_REVISION=5cf2132abc99cad020ac570b19d031efec650f2b

hf download Qwen/Qwen3-Embedding-4B \
  --revision "$ESA_EMBEDDING_REVISION" \
  --local-dir "$ESA_MODEL_ROOT/Qwen3-Embedding-4B"

hf cache verify Qwen/Qwen3-Embedding-4B \
  --revision "$ESA_EMBEDDING_REVISION" \
  --local-dir "$ESA_MODEL_ROOT/Qwen3-Embedding-4B" \
  --fail-on-missing-files
```

如果要进行非正式 reranker 实验，再额外下载：

```bash
export ESA_RERANKER_REVISION=22e683669bc0f0bd69640a1354a6d0aebcfeede5
hf download Qwen/Qwen3-Reranker-4B \
  --revision "$ESA_RERANKER_REVISION" \
  --local-dir "$ESA_MODEL_ROOT/Qwen3-Reranker-4B"

hf cache verify Qwen/Qwen3-Reranker-4B \
  --revision "$ESA_RERANKER_REVISION" \
  --local-dir "$ESA_MODEL_ROOT/Qwen3-Reranker-4B" \
  --fail-on-missing-files
```

生产环境应把 revision 另存到运维记录或模型目录的 `REVISION` 文件，不以浮动 `main`
作为长期可复现身份。

在 SOCKS/代理部署中，Xet 曾发生失速；可回退到标准 HTTP：

```bash
env -u ALL_PROXY -u all_proxy HF_HUB_DISABLE_XET=1 \
  hf download Qwen/Qwen3-Embedding-4B \
  --revision "$ESA_EMBEDDING_REVISION" \
  --local-dir "$ESA_MODEL_ROOT/Qwen3-Embedding-4B"
```

只有遇到同类代理/Xet 问题时才使用该回退；正常网络应优先使用普通 `hf download`。

### 5.2 mm 所需模型和服务

mm 还需要：

1. 一个真实 tokenizer，由 `MM_TOKENIZER_PATH` 指定，用于判断附件走直接上下文还是
   进程内 RAG；
2. 一个 OpenAI-compatible 视觉模型服务，提供 `/v1/chat/completions`；
3. 一个 sentence-transformers 兼容的 Embedding 模型，用于超过阈值的长附件。

视觉服务可与 ESA 主模型分离部署。mm 只要求以下配置可用：

```text
MM_VLM_BASE_URL
MM_VLM_MODEL
MM_VLM_API_KEY（可选）
MM_TOKENIZER_PATH
MM_EMBEDDING_MODEL
MM_EMBEDDING_DEVICE
```

如果只运行 mm 的 fake-provider 单元测试，不需要下载真实 VLM 或模型。

### 5.3 完整 ESA WebAPI 的额外模型

DocIR、RAG 和 mm 的独立 CLI/测试不要求启动 ESA Agent 生成模型。但执行
`python -m backend.main` 会同时初始化完整 Agent，因此还需要配置：

```bash
ESA_MODEL_PATH=/path/to/main-generation-model
ESA_AUXILIARY_MODEL_PATH=/path/to/auxiliary-model
```

辅助模型预期由 OpenAI-compatible sidecar 提供，默认地址是
`http://127.0.0.1:51025/v1`。集群环境可使用 `backend/scripts/run_esa_stack.sh`，并通过
`ESA_CONDA_SH`、`ESA_CONDA_ENV` 和 `ESA_CUDA_HOME` 注入机器相关配置。只验证本文三个
模块时，优先使用各自 CLI 和测试，不必加载完整 Agent 大模型。

## 6. 启动 Qdrant

正式 RAG 使用 Qdrant，默认地址是 `http://127.0.0.1:6333`。Qdrant storage 必须放在
支持可靠文件锁的本地文件系统，不能放在超算的 NFS 项目目录或 NFS 持久盘；否则
Qdrant 会报告数据损坏风险。Slurm 启动脚本默认把在线 storage 放到当前作业的本地
`$SLURM_TMPDIR`，通过 `ESA_QDRANT_SNAPSHOT_PATH` 从 NFS 上的只读 collection snapshot
恢复；`ESA_QDRANT_STORAGE_PATH` 仅用于覆盖为另一处本地文件系统。本机 Docker 示例：

```bash
mkdir -p "$ESA_WORKSPACE/runtime/qdrant/storage"

docker run -d \
  --name esa-rag-qdrant \
  --restart unless-stopped \
  -p 127.0.0.1:6333:6333 \
  -v "$ESA_WORKSPACE/runtime/qdrant/storage:/qdrant/storage" \
  qdrant/qdrant:v1.18.3

curl -fsS http://127.0.0.1:6333/healthz
```

参考部署的已验证实例使用 `qdrant/qdrant:v1.18.3`、`unless-stopped`、仅绑定
`127.0.0.1:6333`，并在容器重启后通过健康检查。复用服务器现有实例时先检查，不要
重复创建同名容器：

```bash
curl -fsS http://127.0.0.1:6333/healthz
docker ps --filter name=esa-rag-qdrant
```

若 Docker daemon 无法拉取镜像，需注意 Shell 代理和 Docker daemon 代理是两套配置；
只有 `docker pull` 确认失败且已获
系统管理权限时，才为 daemon 配置代理并重启 Docker，避免影响同机其他容器。

不要在未配置认证、防火墙和 TLS 时把 6333 暴露到公网。远程或受保护的 Qdrant 可
通过 `RAG_QDRANT_BASE_URL` 和 `QDRANT_API_KEY` 配置。

## 7. 配置环境变量

复制模板：

```bash
cp .env.example .env
```

`.env` 已被 Git 忽略。当前 Python 配置直接读取进程环境，不会自动加载 `.env`，因此
启动前需要由 shell、容器编排或进程管理器注入。例如：

```bash
set -a
source .env
set +a
```

### 7.1 正式 RAG 配置

当前冻结身份为：

| 项目 | 正式值 |
| --- | --- |
| Collection | `collection_e55166f798ef1c361c72de9a` |
| 文档/Chunk | 11 / 941 |
| Deployment | `deployment_357bd9c84d8404fae42c2740` |
| Qdrant collection | `rag_qwen3_embedding_4b_v2` |
| Embedding | Qwen3-Embedding-4B，2560 维 |
| Fusion | `dense` |
| Dense candidates | 20 |
| Final results | 5 |
| Max context | 8192 tokens |
| Reranker | 关闭；契约中的 `rerank_limit=20` 保留 |

最小配置示例：

```bash
RAG_ENABLED=true
RAG_COLLECTION_MANIFEST_PATH=artifacts/chunk/collections/collection_e55166f798ef1c361c72de9a/manifest.json
RAG_INDEX_DEPLOYMENT_MANIFEST_PATH=artifacts/rag/indexes/deployment_357bd9c84d8404fae42c2740/manifest.json
RAG_QDRANT_BASE_URL=http://127.0.0.1:6333
RAG_QDRANT_COLLECTION=rag_qwen3_embedding_4b_v2
RAG_EMBEDDING_BACKEND=transformers
RAG_EMBEDDING_MODEL_PATH=/path/to/model-storage/Qwen3-Embedding-4B
RAG_EMBEDDING_DEVICE=cuda
RAG_EMBEDDING_RUNTIME_DEVICE=
RAG_EMBEDDING_DIMENSION=2560
RAG_FUSION_METHOD=dense
RAG_DENSE_WEIGHT=1.0
RAG_RERANKER_ENABLED=false
RAG_RERANKER_BACKEND=none
RAG_RERANK_LIMIT=20
RAG_FINAL_LIMIT=5
RAG_MAX_CONTEXT_TOKENS=8192
```

选择 vLLM Embedding 后端时，还必须设置 `RAG_EMBEDDING_BASE_URL`；选择 vLLM
Reranker 时还必须设置 `RAG_RERANKER_BASE_URL`。两者的可选认证统一读取
`VLLM_API_KEY`。

### 7.2 mm 配置

mm 默认关闭。启用应用生命周期中的会话服务：

```bash
MM_ENABLED=true
MM_ARTIFACT_ROOT=runtime/mm
MM_MINERU_COMMAND=bin/run-mineru
MINERU_BIN=/path/to/esa-mineru/bin/mineru
MM_DIRECT_CONTEXT_TOKEN_LIMIT=48000
MM_TOKENIZER_PATH=/path/to/tokenizer-or-model
MM_VLM_BASE_URL=http://127.0.0.1:8000/v1
MM_VLM_MODEL=Qwen3-VL
MM_VLM_API_KEY=
MM_EMBEDDING_MODEL=/path/to/sentence-transformers-compatible-model
MM_EMBEDDING_DEVICE=cuda
```

可选稳定性参数及默认值：

| 变量 | 默认值 |
| --- | ---: |
| `MM_MINERU_TIMEOUT_SECONDS` | 7200 |
| `MM_MINERU_ATTEMPTS` | 2 |
| `MM_VLM_TIMEOUT_SECONDS` | 120 |
| `MM_VLM_ATTEMPTS` | 2 |
| `MM_VLM_MAX_CONCURRENCY` | 4 |

启用后，FastAPI lifespan 创建 `app.state.mm_sessions`；该对象按会话保存
`PreparedAttachment`，支持 prepare、list、context_for、clear 和 close。当前仓库提供
应用内会话接口，不自动提供附件上传 HTTP 路由。

## 8. 准备 DocIR、Collection 和 Deployment

有两种部署方式。

### 8.1 使用冻结的正式部署

Git 不包含正式语料、Collection 内容、deployment manifest 或 Qdrant 数据。需要从受信
来源同时提供：

```text
artifacts/chunk/collections/collection_e55166f798ef1c361c72de9a/
artifacts/rag/indexes/deployment_357bd9c84d8404fae42c2740/manifest.json
Qdrant collection: rag_qwen3_embedding_4b_v2
```

三者必须属于同一个索引代次。运行时会校验 Collection ID、manifest SHA-256、Chunk
数量、Embedding 指纹、Qdrant 配置、向量维度和 `index_generation_id`；不能只复制
manifest 而不提供对应 Qdrant Point。

### 8.2 从自己的真实语料构建

把源文件放到本地数据目录，例如：

```bash
mkdir -p data/source_pdfs
```

第一步，运行 MinerU 并生成 DocIR：

```bash
python -m backend.agent.DocIR.tools.batch_corpus \
  --input-dir data/source_pdfs \
  --run-id my-corpus
```

输出位于：

```text
artifacts/mineru/runs/my-corpus/
artifacts/docir/runs/my-corpus/
```

第二步，生成 ChunkCollection：

```bash
python -m backend.agent.rag.chunk.cli \
  --input-root artifacts/docir/runs/my-corpus \
  --output-root artifacts/chunk/collections
```

记录命令输出产生的 `<collection_id>`，然后构建 Qdrant deployment：

```bash
python -m backend.agent.rag.cli.index build \
  --manifest "artifacts/chunk/collections/<collection_id>/manifest.json" \
  --qdrant-url "$RAG_QDRANT_BASE_URL" \
  --collection my-rag-collection \
  --embedding-backend transformers \
  --embedding-model "$RAG_EMBEDDING_MODEL_PATH" \
  --embedding-dimension 2560
```

该命令输出新的 `<deployment_id>` 和 manifest 路径。自建 Collection/deployment 不应
伪装成上面的冻结正式 ID；应在环境变量中显式使用新路径和 Qdrant collection。

## 9. 启动前校验与启动

先验证配置能够加载：

```bash
python - <<'PY'
from backend.core.utils.config import validate_startup_config
from backend.agent.mm import MMConfig

validate_startup_config()
MMConfig.from_env().validate_startup()
print("configuration: ok")
PY
```

`RAG_ENABLED=true` 时缺少 Collection/deployment manifest 会立即失败；
`MM_ENABLED=true` 时 MinerU 包装入口缺失或不可执行也会立即失败。

启动完整后端：

```bash
python -m backend.main
```

在六卡 Slurm 节点使用 `backend/scripts/run_esa_stack.sh` 时，脚本会将前四张卡分给
主模型、第五张卡分给辅助模型、第六张卡分给 Transformers Embedding，并自动把
`RAG_EMBEDDING_RUNTIME_DEVICE` 设置为主后端中的逻辑 `cuda:4`。`RAG_EMBEDDING_DEVICE`
仍保持为冻结部署指纹中的 `cuda`；前者只是物理放置别名，不改变索引身份。若
`RAG_ENABLED=true` 且本机 6333 未运行，脚本还会从
`runtime/qdrant/bin/qdrant` 启动仅监听本机的 Qdrant，拒绝把在线 storage 启动在 NFS，
并在新作业的本地 storage 为空时恢复 `ESA_QDRANT_SNAPSHOT_PATH`。

应用启动时：

- RAG lifecycle 加载并验证 deployment、Collection、Qdrant 和 Embedding provider，
  然后注入 Agent 工具；
- mm lifecycle 在启用时创建会话服务，模型和解析工作在实际附件摄取时使用；
- 应用退出时清理 RAG 全局服务和 mm 会话句柄。

## 10. 分层验证

### 10.1 DocIR

```bash
"$ESA_WORKSPACE/bin/run-mineru" --version
python -m pytest backend/agent/DocIR/tests
```

仓库内小型多格式回归样本位于
`backend/agent/DocIR/mineru_adapter_samples/`；外部真实 PDF 语料不存在时，相关测试应
明确 skip。

### 10.2 RAG 核心与 Chunk

不启动 Qdrant、不加载真实模型即可验证契约和参考后端：

```bash
python -m pytest backend/agent/rag/chunk/tests backend/agent/rag/tests
```

验证真实 deployment：

```bash
python -m backend.agent.rag.cli.index verify \
  --manifest "$RAG_COLLECTION_MANIFEST_PATH" \
  --deployment-manifest "$RAG_INDEX_DEPLOYMENT_MANIFEST_PATH"
```

执行真实查询：

```bash
python -m backend.agent.rag.cli.index query \
  --manifest "$RAG_COLLECTION_MANIFEST_PATH" \
  --deployment-manifest "$RAG_INDEX_DEPLOYMENT_MANIFEST_PATH" \
  --query "什么是进程调度？" \
  --reranker-backend none
```

B1 `get_knowledge_base_stats` 与 B2 `retrieve_knowledge` 的字段结构已冻结，但训练数据中的
成功返回值仍必须来自真实运行，不能根据“看起来合理”的内容编造。

### 10.3 mm

```bash
python -m pytest backend/agent/mm/tests
python -m backend.agent.mm.cli ingest /path/to/notes.pdf
python -m backend.agent.mm.cli query /path/to/notes.pdf \
  --query "总结这份资料的关键结论"
```

前一个命令使用 fake providers，可用于 CI；后两个命令要求 MinerU、tokenizer、VLM 和
长文档所需的 Embedding 均已正确配置。

### 10.4 全部模块

```bash
python -m pytest \
  backend/agent/DocIR/tests \
  backend/agent/rag/tests \
  backend/agent/rag/chunk/tests \
  backend/agent/mm/tests
```

## 11. 常见故障

### `RAG retrieval service is not configured`

应用没有启用/启动 RAG lifecycle。检查 `RAG_ENABLED=true`，并确认进程实际加载了环境
变量。单独 import 工具不会隐式加载模型或连接 Qdrant。

### manifest missing

确认 `RAG_COLLECTION_MANIFEST_PATH` 和 `RAG_INDEX_DEPLOYMENT_MANIFEST_PATH` 是从当前
工作目录可解析的路径。生产部署更推荐绝对路径。

### Collection、SHA-256、fingerprint 或 generation 不匹配

Collection、deployment、Embedding 配置和 Qdrant Point 不是同一索引代次。不要修改
manifest 绕过检查；应重新提供匹配工件或从真实语料重建索引。

### Qdrant 连接失败

检查：

```bash
curl -fsS "$RAG_QDRANT_BASE_URL/healthz"
docker logs esa-rag-qdrant
```

同时检查认证、代理、容器端口绑定和防火墙。

### MinerU executable not found

检查 `MINERU_BIN` 指向真实可执行文件，并验证：

```bash
command -v "$MINERU_BIN"
bin/run-mineru --version
```

### MinerU 导入 OpenCV 时缺少 OpenGL 动态库

先用 `ldd` 确认缺少的库，再把同一套 Conda/系统运行库目录配置到
`MINERU_LIBRARY_PATH`。不要把不匹配版本的单个 `.so` 复制进项目，也不要覆盖主环境的
全局 `LD_LIBRARY_PATH`；包装脚本会把该变量限制在 MinerU 子进程内。

### CUDA OOM

Embedding、Reranker、mm VLM 和 ESA 生成模型不要未经规划地同时加载到同一张 GPU。
可以降低 batch size、关闭 Reranker、把 VLM 部署到独立 GPU/服务，或改用远程 vLLM。

### mm VLM 请求失败

确认 `MM_VLM_BASE_URL` 已包含正确的 `/v1` 前缀，模型名与服务端 served model name
一致，并检查 `MM_VLM_API_KEY`、超时和服务端 `/models` 响应。

## 12. 安全与可复现性要求

- 不提交 `.env`、API Token、私钥、Qdrant 密钥或带凭据的代理地址；
- 不提交模型权重、正式语料、Qdrant storage、数据库、日志或运行 artifacts；
- 模型使用固定 revision，并记录模型身份、维度和推理后端；
- MinerU 升级时重新生成并比较多格式 bundle/DocIR 回归夹具；
- RAG contract 或 B1/B2 字段变化时更新契约测试，并重新采集真实返回；
- 任何 Collection/deployment 都必须由真实 DocIR 和真实索引构建产生，不得手写伪造。
