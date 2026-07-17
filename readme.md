# Local Voice CV Builder

The existing **Create CV** action first asks for an optional company website URL, then
opens a minimal, voice-guided questionnaire. When a company URL is provided, the app
fetches readable text from that page and sends it to OpenRouter as context so the
AI-created CV can be personalized for that company. If the field is left blank, the CV
flow stays general. Audio is transcribed on the machine with `faster-whisper`, only the
transcript, questionnaire context, and optional company page context are sent to
OpenRouter, and the response is spoken locally using the operating system voice through
`pyttsx3`.

## Run with Python 3.10

Create and activate a Python 3.10 virtual environment, then install the local speech
dependencies:

```powershell
py -3.10 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Set the OpenRouter key in the shell that will run the app. Do not put a live key in the
repository:

```powershell
$env:OPENROUTER_API_KEY = "your-openrouter-key"
python app.py
```

Open <http://127.0.0.1:8080> and choose **Create CV**. Add a company website if the CV
should be personalized, or leave the field blank for a general CV, then start the voice
questions. Allow microphone access when the browser asks. The first Whisper run
downloads the selected model; after that, STT inference is local. The default `tiny.en`
model is intentionally small for an MVP. Set `WHISPER_MODEL=small.en` for better English
accuracy, or `WHISPER_MODEL=small` and `STT_LANGUAGE` for another language.

On Linux, `pyttsx3` also needs an installed local speech engine such as `espeak-ng`.
Windows uses its installed SAPI voices.

## Voice interview structure

- `questionnaire.py` is the editable general CV questionnaire outline.
- `voice_interview.py` owns local STT/TTS, OpenRouter calls, validation, and answer storage.
- `create_page.py` contains the intentionally minimal one-button browser UI.
- Each reply is first evaluated as `captured`, `clarify`, or `skipped`. Clarifications stay
  on the same item; captured and skipped items are saved before a second LLM call chooses
  and phrases the next question.
- `interview_data/<session-id>.json` keeps clean CV data under `profile` and the verbatim
  conversational audit trail under `turns`. These local files are ignored by Git.
- Temporary microphone recordings are deleted immediately after transcription.

The model is pinned in `voice_interview.py` as `google/gemini-2.5-flash-lite` for
consistent, inexpensive evaluation and question selection. OpenRouter requests require
strict JSON-schema support and use response healing. If a provider or API request still fails, the page and server
terminal show the sanitized OpenRouter error while the questionnaire safely continues
in its defined order.

## Tests

The unit tests do not need speech models or a live API key:

```powershell
python -m unittest discover -s tests -v
```

# Project Backlog

## Product Vision

Build a CV and interview preparation app that helps users create or upload a CV, personalize it for a specific company, and practice with an AI voice mock interview. The app should turn the process into a guided, game-like experience with clear feedback, downloadable outputs, and actionable improvement points.

## Core User Flows

### 1. Entry Screen

Users land on a screen with two primary options:

- Create a CV with AI assistance
- Upload an existing CV

The screen should make the choice simple and direct.

### 2. Create CV With AI Assistance

If the user chooses to create a CV with AI assistance:

- Start an AI voice-activated mode.
- Ask the user a structured set of questions about their background, experience, skills, education, projects, and career goals.
- Capture and summarize the user's answers.
- Generate a polished CV from the collected information.
- Produce a nicely formatted PDF.
- Allow the user to download the PDF.

### 3. Upload Existing CV

If the user chooses to upload a CV:

- Let the user upload a CV file.
- Store or process the uploaded CV.
- Leave the flow there unless the user chooses another action.

### 4. Company-Specific CV Personalization

The CV should be personalized for a target company.

Users provide:

- A link to the company's homepage

The system should:

- Pull and analyze the company homepage.
- Extract relevant company information, tone, values, industry, products, and hiring signals.
- Use AI to tailor the CV toward that company.
- Emphasize the user's most relevant skills and experience.
- Produce a company-specific CV version.

### 5. Mock Interview

Users can choose a mock interview option.

The mock interview should:

- Use AI voice mode.
- Put the AI in the role of interviewer.
- Ask relevant questions based on the user's CV and target company.
- Let the user answer by voice.
- Track the user's answers for later analysis.

### 6. Gamified Feedback Screen

After the mock interview, show a gamified results screen.

The feedback should include:

- Red flags
- Contradictions
- Missed opportunities
- Suggested improvements
- Strengths or strong answers

Examples:

- Red flag: The CV says the user worked somewhere for one year, but in the interview they said they worked there for four months.
- Missed opportunity: The user could have connected a previous project more clearly to the company's product or role.

The screen should feel rewarding and useful, not punitive.

## Backlog

### MVP

- Create entry screen with two choices: AI-assisted CV creation or CV upload.
- Build CV upload flow.
- Build AI voice-question flow for creating a CV.
- Define the question set for AI-assisted CV creation.
- Save user's voice answers as structured profile data.
- Generate CV content from structured profile data.
- Generate downloadable PDF CV.
- Add company homepage URL input.
- Fetch and analyze company homepage content.
- Personalize generated CV for the target company.
- Add mock interview entry point.
- Build AI voice mock interview flow.
- Generate interview questions using the CV and company context.
- Capture interview answers.
- Compare interview answers against CV content.
- Detect contradictions between CV and interview answers.
- Detect missed opportunities in interview answers.
- Build gamified feedback screen.

### Nice To Have

- Support multiple CV templates.
- Let users edit generated CV sections before downloading.
- Show confidence scores for company fit.
- Add interview score categories such as clarity, relevance, confidence, and specificity.
- Add replay or transcript view for interview answers.
- Let users regenerate selected CV sections.
- Save multiple company-specific CV versions.
- Add export options beyond PDF.
- Add role-specific personalization using a job description link.
- Add progress indicators during voice flows.

### Technical Tasks

- Choose frontend framework and app structure.
- Set up routing between entry, CV creation, upload, company personalization, mock interview, and feedback screens.
- Implement file upload handling.
- Implement PDF generation.
- Implement company homepage scraping or content extraction.
- Implement AI prompt flow for CV generation.
- Implement AI prompt flow for company personalization.
- Implement AI voice interaction.
- Implement transcript storage.
- Implement contradiction detection between CV and interview transcript.
- Implement missed-opportunity detection.
- Design feedback data model.
- Add basic persistence for uploaded CVs, generated CVs, company context, and interview sessions.
- Add error handling for invalid company links, failed uploads, and failed PDF generation.

## Open Questions

- Which CV file types should be supported for upload?
- Should the uploaded CV be parsed immediately or only stored?
- Should the user provide a job description as well as the company homepage?
- Should the mock interview be general, company-specific, role-specific, or all three?
- Should users be able to edit AI-generated answers before creating the CV?
- Should the app store user data permanently, temporarily, or only for the current session?
- What level of gamification should the feedback screen have?

## Suggested Milestones

### Milestone 1: Basic CV Flow

- Entry screen
- CV upload
- AI-assisted CV question flow
- Generated CV content
- Downloadable PDF

### Milestone 2: Company Personalization

- Company homepage URL input
- Homepage analysis
- Company-specific CV generation
- Downloadable personalized PDF

### Milestone 3: Mock Interview

- Voice mock interview
- Company-specific interview questions
- Transcript capture
- Interview answer analysis

### Milestone 4: Gamified Feedback

- Red flag detection
- Contradiction detection
- Missed-opportunity detection
- Feedback screen
- Improvement suggestions
