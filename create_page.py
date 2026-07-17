"""Minimal browser UI for the voice CV interview."""

CREATE_PAGE = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Voice CV interview</title>
  <style>
    :root { color-scheme: light; --blue: #2f80ed; --text: #172033; --muted: #667085; }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      display: grid;
      place-items: center;
      padding: 1.5rem;
      font-family: Arial, Helvetica, sans-serif;
      color: var(--text);
      background: #fbfdff;
    }
    main { width: min(100%, 34rem); text-align: center; }
    #question {
      min-height: 4.5rem;
      margin: 0 0 2.5rem;
      font-size: clamp(1.2rem, 4vw, 1.6rem);
      line-height: 1.45;
    }
    #voice-button {
      appearance: none;
      width: 8.5rem;
      height: 8.5rem;
      border: 0;
      border-radius: 50%;
      color: white;
      background: var(--blue);
      box-shadow: 0 20px 55px rgba(47, 128, 237, .3);
      cursor: pointer;
      font: inherit;
      font-weight: 700;
      transition: transform .15s ease, background .15s ease;
    }
    #voice-button:hover { transform: scale(1.025); }
    #voice-button:focus-visible { outline: 4px solid #b9dcff; outline-offset: 5px; }
    #voice-button.recording { background: #dc3f4f; }
    #voice-button:disabled { cursor: wait; opacity: .6; transform: none; }
    #status { min-height: 1.5rem; margin: 1.5rem 0 0; color: var(--muted); }
    #status.error { color: #b42318; }
  </style>
</head>
<body>
  <main>
    <p id="question">Preparing your first question...</p>
    <button id="voice-button" type="button" disabled aria-describedby="status">Please wait</button>
    <p id="status" role="status" aria-live="polite"></p>
  </main>

  <script>
    const button = document.querySelector("#voice-button");
    const question = document.querySelector("#question");
    const status = document.querySelector("#status");
    let recorder;
    let stream;
    let chunks = [];
    let pendingSpeech = null;
    let pendingWarning = "";
    let recording = false;

    function showError(message) {
      status.textContent = message;
      status.className = "error";
      button.disabled = false;
      button.textContent = "Try again";
    }

    async function api(url, options = {}) {
      const response = await fetch(url, options);
      if (!response.ok) {
        let message = `Request failed (${response.status})`;
        try { message = (await response.json()).error || message; } catch (_) {}
        throw new Error(message);
      }
      return response;
    }

    async function speak(text) {
      const response = await api("/api/interview/speak", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text })
      });
      const url = URL.createObjectURL(await response.blob());
      const audio = new Audio(url);
      try {
        await new Promise((resolve, reject) => {
          audio.addEventListener("ended", resolve, { once: true });
          audio.addEventListener("error", () => reject(new Error("The audio could not be played.")), { once: true });
          audio.play().catch(reject);
        });
      } finally {
        URL.revokeObjectURL(url);
      }
    }

    async function startInterview() {
      try {
        const response = await api("/api/interview/start", { method: "POST" });
        const turn = await response.json();
        question.textContent = turn.question;
        pendingWarning = turn.warning || "";
        status.textContent = "The interviewer is speaking";
        pendingSpeech = turn.response || turn.question;
        try {
          await speak(pendingSpeech);
          pendingSpeech = null;
        } catch (error) {
          status.textContent = "Tap once to hear the question";
        }
        button.disabled = false;
        button.textContent = pendingSpeech ? "Hear question" : "Tap to speak";
        if (!pendingSpeech) status.textContent = pendingWarning;
      } catch (error) {
        question.textContent = "Voice interview unavailable";
        showError(error.message);
      }
    }

    function preferredMimeType() {
      const choices = ["audio/webm;codecs=opus", "audio/ogg;codecs=opus", "audio/webm"];
      return choices.find(type => MediaRecorder.isTypeSupported(type)) || "";
    }

    async function beginRecording() {
      if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
        throw new Error("This browser does not support microphone recording.");
      }
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      chunks = [];
      const mimeType = preferredMimeType();
      recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      recorder.addEventListener("dataavailable", event => {
        if (event.data.size) chunks.push(event.data);
      });
      recorder.start();
      recording = true;
      button.classList.add("recording");
      button.textContent = "Tap to stop";
      status.className = "";
      status.textContent = "Listening...";
    }

    async function finishRecording() {
      button.disabled = true;
      button.textContent = "Thinking...";
      status.textContent = "Transcribing locally";
      const stopped = new Promise(resolve => recorder.addEventListener("stop", resolve, { once: true }));
      recorder.stop();
      await stopped;
      stream.getTracks().forEach(track => track.stop());
      recording = false;
      button.classList.remove("recording");
      const blob = new Blob(chunks, { type: recorder.mimeType || "application/octet-stream" });

      const response = await api("/api/interview/answer", {
        method: "POST",
        headers: { "Content-Type": blob.type },
        body: blob
      });
      const turn = await response.json();
      question.textContent = turn.question || "Your answers are saved.";
      status.textContent = turn.warning || "The interviewer is speaking";
      await speak(turn.response);
      if (turn.complete) {
        button.textContent = "Complete";
        button.disabled = true;
        status.textContent = "Your structured answers were saved locally.";
      } else {
        button.textContent = "Tap to speak";
        button.disabled = false;
        if (!turn.warning) status.textContent = "";
      }
    }

    button.addEventListener("click", async () => {
      try {
        if (pendingSpeech) {
          button.disabled = true;
          await speak(pendingSpeech);
          pendingSpeech = null;
          button.disabled = false;
          button.textContent = "Tap to speak";
          status.textContent = pendingWarning;
        } else if (recording) {
          await finishRecording();
        } else {
          await beginRecording();
        }
      } catch (error) {
        recording = false;
        button.classList.remove("recording");
        if (stream) stream.getTracks().forEach(track => track.stop());
        showError(error.message);
      }
    });

    startInterview();
  </script>
</body>
</html>
"""
