import { create } from 'zustand';

export type CatState = 'idle' | 'thinking' | 'working' | 'memory' | 'sleeping';

export interface ChatMessage {
  role: 'user' | 'cat';
  text: string;
  streaming?: boolean;
}

export type ActionEntry =
  | {
      kind: 'tool';
      id: string;
      name: string;
      args?: unknown;
      result?: unknown;
      status: 'pending' | 'done';
      ts: number;
    }
  | {
      kind: 'curator';
      id: string;
      note: string;
      files?: string[];
      status: 'pending' | 'done' | 'error';
      message?: string;
      ts: number;
    };

interface PetStore {
  catState: CatState;
  bubbleOpen: boolean;
  messages: ChatMessage[];
  connected: boolean;
  actions: ActionEntry[];

  setCatState: (s: CatState) => void;
  setConnected: (c: boolean) => void;
  openBubble: () => void;
  closeBubble: () => void;
  toggleBubble: () => void;
  pushMessage: (m: ChatMessage) => void;
  startCatStream: () => void;
  appendCatToken: (text: string) => void;
  endCatStream: () => void;
  clearMessages: () => void;

  addToolCall: (id: string, name: string, args?: unknown) => void;
  resolveTool: (id: string, result?: unknown) => void;
  addCuratorCall: (id: string, note: string) => void;
  resolveCurator: (
    id: string,
    status: 'done' | 'error',
    files?: string[],
    message?: string,
  ) => void;
}

export const usePetStore = create<PetStore>((set) => ({
  catState: 'idle',
  bubbleOpen: false,
  messages: [],
  connected: false,
  actions: [],

  setCatState: (s) => set({ catState: s }),
  setConnected: (c) => set({ connected: c }),
  openBubble: () => set({ bubbleOpen: true }),
  closeBubble: () => set({ bubbleOpen: false }),
  toggleBubble: () => set((st) => ({ bubbleOpen: !st.bubbleOpen })),
  pushMessage: (m) => set((st) => ({ messages: [...st.messages, m] })),
  startCatStream: () =>
    set((st) => ({
      messages: [...st.messages, { role: 'cat', text: '', streaming: true }],
    })),
  appendCatToken: (text) =>
    set((st) => {
      const msgs = st.messages.slice();
      const last = msgs[msgs.length - 1];
      if (last && last.role === 'cat' && last.streaming) {
        msgs[msgs.length - 1] = { ...last, text: last.text + text };
      } else {
        msgs.push({ role: 'cat', text, streaming: true });
      }
      return { messages: msgs };
    }),
  endCatStream: () =>
    set((st) => {
      const msgs = st.messages.slice();
      const last = msgs[msgs.length - 1];
      if (last && last.role === 'cat' && last.streaming) {
        msgs[msgs.length - 1] = { ...last, streaming: false };
      }
      return { messages: msgs };
    }),
  clearMessages: () => set({ messages: [] }),

  addToolCall: (id, name, args) =>
    set((st) => ({
      actions: [
        ...st.actions,
        { kind: 'tool', id, name, args, status: 'pending', ts: Date.now() },
      ],
    })),
  resolveTool: (id, result) =>
    set((st) => {
      // Match the most recent pending tool entry with this id; tool_result events
      // don't always carry an id, so fall back to last pending tool.
      const idx = (() => {
        for (let i = st.actions.length - 1; i >= 0; i--) {
          const a = st.actions[i];
          if (a.kind === 'tool' && a.status === 'pending' && (a.id === id || !id)) {
            return i;
          }
        }
        return -1;
      })();
      if (idx === -1) return {};
      const next = st.actions.slice();
      const a = next[idx];
      if (a.kind === 'tool') {
        next[idx] = { ...a, status: 'done', result };
      }
      return { actions: next };
    }),
  addCuratorCall: (id, note) =>
    set((st) => ({
      actions: [
        ...st.actions,
        { kind: 'curator', id, note, status: 'pending', ts: Date.now() },
      ],
    })),
  resolveCurator: (id, status, files, message) =>
    set((st) => {
      const idx = st.actions.findIndex((a) => a.kind === 'curator' && a.id === id);
      if (idx === -1) return {};
      const next = st.actions.slice();
      const a = next[idx];
      if (a.kind === 'curator') {
        next[idx] = { ...a, status, files, message };
      }
      return { actions: next };
    }),
}));
