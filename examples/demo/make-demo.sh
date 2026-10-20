#!/usr/bin/env bash
# Build a small, deliberately messy Python project ("weather-cli") to try Libraryan on.
# Usage: make-demo.sh <target-dir>   (target must not exist)
# Deterministic: fixed file contents, author and commit dates.
set -euo pipefail

target=${1:?usage: make-demo.sh <target-dir>}
[ -e "$target" ] && { echo "refusing: $target exists" >&2; exit 1; }
mkdir -p "$target"
cd "$target"

git init -q -b main
git config user.name narek-mn
git config user.email narek-mn@users.noreply.github.com

commit() {  # commit <date> <message>
  git add -A
  GIT_AUTHOR_DATE="$1T10:00:00+00:00" GIT_COMMITTER_DATE="$1T10:00:00+00:00" git commit -q -m "$2"
}

mkdir -p weather_cli docs tests

# --- commit 1: first version -------------------------------------------------
cat > pyproject.toml <<'EOF'
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "weather-cli"
version = "0.2.0"
description = "Current weather and forecasts in your terminal"
requires-python = ">=3.8"
dependencies = ["requests>=2.28"]

[project.scripts]
weather = "weather_cli.cli:main"
EOF

cat > weather_cli/__init__.py <<'EOF'
__version__ = "0.2.0"
EOF

cat > weather_cli/api.py <<'EOF'
import os

import requests

BASE_URL = "https://api.openweathermap.org/data/2.5"


def api_key() -> str:
    key = os.environ.get("OWM_API_KEY")
    if not key:
        raise SystemExit("weather: set OWM_API_KEY")
    return key


def current(city: str, units: str = "metric") -> dict:
    r = requests.get(f"{BASE_URL}/weather", params={"q": city, "units": units, "appid": api_key()}, timeout=10)
    r.raise_for_status()
    return r.json()
EOF

cat > weather_cli/cli.py <<'EOF'
import argparse

from . import api


def main() -> None:
    p = argparse.ArgumentParser(prog="weather")
    p.add_argument("city")
    p.add_argument("--fahrenheit", action="store_true", help="show temperatures in Fahrenheit")
    args = p.parse_args()
    data = api.current(args.city, "imperial" if args.fahrenheit else "metric")
    print(f"{data['name']}: {data['main']['temp']:.0f} degrees, {data['weather'][0]['description']}")
EOF

cat > README.md <<'EOF'
# weather-cli

Current weather and forecasts in your terminal.

## Install

Requires Python 3.8+.

```
pip install -e .
```

## Usage

Get an API key from openweathermap.org and export it:

```
export OWM_API_KEY=your-key
```

Then:

```
weather London
weather "New York" --fahrenheit
```

## Forecast

Show a 5-day forecast with `--forecast 5`.

## Development

Run `python setup.py develop`, then hack away.
EOF

cat > docs/setup-old.md <<'EOF'
# Setup (old)

1. Clone the repo.
2. `pip install requests`
3. `python setup.py install`
4. `export OWM_API_KEY=...` (ask Sam for the team key)
5. Run `weather Paris`.

If you get SSL errors on the office network, set `REQUESTS_CA_BUNDLE`.
EOF
commit 2024-03-04 "Initial weather CLI"

# --- commit 2: cache + dev notes --------------------------------------------
cat > weather_cli/cache.py <<'EOF'
import json
import time
from pathlib import Path

CACHE_DIR = Path.home() / ".cache" / "weather-cli"
TTL_SECONDS = 600


def get(key: str):
    f = CACHE_DIR / f"{key}.json"
    if not f.exists():
        return None
    if time.time() - f.stat().st_mtime > TTL_SECONDS:
        return json.loads(f.read_text())
    return None


def put(key: str, data: dict) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (CACHE_DIR / f"{key}.json").write_text(json.dumps(data))
EOF

cat > NOTES.md <<'EOF'
# notes

- free OWM tier = 60 calls/min, 1M/month. we hit the limit during the demo day, hence the cache
- cache lives in ~/.cache/weather-cli, 10 min TTL
- city names with spaces must be quoted in the shell!!
- maybe switch to open-meteo? (no key needed)
- TODO: ask Sam re team key rotation
EOF
commit 2024-03-18 "Cache API responses on disk"

# --- commit 3: meeting notes and todo list -----------------------------------
cat > meeting-notes-2024.md <<'EOF'
# Meeting notes 2024

## 2024-04-02

Attendees: Sam, Priya, Lee

- Decided: drop `requests` and use `urllib` from the stdlib, so `pipx install` has zero deps.
- Decided: `--fahrenheit` becomes `--units metric|imperial` (Priya: imperial also changes wind speed to mph).
- Lee to look at forecast support (5-day endpoint).
- Next meeting: TBD

## 2024-05-14

- Forecast shipped as `--days`, max 5 days (API limit on the free tier).
- Env var renamed to `WEATHER_API_KEY` because OWM_ looked vendor-specific.
- Nobody owns the docs. Someone should fix the README.
EOF

cat > TODO_old.md <<'EOF'
# TODO

- [x] cache responses
- [ ] --forecast flag
- [ ] colors
- [ ] JSON output for scripts
- [ ] publish to PyPI
- [ ] fix README
EOF
commit 2024-04-03 "Add meeting notes and todo list"

# --- commit 4: stdlib HTTP, --units, --days ----------------------------------
cat > weather_cli/api.py <<'EOF'
import json
import os
import urllib.parse
import urllib.request

from . import cache

BASE_URL = "https://api.openweathermap.org/data/2.5"


def api_key() -> str:
    key = os.environ.get("OWM_API_KEY")
    if not key:
        raise SystemExit("weather: set OWM_API_KEY")
    return key


def _get(path: str, **params) -> dict:
    key = path + "?" + urllib.parse.urlencode(sorted(params.items()))
    hit = cache.get(urllib.parse.quote(key, safe=""))
    if hit is not None:
        return hit
    url = f"{BASE_URL}/{path}?" + urllib.parse.urlencode({**params, "appid": api_key()})
    with urllib.request.urlopen(url, timeout=10) as r:
        data = json.load(r)
    cache.put(urllib.parse.quote(key, safe=""), data)
    return data


def current(city: str, units: str = "metric") -> dict:
    return _get("weather", q=city, units=units)


def forecast(city: str, days: int, units: str = "metric") -> list[dict]:
    data = _get("forecast", q=city, units=units, cnt=days * 8)
    return data["list"][::8]
EOF

cat > weather_cli/cli.py <<'EOF'
import argparse

from . import api


def main() -> None:
    p = argparse.ArgumentParser(prog="weather")
    p.add_argument("city")
    p.add_argument("--units", choices=["metric", "imperial"], default="metric")
    p.add_argument("--days", type=int, default=0, help="forecast for N days (1-5)")
    args = p.parse_args()
    if args.days:
        if not 1 <= args.days <= 5:
            p.error("--days must be between 1 and 5")
        for day in api.forecast(args.city, args.days, args.units):
            print(f"{day['dt_txt'][:10]}  {day['main']['temp']:.0f}  {day['weather'][0]['description']}")
        return
    data = api.current(args.city, args.units)
    print(f"{data['name']}: {data['main']['temp']:.0f} degrees, {data['weather'][0]['description']}")
EOF

sed -i 's/^dependencies = \["requests>=2.28"\]$/dependencies = []/; s/^version = "0.2.0"/version = "0.3.0"/; s/>=3.8/>=3.10/' pyproject.toml
echo '__version__ = "0.3.0"' > weather_cli/__init__.py

cat > CHANGELOG-draft.md <<'EOF'
# Changelog (draft, not released yet)

## 0.3.0 (unreleased?)

- `--fahrenheit` replaced by `--units imperial`
- `--forecast` is now `--days N` (1-5)
- no more `requests` dependency
- needs Python 3.10 now

## 0.4.0

- ???
EOF
commit 2024-05-10 "Use urllib, add --units and --days"

# --- commit 5: env var rename + agent notes ----------------------------------
sed -i 's/OWM_API_KEY/WEATHER_API_KEY/g' weather_cli/api.py
cat > CLAUDE.md <<'EOF'
# Instructions for Claude

- Run tests with `pytest -q`.
- Don't change BASE_URL in api.py, the team key only works against OWM 2.5.
- API key is in `OWM_API_KEY`.
- Keep the CLI dependency-free (stdlib only).

Also: format with black, line length 110.

When you change a flag, update the README. (nobody does)
EOF
commit 2024-05-14 "Rename API key env var to WEATHER_API_KEY"

# --- commit 6: JSON output, formatting, tests --------------------------------
cat > weather_cli/format.py <<'EOF'
import json

UNIT_SYMBOL = {"metric": "°C", "imperial": "°F"}
WIND_UNIT = {"metric": "m/s", "imperial": "mph"}


def line(data: dict, units: str) -> str:
    return (f"{data['name']}: {data['main']['temp']:.0f}{UNIT_SYMBOL[units]}, "
            f"{data['weather'][0]['description']}, wind {data['wind']['speed']:.0f} {WIND_UNIT[units]}")


def as_json(data: dict, units: str) -> str:
    return json.dumps({"city": data["name"], "temp": data["main"]["temp"], "units": units,
                       "description": data["weather"][0]["description"]})
EOF

cat > weather_cli/cli.py <<'EOF'
import argparse

from . import api, format


def main() -> None:
    p = argparse.ArgumentParser(prog="weather")
    p.add_argument("city")
    p.add_argument("--units", choices=["metric", "imperial"], default="metric")
    p.add_argument("--days", type=int, default=0, help="forecast for N days (1-5)")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    args = p.parse_args()
    if args.days:
        if not 1 <= args.days <= 5:
            p.error("--days must be between 1 and 5")
        for day in api.forecast(args.city, args.days, args.units):
            print(f"{day['dt_txt'][:10]}  {day['main']['temp']:.0f}  {day['weather'][0]['description']}")
        return
    data = api.current(args.city, args.units)
    print(format.as_json(data, args.units) if args.json else format.line(data, args.units))
EOF

cat > tests/test_format.py <<'EOF'
from weather_cli import format

DATA = {"name": "Oslo", "main": {"temp": 3.4}, "weather": [{"description": "light snow"}], "wind": {"speed": 4.2}}


def test_line_metric():
    assert format.line(DATA, "metric") == "Oslo: 3°C, light snow, wind 4 m/s"


def test_json():
    assert '"city": "Oslo"' in format.as_json(DATA, "metric")
EOF

sed -i 's/^version = "0.3.0"/version = "0.4.0"/' pyproject.toml
echo '__version__ = "0.4.0"' > weather_cli/__init__.py
printf '# Ideas\n\nTBD\n' > docs/ideas.md
commit 2024-06-20 "Add --json output and tests"

echo "demo project ready: $target"
