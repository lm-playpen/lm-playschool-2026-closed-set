#!/usr/bin/env bash

set -uo pipefail

# Usage:
# cd path/to/playpen
# bash path/to/eval_whole_submission.sh path/to/submissions.csv


# Don't forget to specify paths and GPU

INPUT_FILE="${1:-submission_files/final_submissions.csv}"
MODE="${2:-finetuned}"                                      # please choose finetuned or base
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SUBMISSION_FILES_DIR="${SCRIPT_DIR}/submission_files"
OUTDIR="playpen_eval_runs/submissions_test"

GPU="${GPU:-4}"
B="${B:-4}"                                                 # batch size
MAX_TOKENS="${MAX_TOKENS:-5000}"



echo "Parsing submissions..."
python3 "$SCRIPT_DIR/parse_submissions.py" "$INPUT_FILE" "$SUBMISSION_FILES_DIR"

if [[ "$MODE" == "base" ]]; then
      REGISTRY_FILE="${SUBMISSION_FILES_DIR}/base_model_registry.json"
      echo "Mode: base models"
  elif [[ "$MODE" == "finetuned" ]]; then
      REGISTRY_FILE="${SUBMISSION_FILES_DIR}/model_registry.json"
      echo "Mode: finetuned models"
  else
      echo "ERROR: unknown mode '$MODE'. Use 'finetuned' or 'base'."
      exit 1
  fi

if [[ ! -f "$REGISTRY_FILE" ]]; then
  echo "Registry file not found: $REGISTRY_FILE"
  exit 1
fi

cp "$REGISTRY_FILE" model_registry.json
echo "Copied registry to $(pwd)/model_registry.json"     #running from playpen

INDOMAIN_DIR="${OUTDIR}/clem_indomain" 
OUTOFDOMAIN_DIR="${OUTDIR}/clem_outofdomain" 
SUMMARY_CSV="${OUTDIR}/summary.csv"

mkdir -p "$OUTDIR"
mkdir -p "$INDOMAIN_DIR" "$OUTOFDOMAIN_DIR"

[[ ! -f "$SUMMARY_CSV" ]] && echo "model,team,version" > "$SUMMARY_CSV"   #add header (everything else will be filled in after testing)

echo "========================================="
echo "Playpen batch evaluation"
echo "Registry: $REGISTRY_FILE"
echo "Output:   $OUTDIR"
echo "========================================="

# jq required
if ! command -v jq &>/dev/null; then
  echo "ERROR: jq is required"
  exit 1
fi

NUM_MODELS=$(jq length "$REGISTRY_FILE")

echo "Found $NUM_MODELS models"
echo

for ((i=0; i<NUM_MODELS; i++)); do

    MODEL_NAME=$(jq -r ".[$i].model_name" "$REGISTRY_FILE")
    HF_ID=$(jq -r ".[$i].huggingface_id" "$REGISTRY_FILE")
    BACKEND=$(jq -r ".[$i].backend // \"huggingface_local\"" "$REGISTRY_FILE")
    TEAM=$(jq -r ".[$i]._team" "$REGISTRY_FILE")
    VERSION=$(jq -r ".[$i]._version // \"\"" "$REGISTRY_FILE")

    echo "========================================="
    echo "[$((i+1))/$NUM_MODELS] Evaluating:"
    echo "Model Name : $MODEL_NAME"
    echo "HF ID      : $HF_ID"
    echo "Backend    : $BACKEND"
    echo "========================================="

    MODEL_OUTDIR="${OUTDIR}/${MODEL_NAME}"

    if [[ -d "$MODEL_OUTDIR" ]]; then
          echo "Skipping $MODEL_NAME (results directory already exists: $MODEL_OUTDIR)"
          continue
    fi

    
    PLAYPEN_LOG="${MODEL_OUTDIR}/playpen_eval.log"
    INDOMAIN_LOG="${MODEL_OUTDIR}/clem_indomain.log"
    OUTOFDOMAIN_LOG="${MODEL_OUTDIR}/clem_outofdomain.log"

    mkdir -p "$MODEL_OUTDIR"
    set +e
 
  # playpen eval
    CUDA_VISIBLE_DEVICES="$GPU" playpen eval "$MODEL_NAME" \
         --suite all \
         -r "$MODEL_OUTDIR" \
          -L "$MAX_TOKENS" \
         2>&1 | tee "$PLAYPEN_LOG"
    PLAYPEN_EXIT=${PIPESTATUS[0]}

    [[ $PLAYPEN_EXIT -eq 0 ]] && echo -e "\nSUCCESS: $MODEL_NAME\n" || echo -e "\nFAILED: $MODEL_NAME (exit code
  $PLAYPEN_EXIT)\n"

     
  # in-domain
    CUDA_VISIBLE_DEVICES="$GPU" clem run -g  adventuregame clean_up codenames dond guesswhat imagegame \
         matchit_ascii taboo textmapworld textmapworld_graphreasoning \
         textmapworld_specificroom wordle wordle_withclue wordle_withcritic \
         privateshared referencegame -m "$MODEL_NAME" \
       -r "$INDOMAIN_DIR" -b "$B" -l "$MAX_TOKENS"   \
       2>&1 | tee "$INDOMAIN_LOG"

    #in-domain, adventuregame
    CUDA_VISIBLE_DEVICES={GPU} clem run -g adventuregame -i instances_trimmed.json \
    -m "$MODEL_NAME" \
       -r "$INDOMAIN_DIR" -b "$B" -l "$MAX_TOKENS" \
       2>&1 | tee -a "$INDOMAIN_LOG" 


   # in-domain, static benchmarks (trimmed set via -i)
    CUDA_VISIBLE_DEVICES="$GPU" clem run -g bbh cladder eqbench ifeval mmlu_pro \
       -i instances_trimmed.json -m "$MODEL_NAME" \
       -r "$INDOMAIN_DIR" -b "$B" -l "$MAX_TOKENS" \
       2>&1 | tee -a "$INDOMAIN_LOG" 

    #out of domain
    CUDA_VISIBLE_DEVICES="$GPU" clem run -g chronicle st_clean_up clockwork_courier cryptolect get_to_the_point \
         ta_mastermind ta_blackjack ta_frozen_lake ta_sokoban \
         toh_multi_turn wordle-crazy wordle-crazy_withclue wordle-crazy_withcritic  \
         -m "$MODEL_NAME" -r "$OUTOFDOMAIN_DIR" -b "$B" -l "$MAX_TOKENS"  \
         2>&1 | tee "$OUTOFDOMAIN_LOG"
    OUTOFDOMAIN_EXIT=${PIPESTATUS[0]}

    [[ $OUTOFDOMAIN_EXIT -eq 0 ]] && echo -e "\nSUCCESS out-of-domain: $MODEL_NAME\n" || echo -e "\nFAILED out-of-domain:
  $MODEL_NAME (exit code $OUTOFDOMAIN_EXIT)\n"

    echo "$MODEL_NAME,$TEAM,$VERSION" >> "$SUMMARY_CSV"

done

echo "========================================="
echo "Scoring and evaluating in-domain..."
clem score -g all -r "$INDOMAIN_DIR"
clem eval -r "$INDOMAIN_DIR"

echo "Scoring and evaluating out-of-domain..."
clem score -g all -r "$OUTOFDOMAIN_DIR"
clem eval -r "$OUTOFDOMAIN_DIR"

echo "Merging scores into summary..."
python3 - "$SUMMARY_CSV" "${INDOMAIN_DIR}/results.csv" "${OUTOFDOMAIN_DIR}/results.csv" "$OUTDIR" <<'PYEOF'
import sys, json
import pandas as pd
from pathlib import Path

summary_path, indomain_path, outofdomain_path, outdir = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]

summary = pd.read_csv(summary_path)
summary = summary[["model", "team", "version"]].drop_duplicates()

playpen_rows = []
for model in summary["model"]:
      val_file = Path(outdir) / model / f"{model}.val.json"
      try:
          with open(val_file) as f:
              val = json.load(f)
          playpen_rows.append({
              "model": model,
              "playpen_clemscore": val.get("clemscore"),
              "playpen_statscore": val.get("statscore"),
          })
      except FileNotFoundError:
          playpen_rows.append({"model": model, "playpen_clemscore": None, "playpen_statscore": None})

summary = summary.merge(pd.DataFrame(playpen_rows), on="model", how="left")

indomain = pd.read_csv(indomain_path, index_col=0)
indomain.index.name = "model"
indomain = indomain.reset_index().add_prefix("indomain_").rename(columns={"indomain_model": "model"})

outofdomain = pd.read_csv(outofdomain_path, index_col=0)
outofdomain.index.name = "model"
outofdomain = outofdomain.reset_index().add_prefix("outofdomain_").rename(columns={"outofdomain_model": "model"})

merged = summary.merge(indomain, on="model", how="left")
merged = merged.merge(outofdomain, on="model", how="left")

summary_cols = ["model", "team", "version", 
"playpen_clemscore", "playpen_statscore", "indomain_-, clemscore", "indomain_all, Average % Played",
 "indomain_all, Average Quality Score", "outofdomain_-, clemscore", "outofdomain_all, Average % Played", "outofdomain_all, Average Quality Score"]
present = [c for c in summary_cols if c in merged.columns]           
remaining = [c for c in merged.columns if c not in present]           
merged = merged[present + remaining]

merged.to_csv(summary_path, index=False)
print("Summary updated with in-domain and out-of-domain scores")
PYEOF


echo "========================================="
echo "All evaluations complete"
echo "Results stored in:"
echo "$OUTDIR"
echo "========================================="

