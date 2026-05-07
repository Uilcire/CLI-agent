import { useRef, useState } from 'react';
import { motion, useMotionValue } from 'framer-motion';
import Cat from './Cat';
import { usePetStore } from './store';

const SIZE = 400;
const CLICK_THRESHOLD = 5; // px total movement => treat as click
const PANEL_GUTTER = 340; // ActionPanel (320) + small gap

export default function CatPet() {
  const toggleBubble = usePetStore((s) => s.toggleBubble);

  // Initial position: bottom-right, but offset left to clear the action panel.
  const initialX =
    typeof window !== 'undefined'
      ? window.innerWidth - SIZE - PANEL_GUTTER
      : 0;
  const initialY =
    typeof window !== 'undefined' ? window.innerHeight - SIZE - 24 : 0;

  const x = useMotionValue(initialX);
  const y = useMotionValue(initialY);

  const downPos = useRef<{ x: number; y: number } | null>(null);
  const movedTotal = useRef(0);
  const [grabbing, setGrabbing] = useState(false);

  const onPointerDown = (e: React.PointerEvent) => {
    downPos.current = { x: e.clientX, y: e.clientY };
    movedTotal.current = 0;
  };

  const onPointerMove = (e: React.PointerEvent) => {
    if (!downPos.current) return;
    const dx = e.clientX - downPos.current.x;
    const dy = e.clientY - downPos.current.y;
    movedTotal.current = Math.max(movedTotal.current, Math.hypot(dx, dy));
  };

  const onPointerUp = () => {
    if (movedTotal.current < CLICK_THRESHOLD) {
      // It was a click, not a drag.
      toggleBubble();
    }
    downPos.current = null;
    movedTotal.current = 0;
  };

  return (
    <motion.div
      drag
      dragMomentum={false}
      dragElastic={0}
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        x,
        y,
        width: SIZE,
        height: SIZE,
        cursor: grabbing ? 'grabbing' : 'grab',
        zIndex: 9999,
        userSelect: 'none',
        touchAction: 'none',
      }}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onDragStart={() => setGrabbing(true)}
      onDragEnd={() => setGrabbing(false)}
    >
      <div
        style={{
          width: '100%',
          height: '100%',
          pointerEvents: 'none', // Canvas shouldn't capture pointer events; drag/click on outer div
        }}
      >
        <Cat />
      </div>
    </motion.div>
  );
}
