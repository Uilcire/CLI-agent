import { useEffect, useRef } from 'react';
import { usePetStore, type CatState } from './store';

type ServerEvent =
  | { type: 'state'; state: CatState }
  | { type: 'token'; text: string }
  | { type: 'tool_call'; id?: string; name: string; args?: unknown }
  | { type: 'tool_result'; id?: string; name: string; result?: unknown }
  | { type: 'curator_call'; id: string; note: string }
  | {
      type: 'curator_result';
      id: string;
      status: 'ok' | 'error';
      files?: string[];
      message?: string;
    }
  | { type: 'done' }
  | { type: 'error'; message: string };

const WS_URL =
  (location.protocol === 'https:' ? 'wss://' : 'ws://') +
  location.host +
  '/ws/chat';

export function useChatSocket() {
  const wsRef = useRef<WebSocket | null>(null);
  const setConnected = usePetStore((s) => s.setConnected);
  const setCatState = usePetStore((s) => s.setCatState);
  const appendCatToken = usePetStore((s) => s.appendCatToken);
  const endCatStream = usePetStore((s) => s.endCatStream);
  const addToolCall = usePetStore((s) => s.addToolCall);
  const resolveTool = usePetStore((s) => s.resolveTool);
  const addCuratorCall = usePetStore((s) => s.addCuratorCall);
  const resolveCurator = usePetStore((s) => s.resolveCurator);

  useEffect(() => {
    let cancelled = false;
    let reconnectTimer: number | null = null;

    const connect = () => {
      if (cancelled) return;
      const ws = new WebSocket(WS_URL);
      wsRef.current = ws;

      ws.onopen = () => {
        activeWs = ws;
        setConnected(true);
      };

      ws.onclose = () => {
        if (activeWs === ws) activeWs = null;
        setConnected(false);
        wsRef.current = null;
        if (!cancelled) {
          reconnectTimer = window.setTimeout(connect, 1500);
        }
      };

      ws.onerror = () => ws.close();

      ws.onmessage = (e) => {
        let evt: ServerEvent;
        try {
          evt = JSON.parse(e.data);
        } catch {
          return;
        }
        switch (evt.type) {
          case 'state':
            setCatState(evt.state);
            break;
          case 'token':
            appendCatToken(evt.text);
            break;
          case 'tool_call':
            addToolCall(evt.id ?? `tool-${Date.now()}`, evt.name, evt.args);
            break;
          case 'tool_result':
            resolveTool(evt.id ?? '', evt.result);
            break;
          case 'curator_call':
            addCuratorCall(evt.id, evt.note);
            break;
          case 'curator_result':
            resolveCurator(
              evt.id,
              evt.status === 'ok' ? 'done' : 'error',
              evt.files,
              evt.message,
            );
            break;
          case 'done':
            endCatStream();
            setCatState('idle');
            break;
          case 'error':
            appendCatToken(`\n[错误: ${evt.message}]`);
            endCatStream();
            setCatState('idle');
            break;
        }
      };
    };

    connect();
    return () => {
      cancelled = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      wsRef.current?.close();
    };
  }, [
    setConnected,
    setCatState,
    appendCatToken,
    endCatStream,
    addToolCall,
    resolveTool,
    addCuratorCall,
    resolveCurator,
  ]);

  return wsRef;
}

let activeWs: WebSocket | null = null;
export function sendUserMsg(text: string): boolean {
  if (!activeWs || activeWs.readyState !== WebSocket.OPEN) return false;
  usePetStore.getState().startCatStream();
  activeWs.send(JSON.stringify({ type: 'user_msg', text }));
  return true;
}
