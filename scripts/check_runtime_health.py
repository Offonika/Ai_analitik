#!/usr/bin/env python3
"""Fail unless a cabinet runtime reports the expected healthy contour."""

from __future__ import annotations

import argparse
import json
from urllib.request import ProxyHandler, build_opener


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument(
        "--environment", choices=("production", "test"), required=True
    )
    parser.add_argument("--timeout", type=float, default=10.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    opener = build_opener(ProxyHandler({}))
    with opener.open(args.url, timeout=args.timeout) as response:
        if response.status != 200:
            raise SystemExit(f"health HTTP status is {response.status}")
        payload = json.load(response)
    if payload.get("status") != "ok":
        raise SystemExit(f"runtime health is {payload.get('status')!r}")
    if payload.get("runtimeEnvironment") != args.environment:
        raise SystemExit("runtime environment mismatch")
    backend_build = payload.get("backendBuildId")
    static_build = payload.get("staticBuildId")
    if not backend_build or backend_build != static_build:
        raise SystemExit("backend/static build mismatch")
    print(
        f"status=ok environment={args.environment} buildId={backend_build} "
        f"refreshActive={bool(payload.get('latestSourceRefreshActive'))}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
