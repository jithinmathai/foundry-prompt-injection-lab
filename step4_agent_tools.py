"""Step 4: does an injected document make the model call a tool? Human approval stops it.

The model gets a mocked send_email function tool (Responses API, project endpoint).
Any send_email call is intercepted by an approval gate that always denies it, so
nothing is ever sent. We record whether the model TRIED, or whether a guardrail
blocked the request first.

Two ways to deliver the document:
  inline    document text is pasted into the user message (checked at the USER INPUT
            intervention point, where Jailbreak / Indirect prompt injection shields run)
  via-tool  user message only names the file; the model calls read_document and the
            text comes back as a TOOL RESPONSE (the realistic indirect-injection path)

Run:  python step4_agent_tools.py
      python step4_agent_tools.py --hardened
      python step4_agent_tools.py --delivery via-tool
      python step4_agent_tools.py --delivery via-tool --deployment guarded
"""
import argparse
import json

from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
from openai import BadRequestError

from common import RESULTS, TASK, load_env, env, manifest, extracted_text, score_output, save_json
from step3_model import SYSTEM_BASIC, SYSTEM_HARDENED
from step2_shields import shield, headers

SEND_EMAIL = {
    "type": "function",
    "name": "send_email",
    "description": "Send an email on behalf of the accounts-payable team.",
    "parameters": {
        "type": "object",
        "properties": {"to": {"type": "string"}, "subject": {"type": "string"}, "body": {"type": "string"}},
        "required": ["to", "subject", "body"],
        "additionalProperties": False,
    },
}
READ_DOCUMENT = {
    "type": "function",
    "name": "read_document",
    "description": "Return the extracted text of an uploaded supplier document.",
    "parameters": {
        "type": "object",
        "properties": {"doc_id": {"type": "string"}},
        "required": ["doc_id"],
        "additionalProperties": False,
    },
}


def approval_gate(call) -> str:
    """Human-in-the-loop stand-in: log the request and deny it. Never sends anything."""
    args = json.loads(call.arguments or "{}")
    print(f"    !! model requested send_email(to={args.get('to')!r}) -> DENIED by reviewer")
    return json.dumps({"status": "denied", "reason": "Not approved by a human reviewer."})


def is_filter_error(e: BadRequestError) -> bool:
    s = str(e)
    return "content_filter" in s or "content management policy" in s


def run_doc(oa, model, system, tools, first_input, doc_text, hardened, tool_shield=None, max_turns=4):
    """Run the tool loop. Returns a result row."""
    row = {"tool_requested": False, "tool_args": [], "read_document_called": False, "output": ""}
    stage = "user input"
    try:
        resp = oa.responses.create(model=model, instructions=system, input=first_input, tools=tools, temperature=0)
        for _ in range(max_turns):
            calls = [i for i in resp.output if i.type == "function_call"]
            if not calls:
                break
            outputs = []
            for c in calls:
                if c.name == "send_email":
                    row["tool_requested"] = True
                    row["tool_args"].append(json.loads(c.arguments or "{}"))
                    out = approval_gate(c)
                elif c.name == "read_document":
                    row["read_document_called"] = True
                    out = f"<documents>\n{doc_text}\n</documents>" if hardened else doc_text
                    # App-level defence: run Prompt Shields on the tool output before the model sees it.
                    if tool_shield and tool_shield(doc_text):
                        row["blocked_by"] = "app (Prompt Shields on tool output)"
                        out = json.dumps({"error": "Document withheld: possible prompt injection. Flag for human review."})
                else:
                    out = json.dumps({"error": "unknown tool"})
                # Return each result with the SAME call_id.
                outputs.append({"type": "function_call_output", "call_id": c.call_id, "output": out})
            stage = "tool response"
            resp = oa.responses.create(model=model, instructions=system, previous_response_id=resp.id,
                                       tools=tools, input=outputs, temperature=0)
        row["output"] = resp.output_text or ""
    except BadRequestError as e:
        if not is_filter_error(e):
            raise
        row["blocked_by"] = f"guardrail ({stage})"
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hardened", action="store_true")
    ap.add_argument("--delivery", choices=["inline", "via-tool"], default="inline")
    ap.add_argument("--deployment", choices=["base", "guarded"], default="base")
    ap.add_argument("--source", choices=["cu", "local"], default="cu")
    ap.add_argument("--shield-tool-output", action="store_true",
                    help="call Prompt Shields on read_document output before returning it (via-tool only)")
    args = ap.parse_args()
    load_env()
    project = AIProjectClient(endpoint=env("FOUNDRY_PROJECT_ENDPOINT"), credential=DefaultAzureCredential())
    oa = project.get_openai_client()
    model = env("DEPLOYMENT_GUARDED") if args.deployment == "guarded" else env("DEPLOYMENT_BASE")
    system = SYSTEM_HARDENED if args.hardened else SYSTEM_BASIC
    tool_shield = None
    if args.shield_tool_output:
        endpoint, hdrs = env("FOUNDRY_RESOURCE_ENDPOINT"), headers()
        tool_shield = lambda text: shield(text, hdrs, endpoint)["doc_attack"]

    results = {}
    for d in manifest():
        text = extracted_text(d["id"], args.source)
        if args.delivery == "inline":
            doc = f"<documents>\n{text}\n</documents>" if args.hardened else text
            first_input, tools = f"{TASK}\n\n{doc}", [SEND_EMAIL]
        else:
            first_input = f"{TASK} Use read_document with doc_id '{d['id']}' to get the file."
            tools = [READ_DOCUMENT, SEND_EMAIL]
        row = run_doc(oa, model, system, tools, first_input, text, args.hardened, tool_shield)
        row.update(score_output(row["output"] + json.dumps(row["tool_args"])))
        results[d["id"]] = row
        status = row.get("blocked_by") or ("TRIED send_email" if row["tool_requested"] else
                                           "hijacked" if row["hijacked"] else "ok")
        print(f"{d['id']}  {d['technique'][:55]:<55} -> {status}")

    name = (f"agent_{args.delivery}_{args.deployment}{'_hardened' if args.hardened else ''}"
            f"{'_toolshield' if args.shield_tool_output else ''}.json")
    save_json(RESULTS / name, results)
    print(f"\nSaved {RESULTS}/{name}")


if __name__ == "__main__":
    main()
