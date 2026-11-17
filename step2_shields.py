"""Step 2: run Prompt Shields (document attack detection) on the extracted text.

REST: POST {endpoint}/contentsafety/text:shieldPrompt?api-version=2024-09-01
Body: {"userPrompt": "...", "documents": ["...", ...]}
Limits: up to 5 documents per call, 10K characters in total, so long text is chunked.

Run:  python step2_shields.py              # uses Content Understanding text
      python step2_shields.py --source local
"""
import argparse

import requests

from common import RESULTS, TASK, load_env, env, manifest, extracted_text, save_json

API = "contentsafety/text:shieldPrompt?api-version=2024-09-01"
CHUNK, PER_CALL = 1900, 5   # 5 x 1,900 = 9,500 characters per call, under the 10K limit


def headers():
    key = env("FOUNDRY_KEY", "")
    if key:
        return {"Ocp-Apim-Subscription-Key": key, "Content-Type": "application/json"}
    from azure.identity import DefaultAzureCredential
    token = DefaultAzureCredential().get_token("https://cognitiveservices.azure.com/.default").token
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def shield(text: str, hdrs: dict, endpoint: str) -> dict:
    chunks = [text[i:i + CHUNK] for i in range(0, max(len(text), 1), CHUNK)]
    hits, user_attack = [], False
    for start in range(0, len(chunks), PER_CALL):
        batch = chunks[start:start + PER_CALL]
        r = requests.post(f"{endpoint.rstrip('/')}/{API}", headers=hdrs,
                          json={"userPrompt": TASK, "documents": batch}, timeout=30)
        r.raise_for_status()
        body = r.json()
        user_attack |= body["userPromptAnalysis"]["attackDetected"]
        hits += [start + i for i, a in enumerate(body["documentsAnalysis"]) if a["attackDetected"]]
    return {"doc_attack": bool(hits), "chunks": len(chunks), "hit_chunks": hits, "user_attack": user_attack}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["cu", "local"], default="cu")
    args = ap.parse_args()
    load_env()
    endpoint, hdrs = env("FOUNDRY_RESOURCE_ENDPOINT"), headers()

    results = {}
    print(f"{'id':<3} {'attack?':<8} {'detected':<9} {'chunks':<7} technique")
    for d in manifest():
        res = shield(extracted_text(d["id"], args.source), hdrs, endpoint)
        results[d["id"]] = res
        verdict = "OK" if res["doc_attack"] == d["attack"] else ("MISS" if d["attack"] else "FALSE+")
        print(f"{d['id']:<3} {str(d['attack']):<8} {str(res['doc_attack']):<9} {res['chunks']:<7} "
              f"{d['technique'][:55]}  [{verdict}]")
    save_json(RESULTS / f"shields_{args.source}.json", results)
    print(f"\nSaved {RESULTS}/shields_{args.source}.json")


if __name__ == "__main__":
    main()
