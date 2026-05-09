export function Sidebar({ tab, onTabChange, status }: any) {
  const items = [
    { key: 'overview', label: '📊 总览' },
    { key: 'projects', label: '📁 项目' },
    { key: 'agents', label: '🤖 智能体' },
    { key: 'gpu', label: '⚡ GPU' },
    { key: 'logs', label: '📋 日志' },
    { key: 'create', label: '✨ 创建' },
  ];

  return (
    <aside className="w-64 bg-[#12121a] border-r border-[#252540] p-6 flex flex-col gap-2">
      <div className="flex items-center gap-3 mb-8">
        <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-[#7c3aed] to-[#ec4899] flex items-center justify-center text-xl">🎬</div>
        <div className="text-xl font-bold bg-gradient-to-r from-[#a78bfa] to-[#ec4899] bg-clip-text text-transparent">quanquan</div>
      </div>
      {items.map(i => (
        <button
          key={i.key}
          onClick={() => onTabChange(i.key)}
          className={`flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-all ${
            tab === i.key
              ? 'bg-[#7c3aed]/15 text-[#a78bfa]'
              : 'text-[#8888aa] hover:bg-[#1e1e30] hover:text-[#e8e8f0]'
          }`}
        >
          {i.label}
        </button>
      ))}
      <div className="mt-auto pt-4 border-t border-[#252540] text-xs text-[#555570]">
        v2.0 · {status?.active_projects || 0} 活跃
      </div>
    </aside>
  );
}
