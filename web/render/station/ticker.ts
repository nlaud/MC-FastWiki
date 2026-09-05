export const TICK_INTERVAL_MS = 1200;

type TickListener = (tick: number) => void;

let tickCount = 0;
let intervalId: ReturnType<typeof setInterval> | null = null;
const listeners = new Set<TickListener>();

function shouldTick(): boolean {
  if (typeof window === "undefined") {
    return false;
  }
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    return false;
  }
  if (typeof document !== "undefined" && typeof document.hasFocus === "function") {
    // Only check hasFocus if defined and not running in headless test where document.hasFocus is mockable
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
