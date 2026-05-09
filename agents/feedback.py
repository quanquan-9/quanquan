"""
用户反馈闭环 — Project Recycler 对比原始/修改草稿提取偏好信号
"""
import json
from datetime import datetime, timezone
from typing import Dict, List


class ProjectRecycler:
    """监控用户在剪映中的修改，提取偏好信号"""

    def on_project_reopen(self, original_draft_path: str,
                          modified_draft_path: str) -> List[dict]:
        """对比原始草稿与用户修改版本，提取反馈信号"""
        try:
            with open(original_draft_path) as f:
                original = json.load(f)
        except Exception:
            original = {}
        try:
            with open(modified_draft_path) as f:
                modified = json.load(f)
        except Exception:
            modified = {}

        signals = []

        # 1. 检测配音变更
        orig_voice = original.get("voice_id", "")
        mod_voice = modified.get("voice_id", "")
        if orig_voice and mod_voice and orig_voice != mod_voice:
            signals.append({
                "type": "VOICE_CHANGE",
                "from": orig_voice, "to": mod_voice,
                "strength": -0.3,
                "new_preference": {"voice_id": mod_voice, "weight": 0.2},
            })

        # 2. 检测转场变更
        orig_trans = {t.get("type", "") for t in original.get("transitions", [])}
        mod_trans = {t.get("type", "") for t in modified.get("transitions", [])}
        for t in orig_trans - mod_trans:
            signals.append({"type": "TRANSITION_REMOVED", "transition_type": t, "strength": -0.2})
        for t in mod_trans - orig_trans:
            signals.append({"type": "TRANSITION_ADDED", "transition_type": t, "strength": +0.3})

        # 3. 检测滤镜/调色修改
        orig_filter = original.get("filter_id", "")
        mod_filter = modified.get("filter_id", "")
        if orig_filter and mod_filter and orig_filter != mod_filter:
            signals.append({
                "type": "FILTER_CHANGE",
                "from": orig_filter, "to": mod_filter,
                "strength": -0.3,
                "new_preference": {"filter_id": mod_filter, "weight": 0.25},
            })

        # 4. 检测字幕样式修改
        orig_font = original.get("subtitle_style", {}).get("font", "")
        mod_font = modified.get("subtitle_style", {}).get("font", "")
        if orig_font and mod_font and orig_font != mod_font:
            signals.append({
                "type": "SUBTITLE_FONT_CHANGE",
                "from": orig_font, "to": mod_font,
                "strength": +0.15,
            })

        return signals

    def publish_feedback(self, project_id: str, signals: List[dict],
                         context_bus=None):
        """将反馈信号推送到 Context Bus"""
        from agents.memory import memory_engine

        for signal in signals:
            # 推送到记忆引擎
            memory_engine.on_user_feedback(signal)

            # 推送到 Context Bus
            if context_bus:
                import asyncio
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        asyncio.create_task(
                            context_bus.publish("USER_FEEDBACK", {
                                "project_id": project_id,
                                "signal": signal,
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                            })
                        )
                except Exception:
                    pass


project_recycler = ProjectRecycler()
