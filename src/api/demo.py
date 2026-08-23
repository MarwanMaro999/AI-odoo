"""A local browser demo for recording the questionnaire flow."""

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(include_in_schema=False)


@router.get("/demo", response_class=HTMLResponse)
async def questionnaire_demo() -> str:
    """Serve a self-contained internal demo page."""
    return _DEMO_PAGE


_DEMO_PAGE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Datum Engine | Discovery Questionnaire Demo</title>
  <style>
    :root { --navy:#102a43; --blue:#1677ff; --mist:#f4f7fb; --line:#dbe4ee; --good:#087f5b; --bad:#c92a2a; }
    * { box-sizing:border-box; } body { margin:0; background:var(--mist); color:#1f2937; font-family:Inter,Segoe UI,Arial,sans-serif; }
    header { background:linear-gradient(135deg,var(--navy),#1c4f84); color:#fff; padding:38px max(24px,calc((100vw - 980px)/2)); }
    h1 { margin:0; font-size:30px; } header p { margin:9px 0 0; opacity:.85; }
    main { max-width:980px; margin:28px auto 54px; padding:0 20px; display:grid; grid-template-columns:1.3fr .7fr; gap:22px; }
    .card { background:#fff; border:1px solid var(--line); border-radius:14px; padding:24px; box-shadow:0 8px 22px #102a4310; }
    h2 { margin:0 0 18px; font-size:19px; color:var(--navy); } label { display:block; font-weight:650; font-size:13px; margin:15px 0 6px; }
    input, textarea { width:100%; border:1px solid #bac7d5; border-radius:8px; padding:10px 11px; font:inherit; } textarea { min-height:185px; resize:vertical; }
    .two { display:grid; grid-template-columns:1fr 1fr; gap:12px; } .check { display:flex; gap:8px; align-items:center; margin:18px 0; font-size:14px; } .check input { width:auto; }
    button { width:100%; border:0; border-radius:8px; background:var(--blue); color:#fff; padding:12px; font-size:15px; font-weight:700; cursor:pointer; } button:disabled { opacity:.6; cursor:wait; }
    .note { font-size:13px; color:#52606d; line-height:1.55; } .status { font-size:23px; font-weight:750; text-transform:capitalize; margin:10px 0; }
    .queued,.running { color:#b26a00; }.succeeded { color:var(--good); }.failed { color:var(--bad); } .hidden { display:none; }
    a.download { display:block; text-align:center; text-decoration:none; background:var(--good); color:#fff; padding:12px; border-radius:8px; font-weight:700; margin-top:18px; }
    code { background:#edf2f7; border-radius:4px; padding:2px 4px; word-break:break-all; } @media(max-width:760px){ main{grid-template-columns:1fr;} }
  </style>
</head>
<body>
  <header><h1>Datum Engine</h1><p>Discovery Questionnaire · فريق أودوتك</p></header>
  <main>
    <section class="card">
      <h2>Create a questionnaire</h2>
      <form id="questionnaire-form">
        <div class="two"><div><label for="company">Customer / company name</label><input id="company" required value="OdooTec"></div><div><label for="industry">Industry</label><input id="industry" value="Odoo ERP Implementation"></div></div>
        <div class="two"><div><label for="country">Country</label><input id="country" value="Egypt"></div><div><label for="website">Website (optional)</label><input id="website" type="url" placeholder="https://example.com"></div></div>
        <label for="context">Project requirements</label><textarea id="context" required placeholder="Write the customer's project requirements here. You may write in Arabic or English."></textarea>
        <label for="attachment">Supporting file (optional)</label><input id="attachment" type="file" accept=".pdf,.docx,.txt,.md">
        <label class="check"><input id="research" type="checkbox"> Research the company using public web sources</label>
        <button id="submit" type="submit">Generate Arabic + English questionnaire</button>
      </form>
    </section>
    <aside class="card"><h2>Run status</h2><p class="note">The request is processed in the background. Keep this page open while it generates.</p><div id="empty" class="note">No questionnaire has been submitted yet.</div><div id="result" class="hidden"><div class="status" id="state"></div><p class="note">Run ID</p><code id="run-id"></code><p id="detail" class="note"></p><a id="download" class="download hidden" download>Download PDF</a></div></aside>
  </main>
  <script>
    const base = '/api/v1/discovery-questionnaire';
    const form = document.querySelector('#questionnaire-form'); const button = document.querySelector('#submit');
    const result = document.querySelector('#result'); const state = document.querySelector('#state'); const detail = document.querySelector('#detail'); const download = document.querySelector('#download');
    const show = (run) => { document.querySelector('#empty').classList.add('hidden'); result.classList.remove('hidden'); state.textContent = run.state; state.className = `status ${run.state}`; document.querySelector('#run-id').textContent = run.questionnaire_run_id; detail.textContent = run.failure_code ? `Processing failed: ${run.failure_code}` : ''; if (run.state === 'succeeded' && run.outputs.length) { download.href = run.outputs[0].download_url; download.classList.remove('hidden'); } };
    const poll = async (id) => { const response = await fetch(`${base}/runs/${id}`); const run = await response.json(); show(run); if (run.state === 'queued' || run.state === 'running') window.setTimeout(() => poll(id), 2000); else button.disabled = false; };
    form.addEventListener('submit', async (event) => { event.preventDefault(); button.disabled = true; download.classList.add('hidden'); detail.textContent = 'Submitting request…';
      const sourceMaterial = [{ source_id: crypto.randomUUID(), type:'prospect_context', origin:'staff_provided', text:document.querySelector('#context').value }];
      const file = document.querySelector('#attachment').files[0]; if (file) { const data = new FormData(); data.append('file', file); const extraction = await fetch(`${base}/source-files/extract`, { method:'POST', body:data }); if (!extraction.ok) { detail.textContent = 'File extraction failed.'; button.disabled = false; return; } sourceMaterial.push(await extraction.json()); }
      const website = document.querySelector('#website').value; const customer = { name:document.querySelector('#company').value, industry:document.querySelector('#industry').value, country:document.querySelector('#country').value }; if (website) customer.website = website;
      const response = await fetch(`${base}/runs`, { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({ questionnaire_identifier:'gen-discovery-questions', idempotency_key:`demo-${crypto.randomUUID()}`, customer, source_material:sourceMaterial, options:{ languages:['ar','en'], web_research_enabled:document.querySelector('#research').checked } }) });
      if (!response.ok) { detail.textContent = 'Could not start the questionnaire.'; button.disabled = false; return; } const run = await response.json(); show(run); poll(run.questionnaire_run_id);
    });
  </script>
</body></html>"""
