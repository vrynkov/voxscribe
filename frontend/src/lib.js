// Small helpers shared by the components.

export const SPEAKER_COLORS = ["#2F5DF5", "#E0457B", "#0E9F6E", "#C98A00", "#7A4CE0", "#0891B2", "#D9480F", "#5C7CFA"];

export const colorFor = (speaker, speakers) =>
  SPEAKER_COLORS[Math.max(0, speakers.indexOf(speaker)) % SPEAKER_COLORS.length];

// 743.2 -> "12:23", 3725 -> "1:02:05"
export function formatTime(sec) {
  const s = Math.max(0, Math.floor(sec));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const ss = String(s % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${ss}` : `${String(m).padStart(2, "0")}:${ss}`;
}

const srtTime = (sec) => {
  const ms = Math.round(sec * 1000);
  const p = (n, w = 2) => String(n).padStart(w, "0");
  return `${p(Math.floor(ms / 3600000))}:${p(Math.floor(ms / 60000) % 60)}:${p(Math.floor(ms / 1000) % 60)},${p(ms % 1000, 3)}`;
};

// ---------- API ----------
export async function startJob(file, language, numSpeakers) {
  const body = new FormData();
  body.append("file", file);
  body.append("language", language);
  if (numSpeakers) body.append("num_speakers", numSpeakers);
  const res = await fetch("/api/transcribe", { method: "POST", body });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `Upload failed (${res.status}).`);
  return data.job_id;
}

export async function getJob(jobId) {
  const res = await fetch(`/api/jobs/${jobId}`);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `Could not read job status (${res.status}).`);
  return data;
}

// ---------- exports (use the names the user typed) ----------
export function toText(utterances, names) {
  return utterances.map((u) => `${formatTime(u.start)} [${names[u.speaker]}]: ${u.text}`).join("\n");
}

export function toSrt(utterances, names) {
  return utterances
    .map((u, i) => `${i + 1}\n${srtTime(u.start)} --> ${srtTime(u.end)}\n${names[u.speaker]}: ${u.text}\n`)
    .join("\n");
}

export function download(filename, content, type = "text/plain") {
  const url = URL.createObjectURL(new Blob([content], { type: `${type};charset=utf-8` }));
  const a = Object.assign(document.createElement("a"), { href: url, download: filename });
  a.click();
  URL.revokeObjectURL(url);
}

// ---------- remember the last save folder ----------
// The browser gives us a "handle" (a pointer) to the file you saved. We keep it in
// IndexedDB, the browser's small built-in database, so it survives page reloads.
// Next time, the "Save as" window opens in that file's folder.
const DB_NAME = "voxscribe";
const STORE = "settings";
const LAST_FILE_KEY = "lastSavedFile";

function openDb() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, 1);
    req.onupgradeneeded = () => req.result.createObjectStore(STORE);
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function getSetting(key) {
  try {
    const db = await openDb();
    return await new Promise((resolve) => {
      const req = db.transaction(STORE).objectStore(STORE).get(key);
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => resolve(undefined);
    });
  } catch {
    return undefined; // private window or storage blocked: just use Downloads
  }
}

async function setSetting(key, value) {
  try {
    const db = await openDb();
    db.transaction(STORE, "readwrite").objectStore(STORE).put(value, key);
  } catch {
    /* not critical */
  }
}

// Save a .txt file. In Chrome and Edge this opens a "Save as" window with the name
// already filled in. The first time it starts in Downloads; after that it starts in
// the folder you used last. Other browsers save straight to the Downloads folder.
// Returns "saved", "downloaded" or "cancelled".
export async function saveText(filename, content) {
  if (window.showSaveFilePicker) {
    const options = {
      id: "voxscribe-transcripts", // the browser also remembers the folder per id
      suggestedName: filename,
      types: [{ description: "Text file", accept: { "text/plain": [".txt"] } }],
    };
    const lastFile = await getSetting(LAST_FILE_KEY);
    try {
      let handle;
      try {
        handle = await window.showSaveFilePicker({ ...options, startIn: lastFile || "downloads" });
      } catch (e) {
        if (e?.name === "AbortError" || !lastFile) throw e;
        // The remembered folder was moved or deleted: start in Downloads instead.
        handle = await window.showSaveFilePicker({ ...options, startIn: "downloads" });
      }
      const writable = await handle.createWritable();
      await writable.write(new Blob([content], { type: "text/plain;charset=utf-8" }));
      await writable.close();
      await setSetting(LAST_FILE_KEY, handle);
      return "saved";
    } catch (e) {
      if (e?.name === "AbortError") return "cancelled"; // user closed the window
      // Anything else (blocked, unsupported): fall back to a normal download.
    }
  }
  download(filename, content);
  return "downloaded";
}
