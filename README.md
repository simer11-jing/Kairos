# Kairos OpenClaw 集成

基于 Honcho 的用户建模与主动推理系统，为 OpenClaw 提供用户画像和记忆增强能力。

## 部署状态

| 组件 | 状态 |
|------|------|
| API (http://localhost:8000) | ✅ 运行中 |
| Deriver | ✅ 运行中 |
| Redis | ✅ 运行中 |
| PostgreSQL | ✅ 运行中 |

## 模型配置

- **提供商**: SiliconFlow
- **模型**: Qwen/Qwen2.5-7B-Instruct
- **用途**: 用户画像分析、对话推理、记忆总结

## 核心功能

| 功能 | 状态 | 说明 |
|------|------|------|
| Chat 对话 | ✅ | 核心对话能力 |
| 用户画像 | ✅ | 双端建模（User Peer + AI Peer） |
| 上下文记忆 | ✅ | 自动累积用户偏好 |
| 自动学习 | ✅ | 每小时增量更新画像 |
| 搜索 | ✅ | 基于上下文的用户信息检索 |
| 竞彩模式识别 | ✅ | 连胜/连负、高赔偏好、主客场偏差 |
| 投注历史学习 | ✅ | 从 betting-results.md 统计偏好/胜率 |
| 三态反馈 | ✅ | adopted/adjusted/rejected 推理反馈 |
| 追问链 | ✅ | --follow-up 多轮推理 + session 持久化 |
| 历史学习 | ✅ | --learn-from-history 读取7天记忆 |
| 团队经验共享 | ✅ | hindsight-memory 共享层融合 |
| Embedding 缓存 | ✅ | 24h TTL，3并发，429重试 |

## 文件结构

```
~/.openclaw/skills/kairos/
├── kairos-learner.py   # v2 增量学习脚本（推荐）
├── kairos-cli.py       # CLI 工具（含 append 模式）
├── client.py           # Kairos API Python 客户端
├── SKILL.md            # Skill 定义
└── README.md           # 本文件

~/.openclaw/kairos/     # Docker 部署目录
├── docker-compose.yml  # 容器编排
├── .env                # 环境变量（勿提交）
└── data/               # 数据卷
```

## 快速开始

### 启动服务

```bash
cd ~/.openclaw/kairos
docker compose up -d
```

### 健康检查

```bash
curl http://localhost:8000/health
```

### CLI 使用

```bash
# 健康检查
python3 ~/.openclaw/skills/kairos/kairos-cli.py health

# 发送消息
python3 ~/.openclaw/skills/kairos/kairos-cli.py chat "你好" --user jinghao

# 获取上下文
python3 ~/.openclaw/skills/kairos/kairos-cli.py context --user jinghao

# 搜索用户信息
python3 ~/.openclaw/skills/kairos/kairos-cli.py search "偏好" --user jinghao

# 更新用户知识（全量模式）
python3 ~/.openclaw/skills/kairos/kairos-cli.py update "用户偏好：简洁回复" --type preference

# 更新用户知识（追加模式）
python3 ~/.openclaw/skills/kairos/kairos-cli.py update "新增偏好：喜欢尝试新工具" -a
```

### Python API

```python
import sys
sys.path.insert(0, '~/.openclaw/skills/kairos')
from client import KairosClient

with KairosClient() as client:
    workspace = client.get_or_create_workspace("openclaw-main")
    peer = client.get_or_create_peer(workspace.id, "jinghao")

    # Chat 对话
    response = client.chat(workspace.id, peer.id, "你好")

    # 获取上下文
    context = client.get_context(workspace.id, peer.id)

    # 更新用户知识
    client.update_representation(
        workspace.id, peer.id,
        "用户偏好：简洁回复",
        representation_type="preference"
    )
```

## Kairos Learner v2

增量用户学习脚本，对比旧版的核心改进：

### 改进项

| 改进 | 说明 |
|------|------|
| **增量更新** | 合并新特征，而非全量覆盖历史数据 |
| **置信度机制** | 特征出现越多置信度越高（★评级） |
| **特征分类** | 基本信息 / 偏好习惯 / 技术背景 分开存储 |
| **OpenClaw 集成** | 深度读取 MEMORY.md + 每日记忆 |
| **去重合并** | 自动识别并合并重复特征 |

### 使用方法

```bash
# 增量学习（写入数据）
python3 ~/.openclaw/skills/kairos/kairos-learner.py --user jinghao

# 测试模式（仅打印，不写入）
python3 ~/.openclaw/skills/kairos/kairos-learner.py --user jinghao --dry-run
```

### 输出示例

```
=== Kairos 用户学习 v2 ===
时间: 2026-04-19 03:25
✅ Kairos 连接正常

📥 加载现有画像: 27个特征
📖 读取 OpenClaw 记忆: 4210字符
🤖 生成画像分析...
🔄 合并新特征...

✅ 用户画像已更新
   特征总数: 31
   - basic: 2个
   - preference: 27个
   - tech: 2个
```

## 服务管理

```bash
# 启动
cd ~/.openclaw/kairos && docker compose up -d

# 停止
cd ~/.openclaw/kairos && docker compose down

# 重启
cd ~/.openclaw/kairos && docker compose restart

# 查看日志
docker logs kairos-api --tail 50

# 查看状态
docker ps --format "table {{.Names}}\t{{.Status}}"
```

## 常见问题

**Q: chat 返回 500 错误？**
A: 检查模型是否可用。查看日志：`docker logs kairos-api --tail 30`。通常是 API Key 或模型名称配置错误。

**Q: 特征出现噪音？**
A: 当前版本会读取 MEMORY.md 的结构化内容，部分系统标签可能被识别为特征。后续版本会优化过滤规则。

## v3 新增功能 (2026-04-21)

### 竞彩分析系统

| 功能 | 说明 |
|------|------|
| 模式识别 | 连胜/连负、高赔偏好、主客场偏差 |
| 历史学习 | 从 betting-results.md 统计联赛、赔率区、胜率 |
| 团队经验 | 读取 hindsight-memory 共享层 |
| 直接推理 | `--infer` 调用 glm-5.0，120s超时 |
| 追问链 | `--follow-up` 启用追问链，session迭代持久化 |

### 推理反馈机制

```python
# 三态反馈
- adopted   # 直接采纳
- adjusted  # 调整后采纳
- rejected  # 拒绝采纳

# 示例用法
kairos infer "英超 曼城 vs 利物浦" --follow-up --session-id abc123
```

### Embedding 缓存优化

- TTL: 24 小时自动过期
- 并发控制: 3 个请求/秒
- 维度自检: 自动校验 embedding 维度
- 重试: 429 响应自动重试

## 更新日志

### v3 (2026-04-21)
- 新增投注模式识别（连胜/连负, 高赔偏好, 主客场偏差）
- 推理支持追问链（--follow-up）
- 历史学习（--learn-from-history）
- 共享层 hindsight-memory 集成
(24h TTL, 3并发, 429重试)
- 路径修复：使用 os.path.expanduser 替代硬编码路径

### v2 (2026-04-19)
- 增量更新替代全量覆盖
- 置信度 + 特征分类机制
- 深度集成 OpenClaw MEMORY.md
- CLI 支持 `--append` 追加模式
- 模型从 glm-5 切换为 Qwen/Qwen2.5-7B-Instruct
