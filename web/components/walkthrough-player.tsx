"use client";

import { Pause, Play, SkipBack, SkipForward, Volume2, VolumeX } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { SimulatedBadge } from "@/components/simulated-badge";
import { Button } from "@/components/ui/button";
import { Tag } from "@/components/ui/tag";
import type { Beat, BoxAnnotation } from "@/lib/control-plane";
import { useCanSpeak } from "@/lib/use-browser";

const STEP_MS = 7000;
const SIMULATED_KINDS: Record<string, string> = { negotiation: "simulated seller" };

export function WalkthroughPlayer({
  beats,
  annotations,
  blobBase,
  note,
}: {
  beats: Beat[];
  annotations: BoxAnnotation[];
  blobBase: string;
  note?: string | null;
}) {
  const [index, setIndex] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speak, setSpeak] = useState(false);
  const spoken = useRef(-1);
  const canSpeak = useCanSpeak();

  const beat = beats[index];
  const last = beats.length - 1;

  useEffect(() => {
    if (!playing) return;
    const id = setTimeout(() => {
      if (index >= last) setPlaying(false);
      else setIndex(index + 1);
    }, STEP_MS);
    return () => clearTimeout(id);
  }, [playing, index, last]);

  useEffect(() => {
    if (!speak || !canSpeak || !beat) return;
    if (spoken.current === index) return;
    spoken.current = index;
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(new SpeechSynthesisUtterance(beat.caption));
    return () => window.speechSynthesis.cancel();
  }, [speak, canSpeak, index, beat]);

  if (!beat) return <p className="text-sm text-muted-foreground">No walkthrough was generated for this incident.</p>;

  const annotation = beat.screenshot_sha256 ? annotations.find((a) => a.sha256 === beat.screenshot_sha256) : undefined;

  const go = (next: number) => {
    setPlaying(false);
    spoken.current = -1;
    setIndex(Math.min(Math.max(next, 0), last));
  };

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-[14rem_1fr]">
      <ol className="flex flex-row gap-1.5 overflow-x-auto lg:flex-col" aria-label="Walkthrough steps">
        {beats.map((b, i) => (
          <li key={i}>
            <button
              type="button"
              onClick={() => go(i)}
              aria-current={i === index}
              className={`flex w-full items-center gap-2 rounded-md border px-2.5 py-1.5 text-left text-xs transition-colors ${
                i === index ? "border-foreground/30 bg-muted text-foreground" : "border-transparent text-muted-foreground hover:bg-muted/50"
              }`}
            >
              <span className="font-mono">{i + 1}</span>
              <span className="whitespace-nowrap lg:whitespace-normal">{b.title}</span>
            </button>
          </li>
        ))}
      </ol>

      <div className="flex min-w-0 flex-col gap-4">
        <div className="flex flex-wrap items-center gap-2">
          <Tag tone={b2tone(beat.kind)}>{beat.kind.replace("_", " ")}</Tag>
          {SIMULATED_KINDS[beat.kind] && <SimulatedBadge label={SIMULATED_KINDS[beat.kind]} />}
          <span className="text-sm font-medium text-foreground">{beat.title}</span>
        </div>

        <p className="min-h-16 text-base leading-relaxed text-foreground" aria-live="polite">{beat.caption}</p>
        <span className="text-xs text-muted-foreground">
          caption by {beat.caption_source === "template" ? "template (facts only)" : beat.caption_source}
        </span>

        {beat.screenshot_sha256 && (
          <figure className="flex flex-col gap-2">
            <div className="relative w-full max-w-xl overflow-hidden rounded-md border border-border">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={`${blobBase}/${beat.screenshot_sha256}`} alt="Booking confirmation page" className="block w-full" />
              {annotation?.boxes.map((box, i) => (
                <div
                  key={i}
                  className="pointer-events-none absolute rounded-sm border-2 border-status-failure bg-status-failure/15"
                  style={{
                    left: `${(box.x1 / box.w) * 100}%`,
                    top: `${(box.y1 / box.h) * 100}%`,
                    width: `${((box.x2 - box.x1) / box.w) * 100}%`,
                    height: `${((box.y2 - box.y1) / box.h) * 100}%`,
                  }}
                />
              ))}
            </div>
            <figcaption className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
              <SimulatedBadge label="sandbox airline" />
              {annotation && annotation.boxes.length > 0 ? (
                <span>
                  Red box: {annotation.model} segmentation, prompt “{annotation.prompt}”. It marks the booked departure.
                </span>
              ) : (
                <span>No segmentation overlay for this screenshot.</span>
              )}
            </figcaption>
          </figure>
        )}

        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm" variant="outline" onClick={() => go(index - 1)} disabled={index === 0} aria-label="Previous step">
            <SkipBack />
          </Button>
          <Button size="sm" onClick={() => (index >= last ? go(0) : setPlaying(!playing))}>
            {playing ? <Pause /> : <Play />}
            {playing ? "Pause" : index >= last ? "Replay" : "Play"}
          </Button>
          <Button size="sm" variant="outline" onClick={() => go(index + 1)} disabled={index === last} aria-label="Next step">
            <SkipForward />
          </Button>
          {canSpeak && (
            <Button size="sm" variant="ghost" onClick={() => { spoken.current = -1; setSpeak(!speak); }} aria-pressed={speak}>
              {speak ? <Volume2 /> : <VolumeX />}
              {speak ? "Voice on" : "Voice off"}
            </Button>
          )}
          <span className="ml-auto font-mono text-xs text-muted-foreground">{index + 1} / {beats.length}</span>
        </div>
        {note && <p className="text-xs text-muted-foreground">{note}</p>}
      </div>
    </div>
  );
}

function b2tone(kind: string) {
  return kind === "halt" || kind === "purchase" ? "bad" : kind === "intent" ? "info" : "warn";
}
