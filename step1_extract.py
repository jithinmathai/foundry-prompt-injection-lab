"""Step 1: extract text the way a pipeline would, and check which hidden payloads survive.

Two extractors are compared:
  local  - pypdf text + PDF metadata (what a naive Python pipeline sees)
  cu     - Content Understanding prebuilt-layout (OCR + layout, what Foundry sees)

Run:  python step1_extract.py            # both
      python step1_extract.py --local-only
"""
import argparse

from pypdf import PdfReader

from common import DOCS, EXTRACTED, load_env, env, manifest, save_json


def local_extract(path):
    reader = PdfReader(str(path))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    meta = {k.lstrip("/"): str(v) for k, v in (reader.metadata or {}).items()}
    return text, meta


def cu_client():
    from azure.ai.contentunderstanding import ContentUnderstandingClient
    from azure.core.credentials import AzureKeyCredential
    from azure.identity import DefaultAzureCredential
    key = env("FOUNDRY_KEY", "")
    cred = AzureKeyCredential(key) if key else DefaultAzureCredential()
    return ContentUnderstandingClient(endpoint=env("FOUNDRY_RESOURCE_ENDPOINT"), credential=cred)


def cu_extract(client, path, analyzer):
    poller = client.begin_analyze_binary(analyzer_id=analyzer, binary_input=path.read_bytes())
    result = poller.result()
    return result.contents[0].markdown if result.contents else ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--local-only", action="store_true")
    args = ap.parse_args()
    load_env()
    client = None if args.local_only else cu_client()
    analyzer = env("CU_ANALYZER", "prebuilt-layout")

    print(f"{'id':<3} {'technique':<62} {'human':<6} {'pypdf':<6} {'CU':<6}")
    for d in manifest():
        path = DOCS / d["file"]
        local_text, meta = local_extract(path)
        cu_md = cu_extract(client, path, analyzer) if client else None
        save_json(EXTRACTED / f"{d['id']}.json",
                  {"id": d["id"], "local_text": local_text, "metadata": meta, "cu_markdown": cu_md})

        if d["probe"]:
            in_local = d["probe"] in local_text or any(d["probe"] in v for v in meta.values())
            in_cu = "-" if cu_md is None else ("yes" if d["probe"] in cu_md else "no")
            print(f"{d['id']:<3} {d['technique'][:62]:<62} {('yes' if d['human_visible'] else 'NO'):<6} "
                  f"{('yes' if in_local else 'no'):<6} {in_cu:<6}")
        else:
            print(f"{d['id']:<3} {d['technique'][:62]:<62} {'(control)'}")
    print(f"\nSaved extracted text to {EXTRACTED}/")


if __name__ == "__main__":
    main()
