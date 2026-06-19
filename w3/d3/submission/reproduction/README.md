# AWS S3 2017 Operator-Guardrail Reproduction

This minimal stack models three S3-like subsystems: billing, index, and placement. Start with `docker compose up -d`. The command `bash inject.sh` represents a maintenance interface whose missing target scope stops all three services, while `bash recover.sh` restores them. From the parent directory, `capture_timeline.py` records baseline state, injection, pipeline alerts, and recovery into `timeline.json`.
