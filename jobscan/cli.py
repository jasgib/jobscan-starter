"""jobscan, Claude Code edition.

Python does the free legwork - reading every employer's job board and
filtering out what is obviously wrong (location, seniority, excluded titles).
Claude Code does the judgement, inside your own Claude session: /review-jobs
reads each new posting against me/profile.md and records a score and a
one-line verdict through the commands below. No API key is involved.

    python -m jobscan collect              fetch new postings from every employer
    python -m jobscan inbox [--limit N]    postings waiting for a verdict
    python -m jobscan show KEY             full job description (fetched on demand)
    python -m jobscan score KEY N "WHY"    record a 0-10 score and a verdict
    python -m jobscan dashboard            build dashboard.html from the scores
    python -m jobscan employer-test PLATFORM '{"name":..,...}'   try an employer
    python -m jobscan employer-add  PLATFORM '{"name":..,...}'   add it to config.yaml
    python -m jobscan employers            list configured employers
    python -m jobscan cv-text FILE         plain text of a CV (PDF, DOCX or TXT)
    python -m jobscan render-cv JSON OUT.pdf / render-letter JSON OUT.pdf
    python -m jobscan status               counts at a glance
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import requests
import yaml

from .filter import prefilter
from .models import Posting
from .net import make_session
from .sources import (ashby, eightfold, greenhouse, lever, oraclecloud, reed,
                      sf_rss, smartrecruiters, talentsoft, workable, workday)
from .store import Store

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config.yaml"
DB = ROOT / "jobscan.db"

# Platform name in config.yaml -> (module, how to build its employer object).
PLATFORMS = {
    "workday": (workday, lambda e: workday.WorkdayEmployer(
        name=e["name"], tenant=e["tenant"], site=e["site"], host=e.get("host", "wd3"))),
    "greenhouse": (greenhouse, lambda e: greenhouse.GreenhouseEmployer(name=e["name"], board=e["board"])),
    "ashby": (ashby, lambda e: ashby.AshbyEmployer(name=e["name"], board=e["board"])),
    "lever": (lever, lambda e: lever.LeverEmployer(name=e["name"], board=e["board"])),
    "smartrecruiters": (smartrecruiters, lambda e: smartrecruiters.SmartRecruitersEmployer(
        name=e["name"], board=e["board"])),
    "workable": (workable, lambda e: workable.WorkableEmployer(name=e["name"], account=e["account"])),
    "oraclecloud": (oraclecloud, lambda e: oraclecloud.OracleEmployer(
        name=e["name"], host=e["host"], site=e.get("site", "CX_1"))),
    "sf_rss": (sf_rss, lambda e: sf_rss.SFEmployer(
        name=e["name"], base=e["base"], locale=e.get("locale", "en_GB"))),
    "eightfold": (eightfold, lambda e: eightfold.EightfoldEmployer(
        name=e["name"], base=e["base"], domain=e["domain"])),
    "talentsoft": (talentsoft, lambda e: talentsoft.TalentsoftEmployer(
        name=e["name"], base=e["base"], lcid=e.get("lcid", 2057))),
    "reed": (reed, lambda e: reed.ReedSource(
        name=e.get("name", "Reed"), location=e.get("location", "London"),
        distance=int(e.get("distance", 10)), queries=list(e.get("queries") or []),
        min_salary=int(e.get("min_salary", 0)), max_age_days=int(e.get("max_age_days", 7)))),
}


# --------------------------------------------------------------- helpers

def _load_env() -> None:
    """Read KEY=value lines from .env (only the optional REED_API_KEY uses it)."""
    import os
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            k, sep, v = line.partition("=")
            if sep and k.strip() and not k.lstrip().startswith("#"):
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def load_config() -> dict:
    _load_env()
    if not CONFIG.exists():
        sys.exit("No config.yaml yet. Run /setup in Claude Code first.")
    return yaml.safe_load(CONFIG.read_text()) or {}


def employers(cfg: dict):
    for platform, entries in (cfg.get("employers") or {}).items():
        if platform not in PLATFORMS:
            print(f"  ! unknown platform '{platform}' in config.yaml - skipped", file=sys.stderr)
            continue
        module, build = PLATFORMS[platform]
        for e in entries or []:
            yield module, build(e)


def module_for(p: Posting, cfg: dict):
    # Job boards name the advertiser, not the board, so match them by source first.
    for module, emp in employers(cfg):
        if getattr(module, "AGGREGATOR", False) and p.source == module.SOURCE:
            return module, emp
    for module, emp in employers(cfg):
        if emp.name == p.employer and not getattr(module, "AGGREGATOR", False):
            return module, emp
    return None, None


def fetch(module, emp, queries: list[str], session=None) -> tuple[list[Posting], str]:
    s = session or make_session()
    out: list[Posting] = []
    try:
        if getattr(module, "USES_QUERY", True):
            for q in queries:
                out.extend(module.search(emp, q, s))
                time.sleep(0.5)
        else:
            out.extend(module.search(emp, s))
        return out, ""
    except Exception as exc:  # noqa: BLE001 - one bad source must not stop the run
        return out, str(exc)[:200]


def _row(store: Store, key: str):
    rows = store.conn.execute("SELECT * FROM postings WHERE key = ? OR key LIKE ?",
                              (key, key + "%")).fetchall()
    if len(rows) != 1:
        sys.exit(f"{len(rows)} postings match '{key}'. Use the full key from `inbox`.")
    return rows[0]


def _posting(r) -> Posting:
    return Posting(source=r["source"], employer=r["employer"], external_id=r["external_id"],
                   title=r["title"], location=r["location"] or "", url=r["url"] or "",
                   detail_path=r["detail_path"] or "", posted_text=r["posted_text"] or "",
                   description=r["description"] or "", score=r["score"], verdict=r["verdict"] or "")


# --------------------------------------------------------------- commands

def collect(args) -> None:
    cfg = load_config(); store = Store(DB)
    queries = list((cfg.get("search") or {}).get("queries") or [""])
    emps = list(employers(cfg))
    if not emps:
        sys.exit("No employers in config.yaml yet. Add some with /add-company in Claude Code.")
    print(f"Checking {len(emps)} employers…")
    with ThreadPoolExecutor(max_workers=int((cfg.get("search") or {}).get("workers", 6))) as pool:
        results = list(pool.map(lambda me: (me[1], *fetch(me[0], me[1], getattr(me[1], "queries", None) or queries)), emps))
    new = kept = 0; failed = []
    for emp, posts, err in results:
        store.log_run(emp.__class__.__name__, emp.name, len(posts), err or None)
        if err and not posts:
            failed.append(f"{emp.name}: {err[:80]}")
        for p in {p.key: p for p in posts}.values():
            if store.is_known(p):
                store.touch(p); continue
            new += 1
            keep, _ = prefilter(p, cfg)
            store.record(p)
            if not keep:
                store.conn.execute("UPDATE postings SET suppressed = 1, suppressed_reason = 'filtered' WHERE key = ?", (p.key,))
            else:
                kept += 1
    store.conn.commit()
    waiting = _waiting(store)
    print(f"{new} new postings, {kept} passed your filters. {len(waiting)} now waiting for review.")
    for f in failed:
        print(f"  ! {f}")
    if waiting:
        print("Next: open Claude Code in this folder and type /review-jobs")


def _waiting(store: Store):
    return store.conn.execute(
        "SELECT * FROM postings WHERE score IS NULL AND closed_at IS NULL "
        "AND COALESCE(suppressed, 0) = 0 ORDER BY first_seen DESC").fetchall()


def inbox(args) -> None:
    rows = _waiting(Store(DB))
    print(f"{len(rows)} postings waiting for a verdict" + (f" (showing {args.limit})" if args.limit and len(rows) > args.limit else ""))
    for r in rows[: args.limit or None]:
        print(json.dumps({"key": r["key"], "employer": r["employer"], "title": r["title"],
                          "location": r["location"], "url": r["url"]}, ensure_ascii=False))


def show(args) -> None:
    cfg = load_config(); store = Store(DB); r = _row(store, args.key); p = _posting(r)
    if not p.description:
        module, emp = module_for(p, cfg)
        if module:
            try:
                p.description = module.fetch_description(emp, p, make_session())
            except Exception as exc:  # noqa: BLE001
                print(f"(could not fetch the description: {exc})")
        store.conn.execute("UPDATE postings SET description = ? WHERE key = ?", (p.description, p.key))
        store.conn.commit()
    print(f"{p.title}\n{p.employer} · {p.location}\n{p.url}\n\n{p.description or '(no description available - judge from the title and link)'}")


def score(args) -> None:
    if not 0 <= args.score <= 10:
        sys.exit("Score must be 0-10.")
    store = Store(DB); r = _row(store, args.key)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    store.conn.execute("UPDATE postings SET score = ?, verdict = ?, scored_at = ? WHERE key = ?",
                       (args.score, " ".join(args.verdict.split())[:500], now, r["key"]))
    store.conn.commit()
    print(f"{args.score}/10  {r['employer']} - {r['title']}")


def status(args) -> None:
    store = Store(DB); c = store.conn
    n = lambda q: c.execute(q).fetchone()[0]
    print(f"tracked {n('SELECT COUNT(*) FROM postings')} · waiting {len(_waiting(store))} · "
          f"scored {n('SELECT COUNT(*) FROM postings WHERE score IS NOT NULL')} · "
          f"7+ {n('SELECT COUNT(*) FROM postings WHERE score >= 7 AND closed_at IS NULL')}")


def employers_cmd(args) -> None:
    cfg = load_config()
    for platform, entries in (cfg.get("employers") or {}).items():
        for e in entries or []:
            print(f"{platform:16} {e.get('name')}")


def _entry(args) -> dict:
    if args.platform not in PLATFORMS:
        sys.exit(f"Unknown platform. Use one of: {', '.join(PLATFORMS)}")
    try:
        e = json.loads(args.entry)
    except json.JSONDecodeError as exc:
        sys.exit(f"The entry must be JSON: {exc}")
    if "name" not in e:
        sys.exit('The entry needs a "name".')
    return e


def employer_test(args) -> None:
    e = _entry(args); cfg = load_config() if CONFIG.exists() else {}
    module, build = PLATFORMS[args.platform]
    posts, err = fetch(module, build(e), list((cfg.get("search") or {}).get("queries") or [""]))
    uniq = list({p.key: p for p in posts}.values())
    passing = [p for p in uniq if prefilter(p, cfg)[0]] if cfg else uniq
    print(f"{len(uniq)} live postings, {len(passing)} in your area and filters" + (f" | error: {err}" if err else ""))
    for p in (passing or uniq)[:8]:
        print(f"  - {p.title} | {p.location} | {p.url}")
    if not uniq:
        sys.exit(1)


def employer_add(args) -> None:
    e = _entry(args); cfg = load_config()
    names = {x.get("name", "").lower() for v in (cfg.get("employers") or {}).values() for x in (v or [])}
    if e["name"].lower() in names:
        sys.exit(f"{e['name']} is already in config.yaml.")
    cfg.setdefault("employers", {}).setdefault(args.platform, []).append(e)
    list(employers(cfg))   # every entry must still build before anything is saved
    CONFIG.write_text(yaml.dump(cfg, default_flow_style=False, sort_keys=False, allow_unicode=True))
    print(f"Added {e['name']} ({args.platform}). The next `collect` includes it.")


def cv_text(args) -> None:
    f = Path(args.file)
    if f.suffix.lower() == ".pdf":
        from pypdf import PdfReader
        print("\n".join(page.extract_text() or "" for page in PdfReader(str(f)).pages))
    elif f.suffix.lower() == ".docx":
        xml = zipfile.ZipFile(f).read("word/document.xml").decode("utf8")
        xml = re.sub(r"</w:p>", "\n", xml)
        print(html.unescape(re.sub(r"<[^>]+>", "", xml)))
    else:
        print(f.read_text(errors="replace"))


def render_cv(args) -> None:
    from .cv_render import render_cv as _r
    _r(json.loads(Path(args.json).read_text()), Path(args.out)); print(f"Wrote {args.out}")


def render_letter(args) -> None:
    from .cv_render import render_letter as _r
    _r(json.loads(Path(args.json).read_text()), Path(args.out)); print(f"Wrote {args.out}")


def dashboard(args) -> None:
    from .dashboard import build
    out = build(Store(DB), ROOT / "dashboard.html"); print(f"Wrote {out} - open it in your browser.")


def main() -> None:
    ap = argparse.ArgumentParser(prog="jobscan", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("collect").set_defaults(fn=collect)
    p = sub.add_parser("inbox"); p.add_argument("--limit", type=int, default=0); p.set_defaults(fn=inbox)
    p = sub.add_parser("show"); p.add_argument("key"); p.set_defaults(fn=show)
    p = sub.add_parser("score"); p.add_argument("key"); p.add_argument("score", type=int); p.add_argument("verdict"); p.set_defaults(fn=score)
    sub.add_parser("dashboard").set_defaults(fn=dashboard)
    sub.add_parser("status").set_defaults(fn=status)
    sub.add_parser("employers").set_defaults(fn=employers_cmd)
    for name, fn in (("employer-test", employer_test), ("employer-add", employer_add)):
        p = sub.add_parser(name); p.add_argument("platform"); p.add_argument("entry"); p.set_defaults(fn=fn)
    p = sub.add_parser("cv-text"); p.add_argument("file"); p.set_defaults(fn=cv_text)
    for name, fn in (("render-cv", render_cv), ("render-letter", render_letter)):
        p = sub.add_parser(name); p.add_argument("json"); p.add_argument("out"); p.set_defaults(fn=fn)
    args = ap.parse_args(); args.fn(args)


if __name__ == "__main__":
    main()
