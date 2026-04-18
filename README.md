# Kairos OpenClaw 集成状态

## ✅ 已完成

### 1. 本地部署
- Docker 服务正常运行
- API: http://localhost:8000
- 健康检查通过

### 2. LLM 配置
- 提供商: dayoukewei
- 模型: glm-5
- Base URL: https://ai.dayoukewei.net/v1

### 3. 可用功能

| 功能 | 状态 | 说明 |
|------|------|------|
| Chat 对话 | ✅ 正常 | 核心功能 |
| 记录用户信息 | ✅ 正常 | update_representation |
| 获取上下文 | ✅ 正常 | get_context |
| 自动学习（定时任务） | ✅ 正常 | 每小时运行 |
| 搜索 | ❌ Bug | Kairos 内部 token 计算问题 |

### 4. 文件位置

| 文件 | 说明 |
|------|------|
| `~/.openclaw/kairos/docker-compose.yml` | Docker 配置 |
| `~/.openclaw/kairos/.env` | 环境变量 |
| `~/.openclaw/skills/honcho/client.py` | Python 客户端 |
| `~/.openclaw/skills/honcho/kairos-cli.py` | CLI 工具 |
| `~/.openclaw/skills/honcho/kairos-learner.py` | 学习定时任务脚本 |

## 📝 使用方法

### Python API

```python
from client import KairosClient

with KairosClient() as client:
    workspace = client.get_or_create_workspace("openclaw-main")
    peer = client.get_or_create_peer(workspace.id, "jinghao")
    
    # Chat 对话
    response = client.chat(workspace.id, peer.id, "你好")
    
    # 更新用户知识
    client.update_representation(
        workspace.id, peer.id,
        "用户偏好：简洁回复",
        representation_type="preference"
    )
    
    # 获取上下文
    context = client.get_context(workspace.id, peer.id)
```

### CLI

```bash
# 健康检查
python3 ~/.openclaw/skills/honcho/kairos-cli.py health

# 发送消息
python3 ~/.openclaw/skills/honcho/kairos-cli.py chat "你好" --user jinghao

# 获取上下文
python3 ~/.openclaw/skills/honcho/kairos-cli.py context --user jinghao

# 记录用户信息
python3 ~/.openclaw/skills/honcho/kairos-cli.py update "用户偏好：简洁回复" --type preference
```

## 🔧 服务管理

```bash
# 启动
cd ~/.openclaw/kairos && docker compose up -d

# 停止
cd ~/.openclaw/kairos && docker compose down

# 查看状态
docker ps --format "table {{.Names}}\t{{.Status}}"

# 健康检查
curl http://localhost:8000/health
```

## 🚀 下一步

1. 集成到 OpenClaw 主进程（注册为工具）
2. 等待 Kairos 更新修复搜索 bug

## 🤖 自动学习定时任务

已配置 OpenClaw cron 定时任务，每小时运行一次。

**任务详情：**
- 名称: kairos-learner
- 频率: 每小时（0 * * * *）
- 时区: Asia/Shanghai

**管理命令：**

```bash
# 查看任务
openclaw cron list | grep kairos-learner

# 手动运行
openclaw cron run <job-id>

# 查看状态
openclaw cron status
```

**手动测试：**

```bash
python3 ~/.openclaw/skills/honcho/kairos-learner.py --user jinghao
```
