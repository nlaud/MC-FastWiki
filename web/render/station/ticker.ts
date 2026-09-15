export const TICK_INTERVAL_MS = 1200;

type TickListener = (tick: number) => void;

let tickCount = 0;
let intervalId: ReturnType<typeof setInterval> | null = null;
const listeners = new Set<TickListener>();

/**
 * Whether the shared cycle may advance.
 *
 * `prefers-reduced-motion` used to stop it, and that was the wrong call. The
 * cycle is not decoration: it is the only thing on screen that says a torch
 * takes coal *or* charcoal, and that a plank slot accepts any of twelve woods.
 * Freezing it does not reduce motion so much as delete the information, and
 * Windows sets that preference whenever "Show animations" is off -- which is
 * how a feature that works reports as simply not working.
 *
 * What the preference does still get is the static path: every cycling slot
 * carries the full alternative list on its `title` and is focusable, so the
 * same facts are reachable without waiting for the animation.
 *
 * An unfocused window still holds. That gate is about not moving things in the
 * corner of the reader's eye while they are reading a different window, which
 * costs them nothing.
 */
function shouldTick(): boolean {
  if (typeof window === "undefined") {
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
