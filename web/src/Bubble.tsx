import { useState, useRef, useEffect } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { usePetStore } from './store';
import { sendUserMsg } from './useChatSocket';

export default function Bubble() {
  const open = usePetStore((s) => s.bubbleOpen);
  const close = usePetStore((s) => s.closeBubble);
  const messages = usePetStore((s) => s.messages);
  const pushMessage = usePetStore((s) => s.pushMessage);
  const connected = usePetStore((s) => s.connected);

  const [draft, setDraft] = useState('');
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (listRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight;
    }
  }, [messages, open]);

  const send = () => {
    const text = draft.trim();
    if (!text) return;
    pushMessage({ role: 'user', text });
    setDraft('');
    const ok = sendUserMsg(text);
    if (!ok) {
      pushMessage({
        role: 'cat',
        text: '（连不上后端，先检查 uvicorn 是不是在 :8000 跑着？）',
      });
    }
  };

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          initial={{ opacity: 0, y: 12, scale: 0.96 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: 12, scale: 0.96 }}
          transition={{ duration: 0.18 }}
          style={{
            position: 'fixed',
            right: 760, // clear ActionPanel (320) + cat (400) on the right
            bottom: 40,
            width: 320,
            height: 420,
            background: 'rgba(255,255,255,0.96)',
            backdropFilter: 'blur(6px)',
            borderRadius: 16,
            boxShadow: '0 12px 32px rgba(0,0,0,0.18)',
            display: 'flex',
            flexDirection: 'column',
            overflow: 'hidden',
            zIndex: 9998,
            fontFamily:
              "system-ui, -apple-system, 'PingFang SC', 'Helvetica Neue', sans-serif",
          }}
        >
          {/* header */}
          <div
            style={{
              padding: '10px 14px',
              borderBottom: '1px solid #eee',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              fontSize: 14,
              fontWeight: 600,
              color: '#333',
            }}
          >
            <span>喵喵助手</span>
            <button
              onClick={close}
              style={{
                background: 'transparent',
                border: 'none',
                cursor: 'pointer',
                fontSize: 18,
                color: '#888',
                lineHeight: 1,
              }}
              aria-label="关闭"
            >
              ×
            </button>
          </div>

          {/* messages */}
          <div
            ref={listRef}
            style={{
              flex: 1,
              padding: 12,
              overflowY: 'auto',
              display: 'flex',
              flexDirection: 'column',
              gap: 8,
              fontSize: 14,
            }}
          >
            {messages.length === 0 && (
              <div style={{ color: '#aaa', textAlign: 'center', marginTop: 40 }}>
                和猫咪说点什么吧～
              </div>
            )}
            {messages.map((m, i) => (
              <div
                key={i}
                style={{
                  alignSelf: m.role === 'user' ? 'flex-end' : 'flex-start',
                  maxWidth: '78%',
                  padding: '8px 12px',
                  borderRadius: 12,
                  background: m.role === 'user' ? '#4f8cff' : '#f1f1f3',
                  color: m.role === 'user' ? '#fff' : '#222',
                  whiteSpace: 'pre-wrap',
                  wordBreak: 'break-word',
                }}
              >
                {m.text}
              </div>
            ))}
          </div>

          {/* input */}
          <div
            style={{
              padding: 10,
              borderTop: '1px solid #eee',
              display: 'flex',
              gap: 8,
            }}
          >
            <input
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  send();
                }
              }}
              placeholder="说点什么..."
              style={{
                flex: 1,
                padding: '8px 10px',
                fontSize: 14,
                border: '1px solid #ddd',
                borderRadius: 8,
                outline: 'none',
              }}
            />
            <button
              onClick={send}
              style={{
                padding: '0 14px',
                fontSize: 14,
                background: '#4f8cff',
                color: '#fff',
                border: 'none',
                borderRadius: 8,
                cursor: 'pointer',
              }}
            >
              发送
            </button>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
