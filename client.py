"""
Kairos 客户端 - 用户建模工具

封装 Kairos API，提供简洁的 Python 接口。
支持 SiliconFlow embedding 缓存和请求限流保护。
"""

import os
import json
import time
import hashlib
import threading
from pathlib import Path
from typing import Optional, Dict, Any, List
from dataclasses import dataclass

import httpx


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
    """Kairos API 客户端 - 支持 embedding 缓存和请求限流"""

    # ==================== Embedding 缓存配置 ====================
    EMBEDDING_TTL = 24 * 3600  # 24小时缓存
    EMBEDDING_CACHE_PATH = Path("/tmp/kairos_embedding_cache.json")

    # ==================== 限流配置 ====================
    MAX_CONCURRENT_REQUESTS = 3  # 最大并发
    MIN_REQUEST_INTERVAL = 0.5  # 最小请求间隔（秒）
    MAX_RETRIES = 3  # 429 重试次数

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: float = 30.0,
        embedding_api_key: Optional[str] = None,
        embedding_api_url: Optional[str] = None
    ):
        self.base_url = base_url or os.getenv("KAIROS_API_URL", "http://localhost:8000")
        self.timeout = timeout
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout)

        # Embedding API 配置（SiliconFlow）
        self._embedding_api_key = embedding_api_key or os.getenv("SILICONFLOW_API_KEY", "")
        self._embedding_api_url = embedding_api_url or "https://api.siliconflow.cn/v1/embeddings"

        # Embedding 缓存
        self._embedding_cache = self._load_embedding_cache()

        # 限流机制
        self._request_semaphore = threading.Semaphore(self.MAX_CONCURRENT_REQUESTS)
        self._last_request_time = 0.0
        self._request_lock = threading.Lock()

    # ==================== Embedding 缓存管理 ====================

    def _load_embedding_cache(self) -> Dict[str, Any]:
        """加载 embedding 缓存"""
        if self.EMBEDDING_CACHE_PATH.exists():
            try:
                with open(self.EMBEDDING_CACHE_PATH, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                return {}
        return {}

    def _save_embedding_cache(self):
        """保存 embedding 缓存"""
        try:
            with open(self.EMBEDDING_CACHE_PATH, 'w', encoding='utf-8') as f:
                json.dump(self._embedding_cache, f, ensure_ascii=False)
        except IOError as e:
            print(f"⚠️ 缓存保存失败: {e}")

    def _get_embedding_key(self, text: str) -> str:
        """生成缓存 key（SHA256 hash）"""
        return hashlib.sha256(text.encode('utf-8')).hexdigest()

    def get_embedding_cached(self, text: str, force_refresh: bool = False) -> List[float]:
        """
        获取 embedding（带缓存）

        Args:
            text: 要生成 embedding 的文本
            force_refresh: 强制刷新缓存

        Returns:
            embedding 向量（float list）
        """
        key = self._get_embedding_key(text)
        now = time.time()

        # 缓存命中检查
        if not force_refresh and key in self._embedding_cache:
            entry = self._embedding_cache[key]
            if now - entry.get('ts', 0) < self.EMBEDDING_TTL:
                elapsed = int(now - entry['ts'])
                dim = entry.get('dim', len(entry['embedding']))
                print(f"  📦 embedding 缓存命中 ({dim}维, {elapsed}s前)")
                return entry['embedding']

        # 请求新 embedding（带限流和重试）
        embedding = self._fetch_embedding_with_retry(text)

        # 写入缓存
        self._embedding_cache[key] = {
            'embedding': embedding,
            'dim': len(embedding),
            'ts': now,
            'text_len': len(text),
        }
        self._save_embedding_cache()
        print(f"  🆕 embedding 已缓存 ({len(embedding)}维)")
        return embedding

    def _fetch_embedding_with_retry(self, text: str) -> List[float]:
        """
        带重试的 embedding 请求

        处理 429 限速，指数退避重试
        """
        for attempt in range(self.MAX_RETRIES):
            try:
                embedding = self._fetch_embedding_protected(text)
                return embedding
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    wait = (2 ** attempt) * 1.0  # 1s, 2s, 4s 指数退避
                    print(f"  ⚠️ API 限速，等待 {wait}s 重试 ({attempt+1}/{self.MAX_RETRIES})")
                    time.sleep(wait)
                    continue
                raise
        raise RuntimeError(f"Embedding 请求失败，{self.MAX_RETRIES} 次重试后仍 429")

    def _fetch_embedding_protected(self, text: str) -> List[float]:
        """带限流保护的 embedding 请求"""
        with self._request_semaphore:
            self._rate_limit_wait()
            return self._fetch_embedding(text)

    def _fetch_embedding(self, text: str) -> List[float]:
        """请求 SiliconFlow embedding API"""
        if not self._embedding_api_key:
            # 没有配置 API key，返回空向量
            print("  ⚠️ 未配置 SILICONFLOW_API_KEY，返回空 embedding")
            return [0.0] * 1024

        headers = {
            "Authorization": f"Bearer {self._embedding_api_key}",
            "Content-Type": "application/json",
        }

        body = {
            "model": "BAAI/bge-large-zh-v1.5",  # SiliconFlow embedding model
            "input": text,
            "encoding_format": "float",
        }

        response = httpx.post(
            self._embedding_api_url,
            headers=headers,
            json=body,
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()

        # SiliconFlow 返回格式: {"data": [{"embedding": [...], "index": 0}]}
        embeddings = data.get("data", [])
        if embeddings and len(embeddings) > 0:
            return embeddings[0].get("embedding", [])
        return []

    # ==================== 请求限流保护 ====================

    def _rate_limit_wait(self):
        """限流等待 - 确保请求间隔"""
        with self._request_lock:
            now = time.time()
            elapsed = now - self._last_request_time
            if elapsed < self.MIN_REQUEST_INTERVAL:
                wait = self.MIN_REQUEST_INTERVAL - elapsed
                time.sleep(wait)
            self._last_request_time = time.time()

    def _protected_request(self, method: str, url: str, **kwargs) -> httpx.Response:
        """
        带限流和重试保护的通用请求

        Args:
            method: HTTP 方法
            url: URL（相对于 base_url）
            **kwargs: httpx 请求参数

        Returns:
            httpx.Response
        """
        for attempt in range(self.MAX_RETRIES):
            with self._request_semaphore:
                self._rate_limit_wait()
                try:
                    response = self._client.request(method, url, **kwargs)
                    return response
                except httpx.HTTPStatusError as e:
                    if e.response.status_code == 429:
                        wait = (2 ** attempt) * 1.0
                        print(f"  ⚠️ API 限速，等待 {wait}s 重试 ({attempt+1}/{self.MAX_RETRIES})")
                        time.sleep(wait)
                        continue
                    raise
        raise RuntimeError(f"请求失败，{self.MAX_RETRIES} 次重试后仍 429")

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
        """更新用户知识表示（带备份+回滚）"""
        import time
        # 1. 写入前校验
        if content and len(content.strip()) < 10:
            raise ValueError(f"representation 太短: {len(content)} 字符")
        # 2. 备份旧内容
        old_ctx = self.get_context(workspace_id, peer_id)
        old_rep = old_ctx.get("representation", "") if old_ctx else ""
        if old_rep:
            backup_path = f"/tmp/kairos_rep_backup_{workspace_id}_{peer_id}_{int(time.time())}.txt"
            with open(backup_path, 'w') as f:
                f.write(old_rep)
            print(f"  📦 备份旧 representation → {backup_path}")
        # 3. 写入
        body = {"content": content}
        if representation_type:
            body["type"] = representation_type
        response = self._client.post(
            f"/v3/workspaces/{workspace_id}/peers/{peer_id}/representation",
            json=body
        )
        response.raise_for_status()
        # 4. 写入后验证
        after = self.get_context(workspace_id, peer_id)
        after_rep = after.get("representation", "") if after else ""
        if after_rep != content:
            if old_rep:
                body["content"] = old_rep
                self._client.post(
                    f"/v3/workspaces/{workspace_id}/peers/{peer_id}/representation",
                    json=body
                )
            raise RuntimeError("写入验证失败，已回滚！")
        print(f"  ✅ representation 更新成功 ({len(content)} 字符)")
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

    def _check_embedding_dimensions(self, fix: bool = False):
        """检查 contexts.embedding 列维度，发现错误则修复"""
        import sqlite3
        import re
        db_path = os.path.expanduser("~/.kairos/kairos.db")
        if not os.path.exists(db_path):
            print("  (无本地 Kairos DB，跳过维度检查)")
            return
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(contexts)")
        cols = {r[1]: r[2] for r in cur.fetchall()}
        if 'embedding' not in cols:
            conn.close()
            return
        col_type = cols['embedding']
        match = re.search(r'vector\((\d+)\)', col_type)
        if match and int(match.group(1)) != 1024:
            print(f"  ⚠️ embedding 维度错误: {match.group(1)}，应为 1024")
            if fix:
                cur.execute("ALTER TABLE contexts ALTER COLUMN embedding TYPE vector(1024)")
                conn.commit()
                print("  ✅ 已修复为 vector(1024)")
        conn.close()

    def health_check(self, fix_embedding_dim: bool = False) -> bool:
        """检查服务健康状态"""
        self._check_embedding_dimensions(fix=fix_embedding_dim)
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
