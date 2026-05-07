import CatPet from './CatPet';
import Bubble from './Bubble';
import ActionPanel from './ActionPanel';
import { useChatSocket } from './useChatSocket';
import { usePetStore } from './store';

export default function App() {
  useChatSocket();
  const connected = usePetStore((s) => s.connected);

  return (
    <>
      <div
        style={{
          position: 'fixed',
          inset: 0,
          background:
            'linear-gradient(135deg, #fdfbfb 0%, #ebedee 100%)',
          color: '#888',
          fontFamily:
            "system-ui, -apple-system, 'PingFang SC', 'Helvetica Neue', sans-serif",
          padding: 32,
          pointerEvents: 'none',
        }}
      >
        <h1 style={{ margin: 0, fontSize: 22, color: '#444' }}>CLI-Agent · 桌宠</h1>
        <p style={{ marginTop: 8, fontSize: 14 }}>
          拖动猫咪到任意位置，点击它打开对话气泡。
          <span
            style={{
              marginLeft: 12,
              fontSize: 12,
              padding: '2px 8px',
              borderRadius: 8,
              background: connected ? '#dcfce7' : '#fee2e2',
              color: connected ? '#166534' : '#991b1b',
            }}
          >
            {connected ? '● 已连接' : '○ 未连接'}
          </span>
        </p>
      </div>
      <CatPet />
      <Bubble />
      <ActionPanel />
    </>
  );
}
