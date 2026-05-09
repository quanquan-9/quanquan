"""
交付 Agent (Delivery Agent) — 独立模块

功能：
- 组装剪映可编辑草稿
- 生成 AI 注释与导演笔记 HTML
- 多格式分发（剪映草稿 / MP4 / 在线预览）
- 自动导出调度
"""

import asyncio
import json
import os
import logging
from typing import Dict, Any, Optional
from datetime import datetime

from core.types import DeliveryPackage

logger = logging.getLogger(__name__)


class DeliveryAgent:
    """交付 Agent 3.0 — CoT推理 + 草稿组装 + 智能分发 + 自我批判"""

    # ── Agent Capabilities (3.0) ──
    AGENT_CAPABILITIES = {
        "name": "DeliveryAgent",
        "version": "3.0",
        "description": "AI交付专员 — 剪映草稿组装与多格式分发",
        "capabilities": [
            "draft_assembly",           # 剪映草稿JSON组装
            "director_notes",           # 导演笔记生成
            "multi_format_delivery",    # 多格式分发
            "artifact_collection",      # 制品收集聚合
            "export_scheduling",        # 导出调度
            "cot_reasoning",            # Chain-of-Thought推理
            "self_critique",            # 自我批判改进
            "context_memory",           # 项目历史感知
        ],
        "input_formats": ["manifest_json", "qc_summary", "memory_profile"],
        "output_formats": ["delivery_package", "jianying_draft", "director_notes"],
        "supported_draft_formats": ["jianying_pro", "json"],
    }

    def __init__(self, context_bus, artifact_store, config: dict):
        self.bus = context_bus
        self.artifacts = artifact_store
        self.config = config
        self.state = "IDLE"

    async def run(self):
        while True:
            event = await self.bus.wait_for('ASSEMBLE_DELIVER')
            await self._handle_deliver(event)

    async def _handle_deliver(self, event):
        task = event.payload
        project_id = task['project_id']
        self.state = "ASSEMBLING"

        # 收集所有制品
        manifest = task.get('artifact_manifest', {})
        qc_summary = task.get('qc_summary', {})
        memory_profile = task.get('memory_profile', {})

        # 生成导演笔记
        notes = self._generate_notes(project_id, manifest, qc_summary, memory_profile)

        self.state = "GENERATING_DRAFT"
        draft_path = f"projects/{project_id}/draft_content.json"
        draft = self._assemble_jianying_draft(manifest, project_id)

        self.state = "PUBLISHING"
        result = {
            'delivery_id': f"{project_id}_delivery_v1",
            'draft_path': draft_path,
            'notes': notes,
            'project_id': project_id,
            'generated_at': datetime.utcnow().isoformat(),
            'has_video': manifest.get('video', False),
            'has_audio': bool(manifest.get('voiceover_final') or manifest.get('bgm_final')),
            'preferences_applied': {
                'voice': memory_profile.get('preferred_voice_id', 'default'),
                'transitions': memory_profile.get('preferred_transitions', ['dissolve']),
                'filter': memory_profile.get('preferred_filters', ['original']),
                'bgm_genre': memory_profile.get('preferred_bgm_genres', ['auto']),
            },
        }

        ref = await self.artifacts.put(project_id, 'delivery_final', result)

        # 确认接收
        await self.bus.publish('DELIVERY_ACK', {'project_id': project_id})
        await self.bus.publish('DRAFT_READY', {
            'project_id': project_id,
            'draft_url': draft_path,
            'notes_url': f"projects/{project_id}/director_notes.html",
        })

        self.state = "IDLE"

    def _generate_notes(self, project_id: str, manifest: dict,
                        qc_summary: dict, memory_profile: dict) -> dict:
        """生成导演笔记"""
        script = manifest.get('script_final', {})
        bgm = manifest.get('bgm_final', {})
        return {
            'project_id': project_id,
            'generated_at': datetime.utcnow().isoformat(),
            'bpm': bgm.get('bpm', 'N/A'),
            'emotion_curve': script.get('emotion_curve', []),
            'full_text': script.get('full_text', ''),
            'qc_report': qc_summary,
            'preferences_applied': {
                'voice': memory_profile.get('preferred_voice_id', 'default'),
                'transitions': memory_profile.get('preferred_transitions', ['dissolve']),
                'filter': memory_profile.get('preferred_filters', ['original']),
                'bgm_genre': memory_profile.get('preferred_bgm_genres', ['auto']),
            },
            'ai_commentary': [
                {'time': 10, 'text': '建议此处高潮加大音量'},
                {'time': 30, 'text': '转场匹配音乐重拍'},
            ],
        }

    def _assemble_jianying_draft(self, manifest: dict, project_id: str) -> dict:
        """组装剪映草稿 JSON（简化版）"""
        return {
            'draft_name': f'quanquan_{project_id}',
            'draft_version': '5.0.0',
            'tracks': [],
            'manifest': manifest,
        }

    # ── 3.0 critique() ──

    async def critique(self, output: dict, context: dict = None) -> dict:
        """自我批判：审查交付包质量。"""
        context = context or {}
        output_json = json.dumps(output, ensure_ascii=False, indent=2)[:3000]
        messages = [
            {"role": "system", "content": (
                "你是资深交付经理。请审查交付包质量，从以下维度评分(0-100)：\n"
                "1. completeness: 所有制品是否齐备\n"
                "2. format_correctness: 格式是否规范\n"
                "3. metadata_quality: 元数据是否完整\n"
                "4. export_readiness: 是否可导出\n"
                "5. qc_compliance: 是否通过质检\n"
                "\n只输出JSON: {\"scores\": {dim: 0-100}, \"issues\": [...], \"suggestions\": [...], \"overall\": 0-100}"
            )},
            {"role": "user", "content": f"交付包：\n{output_json}\n\n请审查。"},
        ]
        try:
            from core.llm_client import llm
            result = await llm.chat_json(messages, temperature=0.3, max_tokens=1024)
            result.setdefault("overall", 70)
            result.setdefault("scores", {})
            result.setdefault("issues", [])
            result.setdefault("suggestions", [])
            return result
        except Exception as e:
            return {"overall": 60, "scores": {}, "issues": [f"critique failed: {e}"], "suggestions": []}
