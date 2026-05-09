const AGENTS = [
  { name: '导演', emoji: '🎬', state: 'monitoring' },
  { name: '编剧', emoji: '✍️', state: 'idle' },
  { name: '分镜', emoji: '🎞️', state: 'idle' },
  { name: '配音', emoji: '🎙️', state: 'idle' },
  { name: 'BGM', emoji: '🎵', state: 'idle' },
  { name: '调色', emoji: '🎨', state: 'idle' },
  { name: '审核', emoji: '🔍', state: 'idle' },
  { name: '交付', emoji: '📦', state: 'idle' },
  { name: '字幕', emoji: '💬', state: 'idle' },
];

export function AgentPanel({ full = false }: { full?: boolean }) {
  return (
    <div className="card mb-6">
      <h3 className="text-lg font-semibold mb-4">🤖 智能体集群 ({AGENTS.length})</h3>
      <div className={`grid ${full ? 'grid-cols-3' : 'grid-cols-3 md:grid-cols-5'} gap-3`}>
        {AGENTS.map(a => (
          <div key={a.name} className="bg-[#1e1e30] rounded-lg p-3 text-center hover:bg-[#7c3aed]/10 transition-all">
            <div className="text-2xl mb-1">{a.emoji}</div>
            <div className="text-sm font-semibold">{a.name}</div>
            <div className={`text-xs ${a.state === 'monitoring' ? 'text-green-400' : 'text-[#555570]'}`}>
              {a.state === 'monitoring' ? '● 运行中' : '○ 待命'}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
