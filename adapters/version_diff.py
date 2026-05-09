"""
剪映版本映射 Diff 引擎

功能：
- 自动对比新旧版本 draft_content.json 结构差异
- 生成版本映射表 (version_mapping.yaml)
- 自动生成适配器代码补丁
- CI 集成自动化
"""

import json
import yaml
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime
from collections import defaultdict

logger = logging.getLogger(__name__)


@dataclass
class StructureChange:
    """结构变更记录"""
    path: str
    change_type: str     # added / removed / type_changed / enum_changed / moved
    old_value: Any = None
    new_value: Any = None
    old_type: str = ""
    new_type: str = ""
    severity: str = "info"  # info / warning / breaking
    description: str = ""


@dataclass
class VersionMapping:
    """版本映射"""
    from_version: str
    to_version: str
    updated: str
    changes: List[StructureChange] = field(default_factory=list)
    field_mappings: Dict[str, dict] = field(default_factory=dict)
    removed_fields: List[str] = field(default_factory=list)
    default_values: Dict[str, Any] = field(default_factory=dict)


class DraftSampleGenerator:
    """生成包含所有常见元素的标准化草稿（用于版本对比）"""

    def generate_standard_draft(self, version: str) -> dict:
        """生成标准草稿 JSON"""
        return {
            "platform": {"os": "windows", "version": version},
            "draft_name": f"standard_draft_{version}",
            "draft_version": version,
            "materials": {
                "videos": [self._video_material()],
                "audios": [self._audio_material()],
                "texts": [self._text_style()],
                "effects": [self._effect()],
                "transitions": [self._transition()],
                "filters": [self._filter()],
            },
            "tracks": [
                self._video_track(),
                self._audio_track(),
                self._subtitle_track(),
                self._effect_track(),
            ],
            "color_adjustments": self._color_lut(),
            "keyframe_animations": self._keyframes(),
            "project_settings": self._project_settings(),
        }

    def _video_material(self) -> dict:
        return {
            "id": "mat_video_001", "type": "video",
            "path": "/materials/sample.mp4",
            "duration": 10000, "width": 1920, "height": 1080,
            "fps": 30, "codec": "h264",
        }

    def _audio_material(self) -> dict:
        return {
            "id": "mat_audio_001", "type": "audio",
            "path": "/materials/sample.mp3",
            "duration": 10000, "sample_rate": 48000,
        }

    def _text_style(self) -> dict:
        return {
            "id": "style_text_001", "type": "text_style",
            "font": "PingFang SC", "font_size": 32,
            "color": "#FFFFFF", "outline_color": "#000000",
            "outline_width": 2, "bold": False, "italic": False,
        }

    def _effect(self) -> dict:
        return {
            "id": "effect_001", "type": "effect",
            "name": "glitch", "category": "distortion",
            "params": {"intensity": 0.5, "speed": 1.0},
        }

    def _transition(self) -> dict:
        return {
            "id": "trans_001", "type": "transition",
            "name": "dissolve", "duration_ms": 500,
        }

    def _filter(self) -> dict:
        return {
            "id": "filter_001", "type": "filter",
            "name": "cyberpunk", "intensity": 0.8,
        }

    def _video_track(self) -> dict:
        return {
            "id": "track_video_main", "type": "video",
            "clips": [{
                "id": "clip_001", "material_id": "mat_video_001",
                "start_time": 0, "end_time": 5000,
                "speed": 1.0, "volume": 1.0,
                "transform": {
                    "x": 0.0, "y": 0.0,
                    "scale_x": 1.0, "scale_y": 1.0,
                    "rotation": 0.0, "opacity": 1.0,
                },
                "color_adjustment": {},
                "keyframes": [],
                "transitions": [],
            }],
        }

    def _audio_track(self) -> dict:
        return {
            "id": "track_audio_main", "type": "audio",
            "clips": [{
                "id": "aclip_001", "material_id": "mat_audio_001",
                "start_time": 0, "end_time": 5000,
                "volume": 1.0, "fade_in_ms": 50, "fade_out_ms": 50,
            }],
        }

    def _subtitle_track(self) -> dict:
        return {
            "id": "track_subtitle", "type": "subtitle",
            "clips": [{
                "id": "sub_001", "text": "示例字幕",
                "start_time": 0, "end_time": 2000,
                "style_id": "style_text_001",
            }],
        }

    def _effect_track(self) -> dict:
        return {
            "id": "track_effect", "type": "effect",
            "clips": [{
                "id": "efx_001", "effect_id": "effect_001",
                "start_time": 1000, "end_time": 3000,
            }],
        }

    def _color_lut(self) -> dict:
        return {
            "global": {
                "contrast": 1.0, "saturation": 1.0,
                "temperature": 0, "tint": 0,
                "exposure": 0, "highlights": 0, "shadows": 0,
            },
            "clips": [],
        }

    def _keyframes(self) -> dict:
        return {
            "animations": [{
                "target": "clip_001.transform.scale_x",
                "keyframes": [
                    {"time_ms": 0, "value": 1.0, "easing": "linear"},
                    {"time_ms": 1000, "value": 1.2, "easing": "ease_out"},
                ],
            }],
        }

    def _project_settings(self) -> dict:
        return {
            "width": 1920, "height": 1080,
            "fps": 30, "sample_rate": 48000,
            "bitrate_kbps": 20000,
        }


class DraftStructureDiff:
    """JSON 结构深度对比引擎"""

    def __init__(self, baseline: dict, new_version: dict):
        self.baseline = baseline
        self.new = new_version

    def compute_diff(self) -> List[StructureChange]:
        """深度对比两个版本的草稿结构"""
        changes = []
        self._compare("", self.baseline, self.new, changes)
        return self._deduplicate(changes)

    def _compare(self, path: str, old: Any, new: Any,
                 changes: List[StructureChange]):
        """递归对比"""
        # 类型不同
        if type(old) != type(new):
            changes.append(StructureChange(
                path=path or "/",
                change_type="type_changed",
                old_type=type(old).__name__,
                new_type=type(new).__name__,
                old_value=str(old)[:200],
                new_value=str(new)[:200],
                severity="breaking",
            ))
            return

        # 字典
        if isinstance(old, dict):
            old_keys = set(old.keys())
            new_keys = set(new.keys())
            for k in old_keys - new_keys:
                changes.append(StructureChange(
                    path=f"{path}.{k}" if path else k,
                    change_type="removed",
                    old_value=old[k],
                    severity="warning",
                ))
            for k in new_keys - old_keys:
                changes.append(StructureChange(
                    path=f"{path}.{k}" if path else k,
                    change_type="added",
                    new_value=new[k],
                    severity="info",
                ))
            for k in old_keys & new_keys:
                self._compare(f"{path}.{k}" if path else k,
                             old[k], new[k], changes)

        # 列表
        elif isinstance(old, list):
            if len(old) != len(new):
                changes.append(StructureChange(
                    path=path or "/",
                    change_type="type_changed",
                    description=f"列表长度变化: {len(old)} → {len(new)}",
                    severity="warning",
                ))
            for i in range(min(len(old), len(new))):
                self._compare(f"{path}[{i}]", old[i], new[i], changes)

        # 值不同
        elif old != new:
            change_type = "enum_changed" if isinstance(old, str) else "value_changed"
            changes.append(StructureChange(
                path=path or "/",
                change_type=change_type,
                old_value=old,
                new_value=new,
                severity="warning",
            ))

    def _deduplicate(self, changes: List[StructureChange]) -> List[StructureChange]:
        """去重并排序"""
        seen = set()
        result = []
        for c in sorted(changes, key=lambda x: x.severity != "breaking"):
            key = (c.path, c.change_type)
            if key not in seen:
                seen.add(key)
                result.append(c)
        return result


class MappingTableUpdater:
    """映射表自动更新 + 适配器代码生成"""

    def __init__(self, config_dir: str = "config/"):
        self.config_dir = config_dir
        self.mapping_file = f"{config_dir}/version_mapping.yaml"

    def update_from_diff(
        self, from_version: str, to_version: str,
        changes: List[StructureChange]
    ) -> VersionMapping:
        """根据差异生成版本映射"""
        mapping = VersionMapping(
            from_version=from_version,
            to_version=to_version,
            updated=datetime.utcnow().isoformat(),
        )

        for change in changes:
            mapping.changes.append(change)
            if change.change_type == "added":
                mapping.field_mappings[change.path] = {
                    "action": "add",
                    "default": change.new_value,
                    "type": type(change.new_value).__name__ if change.new_value else "null",
                }
            elif change.change_type == "removed":
                mapping.removed_fields.append(change.path)
            elif change.change_type == "type_changed":
                mapping.field_mappings[change.path] = {
                    "action": "cast",
                    "from_type": change.old_type,
                    "to_type": change.new_type,
                }
            elif change.change_type == "enum_changed":
                mapping.field_mappings[change.path] = {
                    "action": "map_enum",
                    "old_value": change.old_value,
                    "new_value": change.new_value,
                }

        return mapping

    def save_mapping(self, mapping: VersionMapping):
        """保存映射到 YAML"""
        existing = {}
        if Path(self.mapping_file).exists():
            with open(self.mapping_file) as f:
                existing = yaml.safe_load(f) or {}

        existing.setdefault("versions", {})
        existing["versions"][mapping.to_version] = {
            "from_version": mapping.from_version,
            "to_version": mapping.to_version,
            "updated": mapping.updated,
            "field_mappings": mapping.field_mappings,
            "removed_fields": mapping.removed_fields,
            "breaking_changes": [
                c.path for c in mapping.changes if c.severity == "breaking"
            ],
        }

        Path(self.config_dir).mkdir(parents=True, exist_ok=True)
        with open(self.mapping_file, "w") as f:
            yaml.dump(existing, f, default_flow_style=False, allow_unicode=True)

        logger.info(f"Version mapping saved: {self.mapping_file}")

    def generate_adapter_code(self, mapping: VersionMapping) -> str:
        """生成适配器 Python 代码"""
        class_name = f"VersionAdapter_{mapping.to_version.replace('.', '_')}"
        code = f'''"""
Auto-generated adapter for JianYing version {mapping.from_version} → {mapping.to_version}
Generated: {mapping.updated}
Changes: {len(mapping.changes)} ({sum(1 for c in mapping.changes if c.severity=='breaking')} breaking)
"""

import copy
from typing import Any, Dict


class {class_name}:
    """自动版本适配器 — {mapping.from_version} → {mapping.to_version}"""

    def apply(self, draft: Dict[str, Any]) -> Dict[str, Any]:
        """将 {mapping.from_version} 版草稿转换为 {mapping.to_version} 版"""
        draft = copy.deepcopy(draft)
'''
        # 新增字段
        for path, info in mapping.field_mappings.items():
            if info["action"] == "add":
                code += f'        self._set_nested(draft, "{path}", {json.dumps(info["default"], ensure_ascii=False)})\n'

        # 移除字段
        for path in mapping.removed_fields:
            code += f'        self._remove_nested(draft, "{path}")\n'

        # 类型转换
        for path, info in mapping.field_mappings.items():
            if info["action"] == "cast":
                code += f'        val = self._get_nested(draft, "{path}")\n'
                code += f'        if val is not None:\n'
                code += f'            self._set_nested(draft, "{path}", {info["to_type"]}(val))\n'

        code += '''
        return draft

    @staticmethod
    def _get_nested(d: dict, path: str) -> Any:
        keys = path.replace("[", ".").replace("]", "").split(".")
        current = d
        for k in keys:
            if not k: continue
            if isinstance(current, dict):
                current = current.get(k)
            elif isinstance(current, list) and k.isdigit():
                current = current[int(k)] if int(k) < len(current) else None
            else:
                return None
            if current is None:
                return None
        return current

    @staticmethod
    def _set_nested(d: dict, path: str, value: Any):
        keys = path.replace("[", ".").replace("]", "").split(".")
        current = d
        for k in keys[:-1]:
            if not k: continue
            if k.isdigit():
                k = int(k)
                while len(current) <= k:
                    current.append({})
                current = current[k]
            else:
                if k not in current:
                    current[k] = {}
                current = current[k]
        last = keys[-1]
        if last.isdigit():
            last = int(last)
            while len(current) <= last:
                current.append(None)
        current[last] = value

    @staticmethod
    def _remove_nested(d: dict, path: str):
        keys = path.replace("[", ".").replace("]", "").split(".")
        current = d
        for k in keys[:-1]:
            if not k: continue
            if k.isdigit():
                k = int(k)
                if k >= len(current): return
                current = current[k]
            else:
                if k not in current: return
                current = current[k]
        last = keys[-1]
        if last.isdigit():
            last = int(last)
            if last < len(current):
                current.pop(last)
        else:
            current.pop(last, None)
'''
        return code


async def auto_diff_and_update(
    old_version: str,
    new_version: str,
    old_draft_path: Optional[str] = None,
    new_draft_path: Optional[str] = None,
    config_dir: str = "config/",
) -> dict:
    """
    自动化版本对比流水线：
    1. 生成标准草稿（或加载已有草稿）
    2. 深度对比
    3. 生成映射表
    4. 生成适配器代码

    Returns: {"changes": [...], "adapter_code": "...", "mapping_file": "..."}
    """
    generator = DraftSampleGenerator()

    # 加载或生成草稿
    if old_draft_path and Path(old_draft_path).exists():
        old_draft = json.loads(Path(old_draft_path).read_text())
    else:
        old_draft = generator.generate_standard_draft(old_version)

    if new_draft_path and Path(new_draft_path).exists():
        new_draft = json.loads(Path(new_draft_path).read_text())
    else:
        new_draft = generator.generate_standard_draft(new_version)

    # 深度对比
    diff_engine = DraftStructureDiff(old_draft, new_draft)
    changes = diff_engine.compute_diff()

    # 生成映射
    updater = MappingTableUpdater(config_dir)
    mapping = updater.update_from_diff(old_version, new_version, changes)
    updater.save_mapping(mapping)

    # 生成适配器代码
    adapter_code = updater.generate_adapter_code(mapping)

    # 保存适配器代码
    adapter_path = Path(config_dir) / f"adapter_{old_version}_to_{new_version}.py"
    adapter_path.write_text(adapter_code, encoding="utf-8")

    return {
        "from_version": old_version,
        "to_version": new_version,
        "total_changes": len(changes),
        "breaking_changes": sum(1 for c in changes if c.severity == "breaking"),
        "changes": [
            {"path": c.path, "type": c.change_type, "severity": c.severity}
            for c in changes
        ],
        "adapter_code": adapter_code,
        "mapping_file": str(Path(config_dir) / "version_mapping.yaml"),
        "adapter_file": str(adapter_path),
    }
