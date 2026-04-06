# React ERP Console

This directory contains the React frontend for the RevOps demo. It talks to the existing backend API:

- `GET /api/bootstrap`
- `GET /api/runtime`
- `POST /api/run`
- `POST /api/approval`
- `POST /api/reset`

## Run

Start the backend first in another terminal:

```bash
cd /Users/xuhaidong/Desktop/project/afu-agent
python3 run_erp_demo.py
```

Then install and run the React app:

```bash
cd /Users/xuhaidong/Desktop/project/afu-agent/web
npm install
npm run dev
```

Open the local Vite URL printed by the dev server, usually:

```bash
http://127.0.0.1:5173
```

## Notes

- Vite proxies `/api/*` to `http://127.0.0.1:8123`.
- The UI is designed as an ERP-style operator console, not a chat app.
- If you want to build a static production bundle, run `npm run build`.
