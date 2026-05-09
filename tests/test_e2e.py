"""
quanquan 全链路独立测试 — 8 Agent 协作完整演示
无需服务器，直接运行
"""
import asyncio
import sys
sys.path.insert(0, '/data/quanquan')

from core.director import DirectorAgent, DirectorState
from core.context_bus import context_bus
from core.artifact_store import artifact_store
from agents.scriptwriter import scriptwriter
from agents.storyboard import storyboard
from agents.all_agents import voiceover, bgm, qc, styling, delivery


async def test_full_pipeline():
    print("=" * 60)
    print("🎬 quanquan 全链路演示 — 8 Agent 协作")
    print("=" * 60)

    # 1. 编剧生成脚本
    print("\n[1/7] 📝 编剧 Agent — 生成脚本...")
    script = await scriptwriter.generate(
        prompt="AI改变世界的三种方式",
        duration_sec=120,
        style_tags=["科技", "专业"]
    )
    print(f"   ✅ 脚本生成: {script.get('title', 'N/A')}")
    print(f"   场景数: {len(script.get('scenes', []))}")
    print(f"   情感标签: {script.get('keywords', [])}")

    # 2. 分镜
    print("\n[2/7] 🎥 分镜 Agent — 镜头规划...")
    board = await storyboard.plan(script, ["科技", "专业"])
    print(f"   ✅ 镜头数: {board.get('total_shots', 0)}")

    # 3. BGM (并行)
    print("\n[3/7] 🎵 BGM Agent — 音乐匹配...")
    music = await bgm.select(script, "tech", 120)
    print(f"   ✅ BPM: {music.get('bpm')} | 风格: {music.get('genre')}")

    # 4. 配音
    print("\n[4/7] 🎙️ 配音 Agent — 语音合成...")
    voice = await voiceover.generate(script, "neutral_male_01", board)
    print(f"   ✅ 时长: {voice.get('audio_duration_sec', 0):.0f}s")

    # 5. 调色
    print("\n[5/7] 🎨 调色 Agent — 风格化...")
    style = await styling.apply(board, "cyberpunk")
    print(f"   ✅ 滤镜: {style.get('filter_applied')} | 一致度: {style.get('consistency_score', 0):.2f}")

    # 6. QC
    print("\n[6/7] 🔍 QC Agent — 质量检查...")
    report = await qc.inspect({
        "script": script, "voiceover": voice, "stylization": style
    })
    print(f"   ✅ 致命:{report['fatal']} 严重:{report['major']} 轻微:{report['minor']} 通过:{report['pass']}")

    # 7. 交付
    print("\n[7/7] 📦 交付 Agent — 组装草稿...")
    final = await delivery.assemble({
        "script": script, "storyboard": board, "bgm": music,
        "voiceover": voice, "stylization": style, "qc_report": report,
    })
    print(f"   ✅ 格式: {final.get('draft_format')} | 时长: {final.get('video_duration_sec')}s")
    print(f"   导演笔记: {len(final.get('director_notes', {}).get('ai_annotations', []))} 条AI注释")

    # 统计
    print("\n" + "=" * 60)
    print("📊 全链路统计")
    print("=" * 60)
    print(f"  总场景: {len(script.get('scenes', []))}")
    print(f"  总镜头: {board.get('total_shots', 0)}")
    print(f"  配音段: {len(voice.get('segments', []))}")
    print(f"  BGM: {music.get('track_name', 'N/A')} ({music.get('bpm', '?')}BPM)")
    print(f"  调色: {style.get('filter_applied', 'N/A')} (一致度 {style.get('consistency_score', 0):.0%})")
    print(f"  QC: {report['verdict']} (致命{report['fatal']} 严重{report['major']} 轻微{report['minor']})")
    print(f"  交付: {final.get('draft_format', 'N/A')} | 导出就绪: {final.get('export_ready')}")
    print(f"\n  🎉 8 Agent 协作完成！")

    return {
        "script": script,
        "storyboard": board,
        "bgm": music,
        "voiceover": voice,
        "styling": style,
        "qc": report,
        "delivery": final,
    }


if __name__ == "__main__":
    asyncio.run(test_full_pipeline())
