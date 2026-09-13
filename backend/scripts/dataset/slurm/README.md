# ESA evaluation job

The optimized job preserves existing prediction files by default. A run for
`nothink_ep10` writes `pred_nothink_ep10_opt.jsonl` and its companion reports;
it never deletes `pred_nothink_ep10.jsonl`.

Build the relocatable evaluation environment once, after changing the conda
environment:

```bash
backend/scripts/dataset/tools/pack_eval_env.sh
```

Validate configuration and fingerprints without allocating model memory:

```bash
ESA_EVAL_PREFLIGHT_ONLY=1 \
  backend/scripts/dataset/slurm/eval_one.sh nothink_ep10 93728
```

Submit the full evaluation:

```bash
sbatch backend/scripts/dataset/slurm/eval_one.sh nothink_ep10 93728
```

The job resumes only when both the evaluation-data fingerprint and the model
run fingerprint match. Change `ESA_EVAL_OUTPUT_TAG` to intentionally start a
separate result series.
