#!/usr/bin/env python3
"""Stage 1 of submission evaluation: parse the submissions CSV into registries.

Reads the final submissions CSV and produces three artifacts:

  - model_registry.json       finetuned-model registry entries, one per submission,
                              with model_name rewritten to team__basemodel__uid
  - base_model_registry.json  one entry per *unique* base model (entry copied from
                              the submission, with model_name / huggingface_id swapped)
  - base_models.txt           unique base-model HuggingFace links, one per line

Usage:
    python3 parse_submissions.py [submissions.csv] [output_dir]

Defaults: submissions.csv -> submission_files/final_submissions.csv
          output_dir      -> submission_files/
"""

import csv
import json
import sys
from pathlib import Path

# Column headers from the submission form. Matched by prefix because the form
# stores long help text inside the header strings.
COL_TEAM = "Team name"
COL_BASE_LINK_PREFIX = "Link to the base model on Huggingface"
COL_ENTRY_PREFIX = "Entry from the Model Registry"
COL_UID_PREFIX = "A unique identifier to distinguish this model version"

HF_PREFIX = "https://huggingface.co/"


def find_col(fieldnames, prefix):
    """Return the actual CSV header that starts with `prefix`, or None."""
    for name in fieldnames:
        if name.startswith(prefix):
            return name
    return None


def base_name_from_link(base_link):
    """Last path segment of an HF base link, lowercased (e.g. Qwen/Qwen3.5-2B -> qwen3.5-2b)."""
    hf_id = base_link.replace(HF_PREFIX, "").strip().strip("/")
    return hf_id.split("/")[-1].lower()


def base_id_from_link(base_link):
    """Full HF id (owner/name) from a base link, e.g. Qwen/Qwen3.5-2B."""
    return base_link.replace(HF_PREFIX, "").strip().strip("/")


def parse(csv_path, out_dir):
    csv_path = Path(csv_path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    finetuned = []
    base_models = []          # base registry entries, deduped by base name
    base_links = []           # unique base links, insertion order preserved
    seen_base_names = set()
    seen_base_links = set()

    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        col_base = find_col(reader.fieldnames, COL_BASE_LINK_PREFIX)
        col_entry = find_col(reader.fieldnames, COL_ENTRY_PREFIX)
        col_uid = find_col(reader.fieldnames, COL_UID_PREFIX)

        missing = [n for n, c in [
            ("base model link", col_base),
            ("model registry entry", col_entry),
            ("unique identifier", col_uid),
        ] if c is None]
        if COL_TEAM not in reader.fieldnames:
            missing.append("team name")
        if missing:
            sys.exit(f"ERROR: could not find columns in CSV: {', '.join(missing)}")

        for row in reader:
            team = (row.get(COL_TEAM) or "").strip()
            base_link = (row.get(col_base) or "").strip()
            uid = (row.get(col_uid) or "").strip()
            raw_entry = (row.get(col_entry) or "").strip()

            if not raw_entry:
                print(f"WARNING: no registry entry for team '{team}', skipping row", file=sys.stderr)
                continue
            if not base_link:
                print(f"WARNING: no base model link for team '{team}', skipping row", file=sys.stderr)
                continue

            try:
                entry = json.loads(raw_entry)
            except json.JSONDecodeError as e:
                print(f"WARNING: bad JSON entry for team '{team}': {e}", file=sys.stderr)
                continue

            base_name = base_name_from_link(base_link)

            # --- finetuned entry: rewrite model_name to team__basemodel__uid ---
            ft = dict(entry)
            ft["model_name"] = f"{team}__{base_name}__{uid}"
            ft["_team"] = team
            ft["_version"] = uid
            finetuned.append(ft)

            # --- base model link tracking (unique) ---
            if base_link not in seen_base_links:
                seen_base_links.add(base_link)
                base_links.append(base_link)

            # --- base model registry entry (unique): copy submission entry, swap name + id ---
            if base_name not in seen_base_names:
                seen_base_names.add(base_name)
                base = dict(entry)
                base["model_name"] = base_name
                base["huggingface_id"] = base_id_from_link(base_link)
                base["_is_base_model"] = True
                base.pop("_team", None)
                base.pop("_version", None)
                base_models.append(base)

    registry_path = out_dir / "model_registry.json"
    base_registry_path = out_dir / "base_model_registry.json"
    base_links_path = out_dir / "base_models.txt"

    with open(registry_path, "w", encoding="utf-8") as f:
        json.dump(finetuned, f, indent=2)
    with open(base_registry_path, "w", encoding="utf-8") as f:
        json.dump(base_models, f, indent=2)
    with open(base_links_path, "w", encoding="utf-8") as f:
        f.write("\n".join(base_links) + ("\n" if base_links else ""))

    print(f"Parsed {len(finetuned)} finetuned entries -> {registry_path}")
    print(f"Compiled {len(base_models)} unique base entries -> {base_registry_path}")
    print(f"Wrote {len(base_links)} unique base links -> {base_links_path}")


if __name__ == "__main__":
    csv_in = sys.argv[1] if len(sys.argv) > 1 else "submission_files/final_submissions.csv"
    out = sys.argv[2] if len(sys.argv) > 2 else "submission_files"
    parse(csv_in, out)
