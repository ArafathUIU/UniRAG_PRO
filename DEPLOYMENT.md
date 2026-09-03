# 🚀 Deployment Guide — UniRAG PRO

This document compares deployment options (**Render vs. Vercel vs. Netlify**) and provides step-by-step instructions for deploying **UniRAG PRO** to production.

---

## 📊 Deployment Provider Comparison

| Platform | Best For | UniRAG PRO Support | Persistent Disk (ChromaDB) | Verdict |
| :--- | :--- | :--- | :--- | :--- |
| **Render** | **Full Python/Django Web Apps & Background Workers** | **100% Full Support** | **Yes (Disk attachment supported)** | **🏆 BEST CHOICE (Recommended)** |
| **Vercel** | Serverless Next.js / Node.js Apps | Serverless Functions Only | No (Read-only ephemeral storage) | ⚠️ Requires external vector DB migration |
| **Netlify** | Static HTML / Jamstack / SPA Frontends | Static Only (No Python WSGI) | No | ❌ Not suitable for Python Django WSGI |

---

## 🏆 Why Render is the Best Fit

1. **Native Python & WSGI Support**: Runs full `gunicorn` servers with multi-threading and Server-Sent Events (SSE) streaming (`POST /chat/stream/`).
2. **Persistent Storage for ChromaDB & SQLite**: Vector indices in `chroma_store/` and SQLite databases remain saved and persistent.
3. **Built-in Background Workers & Redis**: Easily scale Celery workers for automated web scraping.
4. **Generous Free Tier**: Free tier available for Web Services.

---

## ⚡ 1-Click Render Deployment Instructions

### Step 1: Push Code to GitHub
Ensure your repository `https://github.com/ArafathUIU/UniRAG_PRO.git` has the latest code.

### Step 2: Connect Render to GitHub
1. Log into **[https://dashboard.render.com/](https://dashboard.render.com/)**.
2. Click **New +** ➔ **Blueprint**.
3. Connect your GitHub account and select the **`UniRAG_PRO`** repository.

### Step 3: Configure Environment Variables
Render will automatically detect `render.yaml`. Enter your environment secrets:

- `GEMINI_API_KEY`: `AQ.Ab8...`
- `GROQ_API_KEY`: `gsk_oPX...`

### Step 4: Deploy
Click **Apply**. Render will automatically:
1. Build the Python 3.12 environment
2. Install dependencies from `requirements.txt`
3. Collect static assets and apply database migrations
4. Start the Gunicorn web server on `$PORT` on a public SSL URL (e.g. `https://unirag-pro.onrender.com`).

---

### 🔧 Manual Web Service Settings (If not using Blueprint)
If creating a Render **Web Service** manually:
- **Environment**: `Python 3`
- **Build Command**: `pip install -r requirements.txt && python manage.py collectstatic --noinput && python manage.py migrate`
- **Start Command**: `gunicorn config.wsgi:application --bind 0.0.0.0:$PORT --workers 1 --threads 2 --timeout 120`

> ⚠️ **Troubleshooting Status 137 (Out-Of-Memory Error)**:
> Render Free Tier provides 512MB RAM.
> 1. Do **NOT** use `python manage.py runserver` on Render (it runs StatReloader, spawning duplicate processes that exceed 512MB RAM).
> 2. Always use **`gunicorn config.wsgi:application --bind 0.0.0.0:$PORT --workers 1 --threads 2 --timeout 120`**. This limits Gunicorn memory footprint below 350MB RAM while binding properly to Render's dynamic `$PORT`.

---

## ℹ️ Alternative: Deploying Serverless Frontend to Vercel
If you want to host the frontend UI on Vercel while keeping the Python Django API hosted on Render:
1. Host the Django backend API on Render (e.g. `https://unirag-api.onrender.com`).
2. In `templates/chat.html`, set API fetch endpoints to your Render URL.
3. Deploy frontend to Vercel via `vercel --prod`.
