import { apiPing } from "../api";

declare global {
  interface Window {
    /** Injected by the desktop shell (pywebview); absent in a plain browser. */
    pywebview?: { api?: { set_running?: (running: boolean, title: string, message: string, quit: string, cancel: string) => unknown } };
  }
}

export const PING_INTERVAL_MS = 30_000;

function askBeforeClosing(e: BeforeUnloadEvent): void {
  e.preventDefault();
  e.returnValue = "";
}

/** Tells the desktop shell whether a search is running (it then asks before closing the window,
 *  with `quit`/`cancel` as the button labels where the system allows it);
 *  the browser's own "leave this page?" prompt covers the browser build. */
export function setRunningFlag(running: boolean, title: string, message: string,
                               quit = "", cancel = ""): void {
  try {
    void Promise.resolve(window.pywebview?.api?.set_running?.(running, title, message, quit, cancel)).catch(() => undefined);
  } catch {
    /* the shell is closing or not ready: the browser prompt still applies */
  }
  if (running) window.addEventListener("beforeunload", askBeforeClosing);
  else window.removeEventListener("beforeunload", askBeforeClosing);
}

/** Tells the server the page is still open, now and every 30 s; returns a stop function. */
export function startPinging(): () => void {
  const ping = () => void apiPing().catch(() => undefined);
  ping();
  const id = setInterval(ping, PING_INTERVAL_MS);
  return () => clearInterval(id);
}
