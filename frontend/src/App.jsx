import { useEffect, useRef, useState } from "react";
import ProgressPanel from "./components/ProgressPanel.jsx";
import TranscriptView from "./components/TranscriptView.jsx";
import UploadPanel from "./components/UploadPanel.jsx";
import { getJob, startJob } from "./lib.js";

const POLL_MS = 1500;

export default function App() {
  // view: "upload" -> "working" -> "done"
  const [view, setView] = useState("upload");
  const [error, setError] = useState("");
  const [file, setFile] = useState(null);
  const [audioUrl, setAudioUrl] = useState("");
  const [job, setJob] = useState(null);
  const [engine, setEngine] = useState("deepgram");
  const [codeMode, setCodeMode] = useState("none"); // "required" | "optional" | "none"
  const pollRef = useRef(null);

  // Ask the server which engine it uses (changes the footer and options).
  useEffect(() => {
    fetch("/api/health")
      .then((r) => r.json())
      .then((h) => {
        if (h.engine) setEngine(h.engine);
        if (h.access_code) setCodeMode(h.access_code);
      })
      .catch(() => {});
  }, []);

  const stopPolling = () => clearTimeout(pollRef.current);
  useEffect(() => stopPolling, []);

  // The browser plays the file you picked directly; no need to download it back from the server.
  useEffect(() => {
    if (!file) return;
    const url = URL.createObjectURL(file);
    setAudioUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  async function start(f, language, speakers, code) {
    setError("");
    setFile(f);
    setJob(null);
    setView("working");
    try {
      const jobId = await startJob(f, language, speakers, code);
      const poll = async () => {
        try {
          const j = await getJob(jobId);
          setJob(j);
          if (j.status === "done") return setView("done");
          if (j.status === "error") {
            setError(j.error || "Transcription failed. Try another file.");
            return setView("upload");
          }
          pollRef.current = setTimeout(poll, POLL_MS);
        } catch (e) {
          setError(e.message);
          setView("upload");
        }
      };
      poll();
    } catch (e) {
      setError(e.message);
      setView("upload");
    }
  }

  function reset() {
    stopPolling();
    setJob(null);
    setView("upload");
  }

  return (
    <div className="mx-auto flex min-h-dvh max-w-3xl flex-col px-4 sm:px-6">
      <header className="flex items-center justify-between py-6">
        <button type="button" onClick={reset} className="flex items-center gap-2.5">
          <span aria-hidden className="flex h-5 items-center gap-[3px]">
            {[["#2F5DF5", 12], ["#E0457B", 20], ["#0E9F6E", 8], ["#C98A00", 15]].map(([c, h]) => (
              <span key={c} className="w-[4px] rounded-full" style={{ background: c, height: h }} />
            ))}
          </span>
          <span className="font-display text-lg font-bold tracking-tight">VoxScribe</span>
        </button>
      </header>

      <main className="flex-1 pb-16">
        {view === "upload" && (
          <>
            <h1 className="font-display mt-8 max-w-2xl text-3xl leading-tight font-medium tracking-tight text-balance sm:mt-14 sm:text-[2.6rem]">
              Turn a recording into a transcript that knows who is talking
            </h1>
            <p className="mt-4 mb-10 max-w-xl text-lg text-muted">
              Upload an interview, meeting or podcast. You get every line with its speaker and timestamp, and you can
              click any line to hear it.
            </p>
            <UploadPanel onStart={start} error={error} engine={engine} codeMode={codeMode} />
          </>
        )}
        {view === "working" && (
          <div className="mt-8 sm:mt-14">
            <ProgressPanel job={job} fileName={file?.name} onCancel={reset} engine={engine} />
          </div>
        )}
        {view === "done" && job?.result && (
          <TranscriptView result={job.result} audioUrl={audioUrl} fileName={file?.name ?? "transcript"} onReset={reset} />
        )}
      </main>

      <footer className="border-t border-line py-6 text-sm text-muted">
        {engine === "deepgram"
          ? "Speech recognition and speaker detection by Deepgram Nova-3. Built with React and FastAPI."
          : "Speech recognition by Whisper large-v3 on Groq. Speaker detection by pyannote. Built with React and FastAPI."}
      </footer>
    </div>
  );
}
