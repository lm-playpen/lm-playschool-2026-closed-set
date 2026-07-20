OUTDIR="playpen_eval_runs/submissions_test"
INDOMAIN_DIR="$OUTDIR/clem_indomain"
OUTOFDOMAIN_DIR="$OUTDIR/clem_outofdomain"
SUMMARY_CSV="$OUTDIR/summary.csv"

python3 - "$SUMMARY_CSV" "$INDOMAIN_DIR/results.csv" "$OUTOFDOMAIN_DIR/results.csv" "$OUTDIR" <<'PYEOF'
import sys, json
import pandas as pd
from pathlib import Path

summary_path, indomain_path, outofdomain_path, outdir = sys.argv[1:5]

summary = pd.read_csv(summary_path)[["model", "team", "version"]].drop_duplicates()

rows = []
for model in summary["model"]:
    try:
        val = json.load(open(Path(outdir) / model / f"{model}.val.json"))
    except FileNotFoundError:
        val = {}
    rows.append({"model": model,
                "playpen_clemscore": val.get("clemscore"),
                "playpen_statscore": val.get("statscore")})
summary = summary.merge(pd.DataFrame(rows), on="model", how="left")

indomain = (pd.read_csv(indomain_path, index_col=0)
            .rename_axis("model").reset_index()
            .add_prefix("indomain_").rename(columns={"indomain_model": "model"}))
outofdomain = (pd.read_csv(outofdomain_path, index_col=0)
                .rename_axis("model").reset_index()
                .add_prefix("outofdomain_").rename(columns={"outofdomain_model": "model"}))

merged = summary.merge(indomain, on="model", how="left").merge(outofdomain, on="model", how="left")

cols = ["model", "team", "version", "playpen_clemscore", "playpen_statscore",
        "indomain_-, clemscore", "indomain_all, Average % Played", "indomain_all, Average Quality Score",
        "outofdomain_-, clemscore", "outofdomain_all, Average % Played", "outofdomain_all, Average Quality Score"]
present = [c for c in cols if c in merged.columns]
merged = merged[present + [c for c in merged.columns if c not in present]]

merged.to_csv(summary_path, index=False)
print("Summary updated with playpen, in-domain and out-of-domain scores")
PYEOF