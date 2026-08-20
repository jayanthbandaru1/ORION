# Wake word ("ORION") setup

Push-to-talk works with no setup. Wake word needs two files from
Picovoice that can't be fetched automatically — a personal AccessKey,
and a custom "ORION" keyword model only your account can generate.
Until these exist, the UI just shows "Wake word: not configured" and
push-to-talk keeps working normally.

## 1. Get a free AccessKey

1. Sign up at https://console.picovoice.ai (no card required, free tier).
2. Copy your AccessKey from the console dashboard.
3. Put it in `.env`:
   ```
   PICOVOICE_ACCESS_KEY=your-key-here
   ```

## 2. Generate the "ORION" keyword file

1. In the Picovoice Console, go to **Porcupine** → **Create Wake Word**.
2. Type `ORION` as the wake phrase.
3. Set the target platform to **Web (WASM)** — this matters, the file
   format is platform-specific.
4. Download the generated `.ppn` file.
5. Rename it to exactly `orion_keyword.ppn` and place it at:
   ```
   interfaces/web/models/orion_keyword.ppn
   ```

## 3. Restart and reload

Restart the ORION server and reload the web UI. The header should
switch from "Wake word: not configured" to "Wake word: listening for
'ORION'" (a small green dot). Say "ORION" clearly — the status line
flips to "ORION heard — listening..." and starts recording your next
sentence, auto-sending it after you go quiet for about a second.

## Notes

- `interfaces/web/models/porcupine_params.pv` is already vendored in
  the repo (the base English acoustic model — not account-specific,
  freely distributed by Picovoice). You don't need to fetch this one.
- `interfaces/web/vendor/*.min.js` are the Porcupine Web and Web Voice
  Processor IIFE bundles, vendored directly rather than loaded from a
  CDN or pulled in via a bundler — Picovoice's own docs only document
  an npm+bundler workflow, which conflicts with this project's
  no-build-step design (see PHASE1.md), so these were built once
  locally and the static output committed instead.
- If detection feels too trigger-happy or too insensitive, the
  `sensitivity` field (0–1, default 0.5) can be added next to `label`
  in the `PorcupineWorker.create()` call in `interfaces/web/index.html`.
- Wake-triggered recording auto-stops after ~1.2s of silence following
  detected speech, with a 15s hard cap — see `recordUntilSilence()` in
  `interfaces/web/index.html` if that timing needs tuning.
