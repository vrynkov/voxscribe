---
title: VoxScribe
emoji: 🎙️
colorFrom: blue
colorTo: green
sdk: docker
app_port: 7860
pinned: false
---

# VoxScribe

Upload an MP3, get a transcript that shows **who** spoke and **when**:

```
00:00 [Speaker 1]: Добрый день! Спасибо, что пришли на интервью.
00:06 [Speaker 2]: Thanks for having me. Should we do this in English or in Russian?
```

Works with English and Russian (and mixed recordings). Click any line to hear it, rename speakers, search, and download as `.txt`, `.srt` (subtitles) or `.json`.

**Cost: $0 for demos.** Two engines, both free to use:

| Engine | Words | Speakers | 24 min of audio | Free? |
|---|---|---|---|---|
| **deepgram** (default) | Deepgram Nova-3 | Deepgram (same call) | about 30 seconds | $200 free credit, no card (hundreds of hours) |
| **local** (backup) | Whisper large-v3 on Groq | pyannote on your own CPU | 10–25 minutes | Free forever |

The app uses Deepgram when `DEEPGRAM_API_KEY` is set, otherwise the local engine. Force one with `ENGINE=deepgram` or `ENGINE=local`.

## How it works

```
 Browser (React)                     Server (FastAPI)
 ───────────────                     ────────────────
 1. upload MP3  ───────────────────▶ save file, return a job id
 2. ask "done yet?" every 1.5 s ◀──▶ background worker:
                                       a. ffmpeg → clean 16 kHz mono audio
                                       b. deepgram: words + speakers in one call
                                          local:    Groq → words, pyannote → speakers
                                       c. merge  → give each word to a speaker
 3. show transcript + player  ◀───── result
```

Plain-language terms:

- **Transcription** = turning speech into text.
- **Diarization** = figuring out *who* is speaking *when*. It doesn't know names, only "voice A" vs "voice B".
- **Merging** = the speech model says "the word *hello* was said at 3.2 s". The speaker model says "voice B talked from 3.0 s to 5.0 s". So *hello* belongs to voice B. Do that for every word, then glue neighbouring words from the same voice into one line. Both engines feed into the same `backend/app/merge.py`.
- **Job + polling** = long files take time. Instead of making the browser wait on one request, the server answers immediately with a ticket (job id), and the page checks the ticket every 1.5 s.
- **Why is local speaker detection slow?** pyannote makes a "voice fingerprint" for every few seconds of audio, then groups similar fingerprints. That's a lot of math for a CPU. Deepgram does the same on powerful GPUs.

## Project layout

```
backend/
  app/main.py       API: upload, job status, serves the built React app
  app/pipeline.py   ffmpeg, Deepgram engine, Groq + pyannote engine
  app/merge.py      words + speakers → "12:23 [Speaker 1]: ..."
  tests/            pytest (no API keys needed)
frontend/
  src/App.jsx                       upload → progress → transcript
  src/components/UploadPanel.jsx    drag & drop, language, speaker count (local engine)
  src/components/ProgressPanel.jsx  live stages
  src/components/TranscriptView.jsx player, speaker timeline, transcript, downloads
Dockerfile          one container: builds React, runs FastAPI on port 7860
```

## 1. Get free keys

**For the fast engine (recommended), one key:**

- **Deepgram**: sign up at [console.deepgram.com](https://console.deepgram.com) (no credit card). Go to **API Keys → Create a New API Key**, copy it.

**Only if you also want the local backup engine:**

- **Groq**: [console.groq.com/keys](https://console.groq.com/keys) → **Create API Key**.
- **Hugging Face**: create a *Read* token at [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens), then open [pyannote/speaker-diarization-community-1](https://huggingface.co/pyannote/speaker-diarization-community-1) and click **Agree**. Skip this and you get a 403 error.

## 2. Run it on Windows (Command Prompt)

You need Python 3.11–3.13, Node.js 20+, and ffmpeg (`winget install Gyan.FFmpeg`, then open a new Command Prompt).

**Window 1, backend:**

```cmd
cd backend
python -m venv .venv
.venv\Scripts\activate.bat
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
copy .env.example .env
notepad .env
uvicorn app.main:app --reload --port 8000 --no-access-log
```

In Notepad, paste your key(s), save, and close before running the last line. The server window prints `Engine: deepgram` or `Engine: local` when it starts.

**Window 2, frontend:**

```cmd
cd frontend
npm install
npm run dev
```

Open http://localhost:5173.

Run the tests (no keys needed): in Window 1, `pip install -r requirements-dev.txt` then `python -m pytest`.

## 3. Put it online for free (Hugging Face Spaces)

1. Go to [huggingface.co/new-space](https://huggingface.co/new-space). Pick **Docker** → **Blank**, hardware **CPU basic (free)**, visibility **Public**.
2. In the Space: **Settings → Variables and secrets → New secret**. Add `DEEPGRAM_API_KEY` (and `GROQ_API_KEY` + `HF_TOKEN` if you want the backup engine).
3. Push this folder to the Space (Command Prompt, in the `voxscribe` folder):

   ```cmd
   git init
   git add .
   git commit -m "VoxScribe"
   git branch -M main
   git remote add space https://huggingface.co/spaces/<your-username>/voxscribe
   git push space main
   ```

   When it asks for a password, use a Hugging Face token with *Write* access.
4. The first build takes about 10 minutes. Your app is then live at `https://<your-username>-voxscribe.hf.space`.

Also push to GitHub for your portfolio (`git remote add origin ...`). The README header block is only read by Hugging Face.

### Before a demo

- Free Spaces **fall asleep** when nobody uses them. Open the link 2 minutes before the interview so it wakes up.
- Use the Deepgram engine. The free Space has only 2 CPUs, so the local engine would be very slow there.
- Check your remaining Deepgram credit in its console now and then.

## Settings (environment variables)

| Name | Default | What it does |
|---|---|---|
| `DEEPGRAM_API_KEY` | | Fast engine |
| `ENGINE` | auto | `deepgram` or `local`; auto = deepgram if its key is set |
| `DEEPGRAM_MODEL` | `nova-3` | Deepgram model |
| `GROQ_API_KEY` | | Local engine: speech-to-text |
| `HF_TOKEN` | | Local engine: downloads the speaker model |
| `GROQ_MODEL` | `whisper-large-v3` | `whisper-large-v3-turbo` is faster, slightly less accurate |
| `MAX_UPLOAD_MB` | `100` | Biggest file allowed |
| `MAX_AUDIO_MINUTES` | `60` | Longest audio allowed |
| `CORS_ORIGINS` | `http://localhost:5173` | Only matters if the frontend is hosted separately |

## Talking points for interviews

- **Why a job queue?** Free hosting kills long requests, and the user gets live progress.
- **Why two engines?** I started fully open-source (Whisper + pyannote). Measured on a laptop, speaker detection took about as long as the audio, and the free cloud server is even weaker. So I added Deepgram behind the same interface: same merge step, same UI, swap with one setting. That's a real trade-off story: cost vs speed vs vendor lock-in.
- **The hard part:** Whisper's word list has no punctuation, but its sentence text does. `words_with_punctuation()` lines them up so the transcript reads naturally.
- **Limits:** jobs live in memory, so a restart loses them; one job runs at a time. Next steps would be Redis + a worker, chunked uploads, and word-level highlighting during playback.
