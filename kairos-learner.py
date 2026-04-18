#!/usr/bin/env python3
"""
Kairos 用户学习定时任务 v2

改进：
1. 增量更新 - 合并新特征而非全量覆盖
2. OpenClaw 深度集成 - 直接读取 MEMORY.md 和每日记忆
3. 置信度机制 - 频繁出现的特征置信度高
4. 特征分类 - 基本信息/偏好/技术背景 分开存储

用法：
    python3 kairos-learner.py --user jinghao
    python3 kairos-learner.py --user jinghao --workspace openclaw-main
"""

import os
import sys
import json
import argparse
import re
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from client import KairosClient

DEFAULT_WORKSPACE = os.getenv("KAIROS_WORKSPACE", "openclaw-main")
DEFAULT_API_URL = os.getenv("KAIROS_API_URL", "http://localhost:8000")
OPENCLAW_AGENT_DIR = "/home/jinghao/.openclaw/agents/main"
MEMORY_FILE = Path(OPENCLAW_AGENT_DIR) / "MEMORY.md"
DAILY_MEMORY_DIR = Path(OPENCLAW_AGENT_DIR) / "memory"


# ==================== 特征解析与合并 ====================

class FeatureManager:
    """特征管理器 - 解析、合并、去重特征"""
    
    FEATURE_PATTERNS = {
        'basic': ['姓名', '名字', '年龄', '职业', '所在地', '时区', '称呼'],
        'preference': ['喜欢', '偏好', '习惯', '不喜欢', '倾向', '希望', '想要'],
        'tech': ['编程', '开发', '技术', '语言', '框架', '工具', '模型', 'API'],
    }
    
    def __init__(self):
        self.features = {
            'basic': {},      # key -> {value, confidence, last_seen}
            'preference': {},
            'tech': {},
        }
    
    def parse_raw_text(self, text: str):
        """从文本中提取特征行"""
        lines = []
        for line in text.strip().split('\n'):
            line = line.strip()
            # 跳过空行和注释行
            if not line or line.startswith('#') or line.startswith('//'):
                continue
            # 移除列表前缀 (- * · 等)
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
        return 'preference'  # 默认归类为偏好
    
    def update_from_kairos(self, representation: str):
        """从 Kairos 现有画像解析并加载"""
        if not representation:
            return
        
        lines = self.parse_raw_text(representation)
        for line in lines:
            # 提取特征（忽略时间戳）
            clean_line = re.sub(r'\[\d{4}-\d{2}-\d{2}[^\]]*\]', '', line).strip()
            if not clean_line:
                continue
            
            category = self.classify_feature(clean_line)
            
            # 解析 key-value
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
                        'confidence': 0.3,  # 初始置信度
                        'count': 0,
                        'first_seen': datetime.now().isoformat(),
                    }
                self.features[category][key]['count'] += 1
                self.features[category][key]['last_seen'] = datetime.now().isoformat()
                # 每次出现置信度增加，上限 1.0
                self.features[category][key]['confidence'] = min(
                    1.0, 
                    self.features[category][key]['confidence'] + 0.1
                )
    
    def update_from_text(self, text: str, source: str = "analysis"):
        """从文本更新特征（如 MEMORY.md 内容）"""
        lines = self.parse_raw_text(text)
        timestamp = datetime.now().isoformat()
        
        for line in lines:
            category = self.classify_feature(line)
            
            # 解析 key-value
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
            
            # 同一来源不重复增加计数
            self.features[category][key]['count'] += 1
            self.features[category][key]['last_seen'] = timestamp
            self.features[category][key]['confidence'] = min(
                1.0,
                self.features[category][key]['confidence'] + 0.05
            )
    
    def merge_new_features(self, new_text: str):
        """合并新的分析结果"""
        lines = self.parse_raw_text(new_text)
        
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
            
            timestamp = datetime.now().isoformat()
            
            if key in self.features[category]:
                # 更新已有特征
                old_value = self.features[category][key]['value']
                if old_value != value:
                    # 值变了，可能需要调整判断
                    self.features[category][key]['value'] = value
                    self.features[category][key]['confidence'] = max(
                        0.3,
                        self.features[category][key]['confidence'] - 0.1
                    )
                else:
                    # 值相同，增加置信度
                    self.features[category][key]['confidence'] = min(
                        1.0,
                        self.features[category][key]['confidence'] + 0.15
                    )
                self.features[category][key]['count'] += 1
                self.features[category][key]['last_seen'] = timestamp
            else:
                # 新增特征
                self.features[category][key] = {
                    'value': value,
                    'confidence': 0.4,
                    'count': 1,
                    'first_seen': timestamp,
                    'last_seen': timestamp,
                }
    
    def to_string(self) -> str:
        """转换为格式化字符串"""
        lines = []
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M')
        
        lines.append(f"[{timestamp}] Kairos 用户画像 v2")
        lines.append("")
        
        for category in ['basic', 'preference', 'tech']:
            if not self.features[category]:
                continue
            
            title = {
                'basic': '📋 基本信息',
                'preference': '❤️ 偏好习惯',
                'tech': '💻 技术背景'
            }[category]
            
            lines.append(f"### {title}")
            
            # 按置信度排序
            sorted_features = sorted(
                self.features[category].items(),
                key=lambda x: x[1]['confidence'],
                reverse=True
            )
            
            for key, data in sorted_features:
                conf_bar = '★' * int(data['confidence'] * 5) + '☆' * (5 - int(data['confidence'] * 5))
                lines.append(f"- {key}：{data['value']} [{conf_bar}] ({data['count']}次)")
            
            lines.append("")
        
        return '\n'.join(lines)
    
    def get_summary(self) -> str:
        """获取简短摘要"""
        parts = []
        for category in ['basic', 'preference', 'tech']:
            count = len(self.features[category])
            if count > 0:
                parts.append(f"{count}个{category}")
        return ', '.join(parts) if parts else '暂无特征'


# ==================== OpenClaw 记忆读取 ====================

def read_openclaw_memory() -> str:
    """读取 OpenClaw 记忆文件，提取用户相关信息"""
    contents = []
    
    # 读取 MEMORY.md
    if MEMORY_FILE.exists():
        try:
            content = MEMORY_FILE.read_text(encoding='utf-8')
            # 提取关键段落（避免过长）
            lines = content.split('\n')
            for i, line in enumerate(lines):
                if any(kw in line for kw in ['用户', '偏好', '姓名', '职业', '习惯', '关于', 'MEMORY']):
                    # 获取周围上下文
                    start = max(0, i - 1)
                    end = min(len(lines), i + 3)
                    context = '\n'.join(lines[start:end])
                    contents.append(context)
        except Exception as e:
            print(f"⚠️ 读取 MEMORY.md 失败: {e}")
    
    # 读取最近2天的每日记忆
    today = datetime.now()
    for days_ago in range(2):
        target_date = (today - timedelta(days=days_ago)).strftime('%Y-%m-%d')
        daily_file = DAILY_MEMORY_DIR / f"{target_date}.md"
        if daily_file.exists():
            try:
                content = daily_file.read_text(encoding='utf-8')
                # 只取关键段落
                lines = content.split('\n')
                for i, line in enumerate(lines):
                    if any(kw in line.lower() for kw in ['user', 'pref', '喜欢', '不喜欢', '决策', '项目']):
                        start = max(0, i - 1)
                        end = min(len(lines), i + 2)
                        contents.append('\n'.join(lines[start:end]))
            except Exception as e:
                print(f"⚠️ 读取 {daily_file.name} 失败: {e}")
    
    return '\n'.join(contents) if contents else ''


# ==================== 主逻辑 ====================

def main():
    parser = argparse.ArgumentParser(description="Kairos 用户学习定时任务 v2")
    parser.add_argument("--workspace", default=DEFAULT_WORKSPACE, help="工作区 ID")
    parser.add_argument("--user", required=True, help="用户 ID")
    parser.add_argument("--api-url", default=DEFAULT_API_URL, help="API URL")
    parser.add_argument("--dry-run", action="store_true", help="仅打印结果，不写入")
    
    args = parser.parse_args()

    print(f"=== Kairos 用户学习 v2 ===")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"工作区: {args.workspace}")
    print(f"用户: {args.user}")
    if args.dry_run:
        print("⚠️ DRY-RUN 模式，不写入数据")
    print()

    with KairosClient(args.api_url) as client:
        # 检查健康
        if not client.health_check():
            print("❌ Kairos 服务不可用")
            return 1
        
        print("✅ Kairos 连接正常")
        
        # 获取工作区和用户
        workspace = client.get_or_create_workspace(args.workspace)
        peer = client.get_or_create_peer(workspace.id, args.user)
        print(f"工作区: {workspace.id}, 用户: {peer.id}")
        
        # ====== 步骤1: 加载现有画像 ======
        fm = FeatureManager()
        context = client.get_context(workspace.id, peer.id)
        current_rep = context.get("representation", "")
        
        if current_rep:
            print(f"\n📥 加载现有画像 ({len(current_rep)} 字符)")
            fm.update_from_kairos(current_rep)
            print(f"   当前特征: {fm.get_summary()}")
        else:
            print("\n📥 无现有画像，从头开始")
        
        # ====== 步骤2: 读取 OpenClaw 记忆 ======
        print("\n📖 读取 OpenClaw 记忆...")
        oc_memory = read_openclaw_memory()
        if oc_memory:
            print(f"   获取到 {len(oc_memory)} 字符记忆内容")
            fm.update_from_text(oc_memory, source="openclaw_memory")
        else:
            print("   未找到相关记忆")
        
        # ====== 步骤3: 生成新的分析 ======
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
            workspace.id,
            peer.id,
            analysis_prompt,
            reasoning_level="low"
        )
        
        new_features = response.get("content", "").strip()
        print(f"\n📝 新特征:\n{new_features[:300]}...")
        
        # ====== 步骤4: 合并新特征 ======
        if new_features:
            print("\n🔄 合并新特征...")
            fm.merge_new_features(new_features)
            print(f"   合并后: {fm.get_summary()}")
        
        # ====== 步骤5: 写入 Kairos ======
        final_representation = fm.to_string()
        
        if args.dry_run:
            print("\n⚠️ DRY-RUN - 仅打印结果:")
            print("-" * 40)
            print(final_representation)
            print("-" * 40)
        else:
            try:
                client.update_representation(
                    workspace.id,
                    peer.id,
                    final_representation,
                    representation_type="user_profile"
                )
                print("\n✅ 用户画像已更新")
                
                # 打印更新摘要
                total_features = sum(len(fm.features[c]) for c in fm.features)
                print(f"   特征总数: {total_features}")
                for cat in ['basic', 'preference', 'tech']:
                    if fm.features[cat]:
                        print(f"   - {cat}: {len(fm.features[cat])}个")
                
            except Exception as e:
                print(f"\n⚠️ 更新失败: {e}")
                return 1
        
        print("\n=== 完成 ===")
        return 0


if __name__ == "__main__":
    sys.exit(main())
