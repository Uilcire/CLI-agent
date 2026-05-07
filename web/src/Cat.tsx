import { useEffect, useRef, useState } from 'react';
import { usePetStore, type CatState } from './store';

// Frame counts per state — matches what Pixellab generated.
const FRAMES: Record<CatState, number> = {
  idle: 8,
  thinking: 8,
  working: 6,
  memory: 12,
  sleeping: 10,
};

const FPS: Record<CatState, number> = {
  idle: 8,
  thinking: 6,
  working: 12,
  memory: 9,
  sleeping: 5,
};

type Direction = 'south' | 'east' | 'west';

function spritePath(state: CatState, dir: Direction, frame: number) {
  const f = String(frame).padStart(3, '0');
  return `/cat-sprites/animations/${state}/${dir}/frame_${f}.png`;
}

// Preload every frame so transitions don't show a missing-image flash.
const preloadCache = new Set<string>();
function preload(src: string) {
  if (preloadCache.has(src)) return;
  preloadCache.add(src);
  const img = new Image();
  img.src = src;
}
(['idle', 'thinking', 'working', 'memory', 'sleeping'] as CatState[]).forEach(
  (state) => {
    (['south', 'east', 'west'] as Direction[]).forEach((dir) => {
      for (let i = 0; i < FRAMES[state]; i++) {
        preload(spritePath(state, dir, i));
      }
    });
  },
);

export default function Cat() {
  const catState = usePetStore((s) => s.catState);
  const [frame, setFrame] = useState(0);
  const [direction, setDirection] = useState<Direction>('south');
  const lastTickRef = useRef(performance.now());
  const lastDirSwitchRef = useRef(performance.now());
  const rafRef = useRef<number | null>(null);

  // Reset frame when state changes so animation starts clean.
  useEffect(() => {
    setFrame(0);
    lastTickRef.current = performance.now();
    // Working state alternates east/west; everything else faces user.
    if (catState !== 'working') {
      setDirection('south');
    } else {
      setDirection('east');
      lastDirSwitchRef.current = performance.now();
    }
  }, [catState]);

  useEffect(() => {
    const tick = (now: number) => {
      const fps = FPS[catState];
      const frameDuration = 1000 / fps;
      if (now - lastTickRef.current >= frameDuration) {
        setFrame((f) => (f + 1) % FRAMES[catState]);
        lastTickRef.current = now;
      }
      // Working: flip east/west every ~2.5s for visual liveliness.
      if (catState === 'working' && now - lastDirSwitchRef.current > 2500) {
        setDirection((d) => (d === 'east' ? 'west' : 'east'));
        lastDirSwitchRef.current = now;
      }
      rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);
    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
  }, [catState]);

  return (
    <img
      src={spritePath(catState, direction, frame)}
      alt={`cat ${catState}`}
      draggable={false}
      style={{
        width: '100%',
        height: '100%',
        objectFit: 'contain',
        imageRendering: 'pixelated',
        userSelect: 'none',
        pointerEvents: 'none',
      }}
    />
  );
}
