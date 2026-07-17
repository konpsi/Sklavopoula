import os
import re
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


PAGE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>CV Builder</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #fbfdff;
      --panel: #ffffff;
      --text: #172033;
      --muted: #667085;
      --line: #d8e9ff;
      --line-strong: #a9d2ff;
      --blue: #2f80ed;
      --blue-soft: #eff7ff;
      --shadow: 0 24px 70px rgba(47, 128, 237, 0.08);
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
        radial-gradient(circle at top right, rgba(214, 235, 255, 0.55), transparent 34rem),
        linear-gradient(180deg, #ffffff 0%, var(--bg) 100%);
    }

    main {
      min-height: 100vh;
      display: grid;
      place-items: center;
      padding: 2rem;
    }

    .screen {
      width: min(100%, 44rem);
      text-align: center;
    }

    .brand {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 3.25rem;
      height: 3.25rem;
      margin-bottom: 1.4rem;
      border: 1px solid var(--line);
      border-radius: 1rem;
      background: rgba(255, 255, 255, 0.86);
      box-shadow: var(--shadow);
      color: var(--blue);
      font-weight: 700;
      letter-spacing: 0;
    }

    h1 {
      margin: 0;
      font-size: clamp(2.35rem, 7vw, 4.25rem);
      line-height: 1;
      letter-spacing: 0;
    }

    p {
      max-width: 33rem;
      margin: 1rem auto 0;
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

    .action {
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
    .action:focus-visible {
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

    .upload-input {
      position: absolute;
      width: 1px;
      height: 1px;
      overflow: hidden;
      clip: rect(0 0 0 0);
      white-space: nowrap;
    }

    @media (max-width: 38rem) {
      main {
        padding: 1.25rem;
      }

      .actions {
        grid-template-columns: 1fr;
      }
    }
  </style>
</head>
<body>
  <main>
    <section class="screen" aria-labelledby="page-title">
      <div class="brand" aria-hidden="true">CV</div>
      <h1 id="page-title">Start your CV</h1>
      <p>Choose how you want to begin. Create a new CV with AI guidance, or upload the CV you already have.</p>

      <div class="actions" aria-label="CV start options">
        <a class="action primary" href="/create">Create CV</a>
        <form action="/upload" method="post" enctype="multipart/form-data">
          <label class="action" for="cv-upload">Upload CV</label>
          <input class="upload-input" id="cv-upload" name="cv" type="file" accept=".pdf,.doc,.docx,.txt">
        </form>
      </div>
    </section>
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

    a {{
      color: #1759a8;
      font-weight: 700;
    }}
  </style>
</head>
<body>
  <main class="box">
    <h1>{heading}</h1>
    <p>{message}</p>
    <a href="/">Back to start</a>
  </main>
</body>
</html>
"""


class AppHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            self.respond(200, PAGE)
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
