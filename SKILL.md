# Kairos 用户建模工具

## 概述

封装 Kairos API，为 OpenClaw 提供用户建模能力。Kairos 是一个强大的用户记忆和建模系统，支持双端建模（用户 Peer + AI Peer）、方言推理和结论推导。

## 核心概念

| 概念 | 说明 |
|------|------|
| **Workspace** | 工作区，隔离不同的应用/场景 |
| **Peer** | 实体建模，可以是用户或 AI |
| **Session** | 会话，包含一系列消息 |
| **Message** | 消息，用户或 AI 的对话内容 |
| **Conclusion** | 推导结论，从对话中提取的洞察 |
| **Representation** | 知识表示，Peer 的长期记忆 |

## 端点

### 工作区管理

```
POST   /v3/workspaces                    # 创建工作区
POST   /v3/workspaces/list               # 列出工作区
PUT    /v3/workspaces/{workspace_id}     # 更新工作区
DELETE /v3/workspaces/{workspace_id}     # 删除工作区
```

### Peer 管理

```
POST   /v3/workspaces/{workspace_id}/peers/list           # 列出 Peers
POST   /v3/workspaces/{workspace_id}/peers                # 创建 Peer
PUT    /v3/workspaces/{workspace_id}/peers/{peer_id}      # 更新 Peer
GET    /v3/workspaces/{workspace_id}/peers/{peer_id}/card # 获取 Peer 卡片
```

### 会话管理

```
POST   /v3/workspaces/{workspace_id}/peers/{peer_id}/sessions      # 创建会话
POST   /v3/workspaces/{workspace_id}/sessions/list                 # 列出会话
```

### 消息处理

```
POST   /v3/workspaces/{workspace_id}/peers/{peer_id}/chat          # 发送消息并获取回复
```

### 用户建模

```
GET    /v3/workspaces/{workspace_id}/peers/{peer_id}/context       # 获取用户上下文
POST   /v3/workspaces/{workspace_id}/peers/{peer_id}/representation # 更新知识表示
POST   /v3/workspaces/{workspace_id}/peers/{peer_id}/search        # 搜索用户信息
```

## 配置

环境变量：
- `KAIROS_API_URL`: Kairos API 地址（默认: http://localhost:8000）
- `KAIROS_WORKSPACE`: 默认工作区 ID（默认: openclaw）

## 使用示例

### 初始化

```python
from client import KairosClient

client = KairosClient(base_url="http://localhost:8000")
workspace = client.get_or_create_workspace("openclaw")
```

### 用户建模

```python
# 创建用户 Peer
user_peer = client.create_peer(workspace.id, "user-123")

# 发送消息
response = client.chat(
    workspace.id,
    user_peer.id,
    "我喜欢简洁的回复风格",
    session_id="session-1"
)

# 获取用户上下文
context = client.get_context(workspace.id, user_peer.id)
```

## 注意事项

1. **数据隔离**: 不同工作区的数据完全隔离
2. **Peer ID**: 建议使用稳定的标识符（如用户 ID）
3. **会话管理**: 每个会话应该是独立的对话线程
4. **异步处理**: 某些操作（如 Deriver 推理）是异步的

## 新增功能 (v3)

### 竞彩分析增强

**高级投注模式识别**
- 连胜/连负序列识别
- 高赔偏好检测
- 主客场偏差分析
- 联赛胜率差异计算

**从投注历史学习**
- 自动读取 `betting-results.md`
- 统计联赛偏好
- 分析赔率区间分布
- 计算胜率趋势

### 推理系统优化

**三态反馈机制**
- `session_id` 追踪
- 三态反馈：adopted / adjusted / rejected
- 支持推理结果修正

**追问链支持**
- `--infer --follow-up` 启动追问链
- Session 持久化
- 上下文自动传递

**直接 NewAPI 调用**
- 模型：`glm-5.0`
- 超时：120秒
- 绕过中间层，直接推理

### 记忆系统增强

**历史学习**
- `--learn-from-history` 自动学习
- 读取最近7天 memory 文件
- 跨时间窗口特征聚合

**团队经验共享**
- 推理前自动读取 hindsight-memory 共享层
- 融入团队经验
- 避免重复犯错

### 技术优化

**可配置 Embedding 模型**
- 环境变量：`SILICONFLOW_EMBEDDING_MODEL`
- 支持切换不同模型

**Embedding 缓存**
- TTL：24小时
- 并发控制：3个请求
- 429错误自动重试
- 维度自校验

**路径修复**
- 硬编码路径 → `os.path.expanduser('~/.openclaw/...')`
- 跨环境兼容性增强

## 参考文档

- Kairos GitHub: https://github.com/plastic-labs/honcho
- Kairos 文档: https://docs.honcho.dev
