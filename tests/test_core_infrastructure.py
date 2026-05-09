"""
Integration Test — ContextBus + ArtifactStore + DAGExecutor
端到端验证三大核心模块协同工作
"""
import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.context_bus import ContextBus, EventType
from core.artifact_store import ArtifactStore
from core.dag_executor import DAGExecutor, DAGNode, DAGResult, NodeStatus


# ── 模拟 Agent 执行器 ──

async def scriptwriter_executor(node: DAGNode, artifacts: ArtifactStore):
    """模拟编剧 Agent"""
    await asyncio.sleep(0.01)
    prompt = node.input.get("prompt", "")
    return {
        "title": f"Test: {prompt[:30]}",
        "total_duration_sec": node.input.get("duration", 180),
        "scenes": [
            {"id": 1, "start_sec": 0, "end_sec": 30, "narration": "开场解说", "emotion": "neutral"},
            {"id": 2, "start_sec": 30, "end_sec": 60, "narration": "核心内容", "emotion": "excited"},
        ],
        "emotion_curve": [0.5, 0.8],
    }


async def bgm_executor(node: DAGNode, artifacts: ArtifactStore):
    """模拟 BGM Agent"""
    await asyncio.sleep(0.01)
    return {
        "track_name": "Cyberpunk Synth",
        "bpm": 120,
        "genre": "synthwave",
        "duration_sec": node.input.get("duration", 180),
    }


async def voiceover_executor(node: DAGNode, artifacts: ArtifactStore):
    """模拟配音 Agent — 读取编剧产出"""
    await asyncio.sleep(0.01)
    # 模拟从制品库读取上游产出
    script = node.input.get("script", {})
    return {
        "voice_id": "neutral_male",
        "segments": [{"start": 0, "end": 30, "text": "test"}],
        "audio_duration_sec": script.get("total_duration_sec", 180),
    }


async def qc_executor(node: DAGNode, artifacts: ArtifactStore):
    """模拟 QC Agent"""
    await asyncio.sleep(0.01)
    return {
        "verdict": "PASS",
        "fatal": 0,
        "major": 0,
        "minor": 0,
        "issues": [],
    }


# ── 测试 ──

async def test_context_bus_pubsub():
    """测试 ContextBus 发布/订阅"""
    print("TEST: ContextBus pub/sub...", end=" ")
    bus = ContextBus()
    await bus.connect()

    received_events = []

    async def handler(event):
        received_events.append(event)

    await bus.subscribe(EventType.NODE_COMPLETE, handler)
    await bus.publish(EventType.NODE_COMPLETE, {"node_id": "n1"}, "test_agent")
    await asyncio.sleep(0.1)  # wait for consume loop

    assert len(received_events) == 1, f"Expected 1 event, got {len(received_events)}"
    assert received_events[0].event_type == EventType.NODE_COMPLETE
    assert received_events[0].agent_id == "test_agent"
    assert received_events[0].payload["node_id"] == "n1"

    await bus.disconnect()
    print("PASSED ✅")


async def test_artifact_store_crud():
    """测试 ArtifactStore CRUD + 版本化"""
    print("TEST: ArtifactStore CRUD...", end=" ")
    store = ArtifactStore(base_dir="/tmp/quanquan_test_artifacts")

    # Put
    v1 = await store.put("proj_test", "script", {"title": "v1 script", "scenes": []})
    assert v1 == "v1", f"Expected v1, got {v1}"

    v2 = await store.put("proj_test", "script", {"title": "v2 script", "scenes": [{"id": 1}]})
    assert v2 == "v2", f"Expected v2, got {v2}"

    # Get latest
    data = await store.get("proj_test", "script")
    assert data["title"] == "v2 script", "Expected v2 data"

    # Get specific version
    data_v1 = await store.get("proj_test", "script", version="v1")
    assert data_v1["title"] == "v1 script", "Expected v1 data"

    # List versions
    versions = await store.list_versions("proj_test", "script")
    assert versions == ["v1", "v2"], f"Expected [v1, v2], got {versions}"

    # Cache hit
    data_cached = await store.get("proj_test", "script")
    assert data_cached["title"] == "v2 script", "Cache should return v2"

    # Cleanup
    await store.delete("proj_test")
    print("PASSED ✅")


async def test_dag_executor_basic():
    """测试 DAGExecutor 基本执行"""
    print("TEST: DAGExecutor basic DAG...", end=" ")
    bus = ContextBus()
    artifacts = ArtifactStore(base_dir="/tmp/quanquan_test_dag")
    executor = DAGExecutor(bus, artifacts)

    await bus.connect()

    # 注册 Agent
    executor.register_agent("Scriptwriter", scriptwriter_executor)
    executor.register_agent("BGM", bgm_executor)

    # DAG 定义：编剧 + BGM 并行（无依赖）
    dag = {
        "dag_id": "test_dag_001",
        "nodes": [
            {
                "node_id": "script_gen",
                "agent": "Scriptwriter",
                "depends_on": [],
                "task": "generate_script",
                "input": {"prompt": "赛博朋克科技解说", "duration": 180},
                "output_key": "script_v1",
                "timeout_seconds": 10,
            },
            {
                "node_id": "bgm_select",
                "agent": "BGM",
                "depends_on": [],
                "task": "select_bgm",
                "input": {"mood": "dark", "duration": 180},
                "output_key": "bgm_v1",
                "timeout_seconds": 10,
            },
        ],
    }

    result = await executor.execute(dag, "test_proj_001")

    assert isinstance(result, DAGResult)
    assert result.total_nodes == 2, f"Expected 2 nodes, got {result.total_nodes}"
    assert result.completed == 2, f"Expected 2 completed, got {result.completed}"
    assert result.failed == 0, f"Expected 0 failed, got {result.failed}"
    assert result.elapsed_sec > 0

    # 验证产出已存入制品库
    script = await artifacts.get("test_proj_001", "script_v1")
    assert script is not None, "Script artifact not found"
    assert script["title"].startswith("Test:")

    bgm = await artifacts.get("test_proj_001", "bgm_v1")
    assert bgm is not None, "BGM artifact not found"
    assert bgm["genre"] == "synthwave"

    await executor.cancel()
    await bus.disconnect()
    await artifacts.delete("test_proj_001")
    print("PASSED ✅")


async def test_dag_executor_sequential():
    """测试 DAGExecutor 顺序依赖执行"""
    print("TEST: DAGExecutor sequential DAG...", end=" ")
    bus = ContextBus()
    artifacts = ArtifactStore(base_dir="/tmp/quanquan_test_dag2")
    executor = DAGExecutor(bus, artifacts)

    await bus.connect()
    executor.register_agent("Scriptwriter", scriptwriter_executor)
    executor.register_agent("Voiceover", voiceover_executor)
    executor.register_agent("QC", qc_executor)

    # DAG: 编剧 → 配音 → QC（顺序依赖）
    dag = {
        "dag_id": "test_dag_seq",
        "nodes": [
            {
                "node_id": "script",
                "agent": "Scriptwriter",
                "depends_on": [],
                "input": {"prompt": "科技视频"},
                "output_key": "script",
            },
            {
                "node_id": "voice",
                "agent": "Voiceover",
                "depends_on": ["script"],
                "input": {"script": {"total_duration_sec": 180, "scenes": []}},
                "output_key": "voiceover",
            },
            {
                "node_id": "qc",
                "agent": "QC",
                "depends_on": ["script", "voice"],
                "input": {},
                "output_key": "qc_report",
            },
        ],
    }

    result = await executor.execute(dag, "test_seq")

    assert result.completed == 3, f"Expected 3 completed, got {result.completed}"
    assert result.failed == 0

    # 验证所有产出
    for key in ["script", "voiceover", "qc_report"]:
        data = await artifacts.get("test_seq", key)
        assert data is not None, f"Artifact '{key}' not found"

    await executor.cancel()
    await bus.disconnect()
    await artifacts.delete("test_seq")
    print("PASSED ✅")


async def test_dag_executor_mixed_parallel():
    """测试 DAGExecutor 混合并行+顺序"""
    print("TEST: DAGExecutor mixed parallel...", end=" ")
    bus = ContextBus()
    artifacts = ArtifactStore(base_dir="/tmp/quanquan_test_dag3")
    executor = DAGExecutor(bus, artifacts)

    await bus.connect()
    executor.register_agent("Scriptwriter", scriptwriter_executor)
    executor.register_agent("BGM", bgm_executor)
    executor.register_agent("Voiceover", voiceover_executor)

    # 编剧先跑，BGM和配音并行（都依赖编剧完成后）
    dag = {
        "dag_id": "test_mixed",
        "nodes": [
            {
                "node_id": "script",
                "agent": "Scriptwriter",
                "depends_on": [],
                "input": {"prompt": "测试"},
                "output_key": "script",
            },
            {
                "node_id": "bgm",
                "agent": "BGM",
                "depends_on": ["script"],
                "input": {"mood": "upbeat"},
                "output_key": "bgm",
            },
            {
                "node_id": "voice",
                "agent": "Voiceover",
                "depends_on": ["script"],
                "input": {"script": {}},
                "output_key": "voiceover",
            },
        ],
    }

    result = await executor.execute(dag, "test_mixed")

    assert result.completed == 3, f"Expected 3, got {result.completed}"
    assert result.elapsed_sec < 5, "Should be fast (< 5s)"

    await executor.cancel()
    await bus.disconnect()
    await artifacts.delete("test_mixed")
    print("PASSED ✅")


async def test_heartbeat():
    """测试心跳机制"""
    print("TEST: Heartbeat...", end=" ")
    bus = ContextBus()
    await bus.connect()

    await bus.heartbeat("agent_a")
    await asyncio.sleep(0.1)

    stale = bus.get_stale_agents()
    assert "agent_a" not in stale, "agent_a should not be stale yet"

    # 模拟旧心跳
    bus._heartbeats["agent_b"] = 0  # 远古时间戳
    stale = bus.get_stale_agents()
    assert "agent_b" in stale, "agent_b should be stale"

    await bus.disconnect()
    print("PASSED ✅")


async def main():
    print("=" * 60)
    print("  quanquan 核心模块集成测试")
    print("=" * 60)
    print()

    tests = [
        test_context_bus_pubsub,
        test_artifact_store_crud,
        test_heartbeat,
        test_dag_executor_basic,
        test_dag_executor_sequential,
        test_dag_executor_mixed_parallel,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            await test()
            passed += 1
        except Exception as e:
            print(f"FAILED ❌ — {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print()
    print("=" * 60)
    print(f"  Results: {passed} passed, {failed} failed")
    print("=" * 60)

    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
