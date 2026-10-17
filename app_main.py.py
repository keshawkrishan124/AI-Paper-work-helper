"""
AI Paperwork Helper
Upload a photo/PDF of a bill, notice, contract or form and get a plain-language
explanation: what it is, key facts, what to do, and red flags. Then ask follow-ups.

Replit setup:
  1. Secrets (padlock icon) -> add ANTHROPIC_API_KEY
  2. Shell -> pip install flask anthropic
  3. Press Run
"""
import base64
import json
import os
import re
import uuid

import anthropic
from flask import Flask, Response, jsonify, request

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 12 * 1024 * 1024  # 12 MB upload limit

MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5-5")
client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from Replit Secrets

ALLOWED_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/gif",
    "application/pdf",
}

# In-memory store (resets when the Repl restarts). Swap for a database later.
DOCS = {}

SYSTEM_PROMPT = """You help people understand confusing paperwork (bills, notices, \
contracts, forms, letters). Read the attached document and respond with ONLY a JSON \
object, no markdown fences, using exactly this shape:

{
  "document_type": "short label, e.g. Electricity bill",
  "summary": "1-2 plain sentences: what this document is and why the person received it",
  "key_facts": [{"label": "Amount due", "value": "..."}],
  "actions": [{"task": "what the person should do", "deadline": "date or empty string"}],
  "red_flags": [{"issue": "short title", "why": "one sentence explaining the risk"}],
  "note": "anything unreadable or uncertain, else empty string"
}

Rules:
- Write every value in the language the user asks for.
- Copy amounts, dates, names and reference numbers exactly as printed. Never guess.
- If something is blurry or missing, say so in "note" instead of inventing it.
- Red flags: unusual fees, auto-renewals, penalties, short deadlines, one-sided terms.
  Use an empty list if there are none.
- Use simple words. Do not give legal or financial advice; explain and suggest next steps.
"""

CHAT_SYSTEM = """You are helping a person understand one specific document that they \
uploaded. Answer questions using only what the document says. If the answer is not in \
the document, say so. Keep answers short and in simple words. Reply in the language \
the user asks for. You are not a lawyer or financial advisor; suggest a professional \
when a decision carries real legal or financial risk."""


def doc_block(mime, b64):
    kind = "document" if mime == "application/pdf" else "image"
    return {"type": kind, "source": {"type": "base64", "media_type": mime, "data": b64}}


def parse_json(text):
    text = text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise


@app.post("/api/analyze")
def analyze():
    file = request.files.get("file")
    language = request.form.get("language", "English")
    if not file:
        return jsonify(error="Choose a photo or PDF first."), 400

    mime = file.mimetype
    if mime not in ALLOWED_TYPES:
        return jsonify(error="Unsupported file. Use a JPG, PNG, WEBP, GIF or PDF."), 400

    b64 = base64.standard_b64encode(file.read()).decode("utf-8")
    block = doc_block(mime, b64)

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=1800,
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": [
                        block,
                        {"type": "text", "text": f"Explain this document. Language: {language}."},
                    ],
                }
            ],
        )
        raw = "".join(b.text for b in response.content if b.type == "text")
        result = parse_json(raw)
    except json.JSONDecodeError:
        return jsonify(error="Could not read the result. Try a clearer photo."), 502
    except anthropic.APIError as e:
        return jsonify(error=f"AI service error: {getattr(e, 'message', str(e))}"), 502

    doc_id = uuid.uuid4().hex
    DOCS[doc_id] = {
        "block": block,
        "analysis": raw,
        "chat": [],
    }
    result["doc_id"] = doc_id
    return jsonify(result)


@app.post("/api/ask")
def ask():
    data = request.get_json(silent=True) or {}
    doc = DOCS.get(data.get("doc_id"))
    question = (data.get("question") or "").strip()
    language = data.get("language", "English")
    if not doc:
        return jsonify(error="Document expired. Upload it again."), 404
    if not question:
        return jsonify(error="Type a question."), 400

    messages = [
        {
            "role": "user",
            "content": [doc["block"], {"type": "text", "text": "This is my document."}],
        },
        {"role": "assistant", "content": doc["analysis"]},
        *doc["chat"],
        {"role": "user", "content": f"{question}\n\n(Reply in {language}.)"},
    ]

    try:
        response = client.messages.create(
            model=MODEL, max_tokens=800, system=CHAT_SYSTEM, messages=messages
        )
        answer = "".join(b.text for b in response.content if b.type == "text")
    except anthropic.APIError as e:
        return jsonify(error=f"AI service error: {getattr(e, 'message', str(e))}"), 502

    doc["chat"].append({"role": "user", "content": question})
    doc["chat"].append({"role": "assistant", "content": answer})
    return jsonify(answer=answer)


@app.post("/api/forget")
def forget():
    """Delete a document from memory (the privacy promise in the UI)."""
    data = request.get_json(silent=True) or {}
    DOCS.pop(data.get("doc_id"), None)
    return jsonify(ok=True)


PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Paperwork Helper</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Newsreader:opsz,wght@6..72,500;6..72,600&family=IBM+Plex+Sans:wght@400;500;600&display=swap" rel="stylesheet">
<style>
  :root {
    --bg: #eef1f4;
    --card: #ffffff;
    --ink: #14213d;
    --muted: #5b6676;
    --line: #d5dbe3;
    --mark: #ffe66d;
    --go: #2f6f5e;
    --warn: #c43d4b;
    --warn-bg: #fdecee;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--bg); color: var(--ink);
    font: 16px/1.55 "IBM Plex Sans", system-ui, sans-serif;
  }
  main { max-width: 720px; margin: 0 auto; padding: 32px 18px 80px; }
  h1 { font: 600 2.1rem/1.15 "Newsreader", Georgia, serif; margin: 0 0 6px; }
  h2 { font: 600 1.25rem/1.2 "Newsreader", Georgia, serif; margin: 0 0 10px; }
  .lede { color: var(--muted); margin: 0 0 26px; max-width: 60ch; }

  .drop {
    display: block; border: 2px dashed var(--ink); border-radius: 10px;
    background: var(--card); padding: 34px 18px; text-align: center; cursor: pointer;
  }
  .drop:hover, .drop:focus-within { background: #fffbe0; }
  .drop strong { display: block; font-size: 1.05rem; }
  .drop span { color: var(--muted); font-size: .92rem; }
  .drop input { position: absolute; opacity: 0; width: 1px; height: 1px; }
  #fileName { margin-top: 8px; font-weight: 500; }

  .row { display: flex; gap: 10px; margin-top: 14px; flex-wrap: wrap; }
  select, input[type=text] {
    font: inherit; padding: 11px 12px; border: 1px solid var(--line);
    border-radius: 8px; background: var(--card); color: var(--ink);
  }
  button {
    font: inherit; font-weight: 600; padding: 11px 20px; border: 0; border-radius: 8px;
    background: var(--ink); color: #fff; cursor: pointer;
  }
  button:hover { background: #22345c; }
  button:disabled { opacity: .5; cursor: wait; }
  button.ghost { background: transparent; color: var(--ink); border: 1px solid var(--ink); }
  :focus-visible { outline: 3px solid var(--ink); outline-offset: 2px; }

  #status { margin: 18px 0 0; color: var(--muted); min-height: 1.4em; }
  #status.error { color: var(--warn); font-weight: 500; }

  .card {
    background: var(--card); border: 1px solid var(--line); border-radius: 10px;
    padding: 20px; margin-top: 18px;
  }
  .type { display: inline-block; background: var(--mark); padding: 2px 8px; border-radius: 4px; font-weight: 600; font-size: .9rem; }
  .summary { font-size: 1.12rem; margin: 10px 0 0; }

  dl { margin: 0; display: grid; grid-template-columns: minmax(110px, 38%) 1fr; gap: 8px 14px; }
  dt { color: var(--muted); }
  dd { margin: 0; font-weight: 500; overflow-wrap: anywhere; }

  ul { list-style: none; padding: 0; margin: 0; }
  .actions li { display: flex; gap: 10px; padding: 8px 0; border-top: 1px solid var(--line); }
  .actions li:first-child { border-top: 0; }
  .actions .tick { color: var(--go); font-weight: 700; }
  .due { color: var(--muted); font-size: .9rem; }

  .flags { border-color: var(--warn); background: var(--warn-bg); }
  .flags h2 { color: var(--warn); }
  .flags li { padding: 6px 0; }
  .flags b { display: block; }

  .note { color: var(--muted); font-size: .92rem; margin-top: 14px; }

  #chat .msg { padding: 10px 12px; border-radius: 8px; margin: 8px 0; white-space: pre-wrap; }
  #chat .you { background: var(--mark); margin-left: 18%; }
  #chat .bot { background: #eef1f4; margin-right: 18%; }
  #askForm { display: flex; gap: 10px; margin-top: 12px; }
  #askForm input { flex: 1; min-width: 0; }

  .foot { color: var(--muted); font-size: .85rem; margin-top: 26px; }
  [hidden] { display: none !important; }
  @media (max-width: 480px) { dl { grid-template-columns: 1fr; gap: 0; } dd { margin-bottom: 8px; } }
  @media (prefers-reduced-motion: no-preference) { button { transition: background .15s; } }
</style>
</head>
<body>
<main>
  <h1>Understand any paperwork</h1>
  <p class="lede">Upload a photo or PDF of a bill, notice, contract or form. You get what it is, the key facts, what to do, and anything risky.</p>

  <label class="drop" id="drop">
    <strong>Choose a photo or PDF</strong>
    <span>JPG, PNG, WEBP or PDF, up to 12 MB</span>
    <input type="file" id="file" accept="image/*,application/pdf">
    <div id="fileName"></div>
  </label>

  <div class="row">
    <select id="lang" aria-label="Language">
      <option>English</option>
      <option>Hindi</option>
      <option>Punjabi</option>
      <option>Spanish</option>
      <option>French</option>
      <option>Arabic</option>
    </select>
    <button id="go">Explain this document</button>
  </div>
  <p id="status" role="status"></p>

  <section id="result" hidden>
    <div class="card">
      <span class="type" id="rType"></span>
      <p class="summary" id="rSummary"></p>
    </div>

    <div class="card" id="factsCard"><h2>Key facts</h2><dl id="rFacts"></dl></div>
    <div class="card" id="actionsCard"><h2>What to do</h2><ul class="actions" id="rActions"></ul></div>
    <div class="card flags" id="flagsCard"><h2>Watch out for</h2><ul id="rFlags"></ul></div>
    <p class="note" id="rNote"></p>

    <div class="card" id="chat">
      <h2>Ask about this document</h2>
      <div id="log"></div>
      <form id="askForm">
        <input type="text" id="q" placeholder="e.g. What happens if I pay late?" aria-label="Your question" autocomplete="off">
        <button type="submit">Ask</button>
      </form>
    </div>

    <div class="row"><button class="ghost" id="forget">Delete this document</button></div>
  </section>

  <p class="foot">This tool explains documents. It is not legal or financial advice. Check important details with the sender or a professional.</p>
</main>

<script>
const $ = (id) => document.getElementById(id);
let docId = null;

function el(tag, props = {}, ...kids) {
  const n = document.createElement(tag);
  Object.assign(n, props);
  kids.forEach((k) => n.append(k));
  return n;
}
function setStatus(msg, isError = false) {
  $("status").textContent = msg;
  $("status").className = isError ? "error" : "";
}

$("file").addEventListener("change", () => {
  const f = $("file").files[0];
  $("fileName").textContent = f ? f.name : "";
});

$("go").addEventListener("click", async () => {
  const f = $("file").files[0];
  if (!f) return setStatus("Choose a photo or PDF first.", true);

  const body = new FormData();
  body.append("file", f);
  body.append("language", $("lang").value);

  $("go").disabled = true;
  $("result").hidden = true;
  setStatus("Reading your document...");
  try {
    const res = await fetch("/api/analyze", { method: "POST", body });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Something went wrong.");
    render(data);
    setStatus("");
  } catch (e) {
    setStatus(e.message, true);
  } finally {
    $("go").disabled = false;
  }
});

function render(d) {
  docId = d.doc_id;
  $("rType").textContent = d.document_type || "Document";
  $("rSummary").textContent = d.summary || "";

  const facts = $("rFacts"); facts.replaceChildren();
  (d.key_facts || []).forEach((f) => facts.append(el("dt", { textContent: f.label }), el("dd", { textContent: f.value })));
  $("factsCard").hidden = !(d.key_facts || []).length;

  const acts = $("rActions"); acts.replaceChildren();
  (d.actions || []).forEach((a) => {
    const body = el("div", {}, el("div", { textContent: a.task }));
    if (a.deadline) body.append(el("div", { className: "due", textContent: "By " + a.deadline }));
    acts.append(el("li", {}, el("span", { className: "tick", textContent: "\u2713" }), body));
  });
  $("actionsCard").hidden = !(d.actions || []).length;

  const flags = $("rFlags"); flags.replaceChildren();
  (d.red_flags || []).forEach((r) => flags.append(el("li", {}, el("b", { textContent: r.issue }), el("span", { textContent: r.why }))));
  $("flagsCard").hidden = !(d.red_flags || []).length;

  $("rNote").textContent = d.note || "";
  $("log").replaceChildren();
  $("result").hidden = false;
  $("result").scrollIntoView({ behavior: "smooth" });
}

$("askForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const q = $("q").value.trim();
  if (!q || !docId) return;
  $("q").value = "";
  $("log").append(el("div", { className: "msg you", textContent: q }));
  const pending = el("div", { className: "msg bot", textContent: "Thinking..." });
  $("log").append(pending);
  try {
    const res = await fetch("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ doc_id: docId, question: q, language: $("lang").value }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Something went wrong.");
    pending.textContent = data.answer;
  } catch (err) {
    pending.textContent = err.message;
  }
});

$("forget").addEventListener("click", async () => {
  if (docId) await fetch("/api/forget", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ doc_id: docId }),
  });
  docId = null;
  $("result").hidden = true;
  $("file").value = "";
  $("fileName").textContent = "";
  setStatus("Document deleted.");
});
</script>
</body>
</html>
"""


@app.get("/")
def index():
    return Response(PAGE, mimetype="text/html")


if __name__ == "__main__":
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Missing ANTHROPIC_API_KEY. Add it in Replit Secrets (padlock icon).")
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))






