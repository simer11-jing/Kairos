#!/usr/bin/env python3
"""
Kairos 用户学习定时任务 v3

v2 改进：
1. 增量更新 - 合并新特征而非全量覆盖
2. OpenClaw 深度集成 - 直接读取 MEMORY.md 和每日记忆
3. 置信度机制 - 频繁出现的特征置信度高
4. 特征分类 - 基本信息/偏好/技术背景 分开存储

v3 改进（本次）：
5. Context 质量提升 - 定期压缩、分类存储、遗忘机制
6. 学习反馈循环 - 置信度对比、矛盾特征标记
7. CLI 增强 - diff / infer 命令

v3.1 改进（追问功能）：
8. 推理追问模式 - --infer --follow-up 支持推理链追踪
9. 会话持久化 - --session-id 支持多轮对话

用法：
    python3 kairos-learner.py --user jinghao
    python3 kairos-learner.py --user jinghao --dry-run
    python3 kairos-learner.py --user jinghao --compact    # 压缩旧 context
    python3 kairos-learner.py --user jinghao --feedback   # 打印学习反馈
    python3 kairos-learner.py --user jinghao --fix-dim    # 检查并修复 embedding 维度
    python3 kairos-learner.py --user jinghao --infer "今天适合投什么比赛？"
    python3 kairos-learner.py --user jinghao --infer "英超有什么？" --follow-up "这些比赛里哪个最稳？" --session-id <session-id>
"""

import os
import sys
import json
import argparse
import re
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from client import KairosClient

DEFAULT_WORKSPACE = os.getenv("KAIROS_WORKSPACE", "openclaw-main")
DEFAULT_API_URL = os.getenv("KAIROS_API_URL", "http://localhost:8000")
OPENCLAW_AGENT_DIR = "/home/jinghao/.openclaw/agents/main"
MEMORY_FILE = Path(OPENCLAW_AGENT_DIR) / "MEMORY.md"
DAILY_MEMORY_DIR = Path(OPENCLAW_AGENT_DIR) / "memory"

# ====== 推理会话存储 ======
INFER_SESSIONS_DIR = Path("/tmp/kairos-infer-sessions")
INFER_SESSIONS_DIR.mkdir(exist_ok=True)


def save_infer_session(session_id: str, query: str, response: str, profile_summary: str):
    """保存推理会话到文件"""
    session_file = INFER_SESSIONS_DIR / f"{session_id}.json"
    session_data = {
        "session_id": session_id,
        "profile_summary": profile_summary,
        "history": []
    }
    if session_file.exists():
        with open(session_file, 'r') as f:
            session_data = json.load(f)
    
    session_data["history"].append({
        "query": query,
        "response": response,
        "timestamp": datetime.now().isoformat()
    })
    
    with open(session_file, 'w') as f:
        json.dump(session_data, f, ensure_ascii=False, indent=2)


def load_infer_session(session_id: str) -> dict:
    """加载推理会话"""
    session_file = INFER_SESSIONS_DIR / f"{session_id}.json"
    if session_file.exists():
        with open(session_file, 'r') as f:
            return json.load(f)
    return {}


# ==================== 特征解析与合并 ====================

class FeatureManager:
    """特征管理器 - 解析、合并、去重特征，支持置信度追踪和矛盾检测"""
    
    FEATURE_PATTERNS = {
        'basic': ['姓名', '名字', '年龄', '职业', '所在地', '时区', '称呼'],
        'preference': ['喜欢', '偏好', '习惯', '不喜欢', '倾向', '希望', '想要', '讨厌'],
        'tech': ['编程', '开发', '技术', '语言', '框架', '工具', '模型', 'API', '部署', '版本'],
    }
    
    # 矛盾特征对（同类特征互相矛盾）
    CONTRADICTING_PAIRS = [
        ('喜欢简洁', '喜欢冗长'),
        ('喜欢打包exe', '不打包exe'),
        ('偏好自动化', '偏好手动'),
        ('微信为主', '邮件为主'),
        ('喜欢尝试新工具', '不喜欢换工具'),
    ]
    
    def __init__(self):
        self.features = {
            'basic': {},
            'preference': {},
            'tech': {},
        }
        self.contradictions = []  # 记录矛盾特征
    
    def parse_raw_text(self, text: str):
        """从文本中提取特征行"""
        lines = []
        for line in text.strip().split('\n'):
            line = line.strip()
            if not line or line.startswith('#') or line.startswith('//'):
                continue
            line = re.sub(r'^[\-\*\·]+\s*', '', line)
            if line:
                lines.append(line)
        return lines
    
    def classify_feature(self, line: str) -> str:
        """判断特征属于哪个类别"""
        for category, patterns in self.FEATURE_PATTERNS.items():
            for pattern in patterns:
                if pattern in line:
                    return category
        return 'preference'
    
    def _is_contradiction(self, key1: str, key2: str) -> bool:
        """检测两个特征是否矛盾"""
        k1, k2 = key1.strip(), key2.strip()
        for a, b in self.CONTRADICTING_PAIRS:
            if (a in k1 and b in k2) or (b in k1 and a in k2):
                return True
        return False
    
    def _is_value_contradiction(self, val1: str, val2: str) -> bool:
        """检测两个值是否矛盾（如 "是" vs "否"）"""
        pos = ['是', '喜欢', '有', '会', '能', '支持']
        neg = ['不', '非', '无', '否', '拒绝', '讨厌']
        
        v1_pos = any(p in val1 for p in pos) and not any(p in val1 for p in neg)
        v1_neg = any(p in val1 for p in neg)
        v2_pos = any(p in val2 for p in pos) and not any(p in val2 for p in neg)
        v2_neg = any(p in val2 for p in neg)
        
        return (v1_pos and v2_neg) or (v1_neg and v2_pos)
    
    def update_from_kairos(self, representation: str):
        """从 Kairos 现有画像解析并加载"""
        if not representation:
            return
        
        lines = self.parse_raw_text(representation)
        for line in lines:
            clean_line = re.sub(r'\[\d{4}-\d{2}-\d{2}[^\]]*\]', '', line).strip()
            if not clean_line:
                continue
            
            category = self.classify_feature(clean_line)
            
            if '：' in clean_line:
                key, value = clean_line.split('：', 1)
            elif ':' in clean_line:
                key, value = clean_line.split(':', 1)
            else:
                key = clean_line[:10]
                value = clean_line
            
            key = key.strip()
            value = value.strip()
            
            if key and value:
                if key not in self.features[category]:
                    self.features[category][key] = {
                        'value': value,
                        'confidence': 0.3,
                        'count': 0,
                        'first_seen': datetime.now().isoformat(),
                    }
                self.features[category][key]['count'] += 1
                self.features[category][key]['last_seen'] = datetime.now().isoformat()
                self.features[category][key]['confidence'] = min(
                    1.0,
                    self.features[category][key]['confidence'] + 0.1
                )
    
    def update_from_text(self, text: str, source: str = "analysis"):
        """从文本更新特征"""
        lines = self.parse_raw_text(text)
        timestamp = datetime.now().isoformat()
        
        for line in lines:
            category = self.classify_feature(line)
            
            if '：' in line:
                key, value = line.split('：', 1)
            elif ':' in line:
                key, value = line.split(':', 1)
            else:
                key = line[:15]
                value = line
            
            key = key.strip()
            value = value.strip()
            
            if len(key) < 2 or len(value) < 2:
                continue
            
            if key not in self.features[category]:
                self.features[category][key] = {
                    'value': value,
                    'confidence': 0.2,
                    'count': 0,
                    'first_seen': timestamp,
                }
            
            self.features[category][key]['count'] += 1
            self.features[category][key]['last_seen'] = timestamp
            self.features[category][key]['confidence'] = min(
                1.0,
                self.features[category][key]['confidence'] + 0.05
            )
    
    def merge_new_features(self, new_text: str) -> dict:
        """
        合并新的分析结果
        返回：{added: [], updated: [], contradicted: []}
        """
        result = {'added': [], 'updated': [], 'contradicted': []}
        lines = self.parse_raw_text(new_text)
        timestamp = datetime.now().isoformat()
        
        for line in lines:
            category = self.classify_feature(line)
            
            if '：' in line:
                key, value = line.split('：', 1)
            elif ':' in line:
                key, value = line.split(':', 1)
            else:
                continue
            
            key = key.strip()
            value = value.strip()
            
            if len(key) < 2 or len(value) < 2:
                continue
            
            if key in self.features[category]:
                old_value = self.features[category][key]['value']
                old_conf = self.features[category][key]['confidence']
                
                # 检测值矛盾
                if self._is_value_contradiction(old_value, value):
                    self.features[category][key]['confidence'] = max(
                        0.2,
                        old_conf - 0.2
                    )
                    self.contradictions.append({
                        'key': key,
                        'old': old_value,
                        'new': value,
                        'category': category,
                    })
                    result['contradicted'].append({
                        'key': key,
                        'old': old_value,
                        'new': value,
                    })
                
                # 检测特征矛盾
                for other_key in self.features[category]:
                    if other_key != key and self._is_contradiction(key, other_key):
                        self.contradictions.append({
                            'key': key,
                            'other_key': other_key,
                            'category': category,
                        })
                        result['contradicted'].append({
                            'key': key,
                            'other_key': other_key,
                        })
                
                if old_value != value and not self._is_value_contradiction(old_value, value):
                    self.features[category][key]['value'] = value
                    self.features[category][key]['confidence'] = max(
                        0.3,
                        old_conf - 0.1
                    )
                    result['updated'].append({'key': key, 'new_value': value})
                
                self.features[category][key]['count'] += 1
                self.features[category][key]['last_seen'] = timestamp
                self.features[category][key]['confidence'] = min(
                    1.0,
                    self.features[category][key]['confidence'] + 0.15
                )
            else:
                self.features[category][key] = {
                    'value': value,
                    'confidence': 0.4,
                    'count': 1,
                    'first_seen': timestamp,
                    'last_seen': timestamp,
                }
                result['added'].append({'key': key, 'value': value, 'category': category})
        
        return result
    
    def apply_forgetting(self, max_age_days: int = 30, min_confidence: float = 0.15):
        """
        遗忘机制：降低长期未更新特征的置信度
        超过 max_age_days 未出现的特征，置信度逐渐降低
        """
        now = datetime.now()
        forgotten = []
        
        for category in self.features:
            to_remove = []
            for key, data in self.features[category].items():
                if data['confidence'] < min_confidence:
                    to_remove.append(key)
                    continue
                    
                last_seen = datetime.fromisoformat(data['last_seen'])
                days_ago = (now - last_seen).days
                
                if days_ago > max_age_days:
                    # 每超过一天，置信度降低 0.02
                    decay = min(data['confidence'], (days_ago - max_age_days) * 0.02)
                    data['confidence'] = max(min_confidence, data['confidence'] - decay)
                    
                    if data['confidence'] <= min_confidence:
                        to_remove.append(key)
                        forgotten.append({'key': key, 'category': category, 'last_seen': data['last_seen']})
            
            for key in to_remove:
                del self.features[category][key]
        
        return forgotten
    
    def get_high_confidence_features(self, threshold: float = 0.6) -> dict:
        """获取高置信度特征（用于推理）"""
        result = {}
        for category in self.features:
            result[category] = [
                (k, v) for k, v in self.features[category].items()
                if v['confidence'] >= threshold
            ]
        return result
    
    def generate_compressed_summary(self) -> str:
        """
        生成压缩摘要：将大量低置信度特征合并为高层描述
        """
        lines = []
        lines.append("## 用户画像压缩摘要")
        lines.append(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        
        for category in ['basic', 'preference', 'tech']:
            if not self.features[category]:
                continue
            
            title = {'basic': '📋 基本信息', 'preference': '❤️ 核心偏好', 'tech': '💻 技术特征'}[category]
            lines.append(f"\n### {title}")
            
            # 高置信度特征
            high = [(k, v) for k, v in self.features[category].items() if v['confidence'] >= 0.6]
            if high:
                lines.append("**高置信度（稳定）:**")
                for k, v in sorted(high, key=lambda x: x[1]['confidence'], reverse=True):
                    lines.append(f"- {k}：{v['value']} ({v['count']}次)")
            
            # 中置信度特征
            mid = [(k, v) for k, v in self.features[category].items() 
                   if 0.3 <= v['confidence'] < 0.6]
            if mid:
                lines.append(f"\n**中等置信度（待观察，{len(mid)}项）:**")
                for k, v in sorted(mid, key=lambda x: x[1]['confidence'], reverse=True)[:5]:
                    lines.append(f"- {k}：{v['value']}")
        
        return '\n'.join(lines)
    
    def to_string(self) -> str:
        """转换为格式化字符串"""
        lines = []
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M')
        
        lines.append(f"[{timestamp}] Kairos 用户画像 v3")
        lines.append("")
        
        for category in ['basic', 'preference', 'tech']:
            if not self.features[category]:
                continue
            
            title = {'basic': '📋 基本信息', 'preference': '❤️ 偏好习惯', 'tech': '💻 技术背景'}[category]
            lines.append(f"### {title}")
            
            sorted_features = sorted(
                self.features[category].items(),
                key=lambda x: x[1]['confidence'],
                reverse=True
            )
            
            for key, data in sorted_features:
                conf_bar = '★' * int(data['confidence'] * 5) + '☆' * (5 - int(data['confidence'] * 5))
                lines.append(f"- {key}：{data['value']} [{conf_bar}] ({data['count']}次)")
            
            lines.append("")
        
        # 矛盾特征警告
        if self.contradictions:
            lines.append("### ⚠️ 矛盾特征")
            for c in self.contradictions:
                if 'old' in c and 'new' in c:
                    lines.append(f"- {c['key']}: 「{c['old']}」 vs 「{c['new']}」")
                elif 'other_key' in c:
                    lines.append(f"- {c['key']} vs {c['other_key']} (潜在矛盾)")
        
        return '\n'.join(lines)
    
    def get_summary(self) -> str:
        """获取简短摘要"""
        parts = []
        for category in ['basic', 'preference', 'tech']:
            count = len(self.features[category])
            if count > 0:
                high = sum(1 for v in self.features[category].values() if v['confidence'] >= 0.6)
                parts.append(f"{category}: {count}个({high}高置信)")
        return ', '.join(parts) if parts else '暂无特征'


# ==================== OpenClaw 记忆读取 ====================

def read_openclaw_memory() -> str:
    """读取 OpenClaw 记忆文件，提取用户相关信息"""
    contents = []
    
    if MEMORY_FILE.exists():
        try:
            content = MEMORY_FILE.read_text(encoding='utf-8')
            lines = content.split('\n')
            for i, line in enumerate(lines):
                if any(kw in line for kw in ['用户', '偏好', '姓名', '职业', '习惯', '关于']):
                    start = max(0, i - 1)
                    end = min(len(lines), i + 3)
                    context = '\n'.join(lines[start:end])
                    contents.append(context)
        except Exception as e:
            print(f"⚠️ 读取 MEMORY.md 失败: {e}")
    
    today = datetime.now()
    for days_ago in range(2):
        target_date = (today - timedelta(days=days_ago)).strftime('%Y-%m-%d')
        daily_file = DAILY_MEMORY_DIR / f"{target_date}.md"
        if daily_file.exists():
            try:
                content = daily_file.read_text(encoding='utf-8')
                lines = content.split('\n')
                for i, line in enumerate(lines):
                    if any(kw in line.lower() for kw in ['user', 'pref', '喜欢', '不喜欢', '决策', '项目']):
                        start = max(0, i - 1)
                        end = min(len(lines), i + 2)
                        contents.append('\n'.join(lines[start:end]))
            except Exception as e:
                print(f"⚠️ 读取 {daily_file.name} 失败: {e}")
    
    return '\n'.join(contents) if contents else ''


def read_hindsight_memory(limit: int = 5) -> str:
    """从 hindsight-memory 共享层读取最近的相关经验"""
    try:
        result = subprocess.run(
            ['node', '-e', '''
const {AgentContext} = require('/home/jinghao/.openclaw/skills/hindsight-memory/lib/multi-agent/index.js');
const ctx = new AgentContext('kairos');
ctx.readAllShared(['mentalModels', 'observations']).then(all => {
    const lines = [];
    for (const layer of ['mentalModels', 'observations']) {
        for (const e of (all[layer] || []).slice(0, 3)) {
            lines.push(`[${layer}] ${e.content}`);
        }
    }
    console.log(lines.length > 0 ? lines.join('\\n') : '');
});
'''],
            capture_output=True, text=True, cwd='/home/jinghao', timeout=15
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception as e:
        print(f"   ⚠️ 读取共享记忆失败: {e}")
    return ""


def learn_from_history(days: int = 7) -> str:
    """
    从 OpenClaw 会话历史提取用户特征
    读取最近几天的 daily memory 文件
    
    Args:
        days: 读取最近几天的记忆，默认7天
    
    Returns:
        格式化的历史片段
    """
    memory_dir = DAILY_MEMORY_DIR
    contents = []
    
    # 读最近 N 天的记忆文件
    for i in range(days):
        date = datetime.now() - timedelta(days=i)
        date_str = date.strftime("%Y-%m-%d")
        memory_file = memory_dir / f"{date_str}.md"
        if memory_file.exists():
            try:
                with open(memory_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                    if content.strip():
                        contents.append(f"=== {date_str} ===\n{content[:2000]}")
            except Exception as e:
                print(f"   ⚠️ 读取 {memory_file.name} 失败: {e}")
    
    if contents:
        return "\n\n".join(contents)
    
    return ""


# ==================== Hindsight Memory 集成 ====================

def write_to_hindsight_memory(representation: str, confidence: float = 0.9):
    """
    将 Kairos 推理结果写入 hindsight-memory 共享记忆层
    
    Args:
        representation: Kairos 生成的用户画像
        confidence: 置信度，默认 0.9

    Returns:
        bool: 是否成功写入
    """
    try:
        hindsight_path = '/home/jinghao/.openclaw/skills/hindsight-memory/lib/multi-agent/index.js'
        
        # 使用 JSON.stringify 避免 Shell 注入
        escaped_content = json.dumps(representation.replace('"', '\\"'))
        
        node_script = f"""
const {{AgentContext}} = require('{hindsight_path}');
const content = {escaped_content};
new AgentContext('kairos').writeShared('mentalModels', content, {{
    confidence: {confidence},
    tags: ['kairos', 'user-profile']
}}).then(r => console.log('记忆已写入:', r.agent)).catch(e => {{
    console.error('记忆写入失败:', e.message);
    process.exit(1);
}});
"""
        
        result = subprocess.run(
            ['node', '-e', node_script],
            capture_output=True,
            text=True,
            cwd='/home/jinghao',
            timeout=30
        )
        
        if result.returncode == 0:
            print(f"✅ Hindsight 记忆已更新: {result.stdout.strip()}")
            return True
        else:
            print(f"⚠️ Hindsight 记忆写入失败: {result.stderr.strip()}")
            return False
            
    except subprocess.TimeoutExpired:
        print("⚠️ Hindsight 记忆写入超时")
        return False
    except Exception as e:
        print(f"⚠️ Hindsight 记忆写入异常: {e}")
        return False


# ==================== 主逻辑 ====================

def main():
    parser = argparse.ArgumentParser(description="Kairos 用户学习定时任务 v3")
    parser.add_argument("--workspace", default=DEFAULT_WORKSPACE, help="工作区 ID")
    parser.add_argument("--user", required=True, help="用户 ID")
    parser.add_argument("--api-url", default=DEFAULT_API_URL, help="API URL")
    parser.add_argument("--dry-run", action="store_true", help="仅打印结果，不写入")
    parser.add_argument("--compact", action="store_true", help="压缩旧 context，生成摘要")
    parser.add_argument("--feedback", action="store_true", help="仅打印学习反馈，不写入")
    parser.add_argument("--fix-dim", action="store_true", help="检查并修复 embedding 维度错误（1536→1024）")
    parser.add_argument("--force", action="store_true", help="强制刷新 embedding 缓存")
    parser.add_argument("--infer", metavar="QUERY", help="执行推理查询，基于用户画像回答问题")
    parser.add_argument("--follow-up", metavar="QUESTION", help="追问：在上一轮推理基础上继续追问")
    parser.add_argument("--session-id", default=None, help="指定推理会话 ID（用于追问）")
    parser.add_argument("--learn-from-history", action="store_true", help="从 OpenClaw 会话历史学习用户特征")
    
    args = parser.parse_args()

    print(f"=== Kairos 用户学习 v3 ===")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"工作区: {args.workspace}")
    print(f"用户: {args.user}")
    if args.dry_run:
        print("⚠️ DRY-RUN 模式，不写入数据")
    print()

    # 支持 SiliconFlow API key（用于 embedding 缓存）
    embedding_api_key = os.getenv("SILICONFLOW_API_KEY", "")
    
    with KairosClient(args.api_url, embedding_api_key=embedding_api_key) as client:
        if not client.health_check():
            print("❌ Kairos 服务不可用")
            return 1
        
        print("✅ Kairos 连接正常")
        
        workspace = client.get_or_create_workspace(args.workspace)
        peer = client.get_or_create_peer(workspace.id, args.user)
        print(f"工作区: {workspace.id}, 用户: {peer.id}")
        
        # ====== 加载现有画像 ======
        fm = FeatureManager()
        context = client.get_context(workspace.id, peer.id)
        current_rep = context.get("representation", "")
        
        if current_rep:
            print(f"\n📥 加载现有画像 ({len(current_rep)} 字符)")
            fm.update_from_kairos(current_rep)
            print(f"   当前特征: {fm.get_summary()}")
        else:
            print("\n📥 无现有画像，从头开始")
        
        # ====== 压缩模式 ======
        if args.compact:
            print("\n📦 生成压缩摘要...")
            summary = fm.generate_compressed_summary()
            print(summary)
            
            if not args.dry_run:
                # 用压缩摘要替换现有
                try:
                    client.update_representation(
                        workspace.id, peer.id,
                        summary,
                        representation_type="compressed_profile"
                    )
                    print("\n✅ 压缩摘要已写入")
                except Exception as e:
                    print(f"\n⚠️ 写入失败: {e}")
            return 0
        
        # --fix-dim 单独处理：只做维度修复，不走学习流程
        if args.fix_dim:
            print("\n🔧 检查 embedding 维度...")
            if client.health_check(fix_embedding_dim=True):
                print("✅ 维度检查完成")
            else:
                print("❌ Kairos 服务不可用")
                return 1
            return 0

        # ====== 反馈模式 ======
        if args.feedback:
            print("\n📊 学习反馈报告:")
            print(f"   总特征数: {sum(len(fm.features[c]) for c in fm.features)}")
            
            for cat in ['basic', 'preference', 'tech']:
                if not fm.features[cat]:
                    continue
                print(f"\n   [{cat}] {len(fm.features[cat])}个:")
                for k, v in fm.features[cat].items():
                    conf_bar = '★' * int(v['confidence'] * 5) + '☆' * (5 - int(v['confidence'] * 5))
                    print(f"     {k}: {v['value']} [{conf_bar}] ({v['count']}次)")
            
            if fm.contradictions:
                print(f"\n   ⚠️ 矛盾特征: {len(fm.contradictions)}个")
                for c in fm.contradictions:
                    if 'old' in c:
                        print(f"     {c['key']}: 「{c['old']}」 vs 「{c['new']}」")
            
            # 高置信度特征（用于推理）
            high = fm.get_high_confidence_features(threshold=0.6)
            print(f"\n   🎯 高置信度特征（可用于推理）:")
            for cat, items in high.items():
                if items:
                    print(f"     {cat}: {len(items)}个")
            return 0

        # ====== 推理模式 ======
        if args.infer:
            session_id = args.session_id or f"session-{int(time.time())}"
            
            # 如果是追问，加载历史
            history_context = ""
            if args.follow_up and args.session_id:
                prev_session = load_infer_session(args.session_id)
                if prev_session.get("history"):
                    history_lines = []
                    for h in prev_session["history"]:
                        history_lines.append(f"问: {h['query']}")
                        history_lines.append(f"答: {h['response']}")
                    history_context = "\n\n".join(history_lines)
                    print(f"\n📜 加载历史推理 ({len(prev_session['history'])}轮)")
            
            print(f"\n🤖 执行推理: {args.follow_up or args.infer}")
            
            # 构建推理 prompt
            profile_summary = fm.get_summary() if fm.features else "无现有画像"
            
            if history_context:
                prompt = f"""你是基于用户画像的推理助手。

## 用户画像摘要
{profile_summary}

## 历史推理
{history_context}

## 当前追问
{args.follow_up or args.infer}

请结合历史推理和当前追问，给出连贯的个性化回答。"""
            else:
                prompt = f"""你是基于用户画像的推理助手。

## 用户画像摘要
{profile_summary}

## 用户问题
{args.infer}

请结合用户画像，给出个性化推理回答。"""
            
            try:
                response = client.chat(
                    workspace.id, peer.id,
                    prompt,
                    reasoning_level="medium"
                )
                answer = response.get("content", "").strip()
                print(f"\n💡 推理结果:\n{answer}")
                
                # 保存会话
                save_infer_session(session_id, args.infer, answer, profile_summary)
                
                print(f"\n🔗 推理会话 ID: {session_id}")
                if not args.follow_up:
                    print(f"追问命令: python3 kairos-learner.py --user jinghao --infer '{args.infer}' --follow-up '你的追问' --session-id {session_id}")
                
                return 0
            except Exception as e:
                print(f"推理失败: {e}")
                return 1

        # ====== 正常学习流程 ======
        print("\n📖 读取 OpenClaw 记忆...")
        # 1. 先从 hindsight-memory 共享层读取相关历史经验
        shared_history = read_hindsight_memory()
        if shared_history:
            print(f"   获取到共享层 {len(shared_history)} 条相关经验")
            fm.update_from_text(shared_history, source="shared_memory")
        else:
            print("   共享层暂无相关经验")
        
        oc_memory = read_openclaw_memory()
        if oc_memory:
            print(f"   获取到 {len(oc_memory)} 字符记忆内容")
            fm.update_from_text(oc_memory, source="openclaw_memory")
        else:
            print("   未找到相关记忆")
        
        # 从历史会话中学习（如果启用）
        if args.learn_from_history:
            print("\n📚 从历史会话学习...")
            history_content = learn_from_history(days=7)
            if history_content:
                oc_memory += "\n\n=== 历史会话 ===\n" + history_content
                print(f"   追加了 {len(history_content)} 字符的历史会话")
                fm.update_from_text(history_content, source="history_sessions")
            else:
                print("   未找到历史会话")
        
        # 生成分析
        analysis_prompt = f"""你是一个用户画像分析专家。请从以下信息中提取和更新用户特征。

现有用户画像摘要：
{fm.get_summary()}

OpenClaw 记忆片段：
{oc_memory[:2000] if oc_memory else '（无）'}

请分析并输出用户特征更新，每行一个特征，格式：
- 基本信息：项目内容
- 偏好习惯：项目内容
- 技术背景：项目内容

只输出特征行，不要解释。"""
        
        print("\n🤖 生成画像分析...")
        response = client.chat(
            workspace.id, peer.id,
            analysis_prompt,
            reasoning_level="low"
        )
        
        new_features = response.get("content", "").strip()
        print(f"\n📝 新特征:\n{new_features[:300]}...")
        
        # 合并 + 矛盾检测
        print("\n🔄 合并新特征...")
        merge_result = fm.merge_new_features(new_features)
        
        print(f"   新增: {len(merge_result['added'])}个")
        print(f"   更新: {len(merge_result['updated'])}个")
        print(f"   矛盾: {len(merge_result['contradicted'])}个")
        
        # 遗忘机制（降低30天未更新特征的置信度）
        print("\n🧹 应用遗忘机制...")
        forgotten = fm.apply_forgetting(max_age_days=30, min_confidence=0.15)
        if forgotten:
            print(f"   移除/降低: {len(forgotten)}个低置信度特征")
        
        # 矛盾警告
        if fm.contradictions:
            print(f"\n⚠️ 检测到 {len(fm.contradictions)} 个矛盾特征:")
            for c in fm.contradictions[-3:]:  # 最多显示3个
                if 'old' in c:
                    print(f"   {c['key']}: 「{c['old']}」 vs 「{c['new']}」")
        
        print(f"   合并后: {fm.get_summary()}")
        
        # 写入
        final_representation = fm.to_string()
        
        if args.dry_run:
            print("\n⚠️ DRY-RUN - 仅打印结果:")
            print("-" * 40)
            print(final_representation[:500])
            print("-" * 40)
        else:
            try:
                client.update_representation(
                    workspace.id, peer.id,
                    final_representation,
                    representation_type="user_profile"
                )
                total = sum(len(fm.features[c]) for c in fm.features)
                print(f"\n✅ 用户画像已更新 ({total}个特征)")
                
                # 写入 hindsight-memory 共享记忆层
                write_to_hindsight_memory(final_representation, confidence=0.9)
                
                # 学习反馈
                print("\n📊 本次学习反馈:")
                print(f"   + 新增 {len(merge_result['added'])} 个特征")
                if merge_result['contradicted']:
                    print(f"   ⚠️ {len(merge_result['contradicted'])} 个矛盾被检测并调整")
                
            except Exception as e:
                print(f"\n⚠️ 更新失败: {e}")
                return 1
        
        print("\n=== 完成 ===")
        return 0


if __name__ == "__main__":
    sys.exit(main())
