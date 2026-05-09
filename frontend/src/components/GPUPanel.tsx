import { useState } from 'react';

export function GPUPanel() {
  const [gpu, setGpu] = useState<any>({ name: 'NVIDIA GPU', utilization: 30, encoder: 'h264_nvenc' });

  return (
    <div>
      <h1 className="text-3xl font-bold mb-8">⚡ GPU 监控</h1>
      <div className="card mb-6">
        <div className="flex items-center gap-4 p-4 bg-[#1e1e30] rounded-lg">
          <div className="text-2xl">🖥️</div>
          <div className="flex-1">
            <div className="font-semibold">{gpu.name}</div>
            <div className="h-2 bg-[#252540] rounded-full mt-2 overflow-hidden">
              <div className="h-full bg-gradient-to-r from-[#7c3aed] to-[#22c55e] rounded-full"
                   style={{ width: `${gpu.utilization}%`, transition: 'width 0.5s' }} />
            </div>
          </div>
          <div className="text-sm text-[#8888aa]">{gpu.utilization}%</div>
        </div>
        <div className="mt-4 text-sm text-[#555570]">编码器: {gpu.encoder}</div>
      </div>
    </div>
  );
}
