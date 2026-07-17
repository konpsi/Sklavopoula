"""Browser UI for the AI-assisted CV creation flow."""

CREATE_PAGE = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Create CV</title>
  <style>
    :root {
      color-scheme: light;
      --blue: #2f80ed;
      --blue-soft: #eff7ff;
      --green: #12805c;
      --line: #d8e2ee;
      --text: #172033;
      --muted: #667085;
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
    main { width: min(100%, 42rem); }
    .setup,
    .interview {
      border: 1px solid var(--line);
      border-radius: .75rem;
      background: #fff;
      padding: 1.5rem;
      box-shadow: 0 22px 60px rgba(20, 68, 128, .08);
    }
    .interview { text-align: center; }
    .hidden { display: none; }
    h1 {
      margin: 0;
      font-size: 2rem;
      line-height: 1.1;
      letter-spacing: 0;
    }
    p {
      margin: .8rem 0 0;
      color: var(--muted);
      line-height: 1.55;
    }
    label {
      display: block;
      margin-top: 1.3rem;
      font-weight: 700;
    }
    input {
      width: 100%;
      min-height: 3rem;
      margin-top: .45rem;
      padding: .75rem .9rem;
      border: 1px solid var(--line);
      border-radius: .6rem;
      color: var(--text);
      font: inherit;
    }
    input:focus {
      border-color: #9dc2ea;
      outline: 3px solid var(--blue-soft);
    }
    .actions {
      display: flex;
      gap: .75rem;
      flex-wrap: wrap;
      margin-top: 1.3rem;
    }
    .button {
      appearance: none;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 3rem;
      padding: .75rem 1rem;
      border: 1px solid #a9d2ff;
      border-radius: .6rem;
      background: var(--blue-soft);
      color: #1759a8;
      cursor: pointer;
      font: inherit;
      font-weight: 700;
      text-decoration: none;
    }
    .button.primary {
      border-color: var(--blue);
      background: var(--blue);
      color: #fff;
    }
    .button:disabled {
      cursor: wait;
      opacity: .65;
    }
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
    .context {
      color: var(--green);
      font-weight: 700;
    }
  </style>
</head>
<body>
  <main>
    <section class="setup" id="setup" aria-labelledby="setup-title">
      <h1 id="setup-title">Create your CV</h1>
      <p>Optionally add a company website first. The AI will read that page and use it to personalize the CV. Leave it blank for a general CV.</p>
      <label for="company-url">Company website</label>
      <input id="company-url" type="url" placeholder="https://example.com">
      <div class="actions">
        <button class="button primary" id="start-button" type="button">Start creating CV</button>
        <a class="button" href="/">Home</a>
      </div>
      <p id="setup-status" role="status" aria-live="polite"></p>
    </section>

    <section class="interview hidden" id="interview" aria-live="polite">
      <p id="question">Preparing your first question...</p>
      <button id="voice-button" type="button" disabled aria-describedby="status">Please wait</button>
      <p id="status" role="status" aria-live="polite"></p>
    </section>
  </main>

  <script>
    const setup = document.querySelector("#setup");
    const interview = document.querySelector("#interview");
    const startButton = document.querySelector("#start-button");
    const companyUrl = document.querySelector("#company-url");
    const setupStatus = document.querySelector("#setup-status");
    const button = document.querySelector("#voice-button");
    const question = document.querySelector("#question");
    const status = document.querySelector("#status");
    let recorder;
    let stream;
    let chunks = [];
    let pendingSpeech = null;
    let pendingWarning = "";
    let companyContextAdded = false;
    let recording = false;

    function showIdleStatus() {
      if (pendingWarning) {
        status.textContent = pendingWarning;
      } else if (companyContextAdded) {
        status.innerHTML = "<span class=\"context\">Company context added</span>";
      } else {
        status.textContent = "";
      }
    }

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
      startButton.disabled = true;
      setupStatus.textContent = companyUrl.value.trim() ? "Reading company website..." : "Starting voice questions...";
      try {
        const response = await api("/api/interview/start", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ company_url: companyUrl.value.trim() })
        });
        const turn = await response.json();
        setup.classList.add("hidden");
        interview.classList.remove("hidden");
        question.textContent = turn.question;
        pendingWarning = turn.warning || "";
        companyContextAdded = Boolean(turn.company_context);
        status.textContent = companyContextAdded ? "Company context added" : "The interviewer is speaking";
        pendingSpeech = turn.response || turn.question;
        try {
          await speak(pendingSpeech);
          pendingSpeech = null;
        } catch (error) {
          status.textContent = "Tap once to hear the question";
        }
        button.disabled = false;
        button.textContent = pendingSpeech ? "Hear question" : "Tap to speak";
        if (!pendingSpeech) showIdleStatus();
      } catch (error) {
        setupStatus.textContent = error.message;
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

    startButton.addEventListener("click", startInterview);

    button.addEventListener("click", async () => {
      try {
        if (pendingSpeech) {
          button.disabled = true;
          await speak(pendingSpeech);
          pendingSpeech = null;
          button.disabled = false;
          button.textContent = "Tap to speak";
          showIdleStatus();
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
