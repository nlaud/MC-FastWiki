export const TICK_INTERVAL_MS = 1200;

type TickListener = (tick: number) => void;

let tickCount = 0;
let intervalId: ReturnType<typeof setInterval> | null = null;
const listeners = new Set<TickListener>();

/**
 * Whether the shared cycle may advance.
 *
 * When `prefers-reduced-motion: reduce` is set, the automatic ticker halts to
 * satisfy WCAG 2.2.2 (Pause, Stop, Hide). The information remains accessible
 * through a static path: multi-member slots carry an accent marker, announce
 * their tag, alternative count, and current member via `aria-label`, allow
 * stepping through alternatives on demand via keyboard (Left/Right) or mouse
 * (next button), and open the full member list on activation.
 *
 * An unfocused window also holds. That gate is about not moving things in the
 * corner of the reader's eye while they are reading a different window.
 */
export function shouldTick(): boolean {
  if (typeof window === "undefined") {
    return false;
  }
  if (
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  ) {
    return false;
  }
  if (typeof document !== "undefined" && typeof document.hasFocus === "function") {
    if (!document.hasFocus()) {
      return false;
    }
  }
  return true;
}

function onInterval(): void {
  if (!shouldTick()) {
    return;
  }
  tickCount++;
  for (const listener of listeners) {
    listener(tickCount);
  }
}

function start(): void {
  if (intervalId === null && typeof window !== "undefined") {
    intervalId = setInterval(onInterval, TICK_INTERVAL_MS);
  }
}

function stop(): void {
  if (intervalId !== null) {
    clearInterval(intervalId);
    intervalId = null;
  }
}

/**
 * Subscribes a callback to the shared ticker.
 * The callback is invoked on each tick with the current tick count.
 * Returns an unsubscribe function.
 */
export function subscribeTicker(listener: TickListener): () => void {
  listeners.add(listener);
  if (listeners.size === 1) {
    start();
  }
  return () => {
    listeners.delete(listener);
    if (listeners.size === 0) {
      stop();
    }
  };
}

/** For tests: advance ticker by one tick and notify all listeners. */
export function advanceTickerForTesting(): void {
  tickCount++;
  for (const listener of listeners) {
    listener(tickCount);
  }
}

/** For tests: reset tick count and clear listeners. */
export function resetTickerForTesting(): void {
  tickCount = 0;
  stop();
  listeners.clear();
}

/** Returns the current tick count. */
export function getTickCount(): number {
  return tickCount;
}
