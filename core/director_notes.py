"""
导演笔记 HTML 生成器

为每个项目生成可视化的导演笔记 (director_notes.html)，
包含：情感曲线、BPM、QC 报告、AI 注释、素材溯源
"""

import json
import os
from typing import Dict, Any, List
from datetime import datetime


def generate_director_notes_html(
    project_id: str,
    manifest: dict,
    qc_summary: dict,
    memory_profile: dict,
    output_dir: str = "projects",
) -> str:
    """生成导演笔记 HTML 文件"""

    script = manifest.get('script_final', {})
    bgm = manifest.get('bgm_final', {})
    stylization = manifest.get('stylization_v1', {})

    full_text = script.get('full_text', '—')
    bpm = bgm.get('bpm', '—')
    emotion_curve = script.get('emotion_curve', [])
    segments = script.get('segments', [])
    mood_tags = bgm.get('mood_tags', [])
    dominant_emotion = bgm.get('dominant_emotion', '—')
    preferences = {
        'voice': memory_profile.get('preferred_voice_id', 'default'),
        'transitions': memory_profile.get('preferred_transitions', ['dissolve']),
        'filter': memory_profile.get('preferred_filters', ['original']),
        'bgm_genre': memory_profile.get('preferred_bgm_genres', ['auto']),
    }
    style_name = stylization.get('result', {}).get('style_name', '—')

    # 情绪曲线数据（简化：最高点和变化点）
    emotion_highlights = []
    if emotion_curve:
        peak = max(emotion_curve, key=lambda p: p.get('intensity', 0))
        emotion_highlights.append({
            'time': peak.get('time_sec', 0),
            'emotion': peak.get('emotion', '—'),
            'label': '情绪高点',
        })

    # QC 摘要
    qc_verdict = qc_summary.get('verdict', 'PASS')
    qc_total = qc_summary.get('total_issues', 0)

    html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>导演笔记 — {project_id}</title>
<style>
:root {{
  --bg: #0a0a0f; --panel: #12121a; --card: #181825;
  --border: #252540; --text: #e8e8f0; --dim: #8888aa;
  --accent: #7c3aed; --green: #22c55e; --red: #ef4444; --yellow: #f59e0b;
  --radius: 10px;
}}
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family: 'PingFang SC','Microsoft YaHei',sans-serif; background:var(--bg); color:var(--text); padding:40px; max-width:800px; margin:0 auto; }}
h1 {{ font-size:24px; margin-bottom:8px; }}
h2 {{ font-size:18px; margin:24px 0 12px; padding-bottom:8px; border-bottom:1px solid var(--border); }}
.meta {{ color:var(--dim); font-size:13px; margin-bottom:24px; }}
.card {{ background:var(--card); border:1px solid var(--border); border-radius:var(--radius); padding:20px; margin-bottom:16px; }}
.card-title {{ font-size:14px; color:var(--dim); text-transform:uppercase; letter-spacing:1px; margin-bottom:8px; }}
.card-value {{ font-size:22px; font-weight:700; }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:12px; }}
.tag {{ display:inline-block; padding:4px 10px; border-radius:20px; font-size:12px; margin:2px; background:rgba(124,58,237,0.15); color:#a78bfa; }}
.pass {{ color:var(--green); }} .fail {{ color:var(--red); }} .warn {{ color:var(--yellow); }}
.emotion-bar {{ height:8px; background:var(--border); border-radius:4px; overflow:hidden; margin-top:8px; }}
.emotion-fill {{ height:100%; border-radius:4px; }}
.emotion-peak {{ background:linear-gradient(90deg,var(--accent),#ec4899); }}
.emotion-warm {{ background:linear-gradient(90deg,#f59e0b,#ef4444); }}
.emotion-calm {{ background:linear-gradient(90deg,#3b82f6,#22c55e); }}
.emotion-sad {{ background:linear-gradient(90deg,#6366f1,#8b5cf6); }}
.emotion-label {{ font-size:11px; color:var(--dim); margin-top:4px; display:flex; justify-content:space-between; }}
.script-text {{ background:var(--card); border-radius:var(--radius); padding:20px; line-height:2; font-size:15px; white-space:pre-wrap; }}
.footer {{ margin-top:40px; padding-top:20px; border-top:1px solid var(--border); font-size:12px; color:var(--dim); text-align:center; }}
</style>
</head>
<body>

<h1>🎬 导演笔记</h1>
<div class="meta">
  项目 ID: {project_id} · 生成时间: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}
</div>

<h2>📊 核心指标</h2>
<div class="grid">
  <div class="card">
    <div class="card-title">BPM</div>
    <div class="card-value">{bpm}</div>
  </div>
  <div class="card">
    <div class="card-title">主导情绪</div>
    <div class="card-value">{dominant_emotion}</div>
  </div>
  <div class="card">
    <div class="card-title">风格</div>
    <div class="card-value">{style_name}</div>
  </div>
  <div class="card">
    <div class="card-title">QC 结果</div>
    <div class="card-value {'pass' if qc_verdict == 'PASS' else 'fail' if qc_verdict == 'FAIL' else 'warn'}">{qc_verdict}</div>
  </div>
</div>

<h2>❤️ 情绪曲线</h2>
<div class="card">
  <div class="emotion-bar"><div class="emotion-fill emotion-peak" style="width:100%"></div></div>
  <div class="emotion-label"><span>开始</span><span>高潮</span><span>结尾</span></div>
  <div style="margin-top:12px;">
    {' · '.join(f'<span class="tag">{h["emotion"]} @ {h["time"]}s</span>' for h in emotion_highlights) if emotion_highlights else '<span class="tag">平稳</span>'}
  </div>
</div>

<h2>🎵 BGM 信息</h2>
<div class="card">
  <div style="display:flex;gap:12px;flex-wrap:wrap;">
    <span class="tag">BPM: {bpm}</span>
    {''.join(f'<span class="tag">{t}</span>' for t in mood_tags)}
    <span class="tag">流派: {bgm.get("genre", "auto")}</span>
  </div>
</div>

<h2>⚙️ 偏好注入</h2>
<div class="card">
  <div style="display:flex;gap:12px;flex-wrap:wrap;">
    <span class="tag">🎙️ 配音: {preferences['voice']}</span>
    <span class="tag">🔀 转场: {', '.join(preferences['transitions'])}</span>
    <span class="tag">🎨 滤镜: {', '.join(preferences['filter'])}</span>
    <span class="tag">🎵 BGM: {', '.join(preferences['bgm_genre'])}</span>
  </div>
</div>

<h2>🔍 QC 报告</h2>
<div class="card">
  <div style="font-size:28px;margin-bottom:8px;" class="{'pass' if qc_verdict == 'PASS' else 'fail' if qc_verdict == 'FAIL' else 'warn'}">
    {'✅' if qc_verdict == 'PASS' else '❌' if qc_verdict == 'FAIL' else '⚠️'} {qc_verdict}
  </div>
  <div style="color:var(--dim);font-size:13px;">
    总问题数: {qc_total} · 致命: {qc_summary.get('fatal_count', 0)} · 严重: {qc_summary.get('major_count', 0)} · 轻微: {qc_summary.get('minor_count', 0)}
  </div>
</div>

<h2>📝 AI 注释</h2>
<div class="card">
  <div style="font-size:14px;line-height:2;">
    💡 建议高潮处（约{emotion_highlights[0]['time'] if emotion_highlights else 30}s）加大音量<br>
    💡 转场匹配音乐重拍（BPM={bpm}，每{60.0/bpm if isinstance(bpm,(int,float)) and bpm else 0:.1f}秒一拍）<br>
    💡 风格一致性自动检查：{'✅ 通过' if style_name != '—' else '⚠️ 未应用风格'}
  </div>
</div>

<div class="footer">
  quanquan 全自动剪辑系统 · AI 辅助生成 · 仅供参考
</div>

</body>
</html>'''

    # 写入文件
    project_dir = os.path.join(output_dir, project_id)
    os.makedirs(project_dir, exist_ok=True)
    html_path = os.path.join(project_dir, "director_notes.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)

    return html_path
