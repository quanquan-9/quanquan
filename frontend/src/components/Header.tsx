export function Header({ title, status }: { title: string; status: any }) {
  return (
    <div className="flex justify-between items-center mb-8">
      <h1 className="text-3xl font-bold">
        <span className="inline-block w-3 h-3 bg-green-500 rounded-full mr-3 animate-pulse shadow-[0_0_8px_#4ade80]" />
        {title}
      </h1>
      <div className="flex gap-4 text-sm text-[#8888aa]">
        <span>GPU {status?.gpu_utilization || 0}%</span>
        <span>活跃 {status?.active_projects || 0}</span>
      </div>
    </div>
  );
}
