import { useRef, useState } from "react";

const LANGUAGES = [
  { value: "auto", label: "Detect" },
  { value: "en", label: "English" },
  { value: "ru", label: "Русский" },
];
const SPEAKERS = [
  { value: "", label: "Detect" },
  { value: "2", label: "2" },
  { value: "3", label: "3" },
  { value: "4", label: "4" },
  { value: "5", label: "5" },
];

function Segmented({ label, options, value, onChange }) {
  return (
    <fieldset className="min-w-0">
      <legend className="mb-2 text-sm text-muted">{label}</legend>
      <div className="inline-flex rounded-lg border border-line bg-paper p-1">
        {options.map((o) => (
          <button
            key={o.value}
            type="button"
            aria-pressed={value === o.value}
            onClick={() => onChange(o.value)}
            className={`rounded-md px-3 py-1.5 text-sm transition-colors ${
              value === o.value ? "bg-ink text-paper" : "text-ink hover:bg-line/50"
            }`}
          >
            {o.label}
          </button>
        ))}
      </div>
    </fieldset>
  );
}

export default function UploadPanel({ onStart, error, engine }) {
  const inputRef = useRef(null);
  const [file, setFile] = useState(null);
  const [dragging, setDragging] = useState(false);
  const [language, setLanguage] = useState("auto");
  const [speakers, setSpeakers] = useState("");

  const pick = (f) => f && setFile(f);

  return (
    <section className="rounded-2xl border border-line bg-surface p-5 sm:p-8">
      <div
        role="button"
        tabIndex={0}
        onClick={() => inputRef.current?.click()}
        onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && inputRef.current?.click()}
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => { e.preventDefault(); setDragging(false); pick(e.dataTransfer.files[0]); }}
        className={`flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed px-6 py-12 text-center transition-colors ${
          dragging ? "border-action bg-action/5" : "border-line hover:border-muted"
        }`}
      >
        <input
          ref={inputRef}
          type="file"
          accept=".mp3,audio/mpeg,.wav,.m4a,.ogg,.flac"
          className="hidden"
          onChange={(e) => pick(e.target.files[0])}
        />
        {file ? (
          <>
            <p className="max-w-full truncate text-lg font-medium">{file.name}</p>
            <p className="mt-1 text-sm text-muted">{(file.size / 1024 / 1024).toFixed(1)} MB. Click to choose a different file.</p>
          </>
        ) : (
          <>
            <p className="text-lg font-medium">Drop an MP3 here, or click to choose one</p>
            <p className="mt-1 text-sm text-muted">Up to 100 MB and 60 minutes</p>
          </>
        )}
      </div>

      <div className="mt-6 flex flex-wrap items-end gap-x-8 gap-y-5">
        <Segmented label="Language" options={LANGUAGES} value={language} onChange={setLanguage} />
        {engine !== "deepgram" && (
          <Segmented label="Number of speakers" options={SPEAKERS} value={speakers} onChange={setSpeakers} />
        )}
        <button
          type="button"
          disabled={!file}
          onClick={() => onStart(file, language, engine === "deepgram" ? "" : speakers)}
          className="ml-auto rounded-lg bg-action px-6 py-2.5 font-medium text-action-ink transition-opacity disabled:cursor-not-allowed disabled:opacity-40"
        >
          Transcribe
        </button>
      </div>

      {error && <p role="alert" className="mt-5 text-sm text-danger">{error}</p>}
    </section>
  );
}
