# App

Minimal self-hosted reading library app (Kavita-like, simplified):
- no login/signup/auth
- opens directly to the library page
- scans local filesystem paths
- classifies files into sections by extension

## Run

```bash
python -m pip install -r requirements.txt
python run.py
```

Open http://localhost:5000

## Optional environment variables

- `APP_DB_PATH`: SQLite file location (default: `library.db`)
- `APP_SCAN_PATHS`: comma-separated scan paths to preload at startup

## Test

```bash
python -m unittest discover -s tests -v
```
