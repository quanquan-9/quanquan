import { useState } from 'react';

export function CreateProject() {
  const [text, setText] = useState('');
  const [duration, setDuration] = useState(180);
  const [style, setStyle] = useState('auto');

  const handleCreate = async () => {
    await fetch('/api/v1/create', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, duration, style }),
    });
    setText('');
  };

  return (
    <div>
      <h1 className="text-3xl font-bold mb-8">✨ 创建新项目</h1>
      <div className="card">
        <div className="flex flex-col gap-4">
          <div>
            <label className="text-sm text-[#8888aa] block mb-2">视频主题</label>
            <textarea
              value={text}
              onChange={e => setText(e.target.value)}
              placeholder="例如：3分钟赛博朋克风科技解说视频..."
              className="w-full bg-[#1e1e30] border border-[#252540] rounded-lg p-3 text-[#e8e8f0] resize-y min-h-[100px] focus:outline-none focus:border-[#7c3aed] focus:ring-3 focus:ring-[#7c3aed]/10"
            />
          </div>
          <div className="flex gap-4">
            <div className="flex-1">
              <label className="text-sm text-[#8888aa] block mb-2">时长 (秒)</label>
              <input type="number" value={duration} onChange={e => setDuration(+e.target.value)}
                className="w-full bg-[#1e1e30] border border-[#252540] rounded-lg p-2 text-[#e8e8f0]" />
            </div>
            <div className="flex-1">
              <label className="text-sm text-[#8888aa] block mb-2">风格</label>
              <select value={style} onChange={e => setStyle(e.target.value)}
                className="w-full bg-[#1e1e30] border border-[#252540] rounded-lg p-2 text-[#e8e8f0]">
                <option value="auto">自动</option>
                <option value="cyberpunk">赛博朋克</option>
                <option value="ink_wash">水墨国风</option>
                <option value="modern">现代简约</option>
              </select>
            </div>
          </div>
          <button onClick={handleCreate} className="btn-primary self-start">
            🚀 启动创作
          </button>
        </div>
      </div>
    </div>
  );
}
