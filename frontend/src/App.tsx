import React, { useState, useEffect, useRef } from 'react';
import { useWebSocket } from './hooks/useWebSocket';
import { ProjectPanel } from './components/ProjectPanel';
import { AgentPanel } from './components/AgentPanel';
import { GPUPanel } from './components/GPUPanel';
import { LogPanel } from './components/LogPanel';
import { CreateProject } from './components/CreateProject';
import { Header } from './components/Header';
import { Sidebar } from './components/Sidebar';

type Tab = 'overview' | 'projects' | 'agents' | 'gpu' | 'logs' | 'create';

export default function App() {
  const [tab, setTab] = useState<Tab>('overview');
  const [projects, setProjects] = useState<any[]>([]);
  const [directorStatus, setDirectorStatus] = useState<any>({});
  const [logLines, setLogLines] = useState<string[]>([]);

  const { send, lastMessage } = useWebSocket('/ws');

  useEffect(() => {
    fetch('/api/v1/director/status')
      .then(r => r.json())
      .then(setDirectorStatus);

    fetch('/api/v1/director/projects')
      .then(r => r.json())
      .then(setProjects);

    const interval = setInterval(() => {
      fetch('/api/v1/director/status')
        .then(r => r.json())
        .then(setDirectorStatus);
    }, 5000);

    return () => clearInterval(interval);
  }, []);

  return (
    <div className="flex h-screen bg-[#0a0a0f] text-[#e8e8f0]">
      <Sidebar tab={tab} onTabChange={setTab} status={directorStatus} />
      <main className="flex-1 overflow-y-auto p-8">
        {tab === 'overview' && (
          <div>
            <Header title="导演控制台" status={directorStatus} />
            <ProjectPanel projects={projects} />
            <AgentPanel />
          </div>
        )}
        {tab === 'projects' && <ProjectPanel projects={projects} full />}
        {tab === 'agents' && <AgentPanel full />}
        {tab === 'gpu' && <GPUPanel />}
        {tab === 'logs' && <LogPanel lines={logLines} />}
        {tab === 'create' && <CreateProject />}
      </main>
    </div>
  );
}
