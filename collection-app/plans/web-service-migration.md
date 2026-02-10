# CYD Shorts Converter - Web Service Migration

## Overview

Migrate the CYD Shorts Converter from a local Streamlit app to a public-facing web service. Two product models are considered: an **ephemeral downloader** (paste URL, convert, download) and an **account-based service** (saved collections, user profiles). The ephemeral model is the recommended starting point.

## Why Move Off Streamlit

The current Streamlit app works well as a local tool but has hard blockers for a public service:

| Requirement | Streamlit Support |
|---|---|
| Ad injection (AdSense, etc.) | No HTML control -- impossible |
| User authentication | No native support |
| SEO / discoverability | Single-page app, not crawlable |
| Custom branding / design | Very limited theming |
| Concurrent users at scale | Expensive (full Python process per session) |
| Background job processing | Blocks the user session |
| URL routing | Not supported |
| File downloads to browser | Limited (`st.download_button` only) |

## What We Keep

The existing service layer is cleanly decoupled from Streamlit and is fully reusable:

| File | What It Does | Reusable? |
|---|---|---|
| `src/services/conversion_service.py` | FFmpeg MJPEG pipeline | Yes -- no Streamlit dependency |
| `src/services/download_service.py` | yt-dlp video download | Yes -- no Streamlit dependency |
| `src/services/youtube_service.py` | Channel/video metadata fetching | Yes -- no Streamlit dependency |
| `src/models/` | Data classes (Video, Channel, Settings) | Yes -- plain Python dataclasses |
| `src/utils/ffmpeg_utils.py` | FFmpeg detection and helpers | Yes |
| `src/services/database.py` | SQLite persistence | Needs rework for multi-user |
| `src/components/` | Streamlit UI components | No -- replaced entirely |

## Product Model Decision

### Option A: Ephemeral Downloader (Recommended Start)

Users land on the site, paste a YouTube URL (or browse channels), pick conversion settings, and download the `.mjpeg` file. No account required. Monetize with ads.

**Pros:**
- Simplest to build and ship
- No auth, no user storage, no ongoing data responsibility
- Easy to monetize with display ads
- Low infrastructure cost (temp files auto-cleaned)
- Good for SEO ("youtube to mjpeg converter", "CYD video converter")

**Cons:**
- No user retention / return visits without new features
- Can't save collections or history
- Harder to build a community around

### Option B: Account-Based Service

Users create accounts, save channels, maintain collections, track conversion history.

**Pros:**
- User retention and repeat visits
- Can build community features (share collections, popular channels)
- Subscription potential (free tier with limits, paid for more)

**Cons:**
- Significantly more infrastructure (auth, user DB, file storage)
- Data responsibility (GDPR, user data management)
- Higher hosting costs (persistent storage per user)
- Longer time to ship

### Recommendation

**Start with Option A**, then layer on accounts (Option B) once there's traction. The backend architecture supports both -- adding auth and user-scoped storage later is straightforward.

---

## Technical Architecture

### Option A: Ephemeral Downloader

```
                    ┌─────────────────────────────────────┐
                    │         Frontend (Next.js)           │
                    │  ┌───────────────────────────────┐   │
                    │  │  Landing page (SEO-optimized) │   │
                    │  │  URL input + settings form    │   │
                    │  │  Progress polling UI           │   │
                    │  │  Download button               │   │
                    │  │  Ad placements (sidebar, top)  │   │
                    │  └───────────────────────────────┘   │
                    └──────────────┬──────────────────────┘
                                   │ REST API
                    ┌──────────────▼──────────────────────┐
                    │         Backend (FastAPI)            │
                    │  POST /api/convert                   │
                    │  GET  /api/status/{job_id}           │
                    │  GET  /api/download/{job_id}         │
                    │  GET  /api/presets                   │
                    └──────────────┬──────────────────────┘
                                   │ Task queue
                    ┌──────────────▼──────────────────────┐
                    │     Worker (Celery or arq)           │
                    │  ┌─────────────────────────────┐     │
                    │  │  download_service.py (reuse) │     │
                    │  │  conversion_service.py (reuse│)    │
                    │  └─────────────────────────────┘     │
                    │           │                │          │
                    │     yt-dlp download    FFmpeg convert │
                    └──────────────┬──────────────────────┘
                                   │
                    ┌──────────────▼──────────────────────┐
                    │         Storage                      │
                    │  Redis: job queue + status cache      │
                    │  /tmp/jobs/{job_id}/: temp files      │
                    │  Cron: cleanup files > 1 hour old     │
                    └──────────────────────────────────────┘
```

### Option B: Account-Based (future layer)

Adds on top of Option A:

```
                    ┌──────────────────────────────────────┐
                    │  Auth Provider (Clerk / Supabase)     │
                    └──────────────┬───────────────────────┘
                                   │
                    ┌──────────────▼───────────────────────┐
                    │  PostgreSQL                           │
                    │  ├── users (id, email, plan)          │
                    │  ├── collections (user_id, name)      │
                    │  ├── collection_items (video_id, ...)  │
                    │  └── conversion_history                │
                    └──────────────────────────────────────┘
                                   │
                    ┌──────────────▼───────────────────────┐
                    │  S3 / R2 (persistent file storage)   │
                    │  /{user_id}/{video_id}.mjpeg          │
                    └──────────────────────────────────────┘
```

---

## API Design (Option A)

### POST /api/convert

Start a conversion job.

```json
// Request
{
  "url": "https://www.youtube.com/shorts/abc123",
  "settings": {
    "width": 240,
    "height": 320,
    "quality": 5,
    "fps": 15,
    "brightness": 0.05,
    "contrast": 1.1,
    "aspect_mode": "fit"
  }
}

// Response
{
  "job_id": "uuid-here",
  "status": "queued",
  "estimated_seconds": 30
}
```

### GET /api/status/{job_id}

Poll job progress.

```json
// Response
{
  "job_id": "uuid-here",
  "status": "converting",     // queued | downloading | converting | done | error
  "progress": 65.5,
  "stage": "converting",
  "video_title": "Some Cool Short",
  "thumbnail_url": "https://i.ytimg.com/vi/abc123/hqdefault.jpg"
}
```

### GET /api/download/{job_id}

Download the converted file. Returns the `.mjpeg` file as a binary download.

Headers: `Content-Disposition: attachment; filename="video-title.mjpeg"`

### GET /api/presets

Return available device presets.

```json
{
  "presets": [
    { "name": "CYD 2.8\"", "width": 240, "height": 320, "quality": 5, "fps": 15 },
    { "name": "CYD 4\"", "width": 320, "height": 480, "quality": 5, "fps": 15 }
  ]
}
```

---

## Tech Stack

### Frontend

| Choice | Why |
|---|---|
| **Next.js** (React) | SSR for SEO, file-based routing, easy deployment on Vercel |
| **Tailwind CSS** | Fast styling, responsive design |
| **shadcn/ui** | Clean component library, easy to customize |

Alternatives considered:
- Plain HTML + HTMX: Simpler but harder to do rich progress UI and ad integration
- Astro: Good for static content but less natural for the interactive conversion flow

### Backend

| Choice | Why |
|---|---|
| **FastAPI** | Python (reuse existing services), async, auto-generated API docs |
| **Celery + Redis** | Background task queue for download/conversion jobs |
| **Redis** | Job status caching, rate limiting |

Alternatives considered:
- arq (lighter than Celery): Good for smaller scale, easier setup
- Django: More batteries but heavier than needed for an API

### Infrastructure

| Choice | Why |
|---|---|
| **VPS (Hetzner/DigitalOcean)** | Need CPU for FFmpeg, full control over system deps |
| **Docker Compose** | Single-command deployment of all services |
| **Caddy or nginx** | Reverse proxy, auto-SSL |
| **Cron cleanup job** | Delete temp files older than 1 hour |

**Not suitable:** Vercel/Netlify serverless (need long-running FFmpeg processes, system-level deps)

Frontend can still be on Vercel, calling the backend API on the VPS.

---

## Frontend Pages

### Landing / Converter Page (`/`)

The main page. SEO-optimized for "YouTube to MJPEG converter", "CYD video converter".

```
┌──────────────────────────────────────────────────────────────────┐
│  [Ad banner]                                                      │
├──────────────────────────────────────────────────────────────────┤
│                                                                    │
│  CYD Shorts Converter                                              │
│  Convert YouTube Shorts to MJPEG for your CYD display              │
│                                                                    │
│  ┌──────────────────────────────────────────────────────────┐      │
│  │  Paste YouTube URL here...                        [Go]   │      │
│  └──────────────────────────────────────────────────────────┘      │
│                                                                    │
│  Preset: [CYD 2.8"] [CYD 4"] [Custom]                             │
│                                                                    │
│  ┌─ Advanced Settings (collapsed) ──────────────────────────┐      │
│  │  Width: [240]  Height: [320]  Quality: [5]  FPS: [15]    │      │
│  │  Brightness: [0.05]  Contrast: [1.1]  Aspect: [Fit]      │      │
│  └──────────────────────────────────────────────────────────┘      │
│                                                                    │
│  ── Progress ────────────────────────────────────────────────      │
│  ┌──────────┐                                                      │
│  │ [thumb]  │  "Dance Tutorial #shorts"                            │
│  │          │  ████████████████░░░░░░  Converting... 72%           │
│  └──────────┘                                                      │
│                                                                    │
│  [Download .mjpeg]  (appears when done)                            │
│                                                                    │
├──────────────────────────────────────────────────────────────────┤
│  [Ad sidebar / bottom]                                             │
├──────────────────────────────────────────────────────────────────┤
│  What is CYD?  │  How to use  │  FAQ  │  GitHub                   │
│  (SEO content blocks)                                              │
└──────────────────────────────────────────────────────────────────┘
```

### About / How-To Page (`/about`)

Static content explaining CYD, the conversion process, compatible devices. Good for SEO.

---

## Implementation Phases

### Phase 1: FastAPI Backend (wrap existing services)

**Goal:** API that accepts a YouTube URL and returns a converted `.mjpeg` file.

**Tasks:**
- [ ] Set up FastAPI project structure
- [ ] Create job model and Redis-backed status store
- [ ] Wire up `POST /api/convert` endpoint
- [ ] Integrate existing `DownloadService` and `ConversionService` into Celery worker
- [ ] Implement `GET /api/status/{job_id}` with progress polling
- [ ] Implement `GET /api/download/{job_id}` with file streaming
- [ ] Add `GET /api/presets` endpoint
- [ ] Add rate limiting (3 jobs per hour per IP)
- [ ] Add temp file cleanup (cron or background task)
- [ ] Dockerfile for backend + worker + Redis

**Success criteria:**
- `curl -X POST /api/convert` with a YouTube URL → returns job_id
- Poll status until done → download working `.mjpeg` file
- Files auto-cleaned after 1 hour

### Phase 2: Frontend (Next.js)

**Goal:** Clean, ad-ready landing page with conversion UI.

**Tasks:**
- [ ] Next.js project with Tailwind + shadcn/ui
- [ ] Landing page with URL input and preset selector
- [ ] Advanced settings panel (collapsible)
- [ ] Job progress UI with polling
- [ ] Download button (triggers browser file download)
- [ ] SEO: meta tags, Open Graph, structured data
- [ ] Static content blocks (What is CYD, How to use, FAQ)
- [ ] Mobile responsive layout
- [ ] Ad placement zones (header, sidebar, between content)
- [ ] Error states (invalid URL, conversion failed, rate limited)

**Success criteria:**
- User can paste URL, click Go, wait for progress, download file
- Page loads fast, looks professional
- Works on mobile
- Ad zones render correctly

### Phase 3: Deployment & Infrastructure

**Goal:** Live on the internet, accessible to anyone.

**Tasks:**
- [ ] Docker Compose for backend (FastAPI + Celery + Redis)
- [ ] Deploy backend to VPS (Hetzner or DigitalOcean)
- [ ] Deploy frontend to Vercel (or same VPS behind nginx)
- [ ] Set up domain and SSL
- [ ] Set up Google AdSense (or alternative ad network)
- [ ] Basic monitoring (uptime, error rates)
- [ ] Log aggregation for debugging

**Success criteria:**
- App accessible at chosen domain
- End-to-end flow works publicly
- Ads rendering and generating impressions

### Phase 4: Hardening & Growth (post-launch)

**Tasks:**
- [ ] Analytics (Plausible or PostHog)
- [ ] Abuse prevention (block massive automated usage)
- [ ] Video length / size limits
- [ ] Queue depth management (reject jobs when too busy)
- [ ] Error tracking (Sentry)
- [ ] Social sharing (Open Graph previews)
- [ ] Batch conversion (paste multiple URLs)

### Phase 5: Accounts (Option B, if traction warrants it)

**Tasks:**
- [ ] Add auth provider (Clerk or Supabase Auth)
- [ ] PostgreSQL for user data
- [ ] User dashboard (conversion history, saved presets)
- [ ] Saved collections (bookmarked channels/videos)
- [ ] S3/R2 for persistent file storage
- [ ] Free vs paid tiers (rate limits, priority queue, no ads)

---

## Cost Estimates

### Ephemeral Downloader (Option A)

| Item | Monthly Cost |
|---|---|
| VPS (4 vCPU, 8GB RAM -- Hetzner CX31) | ~$15 |
| Domain | ~$1 |
| Vercel (frontend, free tier) | $0 |
| Redis (on same VPS) | $0 |
| Bandwidth (1TB included on Hetzner) | $0 |
| **Total** | **~$16/month** |

Can handle ~50-100 conversions/day on this setup. Scale by adding worker VPS nodes.

### Account-Based (Option B addition)

| Item | Additional Cost |
|---|---|
| Managed PostgreSQL (or self-host on VPS) | $0-15 |
| S3/R2 storage (Cloudflare R2 has free egress) | $0-5 |
| Auth provider (Clerk free tier) | $0 |
| **Additional total** | **~$0-20/month** |

---

## Revenue Considerations

### Ad Revenue (Option A)

- Display ads (Google AdSense): ~$1-5 RPM (revenue per 1000 page views)
- At 1000 conversions/day with ~3 page views each = 3000 views/day = 90K/month
- Estimated: **$90-450/month** at scale
- Niche audience (CYD/ESP32 hobbyists) may have higher RPM due to tech/maker demographic

### Subscription (Option B)

- Free tier: 3 conversions/day, ads shown
- Pro tier ($5/month): unlimited conversions, no ads, saved collections, priority queue
- Even 50 paying users = $250/month

---

## Risk Analysis

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| YouTube/yt-dlp breakage | Medium | High | Pin yt-dlp version, monitor releases, quick update pipeline |
| High server CPU from FFmpeg | High | Medium | Rate limiting, job queue depth limits, horizontal scaling |
| Abuse (bot traffic, excessive usage) | Medium | Medium | Rate limiting per IP, CAPTCHA on excessive use |
| Low traffic / no traction | Medium | Medium | Low cost base (~$16/mo), easy to sunset |
| DMCA / copyright concerns | Low | High | Only convert user-requested public videos, don't host/cache content |
| yt-dlp TOS concerns | Medium | Medium | App converts format for personal device use, similar to other converter sites |

---

## Migration Path from Current App

The Streamlit app continues to work as-is for local/personal use. The web service is a separate deployment that reuses the core services:

```
digital-photocard-collection/
├── app.py                          # Keep -- local Streamlit app still works
├── src/
│   ├── services/                   # Shared -- used by both Streamlit and FastAPI
│   │   ├── conversion_service.py
│   │   ├── download_service.py
│   │   └── youtube_service.py
│   ├── models/                     # Shared
│   └── components/                 # Streamlit only (stays for local use)
│
├── web/                            # NEW -- web service
│   ├── api/                        # FastAPI backend
│   │   ├── main.py
│   │   ├── routes/
│   │   │   └── convert.py
│   │   ├── worker.py               # Celery worker
│   │   ├── jobs.py                 # Job management
│   │   └── Dockerfile
│   ├── frontend/                   # Next.js frontend
│   │   ├── app/
│   │   │   ├── page.tsx            # Landing / converter
│   │   │   └── about/page.tsx
│   │   ├── components/
│   │   ├── package.json
│   │   └── Dockerfile
│   └── docker-compose.yml          # Full stack deployment
│
├── plans/
│   ├── youtube-shorts-mjpeg-converter.md   # Original plan
│   └── web-service-migration.md            # This document
└── requirements.txt
```

The key insight: **`src/services/` is the shared core**. Both the local Streamlit app and the web service import from it. No code duplication.

---

*Generated with Claude Code*
