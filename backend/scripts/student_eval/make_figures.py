from __future__ import annotations
import argparse
import json
from pathlib import Path
import matplotlib.pyplot as plt
from .common import run_dir

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    args = ap.parse_args()
    out = run_dir(args.run_id)
    figdir = out / "figures"
    figdir.mkdir(exist_ok=True)

    d = json.loads((out / "diagnosis_metrics.json").read_text(encoding="utf-8"))
    labels = ["Precision", "Recall", "F1"]
    vals = [d["overall"]["precision"], d["overall"]["recall"], d["overall"]["f1"]]
    fig, ax = plt.subplots(figsize=(7,4))
    ax.bar(labels, vals)
    ax.set_ylim(0, 1)
    ax.set_ylabel("Score")
    ax.set_title("Virtual Student Diagnosis Accuracy")
    for i, v in enumerate(vals):
        ax.text(i, v + 0.02, f"{v:.3f}", ha="center")
    fig.tight_layout()
    fig.savefig(figdir / "fig1_diagnosis_metrics.png", dpi=180)
    plt.close(fig)

    groups = ["weak", "medium", "strong"]
    vals = [d[g]["f1"] for g in groups]
    fig, ax = plt.subplots(figsize=(7,4))
    ax.bar(["Weak", "Medium", "Strong"], vals)
    ax.set_ylim(0, 1)
    ax.set_ylabel("F1")
    ax.set_title("Diagnosis F1 by Ability Group")
    for i, v in enumerate(vals):
        ax.text(i, v + 0.02, f"{v:.3f}", ha="center")
    fig.tight_layout()
    fig.savefig(figdir / "fig2_diagnosis_by_ability.png", dpi=180)
    plt.close(fig)

    a = out / "ablation_metrics.json"
    if a.exists():
        m = json.loads(a.read_text(encoding="utf-8"))
        vals = [m["full_mean"], m["baseline_mean"]]
        fig, ax = plt.subplots(figsize=(7,4))
        ax.bar(["Full ESA", "No-Personalization"], vals)
        ax.set_ylim(0, 10)
        ax.set_ylabel("Personalization Score (0-10)")
        ax.set_title("Personalization Ablation")
        for i, v in enumerate(vals):
            ax.text(i, v + 0.15, f"{v:.2f}", ha="center")
        fig.tight_layout()
        fig.savefig(figdir / "fig3_personalization_ablation.png", dpi=180)
        plt.close(fig)
    print(f"figures -> {figdir}")

if __name__ == "__main__":
    main()
