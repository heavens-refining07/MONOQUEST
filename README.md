# MONOQUEST · Celestial Sect

Public Flask and SQLite demo with temporary boards and bundled cultivation artwork.

## Deploy on Render

1. Upload the contents of this folder to the GitHub repository root. Check that
   `render.yaml` and `app.py` are visible on the repository's Code tab.
2. In Render, choose **New → Blueprint**, connect the repository and choose its
   default branch. Use `render.yaml` as the Blueprint path.
3. Review the single Free web service and select **Deploy Blueprint**.
4. Open the service URL. Check for the **Live Demo** banner and visit `/health`
   to confirm that it returns `"status": "ok"`.

Render generates the session secret. The demo stores temporary SQLite boards in
`/tmp/monoquest-demo` and uses one synchronous worker.

## Preview locally

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-render.txt
MONOQUEST_SECRET="$(.venv/bin/python -c 'import secrets; print(secrets.token_hex(32))')" \
MONOQUEST_DEMO_HTTPS=0 \
.venv/bin/flask --app app run --port 5007
```

Open http://127.0.0.1:5007. Demo progress can reset when the host restarts.
