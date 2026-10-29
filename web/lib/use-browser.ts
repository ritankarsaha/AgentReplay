"use client";

import { useSyncExternalStore } from "react";

const subscribe = () => () => {};

/** Browser-only values that are stable for the page's lifetime; the server snapshot is the SSR value. */
export const useOrigin = () => useSyncExternalStore(subscribe, () => window.location.origin, () => "");

export const useCanSpeak = () =>
  useSyncExternalStore(subscribe, () => "speechSynthesis" in window, () => false);
