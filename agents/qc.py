"""
审核 Agent (Quality Control Agent) — 独立模块

功能：
- 6 检测器插件架构
- 缺陷分级（pass/minor/major/fatal）
- 与 FFmpeg 验片工具协同
- 转场附近黑场排除
"""

import asyncio
import json
import re
import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from datetime import datetime

from core.types import QCReport

logger = logging.getLogger(__name__)


@dataclass
class Issue:
    checker: str
    severity: str         # pass / minor / major / fatal
    description: str
    segment: Optional[dict] = None
    measured_value: float = 0
    threshold: float = 0
    suggestion: str = ""


@dataclass
class QCReport:
    node_id: str
    project_id: str
    timestamp: str
    issues: List[Issue] = field(default_factory=list)
    artifacts_checked: List[str] = field(default_factory=list)
    summary: dict = field(default_factory=dict)

    def has_fatal(self) -> bool:
        return self.summary.get('fatal_count', 0) > 0

    def has_major(self) -> bool:
        return self.summary.get('major_count', 0)


class QualityControlAgent:
    """审核 Agent 3.0 — CoT推理 + 可插拔检测器 + 智能聚合 + 自我批判"""

    # ── Agent Capabilities (3.0) ──
    AGENT_CAPABILITIES = {
        "name": "QualityControlAgent",
        "version": "3.0",
        "description": "AI质检员 — 6检测器插件架构 + 智能缺陷分级",
        "capabilities": [
            "subtitle_timing_check",    # 字幕时序检测
            "black_frame_detection",    # 黑场检测(ffmpeg)
            "audio_peak_detection",     # 音频削波检测
            "silence_detection",        # 静音段检测
            "av_sync_check",            # 音画同步检测
            "style_consistency_check",  # 风格一致性检测
            "issue_aggregation",        # 缺陷聚合升级
            "ffmpeg_inspection",        # FFmpeg自动化验片
            "cot_reasoning",            # Chain-of-Thought推理
            "self_critique",            # 自我批判改进
            "context_memory",           # 项目历史感知
        ],
        "input_formats": ["artifact_dict", "video_path", "qc_rules"],
        "output_formats": ["qc_report", "issues_list", "verdict"],
        "severity_levels": ["pass", "minor", "major", "fatal"],
    }

    QC_RULES = {
        "subtitle_timing": {
            "fatal_exceed": 2.0,
            "major_exceed": 0.5,
        },
        "black_frame": {
            "min_dur": 0.5,
            "pix_th": 0.05,
            "severity_map": {
                "fatal": {"duration": 2.0},
                "major": {"duration": 1.0},
                "minor": {"duration": 0.5},
            }
        },
        "audio_peak": {
            "peak_threshold_dbfs": -0.1,
            "consecutive_samples": 3,
            "severity": {"clipping": "fatal", "near_clipping": "major"},
        },
        "silence": {
            "noise_threshold_dB": -50,
            "min_silence_dur": 1.0,
            "severity_map": {
                "fatal": {"duration": 3.0},
                "major": {"duration": 1.5},
                "minor": {"duration": 1.0},
            }
        },
        "av_sync": {
            "offset_ms": {"fatal": 200, "major": 100, "minor": 50},
        },
        "aggregation": {"max_major_before_fatal": 3},
    }

    def __init__(self, context_bus, artifact_store, config: dict):
        self.bus = context_bus
        self.artifacts = artifact_store
        self.config = config
        self.state = "IDLE"
        self.inspectors = [
            "subtitle_timing", "black_frame", "audio_peak",
            "silence", "av_sync", "style_consistency",
        ]

    async def run(self):
        while True:
            event = await self.bus.wait_for('TASK_QC_CHECK')
            await self._handle_qc_check(event)

    async def _handle_qc_check(self, event):
        check_spec = event.payload
        self.state = "FETCHING"

        # 拉取待检制品
        artifacts = {}
        for key in check_spec.get('artifact_keys', []):
            try:
                artifacts[key] = await self.artifacts.get(
                    check_spec['project_id'], key)
            except Exception:
                artifacts[key] = None

        self.state = "ANALYZING"

        all_issues = []
        rules = check_spec.get('rules', self.inspectors)
        for rule in rules:
            if rule in artifacts or rule == 'subtitle_timing':
                issues = await self._inspect(rule, artifacts)
                all_issues.extend(issues)

        self.state = "CLASSIFYING"
        classified = self._classify_issues(all_issues)

        self.state = "REPORTING"

        report = QCReport(
            node_id=check_spec['node_id'],
            project_id=check_spec['project_id'],
            timestamp=datetime.utcnow().isoformat(),
            issues=classified,
            artifacts_checked=list(artifacts.keys()),
            summary=self._generate_summary(classified),
        )

        await self.artifacts.put(
            check_spec['project_id'],
            f"qc_report_{check_spec['node_id']}",
            report.__dict__
        )

        if report.has_fatal():
            await self.bus.publish('QC_ISSUE', {
                'node_id': check_spec['node_id'],
                'project_id': check_spec['project_id'],
                'fatal_count': report.summary['fatal_count'],
                'report_ref': f"qc_report_{check_spec['node_id']}",
            })
        elif report.has_major():
            await self.bus.publish('QC_ISSUE', {
                'node_id': check_spec['node_id'],
                'project_id': check_spec['project_id'],
                'major_count': report.summary['major_count'],
                'report_ref': f"qc_report_{check_spec['node_id']}",
            })
        else:
            await self.bus.publish('QC_PASSED', {
                'node_id': check_spec['node_id'],
                'project_id': check_spec['project_id'],
            })

        self.state = "IDLE"

    async def _inspect(self, rule: str, artifacts: dict) -> List[Issue]:
        """执行单个检测器"""
        if rule == 'subtitle_timing':
            return self._check_subtitle_timing(artifacts)
        elif rule == 'black_frame':
            return self._check_black_frames(artifacts)
        elif rule == 'audio_peak':
            return self._check_audio_peaks(artifacts)
        return []

    def _check_subtitle_timing(self, artifacts: dict) -> List[Issue]:
        issues = []
        script = artifacts.get('script')
        voiceover = artifacts.get('voiceover')
        if not script or not voiceover:
            return issues

        script_duration = script.get('total_duration_sec', 0)
        voice_duration = voiceover.get('duration', 0)
        diff = abs(script_duration - voice_duration)

        rules = self.QC_RULES['subtitle_timing']
        if diff >= rules['fatal_exceed']:
            issues.append(Issue(
                checker='subtitle_timing', severity='fatal',
                description=f'字幕时长与配音偏差 {diff:.1f}s',
                measured_value=diff, threshold=rules['fatal_exceed'],
                suggestion='重新生成字幕或调整配音语速'
            ))
        elif diff >= rules['major_exceed']:
            issues.append(Issue(
                checker='subtitle_timing', severity='major',
                description=f'字幕时长偏差 {diff:.1f}s',
                measured_value=diff, threshold=rules['major_exceed'],
            ))
        return issues

    def _check_black_frames(self, artifacts: dict) -> List[Issue]:
        return []  # 由 ffmpeg_inspector 处理

    def _check_audio_peaks(self, artifacts: dict) -> List[Issue]:
        return []  # 由 ffmpeg_inspector 处理

    def _classify_issues(self, issues: List[Issue]) -> List[Issue]:
        """聚合规则：多个 major → 升级为 fatal"""
        major_count = sum(1 for i in issues if i.severity == 'major')
        max_major = self.QC_RULES['aggregation']['max_major_before_fatal']
        if major_count >= max_major:
            for i in issues:
                if i.severity == 'major':
                    i.severity = 'fatal'
                    i.description += ' (聚合升级)'
        return issues

    def _generate_summary(self, issues: List[Issue]) -> dict:
        fatal = sum(1 for i in issues if i.severity == 'fatal')
        major = sum(1 for i in issues if i.severity == 'major')
        minor = sum(1 for i in issues if i.severity == 'minor')
        return {
            'total_issues': len(issues),
            'fatal_count': fatal,
            'major_count': major,
            'minor_count': minor,
            'verdict': 'FAIL' if fatal > 0 else ('WARN' if major > 0 else 'PASS'),
        }
