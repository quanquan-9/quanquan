export function ProjectPanel({ projects = [], full = false }: any) {
  const display = full ? projects : projects.slice(0, 5);

  return (
    <div className="card mb-6">
      <div className="flex justify-between items-center mb-4">
        <h3 className="text-lg font-semibold">📁 项目列表</h3>
      </div>
      {display.length === 0 ? (
        <div className="text-center text-[#555570] py-8">暂无项目</div>
      ) : (
        <div className="flex flex-col gap-2">
          {display.map((p: any, i: number) => (
            <div key={i} className="flex items-center gap-3 p-3 bg-[#1e1e30] rounded-lg hover:bg-[#7c3aed]/8 transition-all">
              <div className={`w-9 h-9 rounded-lg flex items-center justify-center text-lg ${
                p.status === 'active' ? 'bg-green-500/15 text-green-400' :
                p.status === 'queued' ? 'bg-yellow-500/15 text-yellow-400' :
                'bg-purple-500/15 text-purple-400'
              }`}>
                {p.status === 'active' ? '▶' : p.status === 'queued' ? '⏳' : '✓'}
              </div>
              <div className="flex-1 min-w-0">
                <div className="font-semibold text-sm truncate">{p.name || p.project_id}</div>
                <div className="text-xs text-[#8888aa]">{p.duration || '--'}</div>
              </div>
              <span className={`text-xs px-2 py-1 rounded-full font-semibold ${
                p.status === 'active' ? 'bg-green-500/15 text-green-400' :
                p.status === 'queued' ? 'bg-yellow-500/15 text-yellow-400' :
                'bg-purple-500/15 text-purple-400'
              }`}>
                {p.status === 'active' ? '处理中' : p.status === 'queued' ? '排队' : '完成'}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
