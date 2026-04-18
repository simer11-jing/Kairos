#!/usr/bin/env python3
"""
Kairos CLI - OpenClaw 集成命令行工具

用法:
    kairos chat <message> [--user <user_id>] [--session <session_id>]
    kairos context [--user <user_id>] [--query <query>]
    kairos search <query> [--user <user_id>] [--top-k <n>]
    kairos update <content> [--user <user_id>] [--type <type>]
    kairos diff --old <text> [--new <text>]  # 对比两份 context 差异
    kairos infer [--user <user_id>]          # 基于画像推理用户下一步
    kairos health
    kairos workspace <action> [name]
"""

import sys
import os
import json
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from client import KairosClient

DEFAULT_API_URL = os.getenv("KAIROS_API_URL", "http://localhost:8000")
DEFAULT_WORKSPACE = os.getenv("KAIROS_WORKSPACE", "openclaw-main")


def get_current_user():
    """获取当前用户 ID"""
    return os.getenv("KAIROS_USER_ID", "default-user")


def cmd_health(args):
    """健康检查"""
    with KairosClient(DEFAULT_API_URL) as client:
        if client.health_check():
            print("✅ Kairos 服务正常")
            return 0
        else:
            print("❌ Kairos 服务不可用")
            return 1


def cmd_chat(args):
    """发送消息"""
    user_id = args.user or get_current_user()

    with KairosClient(DEFAULT_API_URL) as client:
        workspace = client.get_or_create_workspace(DEFAULT_WORKSPACE)
        peer = client.get_or_create_peer(workspace.id, user_id)

        response = client.chat(
            workspace.id,
            peer.id,
            args.message,
            session_id=args.session
        )

        print(json.dumps(response, indent=2, ensure_ascii=False))
    return 0


def cmd_context(args):
    """获取用户上下文"""
    user_id = args.user or get_current_user()

    with KairosClient(DEFAULT_API_URL) as client:
        workspace = client.get_or_create_workspace(DEFAULT_WORKSPACE)
        peer = client.get_or_create_peer(workspace.id, user_id)

        context = client.get_context(
            workspace.id,
            peer.id,
            query=args.query
        )

        print(json.dumps(context, indent=2, ensure_ascii=False))
    return 0


def cmd_search(args):
    """搜索用户信息"""
    user_id = args.user or get_current_user()

    with KairosClient(DEFAULT_API_URL) as client:
        workspace = client.get_or_create_workspace(DEFAULT_WORKSPACE)
        peer = client.get_or_create_peer(workspace.id, user_id)

        results = client.search_user_info(
            workspace.id,
            peer.id,
            args.query,
            top_k=args.top_k
        )

        for i, item in enumerate(results, 1):
            print(f"\n--- 结果 {i} ---")
            print(json.dumps(item, indent=2, ensure_ascii=False))
    return 0


def cmd_update(args):
    """更新用户知识表示"""
    user_id = args.user or get_current_user()

    with KairosClient(DEFAULT_API_URL) as client:
        workspace = client.get_or_create_workspace(DEFAULT_WORKSPACE)
        peer = client.get_or_create_peer(workspace.id, user_id)

        if args.append:
            context = client.get_context(workspace.id, peer.id)
            existing = context.get("representation", "")
            new_content = f"{existing}\n{args.content}" if existing else args.content
            print(f"📝 追加模式: 新增 {len(args.content)} 字符")
        else:
            new_content = args.content
            print(f"📝 全量模式: 写入 {len(args.content)} 字符")

        result = client.update_representation(
            workspace.id,
            peer.id,
            new_content,
            representation_type=args.type
        )

        print("✅ 已记录")
        if args.verbose:
            print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


def cmd_diff(args):
    """对比两份 context 的差异"""
    user_id = args.user or get_current_user()

    with KairosClient(DEFAULT_API_URL) as client:
        workspace = client.get_or_create_workspace(DEFAULT_WORKSPACE)
        peer = client.get_or_create_peer(workspace.id, user_id)

        context = client.get_context(workspace.id, peer.id)
        current = context.get("representation", "")

        print(f"📊 Context 对比工具")
        print(f"用户: {user_id}, 当前画像: {len(current)} 字符")

        if not args.old:
            print("\n⚠️ 请提供 --old 参数指定旧版内容")
            print("   用法: kairos diff --old '旧版...' --new '新版...'")
            print(f"\n当前内容预览:\n{current[:300]}...")
            return 0

        old_text = args.old
        new_text = args.new or current

        old_lines = set(old_text.strip().split('\n'))
        new_lines = set(new_text.strip().split('\n'))

        added = new_lines - old_lines
        removed = old_lines - new_lines

        print(f"\n📝 差异: +{len(added)} 行, -{len(removed)} 行")

        if added:
            print(f"\n➕ 新增 ({len(added)}):")
            for line in list(added)[:10]:
                if line.strip():
                    print(f"   + {line.strip()[:80]}")

        if removed:
            print(f"\n➖ 删除 ({len(removed)}):")
            for line in list(removed)[:10]:
                if line.strip():
                    print(f"   - {line.strip()[:80]}")

    return 0


def cmd_infer(args):
    """基于当前画像推理用户下一步行动"""
    user_id = args.user or get_current_user()

    with KairosClient(DEFAULT_API_URL) as client:
        workspace = client.get_or_create_workspace(DEFAULT_WORKSPACE)
        peer = client.get_or_create_peer(workspace.id, user_id)

        context = client.get_context(workspace.id, peer.id)
        current_rep = context.get("representation", "")

        if not current_rep:
            print("❌ 无用户画像，请先运行学习任务")
            return 1

        prompt = f"""基于以下用户画像，预测用户可能的下一个问题或需求：

{current_rep[:1500]}

请从以下角度分析并输出：
1. 用户可能会问什么问题？
2. 用户下一步可能想要什么？
3. 有什么需要主动提醒用户的？

每条一行，简洁输出。"""

        print(f"🤖 基于画像推理...")
        response = client.chat(
            workspace.id, peer.id,
            prompt,
            reasoning_level="medium"
        )

        result = response.get("content", "").strip()
        print(f"\n📌 推理结果:\n{result}")
    return 0


def cmd_workspace(args):
    """工作区管理"""
    with KairosClient(DEFAULT_API_URL) as client:
        if args.action == "list":
            workspaces = client.list_workspaces()
            print(f"工作区列表 ({len(workspaces)} 个):")
            for ws in workspaces:
                print(f"  - {ws.id} (创建于 {ws.created_at})")

        elif args.action == "create":
            name = args.name or DEFAULT_WORKSPACE
            ws = client.create_workspace(name)
            print(f"✅ 创建工作区: {ws.id}")

        elif args.action == "delete":
            if not args.name:
                print("❌ 请指定工作区名称")
                return 1
            client.delete_workspace(args.name)
            print(f"✅ 已删除工作区: {args.name}")

        else:
            print(f"未知操作: {args.action}")
            return 1
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Kairos 用户建模 CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  kairos health
  kairos chat "你好" --user alice
  kairos context --user alice
  kairos search "偏好" --user alice
  kairos update "用户喜欢简洁回复" --type preference -a
  kairos diff --old "旧版内容" --new "新版内容"
  kairos infer --user alice
  kairos workspace list
        """
    )

    subparsers = parser.add_subparsers(dest="command", help="命令")

    subparsers.add_parser("health", help="健康检查")

    chat_parser = subparsers.add_parser("chat", help="发送消息")
    chat_parser.add_argument("message", help="消息内容")
    chat_parser.add_argument("--user", help="用户 ID")
    chat_parser.add_argument("--session", help="会话 ID")

    context_parser = subparsers.add_parser("context", help="获取用户上下文")
    context_parser.add_argument("--user", help="用户 ID")
    context_parser.add_argument("--query", help="查询关键词")

    search_parser = subparsers.add_parser("search", help="搜索用户信息")
    search_parser.add_argument("query", help="搜索查询")
    search_parser.add_argument("--user", help="用户 ID")
    search_parser.add_argument("--top-k", type=int, default=5, help="返回结果数量")

    update_parser = subparsers.add_parser("update", help="更新用户知识")
    update_parser.add_argument("content", help="内容")
    update_parser.add_argument("--user", help="用户 ID")
    update_parser.add_argument("--type", help="知识类型")
    update_parser.add_argument("-a", "--append", action="store_true", help="追加模式")
    update_parser.add_argument("-v", "--verbose", action="store_true", help="详细信息")

    diff_parser = subparsers.add_parser("diff", help="对比两份 context 差异")
    diff_parser.add_argument("--old", required=True, help="旧版内容")
    diff_parser.add_argument("--new", help="新版内容（默认当前画像）")
    diff_parser.add_argument("--user", help="用户 ID")

    infer_parser = subparsers.add_parser("infer", help="基于画像推理用户下一步")
    infer_parser.add_argument("--user", help="用户 ID")

    workspace_parser = subparsers.add_parser("workspace", help="工作区管理")
    workspace_parser.add_argument("action", choices=["list", "create", "delete"], help="操作")
    workspace_parser.add_argument("name", nargs="?", help="工作区名称")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    commands = {
        "health": cmd_health,
        "chat": cmd_chat,
        "context": cmd_context,
        "search": cmd_search,
        "update": cmd_update,
        "diff": cmd_diff,
        "infer": cmd_infer,
        "workspace": cmd_workspace,
    }

    return commands[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
