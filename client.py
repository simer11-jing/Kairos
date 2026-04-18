"""
Kairos 客户端 - 用户建模工具

封装 Kairos API，提供简洁的 Python 接口。
"""

import os
import httpx
from typing import Optional, Dict, Any, List
from dataclasses import dataclass


@dataclass
class Workspace:
    id: str
    created_at: str
    metadata: Dict[str, Any]
    configuration: Dict[str, Any]


@dataclass
class Peer:
    id: str
    workspace_id: str
    created_at: str
    metadata: Dict[str, Any]
    configuration: Dict[str, Any]


@dataclass
class Session:
    id: str
    peer_id: str
    workspace_id: str
    created_at: str
    metadata: Dict[str, Any]


class KairosClient:
    """Kairos API 客户端"""

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: float = 30.0
    ):
        self.base_url = base_url or os.getenv("KAIROS_API_URL", "http://localhost:8000")
        self.timeout = timeout
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self._client.close()

    # ==================== 工作区管理 ====================

    def create_workspace(
        self,
        name: str,
        metadata: Optional[Dict[str, Any]] = None,
        configuration: Optional[Dict[str, Any]] = None
    ) -> Workspace:
        """创建工作区"""
        response = self._client.post(
            "/v3/workspaces",
            json={
                "name": name,
                "metadata": metadata or {},
                "configuration": configuration or {}
            }
        )
        response.raise_for_status()
        data = response.json()
        return Workspace(
            id=data["id"],
            created_at=data["created_at"],
            metadata=data.get("metadata", {}),
            configuration=data.get("configuration", {})
        )

    def get_or_create_workspace(self, name: str) -> Workspace:
        """获取或创建工作区"""
        # 先尝试列出
        workspaces = self.list_workspaces()
        for ws in workspaces:
            if ws.id == name:
                return ws
        # 不存在则创建
        return self.create_workspace(name)

    def list_workspaces(self, page: int = 1, size: int = 50) -> List[Workspace]:
        """列出工作区"""
        response = self._client.post(
            "/v3/workspaces/list",
            json={"page": page, "size": size}
        )
        response.raise_for_status()
        data = response.json()
        return [
            Workspace(
                id=item["id"],
                created_at=item["created_at"],
                metadata=item.get("metadata", {}),
                configuration=item.get("configuration", {})
            )
            for item in data.get("items", [])
        ]

    def delete_workspace(self, workspace_id: str) -> bool:
        """删除工作区"""
        response = self._client.delete(f"/v3/workspaces/{workspace_id}")
        response.raise_for_status()
        return True

    # ==================== Peer 管理 ====================

    def create_peer(
        self,
        workspace_id: str,
        peer_id: str,
        metadata: Optional[Dict[str, Any]] = None,
        configuration: Optional[Dict[str, Any]] = None
    ) -> Peer:
        """创建 Peer"""
        response = self._client.post(
            f"/v3/workspaces/{workspace_id}/peers",
            json={
                "name": peer_id,
                "metadata": metadata or {},
                "configuration": configuration or {}
            }
        )
        response.raise_for_status()
        data = response.json()
        return Peer(
            id=data["id"],
            workspace_id=data["workspace_id"],
            created_at=data["created_at"],
            metadata=data.get("metadata", {}),
            configuration=data.get("configuration", {})
        )

    def get_or_create_peer(self, workspace_id: str, peer_id: str) -> Peer:
        """获取或创建 Peer"""
        peers = self.list_peers(workspace_id)
        for peer in peers:
            if peer.id == peer_id:
                return peer
        return self.create_peer(workspace_id, peer_id)

    def list_peers(self, workspace_id: str, page: int = 1, size: int = 50) -> List[Peer]:
        """列出 Peers"""
        response = self._client.post(
            f"/v3/workspaces/{workspace_id}/peers/list",
            json={"page": page, "size": size}
        )
        response.raise_for_status()
        data = response.json()
        return [
            Peer(
                id=item["id"],
                workspace_id=item["workspace_id"],
                created_at=item["created_at"],
                metadata=item.get("metadata", {}),
                configuration=item.get("configuration", {})
            )
            for item in data.get("items", [])
        ]

    def get_peer_card(self, workspace_id: str, peer_id: str) -> Dict[str, Any]:
        """获取 Peer 卡片（用户画像）"""
        response = self._client.get(
            f"/v3/workspaces/{workspace_id}/peers/{peer_id}/card"
        )
        response.raise_for_status()
        return response.json()

    # ==================== 会话管理 ====================

    def create_session(
        self,
        workspace_id: str,
        peer_id: str,
        session_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Session:
        """创建会话"""
        body = {"metadata": metadata or {}}
        if session_id:
            body["id"] = session_id

        response = self._client.post(
            f"/v3/workspaces/{workspace_id}/peers/{peer_id}/sessions",
            json=body
        )
        response.raise_for_status()
        data = response.json()
        return Session(
            id=data["id"],
            peer_id=data["peer_id"],
            workspace_id=data["workspace_id"],
            created_at=data["created_at"],
            metadata=data.get("metadata", {})
        )

    def list_sessions(
        self,
        workspace_id: str,
        peer_id: Optional[str] = None,
        page: int = 1,
        size: int = 50
    ) -> List[Session]:
        """列出会话"""
        body = {"page": page, "size": size}
        if peer_id:
            body["peer_id"] = peer_id

        response = self._client.post(
            f"/v3/workspaces/{workspace_id}/sessions/list",
            json=body
        )
        response.raise_for_status()
        data = response.json()
        return [
            Session(
                id=item["id"],
                peer_id=item["peer_id"],
                workspace_id=item["workspace_id"],
                created_at=item["created_at"],
                metadata=item.get("metadata", {})
            )
            for item in data.get("items", [])
        ]

    # ==================== 消息处理 ====================

    def chat(
        self,
        workspace_id: str,
        peer_id: str,
        query: str,
        session_id: Optional[str] = None,
        target: Optional[str] = None,
        reasoning_level: str = "low",
        stream: bool = False
    ) -> Dict[str, Any]:
        """
        发送查询并获取 AI 回复

        Args:
            workspace_id: 工作区 ID
            peer_id: 用户 Peer ID
            query: 查询/消息内容
            session_id: 会话 ID（可选）
            target: 目标 Peer ID（可选）
            reasoning_level: 推理级别 (minimal/low/medium/high/max)
            stream: 是否流式返回

        Returns:
            包含回复和元数据的字典
        """
        body = {
            "query": query,
            "reasoning_level": reasoning_level,
            "stream": stream
        }
        if session_id:
            body["session_id"] = session_id
        if target:
            body["target"] = target

        response = self._client.post(
            f"/v3/workspaces/{workspace_id}/peers/{peer_id}/chat",
            json=body
        )
        response.raise_for_status()
        return response.json()

    # ==================== 用户建模 ====================

    def get_context(
        self,
        workspace_id: str,
        peer_id: str,
        query: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        获取用户上下文

        Returns:
            包含用户相关信息、历史消息、结论等
        """
        params = {}
        if query:
            params["query"] = query

        response = self._client.get(
            f"/v3/workspaces/{workspace_id}/peers/{peer_id}/context",
            params=params
        )
        response.raise_for_status()
        return response.json()

    def update_representation(
        self,
        workspace_id: str,
        peer_id: str,
        content: str,
        representation_type: Optional[str] = None
    ) -> Dict[str, Any]:
        """更新用户知识表示"""
        body = {"content": content}
        if representation_type:
            body["type"] = representation_type

        response = self._client.post(
            f"/v3/workspaces/{workspace_id}/peers/{peer_id}/representation",
            json=body
        )
        response.raise_for_status()
        return response.json()

    def search_user_info(
        self,
        workspace_id: str,
        peer_id: str,
        query: str,
        limit: int = 5
    ) -> List[Dict[str, Any]]:
        """搜索用户相关信息"""
        response = self._client.post(
            f"/v3/workspaces/{workspace_id}/peers/{peer_id}/search",
            json={"query": query, "limit": limit}
        )
        response.raise_for_status()
        data = response.json()
        return data.get("items", [])

    # ==================== 便捷方法 ====================

    def health_check(self) -> bool:
        """检查服务健康状态"""
        try:
            response = self._client.get("/health")
            return response.status_code == 200
        except Exception:
            return False

    def close(self):
        """关闭客户端"""
        self._client.close()


# 便捷函数
def create_client(base_url: Optional[str] = None) -> KairosClient:
    """创建 Kairos 客户端"""
    return KairosClient(base_url=base_url)


if __name__ == "__main__":
    # 测试代码
    client = KairosClient()
    print(f"Health check: {client.health_check()}")

    # 创建工作区
    workspace = client.get_or_create_workspace("test-workspace")
    print(f"Workspace: {workspace.id}")

    # 创建用户
    user = client.get_or_create_peer(workspace.id, "test-user")
    print(f"Peer: {user.id}")

    # 发送消息
    response = client.chat(workspace.id, user.id, "你好，我喜欢简洁的回复")
    print(f"Response: {response}")

    client.close()
