# W3-D3 — Trần Đình Thông

Start Docker, then run `docker compose -f reproduction/docker-compose.yml up -d`. Start the local pipeline with `uv run python pipeline.py`. In another terminal run `uv run python capture_timeline.py --duration 24 --inject-after 3 --recover-after 12 --out timeline.json`; the capture invokes `reproduction/inject.sh` and `reproduction/recover.sh`. Query `/alerts` and `/rca` to regenerate the observed JSON files. Run `uv run python cost_model.py` for the three break-even examples.
