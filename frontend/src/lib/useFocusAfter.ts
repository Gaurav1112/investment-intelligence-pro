import { useCallback, useEffect, useRef, useState } from "react";

const MAX_RENDERS = 5;

/**
 * Move focus to an element once it exists (WCAG 2.4.3). Call the setter with element ids from a handler whose control is
 * about to be removed (Select, Remove, Change instrument). After each render the hook focuses the first id that is in
 * the DOM, so focus never falls back to <body>. Nothing happens while the triggering control is still in the DOM (a URL
 * change can commit a render or two later; if the control stays, focus was never lost). The hook gives up after a few
 * renders so a late element cannot steal focus.
 */
export function useFocusAfter(): (...ids: string[]) => void {
  const [want, setWant] = useState<string[] | null>(null);
  const tries = useRef(0);
  const trigger = useRef<Element | null>(null);
  useEffect(() => {
    if (want === null) return;
    tries.current += 1;
    // While the triggering control is still on screen the change has not committed yet (and focus is not lost): wait,
    // so that the first id is judged against the NEW content rather than falling through to a fallback too early.
    const pending = trigger.current !== null && trigger.current.isConnected;
    const el = pending ? undefined : want.map((id) => document.getElementById(id)).find((x) => x !== null);
    if (el) el.focus();
    if (el || tries.current >= MAX_RENDERS) setWant(null);
  });
  return useCallback((...ids: string[]) => {
    tries.current = 0;
    trigger.current = document.activeElement;
    setWant(ids);
  }, []);
}
