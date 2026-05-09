export function LogPanel({ lines = [] }: { lines: string[] }) {
  return (
    <div>
      <h1 className="text-3xl font-bold mb-8">📋 实时日志</h1>
      <div className="card">
        <div className="font-mono text-xs leading-relaxed max-h-[600px] overflow-y-auto">
          {lines.length === 0 ? (
            <div className="text-center text-[#555570] py-8">等待日志...</div>
          ) : (
            lines.map((l, i) => (
              <div key={i} className="py-0.5 px-2 hover:bg-white/3 rounded">{l}</div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
