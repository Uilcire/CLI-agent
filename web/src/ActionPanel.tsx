import { useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { usePetStore, type ActionEntry } from './store';

const PANEL_WIDTH = 320;

function formatTime(ts: number): string {
  const d = new Date(ts);
  return `${d.getHours().toString().padStart(2, '0')}:${d
    .getMinutes()
    .toString()
    .padStart(2, '0')}:${d.getSeconds().toString().padStart(2, '0')}`;
}

function truncate(s: string, n: number): string {
  if (s.length <= n) return s;
  return s.slice(0, n) + '…';
}

function summarize(value: unknown, max = 80): string {
  if (value == null) return '';
  if (typeof value === 'string') return truncate(value, max);
  try {
    return truncate(JSON.stringify(value), max);
  } catch {
    return String(value);
  }
}

function statusDot(status: string): { color: string; label: string } {
  switch (status) {
    case 'pending':
      return { color: '#f59e0b', label: '运行中' };
    case 'done':
    case 'ok':
      return { color: '#10b981', label: '完成' };
    case 'error':
      return { color: '#ef4444', label: '错误' };
    default:
      return { color: '#9ca3af', label: status };
  }
}

function ToolBlock({ entry }: { entry: Extract<ActionEntry, { kind: 'tool' }> }) {
  const dot = statusDot(entry.status);
  return (
    <div
      style={{
        background: '#fff',
        border: '1px solid #e5e7eb',
        borderRadius: 10,
        padding: 10,
        boxShadow: '0 1px 2px rgba(0,0,0,0.04)',
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: 6,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span
            style={{
              fontSize: 10,
              fontWeight: 700,
              padding: '2px 6px',
              borderRadius: 4,
              background: '#eef2ff',
              color: '#4338ca',
              letterSpacing: 0.5,
            }}
          >
            TOOL
          </span>
          <span style={{ fontSize: 13, fontWeight: 600, color: '#111827' }}>
            {entry.name}
          </span>
        </div>
        <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span
            style={{
              width: 8,
              height: 8,
              borderRadius: '50%',
              background: dot.color,
              display: 'inline-block',
            }}
          />
          <span style={{ fontSize: 11, color: '#6b7280' }}>{formatTime(entry.ts)}</span>
        </span>
      </div>
      {entry.args !== undefined && (
        <div style={{ fontSize: 12, color: '#374151', marginBottom: 4 }}>
          <span style={{ color: '#9ca3af' }}>args: </span>
          <code style={{ fontSize: 11 }}>{summarize(entry.args)}</code>
        </div>
      )}
      {entry.result !== undefined && (
        <div style={{ fontSize: 12, color: '#374151' }}>
          <span style={{ color: '#9ca3af' }}>→ </span>
          <code style={{ fontSize: 11 }}>{summarize(entry.result, 120)}</code>
        </div>
      )}
    </div>
  );
}

function CuratorBlock({
  entry,
}: {
  entry: Extract<ActionEntry, { kind: 'curator' }>;
}) {
  const dot = statusDot(entry.status);
  return (
    <div
      style={{
        background: '#fffbeb',
        border: '1px solid #fde68a',
        borderRadius: 10,
        padding: 10,
        boxShadow: '0 1px 2px rgba(0,0,0,0.04)',
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: 6,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span
            style={{
              fontSize: 10,
              fontWeight: 700,
              padding: '2px 6px',
              borderRadius: 4,
              background: '#fde68a',
              color: '#92400e',
              letterSpacing: 0.5,
            }}
          >
            MEMORY
          </span>
        </div>
        <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span
            style={{
              width: 8,
              height: 8,
              borderRadius: '50%',
              background: dot.color,
              display: 'inline-block',
            }}
          />
          <span style={{ fontSize: 11, color: '#6b7280' }}>{formatTime(entry.ts)}</span>
        </span>
      </div>
      <div style={{ fontSize: 12, color: '#1f2937', marginBottom: 4, lineHeight: 1.4 }}>
        {entry.note}
      </div>
      {entry.status === 'done' && entry.files && entry.files.length > 0 && (
        <div style={{ fontSize: 11, color: '#6b7280' }}>
          → {entry.files.map((f) => f.split('/').pop()).join(', ')}
        </div>
      )}
      {entry.status === 'error' && entry.message && (
        <div style={{ fontSize: 11, color: '#b91c1c' }}>{entry.message}</div>
      )}
    </div>
  );
}

export default function ActionPanel() {
  const actions = usePetStore((s) => s.actions);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [actions]);

  return (
    <div
      style={{
        position: 'fixed',
        right: 0,
        top: 0,
        width: PANEL_WIDTH,
        height: '100vh',
        background: 'rgba(248, 250, 252, 0.94)',
        backdropFilter: 'blur(8px)',
        borderLeft: '1px solid #e5e7eb',
        display: 'flex',
        flexDirection: 'column',
        zIndex: 9997,
        fontFamily:
          "system-ui, -apple-system, 'PingFang SC', 'Helvetica Neue', sans-serif",
      }}
    >
      <div
        style={{
          padding: '14px 16px',
          borderBottom: '1px solid #e5e7eb',
          fontSize: 13,
          fontWeight: 600,
          color: '#374151',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
        }}
      >
        <span>动作日志</span>
        <span style={{ fontSize: 11, color: '#9ca3af', fontWeight: 400 }}>
          {actions.length} 条
        </span>
      </div>

      <div
        ref={scrollRef}
        style={{
          flex: 1,
          overflowY: 'auto',
          padding: 12,
          display: 'flex',
          flexDirection: 'column',
          gap: 8,
        }}
      >
        {actions.length === 0 && (
          <div
            style={{
              color: '#9ca3af',
              fontSize: 12,
              textAlign: 'center',
              marginTop: 60,
              lineHeight: 1.6,
            }}
          >
            暂无动作。
            <br />
            工具调用和记忆写入会显示在这里。
          </div>
        )}
        <AnimatePresence initial={false}>
          {actions.map((a) => (
            <motion.div
              key={a.kind + a.id}
              initial={{ opacity: 0, x: 16 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: 16 }}
              transition={{ duration: 0.18 }}
            >
              {a.kind === 'tool' ? (
                <ToolBlock entry={a} />
              ) : (
                <CuratorBlock entry={a} />
              )}
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
    </div>
  );
}

export { PANEL_WIDTH };
