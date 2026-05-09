"""
测试 TypedDict 类型 — core/types.py 的类型合约验证
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from core.types import (
    Scene, Script, Shot, Storyboard,
    VoiceSegment, Voiceover, BGMTrack,
    StylizationResult, QCReport, DeliveryPackage,
    ShotType, EmotionType, TransitionType,
)


class TestTypedDicts:
    """TypedDict 结构验证"""

    def test_scene(self):
        s: Scene = {
            "id": "s1",
            "title": "开场",
            "duration_sec": 10,
            "narration": "大家好",
            "visual_description": "黑屏淡入",
            "emotion": "激昂",
        }
        assert s["id"] == "s1"
        assert s["emotion"] == "激昂"

    def test_scene_with_transition(self):
        s: Scene = {
            "id": "s2",
            "title": "转场",
            "duration_sec": 5,
            "narration": "...",
            "visual_description": "淡出",
            "emotion": "舒缓",
            "transition": "fade",
        }
        assert s["transition"] == "fade"

    def test_script(self):
        script: Script = {
            "title": "AI改变世界",
            "total_duration_sec": 120,
            "scenes": [
                {"id": "s1", "title": "开场", "duration_sec": 10,
                 "narration": "Hello", "visual_description": "...", "emotion": "激昂"},
            ],
            "keywords": ["AI", "科技"],
            "style_tags": ["tech", "专业"],
        }
        assert script["title"] == "AI改变世界"
        assert len(script["scenes"]) == 1

    def test_shot(self):
        shot: Shot = {
            "id": "sh1",
            "scene_id": "s1",
            "type": "wide",
            "duration_sec": 3.5,
            "description": "远景城市",
        }
        assert shot["type"] == "wide"

    def test_storyboard(self):
        sb: Storyboard = {
            "project_id": "proj_001",
            "total_shots": 2,
            "shots": [
                {"id": "sh1", "scene_id": "s1", "type": "wide",
                 "duration_sec": 5.0, "description": "远景"},
            ],
            "transitions": [{"from": "sh1", "to": "sh2", "type": "cut"}],
        }
        assert sb["total_shots"] == 2

    def test_voice_segment(self):
        vs: VoiceSegment = {
            "scene_id": "s1",
            "text": "大家好欢迎收看",
            "duration_sec": 3.0,
        }
        assert vs["text"] == "大家好欢迎收看"

    def test_voiceover(self):
        vo: Voiceover = {
            "project_id": "proj_001",
            "voice_profile": "neutral_male_01",
            "segments": [
                {"scene_id": "s1", "text": "Hello", "duration_sec": 2.0},
            ],
            "audio_duration_sec": 2.0,
        }
        assert vo["voice_profile"] == "neutral_male_01"

    def test_bgm_track(self):
        bgm: BGMTrack = {
            "track_name": "Epic Cinematic",
            "bpm": 120,
            "genre": "orchestral",
            "duration_sec": 180,
            "mood": "epic",
        }
        assert bgm["bpm"] == 120

    def test_stylization_result(self):
        sr: StylizationResult = {
            "filter_applied": "cyberpunk",
            "consistency_score": 0.95,
            "color_palette": ["#ff00ff", "#00ffff"],
        }
        assert sr["filter_applied"] == "cyberpunk"

    def test_qc_report(self):
        qc: QCReport = {
            "fatal": 0,
            "major": 1,
            "minor": 3,
            "pass_count": 10,
            "verdict": "pass_with_warnings",
            "issues": [{"type": "audio_sync", "severity": "major", "detail": "..."}],
        }
        assert qc["verdict"] == "pass_with_warnings"

    def test_delivery_package(self):
        dp: DeliveryPackage = {
            "draft_format": "mp4",
            "video_duration_sec": 120,
            "director_notes": {"annotations": ["需要调色"]},
            "export_ready": True,
        }
        assert dp["export_ready"] is True


class TestLiterals:
    """枚举类型测试"""

    def test_shot_types_exist(self):
        assert "wide" in ShotType.__args__
        assert "close-up" in ShotType.__args__
        assert "aerial" in ShotType.__args__

    def test_emotion_types_exist(self):
        assert "激昂" in EmotionType.__args__
        assert "温暖" in EmotionType.__args__
        assert "紧张" in EmotionType.__args__

    def test_transition_types_exist(self):
        assert "硬切" in TransitionType.__args__
        assert "淡入" in TransitionType.__args__
        assert "溶解" in TransitionType.__args__
