import os
import re
import mimetypes
from email import policy
from email.parser import BytesParser
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse


HOST = "127.0.0.1"
PORT = int(os.environ.get("PORT", "8080"))
UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploaded_cv")
ALLOWED_CV_EXTENSIONS = {".pdf", ".doc", ".docx", ".txt"}
MAX_UPLOAD_SIZE = 10 * 1024 * 1024


HOME_PAGE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>CV Builder Home</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f7fafc;
      --panel: #ffffff;
      --text: #172033;
      --muted: #667085;
      --line: #d8e2ee;
      --line-strong: #9dc2ea;
      --blue: #2f80ed;
      --blue-soft: #eff7ff;
      --green: #12805c;
      --green-soft: #eaf8f2;
      --amber: #9a6700;
      --amber-soft: #fff6db;
      --shadow: 0 24px 70px rgba(20, 68, 128, 0.08);
    }

    * {
      box-sizing: border-box;
    }

    body {
      margin: 0;
      min-height: 100vh;
      font-family: Arial, Helvetica, sans-serif;
      color: var(--text);
      background:
        radial-gradient(circle at top right, rgba(211, 233, 255, 0.64), transparent 34rem),
        radial-gradient(circle at bottom left, rgba(226, 247, 238, 0.8), transparent 30rem),
        linear-gradient(180deg, #ffffff 0%, var(--bg) 100%);
    }

    main {
      min-height: 100vh;
      padding: 2rem;
    }

    .dashboard {
      width: min(100%, 72rem);
      margin: 0 auto;
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(20rem, 26rem);
      gap: 1.5rem;
      align-items: start;
    }

    .hero,
    .side-panel,
    .next-panel {
      border: 1px solid var(--line);
      border-radius: 0.75rem;
      background: rgba(255, 255, 255, 0.9);
      box-shadow: var(--shadow);
    }

    .hero {
      padding: 2rem;
    }

    .brand-row {
      display: flex;
      align-items: center;
      gap: 0.8rem;
      margin-bottom: 1.5rem;
    }

    .brand {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 3.25rem;
      height: 3.25rem;
      border: 1px solid var(--line);
      border-radius: 0.75rem;
      background: rgba(255, 255, 255, 0.86);
      color: var(--blue);
      font-weight: 700;
      letter-spacing: 0;
    }

    .eyebrow {
      color: var(--green);
      font-size: 0.8rem;
      font-weight: 700;
      text-transform: uppercase;
    }

    h1 {
      margin: 0;
      font-size: 2.8rem;
      line-height: 1.05;
      letter-spacing: 0;
    }

    p {
      max-width: 33rem;
      margin: 1rem 0 0;
      color: var(--muted);
      font-size: 1.05rem;
      line-height: 1.6;
    }

    .actions {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 1rem;
      margin-top: 2.25rem;
    }

    .action,
    .button {
      appearance: none;
      display: flex;
      align-items: center;
      justify-content: center;
      min-height: 4rem;
      padding: 1rem 1.25rem;
      border: 1px solid var(--line);
      border-radius: 0.75rem;
      background: rgba(255, 255, 255, 0.92);
      color: var(--text);
      box-shadow: 0 10px 30px rgba(20, 68, 128, 0.05);
      cursor: pointer;
      font: inherit;
      font-size: 1rem;
      font-weight: 700;
      text-decoration: none;
      transition: border-color 160ms ease, background 160ms ease, transform 160ms ease, box-shadow 160ms ease;
    }

    .action:hover,
    .action:focus-visible,
    .button:hover,
    .button:focus-visible {
      border-color: var(--line-strong);
      background: var(--blue-soft);
      box-shadow: 0 14px 36px rgba(47, 128, 237, 0.12);
      outline: none;
      transform: translateY(-1px);
    }

    .action.primary {
      border-color: var(--line-strong);
      background: linear-gradient(180deg, #ffffff 0%, #f5fbff 100%);
      color: #1759a8;
    }

    .button {
      min-height: 2.8rem;
      padding: 0.7rem 1rem;
      border-radius: 0.6rem;
      box-shadow: none;
      width: 100%;
    }

    .button.green {
      border-color: #a7dbc7;
      background: var(--green-soft);
      color: var(--green);
    }

    .side-panel {
      padding: 1.25rem;
    }

    .panel-section + .panel-section {
      margin-top: 1.25rem;
      padding-top: 1.25rem;
      border-top: 1px solid var(--line);
    }

    .panel-title {
      margin: 0 0 0.75rem;
      font-size: 1rem;
      line-height: 1.2;
    }

    .cv-link {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 1rem;
      min-height: 3.25rem;
      padding: 0.8rem 0.9rem;
      border: 1px solid var(--line);
      border-radius: 0.6rem;
      background: #ffffff;
      color: var(--text);
      font-weight: 700;
      text-decoration: none;
    }

    .cv-link:hover,
    .cv-link:focus-visible {
      border-color: var(--line-strong);
      outline: none;
    }

    .cv-type {
      flex: 0 0 auto;
      border-radius: 999px;
      background: var(--blue-soft);
      color: #1759a8;
      padding: 0.25rem 0.55rem;
      font-size: 0.75rem;
      font-weight: 700;
      text-transform: uppercase;
    }

    .empty-state {
      border: 1px dashed var(--line-strong);
      border-radius: 0.6rem;
      padding: 1rem;
      color: var(--muted);
      line-height: 1.5;
    }

    .stat-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 0.75rem;
    }

    .stat {
      border: 1px solid var(--line);
      border-radius: 0.6rem;
      padding: 0.8rem;
      background: #ffffff;
    }

    .stat strong {
      display: block;
      font-size: 1.35rem;
      line-height: 1.1;
    }

    .stat span {
      display: block;
      margin-top: 0.3rem;
      color: var(--muted);
      font-size: 0.82rem;
      line-height: 1.35;
    }

    .next-panel {
      margin-top: 1.5rem;
      padding: 1.25rem;
    }

    .next-list {
      display: grid;
      gap: 0.75rem;
      margin-top: 0.9rem;
    }

    .next-item {
      display: flex;
      gap: 0.75rem;
      align-items: flex-start;
      padding: 0.8rem;
      border: 1px solid var(--line);
      border-radius: 0.6rem;
      background: #ffffff;
    }

    .next-dot {
      width: 0.7rem;
      height: 0.7rem;
      flex: 0 0 auto;
      margin-top: 0.3rem;
      border-radius: 50%;
      background: var(--amber);
    }

    .next-item strong {
      display: block;
      margin-bottom: 0.2rem;
    }

    .next-item span {
      color: var(--muted);
      line-height: 1.45;
    }

    .upload-input {
      position: absolute;
      width: 1px;
      height: 1px;
      overflow: hidden;
      clip: rect(0 0 0 0);
      white-space: nowrap;
    }

    form {
      margin: 0;
    }

    .muted {
      color: var(--muted);
    }

    @media (max-width: 38rem) {
      main {
        padding: 1.25rem;
      }

      .dashboard {
        grid-template-columns: 1fr;
      }

      .hero {
        padding: 1.35rem;
      }

      h1 {
        font-size: 2.2rem;
      }

      .actions {
        grid-template-columns: 1fr;
      }

      .stat-grid {
        grid-template-columns: 1fr;
      }
    }
  </style>
</head>
<body>
  <main>
    <div class="dashboard">
      <section>
        <div class="hero" aria-labelledby="page-title">
          <div class="brand-row">
            <div class="brand" aria-hidden="true">CV</div>
            <div>
              <div class="eyebrow">Career workspace</div>
              <div class="muted">CV, company fit, and interview practice</div>
            </div>
          </div>
          <h1 id="page-title">Build from where you are.</h1>
          <p>Start a new CV, upload the one you already have, then use it as the base for interview practice and later company-specific tailoring.</p>

          <div class="actions" aria-label="CV start options">
            <a class="action primary" href="/create">Create CV</a>
            <form action="/upload" method="post" enctype="multipart/form-data">
              <label class="action" for="cv-upload">Upload CV</label>
              <input class="upload-input" id="cv-upload" name="cv" type="file" accept=".pdf,.doc,.docx,.txt">
            </form>
          </div>
        </div>

        <section class="next-panel" aria-labelledby="next-title">
          <h2 class="panel-title" id="next-title">Good next steps</h2>
          <div class="next-list">
            <div class="next-item">
              <span class="next-dot" aria-hidden="true"></span>
              <div>
                <strong>Choose a target company</strong>
                <span>Add the company homepage later so the CV and interview can be aimed at a real opportunity.</span>
              </div>
            </div>
            <div class="next-item">
              <span class="next-dot" aria-hidden="true"></span>
              <div>
                <strong>Practice from the same CV</strong>
                <span>Using one current CV keeps interview feedback tied to the version employers will see.</span>
              </div>
            </div>
          </div>
        </section>
      </section>

      <aside class="side-panel" aria-label="Current progress">
        <section class="panel-section">
          <h2 class="panel-title">Current CV</h2>
          {cv_section}
        </section>

        <section class="panel-section">
          <h2 class="panel-title">Previous interview</h2>
          {interview_section}
        </section>
      </aside>
    </div>
  </main>

  <script>
    const upload = document.querySelector("#cv-upload");
    upload.addEventListener("change", () => {
      if (upload.files.length > 0) {
        upload.form.submit();
      }
    });
  </script>
</body>
</html>
"""


MESSAGE_PAGE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    body {{
      margin: 0;
      min-height: 100vh;
      display: grid;
      place-items: center;
      padding: 2rem;
      font-family: Arial, Helvetica, sans-serif;
      color: #172033;
      background: #fbfdff;
    }}

    .box {{
      width: min(100%, 34rem);
      text-align: center;
    }}

    h1 {{
      margin: 0;
      font-size: 2rem;
      letter-spacing: 0;
    }}

    p {{
      color: #667085;
      line-height: 1.6;
    }}

    .button {{
      appearance: none;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 2.8rem;
      margin-top: 0.8rem;
      padding: 0.7rem 1.1rem;
      border: 1px solid #a9d2ff;
      border-radius: 0.6rem;
      background: #eff7ff;
      color: #1759a8;
      font-weight: 700;
      text-decoration: none;
    }}
  </style>
</head>
<body>
  <main class="box">
    <h1>{heading}</h1>
    <p>{message}</p>
    <a class="button" href="/">Home</a>
  </main>
</body>
</html>
"""


def get_current_cv():
    if not os.path.isdir(UPLOAD_DIR):
        return None

    cv_files = []
    for filename in os.listdir(UPLOAD_DIR):
        path = os.path.join(UPLOAD_DIR, filename)
        _, extension = os.path.splitext(filename)
        if os.path.isfile(path) and extension.lower() in ALLOWED_CV_EXTENSIONS:
            cv_files.append(
                {
                    "filename": filename,
                    "path": path,
                    "extension": extension.lower().lstrip("."),
                    "updated": os.path.getmtime(path),
                }
            )

    if not cv_files:
        return None

    return max(cv_files, key=lambda item: item["updated"])


def render_home_page():
    cv = get_current_cv()
    if cv:
        cv_section = f"""
          <a class="cv-link" href="/cv" target="_blank" rel="noreferrer">
            <span>{escape(cv["filename"])}</span>
            <span class="cv-type">{escape(cv["extension"])}</span>
          </a>
        """
    else:
        cv_section = """
          <div class="empty-state">
            No CV saved yet. Upload one or create a new CV to make it your current version.
          </div>
        """

    interview_section = """
      <div class="empty-state">
        No interviews yet. Once you practice, your latest score and feedback summary will appear here.
      </div>
      <a class="button green" href="/interview">Start interview</a>
    """

    return HOME_PAGE.replace("{cv_section}", cv_section).replace(
        "{interview_section}", interview_section
    )


class AppHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            self.respond(200, render_home_page())
            return
        if path == "/cv":
            self.serve_current_cv()
            return
        if path == "/create":
            self.respond(
                200,
                MESSAGE_PAGE.format(
                    title="Create CV",
                    heading="Create CV",
                    message="This is where the AI voice-guided CV creation flow will start.",
                ),
            )
            return
        if path == "/interview":
            self.respond(
                200,
                MESSAGE_PAGE.format(
                    title="Start interview",
                    heading="Start interview",
                    message="The mock interview flow will start here once it is connected.",
                ),
            )
            return
        self.respond(404, "Not found", "text/plain")

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/upload":
            result = self.save_uploaded_cv()
            if not result["ok"]:
                self.respond(
                    400,
                    MESSAGE_PAGE.format(
                        title="Upload CV",
                        heading="Upload failed",
                        message=escape(result["message"]),
                    ),
                )
                return

            self.respond(
                200,
                MESSAGE_PAGE.format(
                    title="Upload CV",
                    heading="CV uploaded",
                    message=(
                        "Your CV has been saved locally as "
                        f"{escape(result['filename'])}. You can go back if you want to choose another action."
                    ),
                ),
            )
            return
        self.respond(404, "Not found", "text/plain")

    def save_uploaded_cv(self):
        content_type = self.headers.get("Content-Type", "")
        if not content_type.startswith("multipart/form-data"):
            return {"ok": False, "message": "Please choose a CV file to upload."}

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return {"ok": False, "message": "The upload could not be read."}

        if content_length <= 0:
            return {"ok": False, "message": "Please choose a CV file to upload."}
        if content_length > MAX_UPLOAD_SIZE:
            return {"ok": False, "message": "Please upload a CV smaller than 10 MB."}

        body = self.rfile.read(content_length)
        raw_message = (
            f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("utf-8")
            + body
        )
        message = BytesParser(policy=policy.default).parsebytes(raw_message)

        for part in message.iter_parts():
            disposition = part.get("Content-Disposition", "")
            field_name = part.get_param("name", header="content-disposition")
            original_filename = part.get_filename()
            if "form-data" not in disposition or field_name != "cv" or not original_filename:
                continue

            _, extension = os.path.splitext(original_filename)
            extension = extension.lower()
            if extension not in ALLOWED_CV_EXTENSIONS:
                allowed = ", ".join(sorted(ALLOWED_CV_EXTENSIONS))
                return {"ok": False, "message": f"Please upload one of these file types: {allowed}."}

            file_data = part.get_payload(decode=True)
            if not file_data:
                return {"ok": False, "message": "The selected CV file is empty."}

            os.makedirs(UPLOAD_DIR, exist_ok=True)
            for existing_name in os.listdir(UPLOAD_DIR):
                existing_path = os.path.join(UPLOAD_DIR, existing_name)
                if os.path.isfile(existing_path):
                    os.remove(existing_path)

            safe_original = re.sub(r"[^A-Za-z0-9_.-]+", "_", os.path.basename(original_filename))
            stored_filename = safe_original or f"current_cv{extension}"
            if not stored_filename.lower().endswith(extension):
                stored_filename = f"current_cv{extension}"
            stored_path = os.path.join(UPLOAD_DIR, stored_filename)
            with open(stored_path, "wb") as file:
                file.write(file_data)

            return {
                "ok": True,
                "filename": stored_filename,
                "original_filename": safe_original,
                "path": stored_path,
            }

        return {"ok": False, "message": "Please choose a CV file to upload."}

    def serve_current_cv(self):
        cv = get_current_cv()
        if not cv:
            self.respond(
                404,
                MESSAGE_PAGE.format(
                    title="CV not found",
                    heading="No CV saved",
                    message="Upload or create a CV first, then it will appear here.",
                ),
            )
            return

        content_type, _ = mimetypes.guess_type(cv["path"])
        if content_type is None:
            content_type = "application/octet-stream"

        with open(cv["path"], "rb") as file:
            content = file.read()

        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Content-Disposition", f'inline; filename="{cv["filename"]}"')
        self.end_headers()
        self.wfile.write(content)

    def respond(self, status, body, content_type="text/html; charset=utf-8"):
        encoded = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format, *args):
        return


def main():
    server = ThreadingHTTPServer((HOST, PORT), AppHandler)
    print(f"Open http://{HOST}:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
