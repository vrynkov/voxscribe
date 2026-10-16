import { useEffect, useMemo, useRef, useState } from "react";
import { colorFor, download, formatTime, saveText, toSrt, toText } from "../lib.js";

const LANGUAGE_NAMES = { en: "English", english: "English", ru: "Russian", russian: "Russian" };

// Who spoke when: one lane per speaker. Click anywhere to jump there.
function SpeakerTimeline({ utterances, speakers, names, duration, time, onSeek }) {
  const seekFromEvent = (e) => {
    const rect = e.currentTarget.getBoundingClientRect();
    onSeek(((e.clientX - rect.left) / rect.width) * duration);
  };
  const onKey = (e) => {
    if (e.key === "ArrowRight") onSeek(Math.min(duration, time + 5));
    if (e.key === "ArrowLeft") onSeek(Math.max(0, time - 5));
  };
  return (
    <div className="mt-5">
      <div
        role="slider"
        tabIndex={0}
        aria-label="Speaker timeline"
        aria-valuemin={0}
        aria-valuemax={Math.round(duration)}
        aria-valuenow={Math.round(time)}
        aria-valuetext={formatTime(time)}
        onClick={seekFromEvent}
        onKeyDown={onKey}
        className="relative cursor-pointer space-y-1.5 rounded-lg py-1"
      >
        {speakers.map((spk) => (
          <div key={spk} className="relative h-3.5 rounded-sm bg-line/40" title={names[spk]}>
            {utterances
              .filter((u) => u.speaker === spk)
              .map((u, i) => (
                <span
                  key={i}
                  className="absolute inset-y-0 rounded-sm"
                  style={{
                    left: `${(u.start / duration) * 100}%`,
                    width: `max(2px, ${((u.end - u.start) / duration) * 100}%)`,
                    background: colorFor(spk, speakers),
                  }}
                />
              ))}
          </div>
        ))}
        <span
          aria-hidden
          className="pointer-events-none absolute inset-y-0 w-0.5 bg-ink"
          style={{ left: `${(time / duration) * 100}%` }}
        />
      </div>
      <div className="tabular mt-1 flex justify-between text-xs text-muted">
        <span>{formatTime(0)}</span>
        <span>{formatTime(duration)}</span>
      </div>
    </div>
  );
}

function Highlight({ text, query }) {
  if (!query) return text;
  const parts = text.split(new RegExp(`(${query.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")})`, "gi"));
  return parts.map((p, i) =>
    p.toLowerCase() === query.toLowerCase() ? <mark key={i} className="rounded bg-action/20 px-0.5 text-ink">{p}</mark> : p
  );
}

export default function TranscriptView({ result, audioUrl, fileName, onReset }) {
  const { utterances, speakers, duration, language, warning } = result;
  const audioRef = useRef(null);
  const activeRef = useRef(null);
  const [time, setTime] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [query, setQuery] = useState("");
  const [copied, setCopied] = useState(false);
  const [saveMsg, setSaveMsg] = useState("");
  const [names, setNames] = useState(() => Object.fromEntries(speakers.map((s) => [s, s])));

  // Index of the line being spoken right now.
  const activeIndex = useMemo(() => {
    let idx = -1;
    for (let i = 0; i < utterances.length && utterances[i].start <= time + 0.05; i++) idx = i;
    return idx;
  }, [time, utterances]);

  useEffect(() => {
    if (playing) activeRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [activeIndex, playing]);

  const seek = (t) => {
    const a = audioRef.current;
    if (!a) return;
    a.currentTime = t;
    setTime(t);
    a.play().catch(() => {});
  };

  const visible = query
    ? utterances.map((u, i) => [u, i]).filter(([u]) => u.text.toLowerCase().includes(query.toLowerCase()))
    : utterances.map((u, i) => [u, i]);

  const base = fileName.replace(/\.[^.]+$/, "");
  const txtName = `${base}.txt`; // "interview.mp3" -> "interview.txt"
  const save = async () => {
    const outcome = await saveText(txtName, toText(utterances, names));
    if (outcome === "cancelled") return;
    setSaveMsg(
      outcome === "saved"
        ? `Saved ${txtName}. Next time the Save window opens in the same folder.`
        : `Downloaded ${txtName}. This browser picks the folder itself; use Chrome or Edge to have it remembered.`
    );
    setTimeout(() => setSaveMsg(""), 8000);
  };

  const copy = async () => {
    await navigator.clipboard.writeText(toText(utterances, names));
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  const words = utterances.reduce((n, u) => n + u.text.split(/\s+/).length, 0);

  return (
    <section>
      {/* Player + timeline stay visible while you scroll the transcript */}
      <div className="sticky top-0 z-10 -mx-4 border-b border-line bg-paper/95 px-4 pb-4 pt-4 backdrop-blur sm:-mx-6 sm:px-6">
        <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
          <div className="flex min-w-0 items-center gap-3">
            <h2 className="min-w-0 truncate text-lg font-semibold">{fileName}</h2>
            <button
              type="button"
              onClick={save}
              className="shrink-0 rounded-lg bg-action px-4 py-1.5 text-sm font-medium text-action-ink"
            >
              Save transcript
            </button>
          </div>
          <p className="tabular text-sm text-muted">
            {formatTime(duration)}, {speakers.length} {speakers.length === 1 ? "speaker" : "speakers"},{" "}
            {LANGUAGE_NAMES[language?.toLowerCase()] ?? language ?? "unknown language"}
          </p>
        </div>
        <p role="status" aria-live="polite" className="mt-1 h-5 text-sm text-muted">{saveMsg}</p>
        <audio
          ref={audioRef}
          src={audioUrl}
          controls
          className="mt-1 w-full"
          onTimeUpdate={(e) => setTime(e.currentTarget.currentTime)}
          onPlay={() => setPlaying(true)}
          onPause={() => setPlaying(false)}
        />
        <SpeakerTimeline utterances={utterances} speakers={speakers} names={names} duration={duration} time={time} onSeek={seek} />
      </div>

      {warning && <p role="status" className="mt-4 rounded-lg border border-line bg-surface p-3 text-sm">{warning}</p>}

      {/* Speakers: type to rename. Names are used in the transcript and downloads. */}
      <p className="mt-6 text-sm text-muted">Click a name to rename the speaker everywhere, including downloads.</p>
      <div className="mt-2 flex flex-wrap gap-3">
        {speakers.map((spk) => (
          <label key={spk} className="flex items-center gap-2 rounded-lg border border-line bg-surface py-1.5 pl-3 pr-1.5">
            <span aria-hidden className="size-2.5 rounded-full" style={{ background: colorFor(spk, speakers) }} />
            <span className="sr-only">Rename {spk}</span>
            <input
              value={names[spk]}
              onChange={(e) => setNames({ ...names, [spk]: e.target.value || spk })}
              className="w-28 rounded bg-transparent px-1 py-0.5 text-sm font-medium outline-none focus:bg-paper"
            />
          </label>
        ))}
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-2">
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search the transcript"
          className="min-w-0 flex-1 basis-56 rounded-lg border border-line bg-surface px-3 py-2 text-sm outline-none focus:border-action"
        />
        <button type="button" onClick={copy} className="rounded-lg border border-line bg-surface px-3 py-2 text-sm hover:border-muted">
          {copied ? "Copied" : "Copy"}
        </button>
        <button type="button" onClick={() => download(`${base}.srt`, toSrt(utterances, names))} className="rounded-lg border border-line bg-surface px-3 py-2 text-sm hover:border-muted">
          Subtitles (.srt)
        </button>
        <button
          type="button"
          onClick={() => download(`${base}.json`, JSON.stringify({ ...result, utterances: utterances.map((u) => ({ ...u, speaker: names[u.speaker] })) }, null, 2), "application/json")}
          className="rounded-lg border border-line bg-surface px-3 py-2 text-sm hover:border-muted"
        >
          Data (.json)
        </button>
      </div>

      <ol className="mt-6 divide-y divide-line/70">
        {visible.length === 0 && <li className="py-8 text-center text-sm text-muted">No lines contain “{query}”.</li>}
        {visible.map(([u, i]) => {
          const active = i === activeIndex;
          const color = colorFor(u.speaker, speakers);
          return (
            <li key={i} ref={active ? activeRef : null}>
              <button
                type="button"
                onClick={() => seek(u.start)}
                className={`grid w-full grid-cols-[3.75rem_1fr] items-start gap-x-3 rounded-lg px-2 py-3 text-left transition-colors sm:grid-cols-[4.25rem_9rem_1fr] ${
                  active ? "bg-surface" : "hover:bg-surface/60"
                }`}
                style={active ? { boxShadow: `inset 3px 0 0 ${color}` } : undefined}
              >
                <span className="tabular pt-px text-sm text-muted">{formatTime(u.start)}</span>
                <span className="flex min-w-0 items-center gap-2 pt-px text-sm font-semibold">
                  <span aria-hidden className="size-2 shrink-0 rounded-full" style={{ background: color }} />
                  <span className="truncate">{names[u.speaker]}</span>
                </span>
                <span className="col-span-2 mt-1 leading-relaxed sm:col-span-1 sm:mt-0">
                  <Highlight text={u.text} query={query} />
                </span>
              </button>
            </li>
          );
        })}
      </ol>

      <div className="mt-10 flex flex-wrap items-center justify-between gap-4 border-t border-line pt-6 text-sm text-muted">
        <span className="tabular">{utterances.length} lines, {words.toLocaleString()} words</span>
        <button type="button" onClick={onReset} className="rounded-lg bg-action px-5 py-2.5 font-medium text-action-ink">
          Transcribe another file
        </button>
      </div>
    </section>
  );
}
