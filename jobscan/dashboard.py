"""dashboard.html: every scored role, best first, with its verdict."""
from __future__ import annotations

import html
import json
from datetime import datetime
from pathlib import Path

from .store import Store

PAGE = """<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>jobscan</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--ink:#1d2430;--muted:#6a7381;--rule:#e2e5ea;--accent:#1f4e79;--good:#1b7a4c;--mid:#a86410;--low:#8a929e}
@media (prefers-color-scheme:dark){:root{--bg:#111418;--card:#1a1f26;--ink:#e6e9ee;--muted:#98a1ad;--rule:#2b323c;--accent:#8db8e4;--good:#4fc58a;--mid:#e0a24a;--low:#7d8693}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif}
.wrap{max-width:960px;margin:0 auto;padding:28px 18px 60px}
h1{margin:0;font-size:1.6rem;letter-spacing:-.01em}.sub{color:var(--muted);font-size:.85rem;margin:2px 0 18px}
.bar{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px}
.bar input{flex:1 1 220px;padding:8px 10px;border:1px solid var(--rule);border-radius:6px;background:var(--card);color:var(--ink);font:inherit}
.bar button{padding:7px 12px;border:1px solid var(--rule);border-radius:999px;background:var(--card);color:var(--ink);font:inherit;font-size:.85rem;cursor:pointer}
.bar button[aria-pressed=true]{background:var(--accent);border-color:var(--accent);color:var(--card)}
.card{background:var(--card);border:1px solid var(--rule);border-radius:8px;padding:12px 14px;margin-bottom:8px}
.top{display:flex;justify-content:space-between;gap:12px;align-items:baseline}
.t{font-weight:600}.t a{color:inherit;text-decoration:none}.t a:hover{text-decoration:underline}
.meta{color:var(--muted);font-size:.8rem}.v{font-size:.9rem;margin-top:6px}
.s{font-weight:700;white-space:nowrap}.hi{color:var(--good)}.md{color:var(--mid)}.lo{color:var(--low)}
.empty{color:var(--muted);padding:30px;text-align:center;border:1px dashed var(--rule);border-radius:8px}
</style></head><body><div class="wrap">
<h1>jobscan</h1><div class="sub">__SUB__</div>
<div class="bar"><input id="q" type="search" placeholder="Search title, employer or verdict…" aria-label="Search">
<button data-min="7" aria-pressed="true">7 and above</button><button data-min="5" aria-pressed="false">5 and above</button><button data-min="0" aria-pressed="false">All scored</button></div>
<div id="list"></div></div>
<script>
const D = __DATA__; let min = 7, q = "";
const safeUrl = u => /^https?:[/][/]/i.test(u || "") ? u : "#";
const esc = s => { const d = document.createElement("div"); d.textContent = s ?? ""; return d.innerHTML; };
function render(){
  const rows = D.filter(r => r.score >= min && (r.title + r.employer + r.verdict).toLowerCase().includes(q));
  document.getElementById("list").innerHTML = rows.length ? rows.map(r => `<div class="card"><div class="top">
    <div class="t"><a href="${esc(safeUrl(r.url))}" target="_blank" rel="noopener">${esc(r.title)}</a></div>
    <div class="s ${r.score >= 7 ? "hi" : r.score >= 5 ? "md" : "lo"}">${r.score}/10</div></div>
    <div class="meta">${esc(r.employer)} · ${esc(r.location)} · first seen ${esc(r.first_seen)}</div>
    <div class="v">${esc(r.verdict)}</div></div>`).join("") : '<div class="empty">Nothing here yet. Run collect, then /review-jobs in Claude Code.</div>';
}
document.getElementById("q").oninput = e => { q = e.target.value.toLowerCase(); render(); };
document.querySelectorAll("[data-min]").forEach(b => b.onclick = () => {
  document.querySelectorAll("[data-min]").forEach(x => x.setAttribute("aria-pressed", "false"));
  b.setAttribute("aria-pressed", "true"); min = +b.dataset.min; render(); });
render();
</script></body></html>"""


def build(store: Store, out: Path) -> Path:
    rows = store.conn.execute(
        "SELECT title, employer, location, url, score, verdict, substr(first_seen,1,10) AS first_seen "
        "FROM postings WHERE score IS NOT NULL AND closed_at IS NULL ORDER BY score DESC, first_seen DESC"
    ).fetchall()
    data = [dict(r) for r in rows]
    waiting = store.conn.execute(
        "SELECT COUNT(*) FROM postings WHERE score IS NULL AND closed_at IS NULL AND COALESCE(suppressed,0)=0"
    ).fetchone()[0]
    sub = (f"{len(data)} roles scored · {sum(1 for r in data if r['score'] >= 7)} at 7 or above · "
           f"{waiting} waiting for review · updated {datetime.now():%d %b %Y %H:%M}")
    out.write_text(PAGE.replace("__SUB__", html.escape(sub))
                       .replace("__DATA__", json.dumps(data).replace("</", "<\\/")), encoding="utf-8")
    return out
