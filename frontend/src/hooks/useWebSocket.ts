import { useEffect, useRef, useCallback } from 'react';

export function useWebSocket(path: string) {
  const ws = useRef<WebSocket | null>(null);

  useEffect(() => {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws.current = new WebSocket(`${protocol}//${location.host}${path}`);

    ws.current.onopen = () => console.log('WS connected');
    ws.current.onclose = () => console.log('WS disconnected');

    return () => ws.current?.close();
  }, [path]);

  const send = useCallback((data: any) => {
    ws.current?.send(JSON.stringify(data));
  }, []);

  return { send, ws: ws.current };
}
