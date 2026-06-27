"""CLI runner for offline ML training.

Usage:
    uv run python scripts/ml_train.py [--security-id ID] [--timeframe TF]
        [--days N] [--version VER] [--head HEAD]
"""
import argparse
import sys

p = argparse.ArgumentParser(description="Train the candlestick-ml-signals LightGBM model")
p.add_argument("--security-id", default="13", help="Security ID (default: 13 = NIFTY)")
p.add_argument("--timeframe", default="15m", help="Bar timeframe (default: 15m)")
p.add_argument("--days", type=int, default=90, help="Training window in days (default: 90)")
p.add_argument("--version", default=None, help="Artifact version string (default: auto)")
p.add_argument("--head", default="directional", help="Label head: directional|expiry (default: directional)")
args = p.parse_args()

from pdp.ml.train import train  # noqa: E402

ver = train(args.security_id, args.timeframe, args.days, args.version, args.head)
print(f"Artifact written: {ver}", file=sys.stderr)
