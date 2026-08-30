# Tuojing Model Platform Service

内部模型发版与查询服务。开发者通过 Streamlit 页面提交共享目录中的模型，服务负责版本计算、目录复制、SHA-256 和 Metadata 更新。

第一版只做直接发版，不区分运行环境，也不提供模型推理服务。

## 功能

- Streamlit 新增模型和查询页面；
- FastAPI 发版、查询和健康检查接口；
- 默认自动递增 PATCH 版本；
- 支持递增 MINOR、MAJOR 和指定版本；
- 支持显式强制替换已有版本；
- 限制模型来源必须位于共享 workspace；
- 发版前检查路径和读取权限，权限不足时返回修复命令；
- 记录可选发布人，并自动生成 UTC 发布时间；
- 维护最新 Metadata 和历史 Metadata；
- 使用文件锁支持多个 API Worker。

## 环境要求

- Linux；
- Python 3.11 或更高版本；
- [uv](https://docs.astral.sh/uv/)；
- API 服务能够读写模型 workspace、发版目录和 Metadata 目录。

安装锁定依赖：

```bash
uv sync --locked --all-groups
```

## 默认路径

| 用途 | 默认值 |
|---|---|
| 开发者模型根目录 | `/data/workspace` |
| 模型发版目录 | `/data/model-registry/model_release` |
| Metadata 目录 | `/data/model-registry/model_meta` |

`source_path` 必须满足：

1. 是绝对路径，并且真实存在；
2. 是 `/data/workspace` 下面的目录；
3. 最后一级目录名与 `model_name` 相同；
4. 至少包含一个文件；
5. 软链接目标真实存在，并且仍位于配置的 workspace 内；
6. API 服务用户能够遍历目录并读取全部文件及软链接目标。

例如：

```text
/data/workspace/umi-policy/
├── model.pt
├── config.yaml
└── tokenizer.json
```

允许文件或目录软链接。平台发布时会解除软链接并复制目标的真实内容，因此发版目录不依赖原 workspace；失效链接、循环链接或指向 workspace 外的链接会被拒绝。

## 启动 API

使用默认配置：

```bash
uv run tuojing-model-api \
  --host 0.0.0.0 \
  --port 8000 \
  --workers 1
```

指定 Metadata 和其他目录：

```bash
uv run tuojing-model-api \
  --host 0.0.0.0 \
  --port 8000 \
  --workers 2 \
  --meta-dir /data/custom/model_meta \
  --release-dir /data/model-registry/model_release \
  --workspace-root /data/workspace
```

参数：

| 参数 | 默认值 |
|---|---|
| `--host` | `0.0.0.0` |
| `--port` | `8000` |
| `--workers` | `1` |
| `--meta-dir` | `/data/model-registry/model_meta` |
| `--release-dir` | `/data/model-registry/model_release` |
| `--workspace-root` | `/data/workspace` |

也可以使用环境变量：

```text
MODEL_PLATFORM_META_DIR
MODEL_PLATFORM_RELEASE_DIR
MODEL_PLATFORM_WORKSPACE_ROOT
```

API 文档地址：

```text
http://<host>:8000/docs
```

## 启动 Streamlit

API 启动后，在另一个终端运行：

```bash
uv run tuojing-model-ui \
  --host 0.0.0.0 \
  --port 8501 \
  --api-url http://127.0.0.1:8000
```

页面地址：

```text
http://<host>:8501
```

Streamlit 只调用 FastAPI，不直接读写模型目录和 Metadata。

## API

### 健康检查

```bash
curl http://127.0.0.1:8000/api/v1/health
```

响应会显示服务实际使用的三个目录，可用于确认 `--meta-dir` 是否生效。

### 发版模型

默认递增 PATCH：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/models/release \
  -H 'Content-Type: application/json' \
  -d '{
    "project_name": "Umi2Isaac",
    "model_name": "umi-policy",
    "source_path": "/data/workspace/umi-policy/",
    "released_by": "alice"
  }'
```

`released_by` 可不填；`released_at` 由服务自动生成 UTC ISO-8601 时间戳，客户端不能指定。

如果服务没有复制权限，接口返回 `403` 和可执行的最小 ACL 授权命令，例如：

```json
{
  "detail": "service user 'model-service' cannot read model source: /data/workspace/umi-policy",
  "suggested_command": "sudo setfacl -m u:model-service:x -- /data/workspace && sudo setfacl -R -m u:model-service:rX -- /data/workspace/umi-policy"
}
```

由模型目录所有者或管理员审核后执行 `suggested_command`，再重新发版。服务不会自动修改源目录权限。

版本策略：

```json
{"version_strategy": "minor"}
{"version_strategy": "major"}
{"version_strategy": "exact", "version": "1.2.3"}
```

替换已有版本：

```json
{
  "version_strategy": "exact",
  "version": "1.2.3",
  "force_replace": true
}
```

强制替换会覆盖旧模型文件，仅将旧 Metadata 放入历史文件，不提供旧模型恢复能力。

### 查询模型

查询最新版本：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/models/query \
  -H 'Content-Type: application/json' \
  -d '{
    "project_name": "Umi2Isaac",
    "model_name": "umi-policy",
    "latest_only": true
  }'
```

查询包括历史版本在内的全部结果：

```json
{
  "project_name": "Umi2Isaac",
  "model_name": "umi-policy",
  "latest_only": false
}
```

## 发版结果

```text
/data/model-registry/model_release/
└── Umi2Isaac/
    └── umi-policy/
        └── 0.0.1/
            ├── model.pt
            ├── config.yaml
            └── tokenizer.json
```

Metadata：

```text
/data/model-registry/model_meta/
├── model_meta.json
└── model_meta_record.json
```

- `model_meta.json` 保存每个模型当前最新版本；
- `model_meta_record.json` 保存已经被新版本替换的历史 Metadata。

## 测试和构建

```bash
uv lock --check
uv sync --locked --all-groups
uv run --locked pytest -q
uv build --no-sources
```

`dist/` 是 `uv build` 自动生成的构建输出目录，不是源码包目录：

- `*.whl` 是可以用 `pip install` 或 `uv pip install` 安装的 Wheel；
- `*.tar.gz` 是 Python 源码发行包（sdist）；
- 两者都可以删除，并通过 `uv build --no-sources` 重新生成，因此 `dist/` 默认不提交 Git。

详细架构见 [ARCHITECTURE.md](ARCHITECTURE.md)。
