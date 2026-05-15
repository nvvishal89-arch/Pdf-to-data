# How to run the ERP SQ Intelligence Engine

## 1. Install dependencies

From the project root (`Pdf to data`):

```powershell
pip install -r requirements.txt
```

(Use a virtual environment if you prefer: `python -m venv .venv` then `.\.venv\Scripts\Activate.ps1` on Windows.)

## 2. Start the server

```powershell
cd "c:\Users\pc\Desktop\Vision\Pdf to data"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

## 3. Open the UI

In your browser go to:

- **http://127.0.0.1:8000/ui**

From there you can upload an SQ PDF, parse it, view/export data, generate view images (DALL·E), and generate construction drawings.

## 4. GenCAD (AI 3D → 2D drawings)

Construction drawings can use **GenCAD** when it is set up. By default the app uses **built-in GenCAD** at `/gencad` (no separate process):

- Leave the **GenCAD URL** field **empty** in the UI so it uses `http://127.0.0.1:8000/gencad`.
- If GenCAD is not configured, the app falls back to image vectorization (DXF/SVG/PNG with dimensions on PNG).

Full GenCAD setup (checkpoints, conda env, pythonocc):

- See **[gencad_service/README.md](gencad_service/README.md)** for clone, checkpoints, conda env, and running with inference.

## 5. Optional: OpenAI for view images

To generate Front/Side/Top/Isometric images with DALL·E 3, set **OPENAI_API_KEY** (e.g. in the UI or in the environment) before clicking "Generate all view images".
