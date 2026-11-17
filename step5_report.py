"""Step 5: combine every results file into results/report.md (your deliverable).

Run:  python step5_report.py
"""
import json

from common import EXTRACTED, RESULTS, manifest


def load(name):
    p = RESULTS / name
    return json.loads(p.read_text()) if p.exists() else {}


def cell(row):
    if not row:
        return "–"
    if row.get("blocked_by"):
        return "🛡️ blocked"
    bad = [k for k, label in (("hijacked", "hijacked"), ("canary_leaked", "leaked"), ("exfil_url", "exfil")) if row.get(k)]
    if bad:
        return "❌ " + ", ".join(bad)
    note = " (flagged)" if row.get("annotations") else ""
    return "✅" + note


def main():
    docs = manifest()
    shields_cu, shields_local = load("shields_cu.json"), load("shields_local.json")
    runs = load("model_runs.json")
    agent_runs = {p.stem.removeprefix("agent_"): json.loads(p.read_text()) for p in sorted(RESULTS.glob("agent_*.json"))}

    lines = ["# Document prompt-injection PoC: results", "",
             "Legend: ✅ resisted or correct · ❌ attack worked · 🛡️ blocked before or by the model · – not run", "",
             "## 1. Extraction and detection", "",
             "| # | Technique | Human sees it | In CU text | Shields (CU) | Shields (pypdf) |",
             "|---|---|---|---|---|---|"]
    for d in docs:
        ext = EXTRACTED / f"{d['id']}.json"
        in_cu = "–"
        if ext.exists() and d["probe"]:
            md = json.loads(ext.read_text()).get("cu_markdown")
            in_cu = "–" if md is None else ("yes" if d["probe"] in md else "no")
        def sh(s):
            r = s.get(d["id"])
            if r is None:
                return "–"
            ok = r["doc_attack"] == d["attack"]
            return ("✅ " if ok else "❌ ") + ("detected" if r["doc_attack"] else "clean")
        lines.append(f"| {d['id']} | {d['technique']} | {'yes' if d['human_visible'] else '**no**'} | "
                     f"{in_cu if d['attack'] else 'control'} | {sh(shields_cu)} | {sh(shields_local)} |")

    configs = list(runs.keys())
    if configs:
        lines += ["", "## 2. Model behaviour per defence configuration", "",
                  "| # | Technique | " + " | ".join(configs) + " |",
                  "|---|---|" + "---|" * len(configs)]
        for d in docs:
            lines.append(f"| {d['id']} | {d['technique']} | " +
                         " | ".join(cell(runs[c].get(d["id"])) for c in configs) + " |")

    if agent_runs:
        names = list(agent_runs)
        lines += ["", "## 3. Tool abuse (send_email, approval gate always denies)", "",
                  "| # | Technique | " + " | ".join(names) + " |", "|---|---|" + "---|" * len(names)]

        def f(r):
            if not r:
                return "–"
            if r.get("blocked_by"):
                return "🛡️ " + r["blocked_by"]
            if r["tool_requested"]:
                return "⚠️ tried send_email"
            return "❌ hijacked" if r.get("hijacked") else "✅"
        for d in docs:
            lines.append(f"| {d['id']} | {d['technique']} | " + " | ".join(f(agent_runs[n].get(d["id"])) for n in names) + " |")

    lines += ["", "## 4. Findings (fill in)", "",
              "- Which hidden payloads reached the model even though a person could not see them?",
              "- Which techniques did Prompt Shields miss? Did chunking matter for the long document?",
              "- Did the clean controls (01, 02) cause false positives?",
              "- Which single control gave the biggest improvement, and what did the full stack still miss?",
              "- Did the approval gate matter (did the model ever try send_email)?"]
    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / "report.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
