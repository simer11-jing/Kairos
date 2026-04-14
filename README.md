# Kairos 本地部署

## 项目简介

**Kairos** 是基于 Honcho (plastic-labs/honcho) 的用户建模与主动推理系统，具备以下能力：

- 👤 **用户画像** - 双端建模（User Peer + AI Peer）
- 🗣️ **方言推理** - 理解用户表达习惯
- 🔮 **主动推理** - 后台思考，主动服务
- 🧠 **记忆反思** - 周期性回顾与学习

## 状态

✅ **部署成功** (2026-04-12)

## 访问地址

- **API**: http://localhost:8000
- **文档**: http://localhost:8000/docs
- **健康检查**: http://localhost:8000/health

## LLM 配置

使用 newapi OpenAI 兼容接口：
- 模型: `glm-5`
- Base URL: `http://192.168.50.2:3000/v1`

## 服务状态

| 服务 | 端口 | 状态 |
|------|------|------|
| API | 8000 | ✅ healthy |
| Deriver | 8000 | ✅ healthy |
| Redis | 6379 | ✅ healthy |
| PostgreSQL | 5432 | ✅ healthy |

## 使用方法

```bash
# 启动
cd ~/.openclaw/kairos
docker compose up -d

# 停止
docker compose down

# 查看日志
docker logs kairos-api

# 健康检查
curl http://localhost:8000/health
```

## API 示例

### 创建工作区
```bash
curl -X POST http://localhost:8000/v3/workspaces \
  -H "Content-Type: application/json" \
  -d '{"name": "my-workspace"}'
```

### 创建 Peer（用户）
```bash
curl -X POST http://localhost:8000/v3/workspaces/my-workspace/peers \
  -H "Content-Type: application/json" \
  -d '{"name": "user-id"}'
```

### 发送消息
```bash
curl -X POST http://localhost:8000/v3/workspaces/my-workspace/peers/user-id/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "你好"}'
```

## 与 OpenClaw 集成

Kairos 可作为 OpenClaw 的用户建模后端，提供：
- 用户偏好学习
- 对话上下文理解
- 主动建议生成

## 注意事项

1. **Deriver 已启用** - 后台推理服务运行中
2. **内存占用** - API 约 160MB，数据库约 24MB
3. **启动时间** - 约 30-60 秒完成初始化
