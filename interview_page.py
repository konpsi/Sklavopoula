"""Minimal browser UI for the conversational mock interview."""


INTERVIEW_PAGE = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Mock interview</title>
  <style>
    :root {
      color-scheme: light;
      --text: #172033;
      --muted: #667085;
      --line: #d8e2ee;
      --blue: #4f7fe5;
      --red: #dc3f4f;
      --green: #12805c;
    }
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
    main { width: min(100%, 43rem); }
    .setup, .interview {
      padding: clamp(1.25rem, 4vw, 2.5rem);
      border: 1px solid var(--line);
      border-radius: 1rem;
      background: white;
    }
    .interview { text-align: center; }
    .hidden { display: none; }
    h1 { margin: 0 0 .65rem; font-size: 2rem; }
    p { color: var(--muted); line-height: 1.55; }
    label { display: block; margin: 1rem 0 .4rem; font-weight: 700; }
    input {
      width: 100%;
      min-height: 3rem;
      padding: .75rem .85rem;
      border: 1px solid #b8c6d8;
      border-radius: .65rem;
      font: inherit;
      color: var(--text);
    }
    input:focus { outline: 3px solid #cfe0ff; border-color: var(--blue); }
    .actions { display: flex; gap: .7rem; margin-top: 1.25rem; }
    .button {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 2.9rem;
      padding: .7rem 1rem;
      border: 1px solid #b8c6d8;
      border-radius: .65rem;
      background: white;
      color: var(--text);
      font: inherit;
      font-weight: 700;
      text-decoration: none;
      cursor: pointer;
    }
    .button.primary { border-color: var(--blue); background: var(--blue); color: white; }
    .button:disabled { cursor: wait; opacity: .65; }
    #question {
      min-height: 4rem;
      margin: 0 auto 1.5rem;
      color: var(--text);
      font-size: 1.25rem;
      line-height: 1.45;
    }
    #voice-button {
      width: 10rem;
      height: 10rem;
      border: 0;
      border-radius: 50%;
      background: var(--blue);
      color: white;
      font: inherit;
      font-weight: 700;
      box-shadow: 0 18px 45px rgba(79, 127, 229, .23);
      cursor: pointer;
      transition: transform .15s ease, background .15s ease;
    }
    #voice-button:hover { transform: scale(1.025); }
    #voice-button:focus-visible { outline: 4px solid #b9dcff; outline-offset: 5px; }
    #voice-button.recording { background: var(--red); }
    #voice-button:disabled { cursor: wait; opacity: .6; transform: none; }
    #status, #setup-status { min-height: 1.5rem; margin: 1.25rem 0 0; color: var(--muted); }
    #status.error, #setup-status.error { color: #b42318; }
    #progress { color: var(--green); font-size: .9rem; font-weight: 700; }
    @media (max-width: 34rem) {
      .actions { flex-direction: column; }
      .button { width: 100%; }
    }
  </style>
</head>
<body>
  <main>
    <section class="setup" id="setup" aria-labelledby="setup-title">
      <h1 id="setup-title">Mock interview</h1>
      <p>Your current CV, the company website, and the role will be used to prepare a conversational interview.</p>
      <label for="company-url">Company website</label>
      <input id="company-url" type="url" placeholder="https://example.com" required>
      <label for="job-title">Job title</label>
      <input id="job-title" type="text" maxlength="160" placeholder="e.g. Junior Product Designer" required>
      <div class="actions">
        <button class="button primary" id="start-button" type="button">Prepare interview</button>
        <a class="button" href="/">Home</a>
      </div>
      <p id="setup-status" role="status" aria-live="polite"></p>
    </section>

    <section class="interview hidden" id="interview" aria-live="polite">
      <p id="progress"></p>
      <p id="question">Preparing the interview...</p>
      <button id="voice-button" type="button" disabled aria-describedby="status">Please wait</button>
      <p id="status" role="status" aria-live="polite"></p>
    </section>
  </main>

  <script>
    const setup = document.querySelector("#setup");
    const interview = document.querySelector("#interview");
    const startButton = document.querySelector("#start-button");
    const companyUrl = document.querySelector("#company-url");
    const jobTitle = document.querySelector("#job-title");
    const setupStatus = document.querySelector("#setup-status");
    const button = document.querySelector("#voice-button");
    const question = document.querySelector("#question");
    const status = document.querySelector("#status");
    const progress = document.querySelector("#progress");
    let recorder;
    let stream;
    let chunks = [];
    let pendingSpeech = null;
    let recording = false;

    async function api(url, options = {}) {
      const response = await fetch(url, options);
      if (!response.ok) {
        let message = `Request failed (${response.status})`;
        try { message = (await response.json()).error || message; } catch (_) {}
        throw new Error(message);
      }
      return response;
    }

    function showError(message) {
      status.textContent = message;
      status.className = "error";
      button.disabled = false;
      button.textContent = "Try again";
    }

    function updateProgress(turn) {
      progress.textContent = turn.complete
        ? "Interview complete"
        : `${turn.answered} of about ${turn.target} questions answered`;
    }

    async function speak(text) {
      const response = await api("/api/mock-interview/speak", {
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
      const url = companyUrl.value.trim();
      const title = jobTitle.value.trim();
      setupStatus.className = "";
      if (!url || !title) {
        setupStatus.textContent = "Enter both the company website and job title.";
        setupStatus.className = "error";
        return;
      }
      startButton.disabled = true;
      setupStatus.textContent = "Reading your CV and company website, then preparing the interview...";
      try {
        const response = await api("/api/mock-interview/start", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ company_url: url, job_title: title })
        });
        const turn = await response.json();
        setup.classList.add("hidden");
        interview.classList.remove("hidden");
        question.textContent = turn.question;
        updateProgress(turn);
        status.textContent = "The interviewer is speaking";
        pendingSpeech = turn.response;
        try {
          await speak(pendingSpeech);
          pendingSpeech = null;
        } catch (_) {
          status.textContent = "Tap once to hear the question";
        }
        button.disabled = false;
        button.textContent = pendingSpeech ? "Hear question" : "Tap to speak";
        if (!pendingSpeech) status.textContent = "";
      } catch (error) {
        setupStatus.textContent = error.message;
        setupStatus.className = "error";
        startButton.disabled = false;
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
      const response = await api("/api/mock-interview/answer", {
        method: "POST",
        headers: { "Content-Type": blob.type },
        body: blob
      });
      const turn = await response.json();
      question.textContent = turn.question || "Thank you for completing the interview.";
      updateProgress(turn);
      status.textContent = turn.warning || "The interviewer is speaking";
      await speak(turn.response);
      if (turn.complete) {
        button.textContent = "Complete";
        button.disabled = true;
        status.innerHTML = "Your interview transcript was saved locally. <a href=\"/interview-transcript\" target=\"_blank\">View transcript</a>.";
      } else {
        button.textContent = "Tap to speak";
        button.disabled = false;
        if (!turn.warning) status.textContent = "";
      }
    }

    startButton.addEventListener("click", startInterview);
    button.addEventListener("click", async () => {
      try {
        if (pendingSpeech) {
          button.disabled = true;
          await speak(pendingSpeech);
          pendingSpeech = null;
          button.disabled = false;
          button.textContent = "Tap to speak";
          status.textContent = "";
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
  </script>
</body>
</html>
"""
