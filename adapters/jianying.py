"""
剪映适配层 — pyJianYingDraft + 版本映射 + 自动差异对比
"""
import json
import os
import yaml
from datetime import datetime, timezone
from typing import Dict, List, Optional
from deepdiff import DeepDiff


class DraftSampleGenerator:
    """生成包含所有常见元素的标准剪映草稿"""

    def generate_standard_draft(self, version: str = "5.0") -> dict:
        draft = {
            "platform": {"os": "windows", "version": version},
            "materials": {
                "videos": [self._minimal_video_material()],
                "audios": [self._minimal_audio_material()],
                "texts": [self._minimal_text_style()],
                "effects": [self._minimal_effect()],
                "transitions": [self._minimal_transition()],
            },
            "tracks": [
                self._video_track_with_clips(),
                self._audio_track_with_clips(),
                self._subtitle_track(),
            ],
            "color_adjustments": self._sample_color_lut(),
            "project_settings": self._project_settings(),
        }
        return draft

    def _minimal_video_material(self): return {"id": "mat_vid_1", "type": "video", "duration": 5000}
    def _minimal_audio_material(self): return {"id": "mat_aud_1", "type": "audio", "duration": 5000}
    def _minimal_text_style(self): return {"id": "mat_txt_1", "font": "Microsoft YaHei", "size": 48, "color": "#FFFFFF"}
    def _minimal_effect(self): return {"id": "mat_eff_1", "type": "blur", "intensity": 0.5}
    def _minimal_transition(self): return {"id": "mat_tr_1", "type": "smooth_cut", "duration_ms": 500}

    def _video_track_with_clips(self) -> dict:
        return {
            "id": "track_video_main", "type": "video",
            "clips": [{
                "id": "clip_001", "file_id": "material_video_1",
                "start_time": 0, "end_time": 5000, "speed": 1.0, "volume": 1.0,
                "transform": {"x": 0, "y": 0, "scale_x": 1.0, "scale_y": 1.0, "rotation": 0, "opacity": 1.0},
            }],
        }

    def _audio_track_with_clips(self) -> dict:
        return {
            "id": "track_audio_main", "type": "audio",
            "clips": [{"id": "clip_a01", "file_id": "material_audio_1", "start_time": 0, "end_time": 5000, "volume": 1.0}],
        }

    def _subtitle_track(self) -> dict:
        return {
            "id": "track_subtitle", "type": "text",
            "clips": [{"id": "sub_001", "text": "示例字幕", "start_time": 0, "end_time": 2000,
                        "style": {"font": "Microsoft YaHei", "size": 36}}],
        }

    def _sample_color_lut(self) -> dict:
        return {"temperature": 5500, "tint": 0, "exposure": 0, "contrast": 0, "saturation": 0}

    def _project_settings(self) -> dict:
        return {"resolution": "1920x1080", "fps": 30, "duration_ms": 5000}


class DraftStructureDiff:
    """JSON 结构深度对比引擎"""

    def __init__(self, baseline_draft: dict, new_draft: dict):
        self.baseline = baseline_draft
        self.new = new_draft

    def compute_diff(self) -> dict:
        dd = DeepDiff(self.baseline, self.new, ignore_order=True, verbose_level=2)
        return self._categorize_changes(dd)

    def _categorize_changes(self, diff_result) -> dict:
        changes = {
            "new_fields": [], "removed_fields": [],
            "type_changes": [], "enum_changes": [], "structure_changes": [],
        }
        for item in diff_result.get("dictionary_item_added", []):
            changes["new_fields"].append({"path": str(item.path), "new_value": item.t2})
        for item in diff_result.get("dictionary_item_removed", []):
            changes["removed_fields"].append({"path": str(item.path), "old_value": item.t1})
        for item in diff_result.get("type_changes", []):
            changes["type_changes"].append({"path": str(item.path), "old_type": type(item.t1).__name__, "new_type": type(item.t2).__name__})
        return changes


class MappingTableUpdater:
    """自动维护 version_map.yaml 并生成适配器补丁"""

    def __init__(self, version_map_path: str = "config/version_mapping.yaml"):
        self.path = version_map_path
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.mapping = self._load()

    def _load(self) -> dict:
        if os.path.exists(self.path):
            with open(self.path) as f:
                return yaml.safe_load(f) or {}
        return {"versions": {}}

    def update_from_diff(self, from_version: str, to_version: str, changes: dict) -> str:
        entry = {
            "from_version": from_version, "to_version": to_version,
            "updated": datetime.now(timezone.utc).isoformat(),
            "field_mappings": {}, "removed_fields": [], "default_values": {},
        }
        for f in changes.get("new_fields", []):
            entry["field_mappings"][f["path"]] = {"action": "add", "default": f.get("new_value")}
        for f in changes.get("removed_fields", []):
            entry["removed_fields"].append(f["path"])
        self.mapping["versions"][to_version] = entry
        with open(self.path, "w") as f:
            yaml.dump(self.mapping, f, default_flow_style=False, allow_unicode=True)
        return self._generate_adapter(entry)

    def _generate_adapter(self, entry: dict) -> str:
        return f"""# Auto-generated adapter for v{entry['to_version']}
# Generated: {entry['updated']}
class VersionAdapter_{entry['to_version'].replace('.', '_')}:
    def apply(self, draft: dict) -> dict:
        # Apply {len(entry['field_mappings'])} mappings
        return draft
"""


generator = DraftSampleGenerator()
diff_engine = DraftStructureDiff
updater = MappingTableUpdater()
