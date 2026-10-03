import type { TUI } from "@earendil-works/pi-tui";

/** Repair terminal reflow even when a resize burst ends at its original size. */
export function watchTerminalResize(
  tui: Pick<TUI, "invalidate" | "requestRender">,
  source: { on(event: "resize", listener: () => void): unknown; off(event: "resize", listener: () => void): unknown } = process.stdout,
  delay = 120,
  signals: { on(event: "SIGWINCH", listener: () => void): unknown; off(event: "SIGWINCH", listener: () => void): unknown } | undefined = source === process.stdout ? process : undefined,
): () => void {
  let timer: ReturnType<typeof setTimeout> | undefined;
  let disposed = false;
  const resize = () => {
    clearTimeout(timer);
    timer = setTimeout(() => {
      timer = undefined;
      if (disposed) return;
      // Pi handles ordinary dimension changes immediately. This final forced
      // frame also covers A -> B -> A changes coalesced into one render, and
      // terminal reflow that finishes after its initial SIGWINCH notification.
      tui.invalidate();
      tui.requestRender(true);
    }, delay);
    timer.unref();
  };
  source.on("resize", resize);
  // Node emits stdout's resize only if ioctl reports changed dimensions. The
  // kernel can coalesce a rapid A -> B -> A into one SIGWINCH reporting A, so
  // listen to the raw signal as well. Both events share the same debounce.
  signals?.on("SIGWINCH", resize);
  return () => {
    disposed = true;
    clearTimeout(timer);
    source.off("resize", resize);
    signals?.off("SIGWINCH", resize);
  };
}
