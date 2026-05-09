"""
quanquan 完整测试套件 (Comprehensive Test Suite)
"""

import pytest
import asyncio
import os
import json
import sys
import importlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ═══════════ 测试工具 ═══════════

class MockContextBus:
    """Mock 上下文总线"""
    def __init__(self):
        self.events = []
        self.subscribers = {}

    async def connect(self):
        pass

    async def disconnect(self):
        pass

    async def publish(self, event_type: str, payload: dict):
        self.events.append((event_type, payload))

    async def wait_for(self, event_type: str, filter=None, timeout=None):
        return type('Event', (), {'type': event_type, 'payload': {}})()

    async def subscribe(self, event_type: str, handler):
        self.subscribers.setdefault(event_type, []).append(handler)


class MockArtifactStore:
    """Mock 制品存储"""
    def __init__(self):
        self.artifacts = {}

    async def put(self, project_id: str, key: str, value):
        self.artifacts[f"{project_id}/{key}"] = value
        return f"mock://{project_id}/{key}"

    async def get(self, project_id: str, key: str):
        return self.artifacts.get(f"{project_id}/{key}")


# ═══════════ 导演 Agent 测试 ═══════════

class TestDirectorAgent:
    """导演 Agent 测试"""

    def test_initial_state(self):
        from core.director import DirectorState
        assert DirectorState.IDLE.value == "idle"

    def test_state_transitions(self):
        from core.director import DirectorState
        states = list(DirectorState)
        assert len(states) == 11  # 11 状态机
        assert DirectorState.IDLE in states
        assert DirectorState.ANALYZING in states
        assert DirectorState.PLANNING in states
        assert DirectorState.MONITORING in states
        assert DirectorState.REFLECTING in states


# ═══════════ 视频引擎测试 ═══════════

class TestChunkedProcessor:
    """分段处理器测试"""

    def test_metadata_parsing(self):
        from core.chunked_processor import VideoMetadata
        meta = VideoMetadata(
            path="/test/video.mp4", width=3840, height=2160,
            duration_sec=600, fps=30, total_frames=18000,
            file_size_bytes=5 * 1024**3,
        )
        assert meta.is_4k
        assert meta.is_long is False  # 10 mins < 1h
        assert meta.resolution_label == "4K"

    def test_should_chunk(self):
        from core.chunked_processor import ChunkedProcessor, VideoMetadata

        cp = ChunkedProcessor()

        # 4K 视频应该分段
        meta_4k = VideoMetadata(
            path="test.mp4", width=3840, height=2160,
            duration_sec=120, fps=30, total_frames=3600,
            file_size_bytes=500 * 1024**2,
        )
        assert cp.should_chunk(meta_4k)

        # 1080p 短视频不分段
        meta_small = VideoMetadata(
            path="test.mp4", width=1920, height=1080,
            duration_sec=30, fps=30, total_frames=900,
            file_size_bytes=50 * 1024**2,
        )
        assert not cp.should_chunk(meta_small)


class TestGPUEncoder:
    """GPU 编码器测试"""

    def test_encoder_config(self):
        from core.gpu_encoder import EncodeConfig, EncoderPreset
        config = EncodeConfig(
            codec="h264",
            preset=EncoderPreset.FAST,
            crf=20,
            width=1920,
            height=1080,
        )
        assert config.codec == "h264"
        assert config.crf == 20

    def test_codec_map(self):
        from core.gpu_encoder import GPUDetector
        # 测试软件编码器回退
        encoder = asyncio.run(GPUDetector.get_best_encoder([], "h264"))
        assert encoder == "libx264"
        encoder = asyncio.run(GPUDetector.get_best_encoder([], "h265"))
        assert encoder == "libx265"


# ═══════════ 多平台测试 ═══════════

class TestMultiPlatform:
    """多平台输出测试"""

    def test_platform_configs(self):
        from core.multi_platform import Platform, PLATFORM_CONFIGS
        assert Platform.DOUYIN in PLATFORM_CONFIGS
        assert PLATFORM_CONFIGS[Platform.DOUYIN].aspect_ratio == (9, 16)
        assert PLATFORM_CONFIGS[Platform.YOUTUBE].aspect_ratio == (16, 9)
        assert PLATFORM_CONFIGS[Platform.YOUTUBE].max_resolution == (3840, 2160)

    def test_smart_crop(self):
        from core.multi_platform import SmartCropper
        cropper = SmartCropper()

        # 16:9 → 9:16 裁剪
        x, y, w, h = cropper.calculate_crop_region(1920, 1080, (9, 16))
        assert w == 607  # 1080 * 9/16 = 607.5 → 607
        assert h == 1080

        # 9:16 → 16:9
        x2, y2, w2, h2 = cropper.calculate_crop_region(1080, 1920, (16, 9))
        assert h2 == 607


# ═══════════ 高光提取测试 ═══════════

class TestHighlightDetector:
    """高光提取测试"""

    def test_emotion_peak_detection(self):
        from core.highlight_detector import EmotionPeakDetector
        detector = EmotionPeakDetector()

        emotion_curve = [
            {"time_sec": 0, "emotion": "中立", "intensity": 0.3},
            {"time_sec": 1, "emotion": "激昂", "intensity": 0.9},
            {"time_sec": 2, "emotion": "激昂", "intensity": 0.95},
            {"time_sec": 3, "emotion": "紧张", "intensity": 0.7},
            {"time_sec": 4, "emotion": "舒缓", "intensity": 0.2},
        ]

        highlights = asyncio.run(detector.detect(emotion_curve, top_k=2))
        assert len(highlights) > 0
        assert highlights[0].peak_type == "emotion"


# ═══════════ 配置中心测试 ═══════════

class TestConfigManager:
    """配置管理器测试"""

    def test_singleton(self):
        from core.config_manager import ConfigManager, config
        cm1 = ConfigManager()
        cm2 = ConfigManager()
        assert cm1 is cm2

    def test_default_values(self):
        from core.config_manager import ConfigManager
        cm = ConfigManager()
        assert cm.get("director.max_replan_attempts") == 3
        assert cm.get("llm.provider") == "deepseek"
        assert cm.get("nonexistent.key", "default") == "default"

    def test_set_and_get(self):
        from core.config_manager import ConfigManager
        cm = ConfigManager()
        cm.set("test.key", "value123")
        assert cm.get("test.key") == "value123"


# ═══════════ 冷启动测试 ═══════════

class TestColdStart:
    """冷启动模板测试"""

    def test_template_count(self):
        from core.cold_start import COLD_START_TEMPLATES
        assert len(COLD_START_TEMPLATES) >= 6  # dynamic: 模板会增长

    def test_tag_matching(self):
        from core.cold_start import ColdStartMatcher
        # 科技标签应匹配科技解说模板
        template = ColdStartMatcher.match(["科技", "AI", "技术"])
        assert "tech" in template.name.lower() or "科技" in template.name

        # 美食标签应匹配 Vlog 模板
        template2 = ColdStartMatcher.match(["美食", "探店", "日常"])
        assert "vlog" in template2.name.lower() or "生活" in template2.name


# ═══════════ 字幕翻译测试 ═══════════

class TestSubtitleTranslator:
    """字幕翻译测试"""

    def test_parse_srt(self):
        from core.subtitle_translator import SubtitleTranslator
        translator = SubtitleTranslator()
        srt = "1\n00:00:00,000 --> 00:00:02,000\nHello World\n\n2\n00:00:02,000 --> 00:00:04,000\nTest\n"
        entries = translator._parse_srt(srt)
        assert len(entries) == 2
        assert entries[0]["text"] == "Hello World"

    def test_glossary_application(self):
        from core.subtitle_translator import SubtitleTranslator
        translator = SubtitleTranslator()
        glossary = {"AI": "人工智能"}
        result = translator._apply_glossary("AI is powerful", glossary)
        assert "人工智能" in result


# ═══════════ 通知系统测试 ═══════════

class TestNotification:
    """通知系统测试"""

    def test_notification_config(self):
        from core.notification import NotificationConfig, NotificationLevel
        config = NotificationConfig(
            email_enabled=True,
            email_to=["test@test.com"],
            webhook_enabled=True,
            webhook_url="https://hooks.example.com",
            webhook_type="feishu",
        )
        assert config.email_enabled
        assert len(config.email_to) == 1

    def test_level_values(self):
        from core.notification import NotificationLevel
        assert NotificationLevel.INFO.value == "info"
        assert NotificationLevel.CRITICAL.value == "critical"


# ═══════════ 插件系统测试 ═══════════

class TestPluginSystem:
    """插件系统测试"""

    def test_plugin_registration(self):
        from core.plugin_system import PluginManager, BasePlugin, PluginInfo, PluginHook

        class TestPlugin(BasePlugin):
            info = PluginInfo(
                name="test", version="1.0",
                hooks=[PluginHook.ON_STARTUP],
            )
            async def on_startup(self):
                pass

        manager = PluginManager(plugin_dir="/tmp/plugins")
        plugin = TestPlugin()
        manager.register(plugin)
        assert "test" in manager._plugins
        assert len(manager.list_plugins()) == 1

    def test_plugin_hooks(self):
        from core.plugin_system import PluginManager, PluginHook
        manager = PluginManager()
        assert PluginHook.ON_PROJECT_CREATE in manager._hook_handlers


# ═══════════ 端到端集成测试 ═══════════

class TestE2E:
    """端到端集成测试"""

    def test_full_pipeline_imports(self):
        """验证所有核心模块可导入"""
        modules = [
            'core.director', 'core.chunked_processor', 'core.gpu_encoder',
            'core.multi_platform', 'core.highlight_detector', 'core.super_resolution',
            'core.digital_human', 'core.subtitle_translator', 'core.notification',
            'core.video_to_gif', 'core.config_manager', 'core.vector_store',
            'core.cold_start', 'core.director_notes', 'core.post_export_inspector',
            'core.proxy_editor', 'core.voice_to_video', 'core.plugin_system',
            'core.database_schema',
            'agents.scriptwriter', 'agents.storyboard', 'agents.voiceover',
            'agents.bgm', 'agents.stylization', 'agents.qc', 'agents.delivery',
            'agents.subtitle', 'agents.memory', 'agents.feedback',
            'adapters.ffmpeg_inspector', 'adapters.jianying', 'adapters.material_library',
            'adapters.music_library', 'adapters.thumbnail_generator', 'adapters.version_diff',
        ]
        for module_name in modules:
            try:
                importlib.import_module(module_name)
            except ImportError as e:
                pytest.fail(f"Failed to import {module_name}: {e}")
