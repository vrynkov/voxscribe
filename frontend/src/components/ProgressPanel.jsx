import { useEffect, useState } from "react";
import { formatTime } from "../lib.js";

// These match the "stage" names the backend sends.
const STAGES = ["Preparing audio", "Transcribing speech", "Identifying speakers", "Building transcript"];

export default function ProgressPanel({ job, fileName, onCancel, engine }) {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    const t0 = Date.now();
    const id = setInterval(() => setElapsed((Date.now() - t0) / 1000), 1000);
    return () => clearInterval(id);
  }, []);

  const current = Math.max(0, STAGES.indexOf(job?.stage));
  const queued = !job || job.status === "queued";
  const pct = Math.round((job?.progress ?? 0) * 100);

  return (
    <section className="rounded-2xl border border-line bg-surface p-5 sm:p-8" aria-live="polite">
      <div className="flex items-baseline justify-between gap-4">
        <p className="min-w-0 truncate font-medium">{fileName}</p>
        <p className="tabular shrink-0 text-sm text-muted">{pct}% after {formatTime(elapsed)}</p>
      </div>

      <div className="mt-4 h-1.5 overflow-hidden rounded-full bg-line/60">
        <div className="h-full rounded-full bg-action transition-[width] duration-500" style={{ width: `${Math.max(pct, 3)}%` }} />
      </div>

      <ol className="mt-6 space-y-3">
        {STAGES.map((stage, i) => {
          const done = !queued && i < current;
          const active = !queued && i === current;
          return (
            <li key={stage} className={`flex items-center gap-3 text-sm ${done || active ? "text-ink" : "text-muted"}`}>
              <span
                aria-hidden
                className={`grid size-5 place-items-center rounded-full border text-[11px] ${
                  done ? "border-action bg-action text-action-ink" : active ? "border-action text-action" : "border-line"
                }`}
              >
                {done ? "✓" : i + 1}
              </span>
              {stage}
              {active && job?.detail && <span className="text-muted">({job.detail})</span>}
            </li>
          );
        })}
      </ol>

      <p className="mt-6 text-sm text-muted">
        {queued
          ? "Another file is being processed. Yours starts next."
          : engine === "deepgram"
            ? "Usually done in under a minute, even for long recordings."
            : "Speaker detection runs on this computer's CPU, so it can take about as long as the audio."}
      </p>
      <button type="button" onClick={onCancel} className="mt-4 text-sm text-muted underline underline-offset-4 hover:text-ink">
        Choose another file
      </button>
    </section>
  );
}
