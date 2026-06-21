import os
import uuid
import shutil
import glob
import time
import asyncio
import json
from datetime import datetime
from dotenv import load_dotenv
from typing import Dict, Optional, List
from contextlib import asynccontextmanager
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# YouTube Studio specific backend modules
from youtube_upload import is_authenticated, get_auth_url, handle_callback, exchange_code_manual, upload_video
from thumbnail import analyze_video_for_titles, refine_titles, generate_thumbnail, generate_youtube_description

load_dotenv()

# Constants
UPLOAD_DIR = "uploads"
OUTPUT_DIR = "output"
GAMES_FILE = "data/games.json"
THUMBNAILS_DIR = os.path.join(OUTPUT_DIR, "thumbnails")
SESSIONS_DIR = "data/sessions"

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(THUMBNAILS_DIR, exist_ok=True)
os.makedirs(SESSIONS_DIR, exist_ok=True)

DISABLE_YOUTUBE_URL = os.environ.get("DISABLE_YOUTUBE_URL", "false").lower() in ("1", "true", "yes")

# Application State
thumbnail_sessions: Dict[str, Dict] = {}
publish_jobs: Dict[str, Dict] = {}  # {publish_id: {status, result, error}}

def _session_path(session_id: str) -> str:
    return os.path.join(SESSIONS_DIR, f"{session_id}.json")

def _save_session(session_id: str):
    """Persist a thumbnail session to disk as JSON."""
    if session_id not in thumbnail_sessions:
        return
    session = thumbnail_sessions[session_id]
    # Make a serializable copy (exclude non-JSON-safe fields like events)
    safe = {k: v for k, v in session.items() if k not in ("transcript_event",)}
    try:
        with open(_session_path(session_id), "w") as f:
            json.dump(safe, f, indent=2, default=str)
    except Exception as e:
        print(f"⚠️ Failed to save session {session_id}: {e}")

def _load_sessions():
    """Load all persisted sessions from disk into thumbnail_sessions."""
    loaded = 0
    if not os.path.exists(SESSIONS_DIR):
        return
    for fname in os.listdir(SESSIONS_DIR):
        if not fname.endswith(".json"):
            continue
        sid = fname[:-5]
        try:
            with open(os.path.join(SESSIONS_DIR, fname)) as f:
                data = json.load(f)
            thumbnail_sessions[sid] = data
            loaded += 1
        except Exception as e:
            print(f"⚠️ Failed to load session {sid}: {e}")
    if loaded:
        print(f"📂 Loaded {loaded} saved session(s)")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Load persisted data from disk
    _load_sessions()
    _load_schedules()
    # Start background scheduler checking
    schedule_task = asyncio.create_task(_check_due_publishes())
    yield

app = FastAPI(lifespan=lifespan)

# Enable CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files for serving videos (used to play source videos in Studio)
app.mount("/videos", StaticFiles(directory=UPLOAD_DIR), name="videos")

# Mount static files for serving thumbnails
app.mount("/thumbnails", StaticFiles(directory=THUMBNAILS_DIR), name="thumbnails")

@app.get("/api/config")
async def get_config():
    return {"youtubeUrlEnabled": not DISABLE_YOUTUBE_URL}

# --- Thumbnail Studio Endpoints ---

@app.post("/api/thumbnail/upload")
async def thumbnail_upload(
    file: Optional[UploadFile] = File(None),
    url: Optional[str] = Form(None),
):
    """Upload video and start background transcription immediately."""
    if not url and not file:
        raise HTTPException(status_code=400, detail="Must provide URL or File")

    session_id = str(uuid.uuid4())
    transcript_event = asyncio.Event()

    # Save file if uploaded directly
    video_path = None
    if file:
        video_path = os.path.join(UPLOAD_DIR, f"thumb_{session_id}_{file.filename}")
        with open(video_path, "wb") as buffer:
            content = await file.read()
            buffer.write(content)

    # Initialize session
    thumbnail_sessions[session_id] = {
        "video_path": video_path,
        "transcript_event": transcript_event,
        "transcript_ready": False,
        "transcript": None,
        "transcript_segments": [],
        "video_duration": 0,
        "language": "en",
        "context": "",
        "titles": [],
        "conversation": [],
        "_url": url,  # Store URL for deferred download
    }

    async def run_background_whisper():
        """Transcribe video in the background."""
        try:
            nonlocal video_path
            # Check if we need to download from URL first
            if url:
                from main import download_youtube_video
                print(f"📥 [Thumbnail] Downloading YouTube URL in background: {url}")
                video_path, _ = download_youtube_video(url, UPLOAD_DIR)
                thumbnail_sessions[session_id]["video_path"] = video_path

            # Now run transcription
            from main import transcribe_video
            print(f"🎙️ [Thumbnail] Transcribing video in background: {video_path}")
            
            # Since transcribe_video is blocking, run in executor
            loop = asyncio.get_running_loop()
            transcript = await loop.run_in_executor(None, transcribe_video, video_path)
            
            segments = transcript.get("segments", [])
            video_duration = segments[-1]["end"] if segments else 0
            
            thumbnail_sessions[session_id].update({
                "transcript_ready": True,
                "transcript": transcript,
                "transcript_segments": segments,
                "video_duration": video_duration,
                "language": transcript.get("language", "en"),
            })
            _save_session(session_id)
            print(f"✅ [Thumbnail] Transcription complete for session {session_id}")
        except Exception as e:
            print(f"❌ [Thumbnail] Background transcription failed: {e}")
            thumbnail_sessions[session_id]["transcript_error"] = str(e)
        finally:
            transcript_event.set()

    asyncio.create_task(run_background_whisper())
    _save_session(session_id)
    return {"session_id": session_id}

@app.post("/api/thumbnail/analyze")
async def thumbnail_analyze(
    request: Request,
    file: Optional[UploadFile] = File(None),
    url: Optional[str] = Form(None),
    session_id: Optional[str] = Form(None),
    game: Optional[str] = Form(None),
    x_gemini_key: Optional[str] = Header(None, alias="X-DeepSeek-Key")
):
    """Analyze a video and suggest viral YouTube titles."""
    api_key = x_gemini_key
    if not api_key:
        raise HTTPException(status_code=400, detail="Missing X-DeepSeek-Key header")

    pre_transcript = None

    # Check for pre-existing session with background Whisper
    if session_id and session_id in thumbnail_sessions:
        session = thumbnail_sessions[session_id]

        # Wait for background Whisper to complete
        transcript_event = session.get("transcript_event")
        if transcript_event:
            print(f"⏳ [Thumbnail] Waiting for background Whisper to finish...")
            await transcript_event.wait()

        if session.get("transcript_error"):
            raise HTTPException(status_code=500, detail=f"Transcription failed: {session['transcript_error']}")

        video_path = session["video_path"]
        if not video_path or not os.path.exists(video_path):
            raise HTTPException(status_code=404, detail="Video file not found in session")

        if session.get("transcript_ready"):
            pre_transcript = session["transcript"]
    else:
        # No pre-existing session — need file or URL
        if not url and not file:
            raise HTTPException(status_code=400, detail="Must provide URL, File, or session_id")

        session_id = str(uuid.uuid4())

        if url:
            from main import download_youtube_video
            video_path, _ = download_youtube_video(url, UPLOAD_DIR)
        else:
            video_path = os.path.join(UPLOAD_DIR, f"thumb_{session_id}_{file.filename}")
            with open(video_path, "wb") as buffer:
                content = await file.read()
                buffer.write(content)

    try:
        # Run analysis in thread pool (skips Whisper if pre_transcript is available)
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, analyze_video_for_titles, api_key, video_path, pre_transcript, game)

        # Store/update session context
        if session_id not in thumbnail_sessions:
            thumbnail_sessions[session_id] = {}

        current_context = result.get("transcript_summary", "")
        if game:
            current_context = f"[Game: {game}] " + current_context

        thumbnail_sessions[session_id].update({
            "context": current_context,
            "titles": result.get("titles", []),
            "language": result.get("language", "en"),
            "conversation": thumbnail_sessions[session_id].get("conversation", []),
            "video_path": video_path,
            "transcript_segments": result.get("segments", []),
            "video_duration": result.get("video_duration", 0),
            "game": game
        })
        _save_session(session_id)

        return {
            "session_id": session_id,
            "titles": result.get("titles", []),
            "context": result.get("transcript_summary", ""),
            "language": result.get("language", "en"),
            "recommended": result.get("recommended", [])
        }

    except Exception as e:
        print(f"❌ Thumbnail Analyze Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

class ThumbnailTitlesRequest(BaseModel):
    session_id: Optional[str] = None
    message: Optional[str] = None
    title: Optional[str] = None

@app.post("/api/thumbnail/titles")
async def thumbnail_titles(
    req: ThumbnailTitlesRequest,
    x_gemini_key: Optional[str] = Header(None, alias="X-DeepSeek-Key")
):
    """Refine title suggestions or accept a manual title."""
    api_key = x_gemini_key
    if not api_key:
        raise HTTPException(status_code=400, detail="Missing X-DeepSeek-Key header")

    # Manual title mode - just create a session with the user's title
    if req.title:
        session_id = req.session_id or str(uuid.uuid4())
        if session_id not in thumbnail_sessions:
            thumbnail_sessions[session_id] = {
                "context": "",
                "titles": [req.title],
                "language": "en",
                "conversation": []
            }
            _save_session(session_id)
        return {"session_id": session_id, "titles": [req.title]}

    # Refinement mode
    if not req.session_id or req.session_id not in thumbnail_sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    if not req.message:
        raise HTTPException(status_code=400, detail="Must provide message or title")

    session = thumbnail_sessions[req.session_id]

    # Add user message to conversation history
    session["conversation"].append({"role": "user", "content": req.message})

    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            refine_titles,
            api_key,
            session["context"],
            req.message,
            session["conversation"]
        )

        new_titles = result.get("titles", [])
        session["titles"] = new_titles
        session["conversation"].append({"role": "assistant", "content": json.dumps(new_titles)})
        _save_session(req.session_id)

        return {"titles": new_titles}

    except Exception as e:
        print(f"❌ Thumbnail Titles Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/thumbnail/generate")
async def thumbnail_generate(
    request: Request,
    session_id: str = Form(...),
    title: str = Form(...),
    extra_prompt: str = Form(""),
    count: int = Form(3),
    face: Optional[UploadFile] = File(None),
    background: Optional[UploadFile] = File(None),
    x_gemini_key: Optional[str] = Header(None, alias="X-DeepSeek-Key")
):
    """Generate YouTube thumbnails with simple Pillow."""
    api_key = x_gemini_key
    if not api_key:
        raise HTTPException(status_code=400, detail="Missing X-DeepSeek-Key header")

    count = min(max(1, count), 6)

    face_path = None
    bg_path = None
    thumb_upload_dir = os.path.join(UPLOAD_DIR, f"thumb_{session_id}")
    os.makedirs(thumb_upload_dir, exist_ok=True)

    try:
        if face and face.filename:
            face_path = os.path.join(thumb_upload_dir, f"face_{face.filename}")
            with open(face_path, "wb") as f:
                f.write(await face.read())

        if background and background.filename:
            bg_path = os.path.join(thumb_upload_dir, f"bg_{background.filename}")
            with open(bg_path, "wb") as f:
                f.write(await background.read())

        video_context = ""
        if session_id in thumbnail_sessions:
            video_context = thumbnail_sessions[session_id].get("context", "")

        loop = asyncio.get_event_loop()
        thumbnails = await loop.run_in_executor(
            None,
            generate_thumbnail,
            api_key,
            title,
            session_id,
            face_path,
            bg_path,
            extra_prompt,
            count,
            video_context
        )

        if not thumbnails:
            raise HTTPException(status_code=500, detail="Thumbnail generation failed.")

        return {"thumbnails": thumbnails}

    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Thumbnail Generate Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

class ThumbnailDescribeRequest(BaseModel):
    session_id: str
    title: str

@app.post("/api/thumbnail/describe")
async def thumbnail_describe(
    req: ThumbnailDescribeRequest,
    x_gemini_key: Optional[str] = Header(None, alias="X-DeepSeek-Key")
):
    """Generate a YouTube description with chapters from the transcript."""
    api_key = x_gemini_key
    if not api_key:
        raise HTTPException(status_code=400, detail="Missing X-DeepSeek-Key header")

    if req.session_id not in thumbnail_sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    session = thumbnail_sessions[req.session_id]
    segments = session.get("transcript_segments", [])
    game = session.get("game", "")
    context = session.get("context", "")

    try:
        loop = asyncio.get_event_loop()
        
        if segments:
            # Normal mode with transcript segments
            result = await loop.run_in_executor(
                None,
                generate_youtube_description,
                api_key,
                req.title,
                segments,
                session.get("language", "en"),
                session.get("video_duration", 0)
            )
        else:
            # No transcript (Whisper disabled or empty)
            from openai import OpenAI
            client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
            
            game_hint = f" about {game}" if game else ""
            desc_prompt = f"""Write a YouTube video description{game_hint}.

TITLE: "{req.title}"
CONTEXT: {context}

Write a compelling 3-5 sentence description. Include 5 relevant hashtags at the end.
Do NOT include chapter timestamps.

Output just the description text, no JSON."""
            
            desc_response = client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": "You write YouTube descriptions. Output the description text only."},
                    {"role": "user", "content": desc_prompt}
                ]
            )
            desc_text = desc_response.choices[0].message.content.strip()
            result = {"description": desc_text}
        
        return {"description": result.get("description", "")}

    except Exception as e:
        print(f"❌ Thumbnail Describe Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================
# YouTube OAuth + Direct Upload
# ============================================================

@app.get("/auth/youtube/status")
async def youtube_auth_status():
    """Check if YouTube is authenticated."""
    return {"authenticated": is_authenticated()}

@app.get("/auth/youtube/login")
async def youtube_auth_login():
    """Get Google OAuth URL for YouTube."""
    auth_url = get_auth_url()
    if not auth_url:
        raise HTTPException(
            status_code=400,
            detail="YouTube client_secrets.json not found. Create it in Google Cloud Console and save to data/youtube_client_secrets.json"
        )
    return {"auth_url": auth_url}

@app.post("/auth/youtube/exchange")
async def youtube_auth_exchange(code: str = Form(...)):
    """Exchange an OAuth code for tokens (manual paste fallback)."""
    success = exchange_code_manual(code)
    if success:
        return {"status": "authenticated", "message": "YouTube connected!"}
    raise HTTPException(status_code=400, detail="Failed to exchange code")

@app.get("/auth/youtube/callback")
async def youtube_auth_callback(code: str = ""):
    """Handle OAuth callback and save tokens."""
    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code")
    success = handle_callback(code)
    if success:
        return {"status": "authenticated", "message": "YouTube connected successfully!"}
    raise HTTPException(status_code=400, detail="Authentication failed")

@app.post("/api/thumbnail/publish")
async def thumbnail_publish(
    session_id: str = Form(...),
    title: str = Form(...),
    description: str = Form(...),
    thumbnail_url: str = Form(...),
):
    """Publish video directly to YouTube via YouTube Data API v3."""
    if not is_authenticated():
        raise HTTPException(status_code=401, detail="YouTube not connected.")

    if session_id not in thumbnail_sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    session = thumbnail_sessions[session_id]
    video_path = session.get("video_path")
    if not video_path or not os.path.exists(video_path):
        raise HTTPException(status_code=404, detail="Original video file not found")

    thumb_relative = thumbnail_url.lstrip("/")
    if thumb_relative.startswith("thumbnails/"):
        thumb_path = os.path.join(OUTPUT_DIR, thumb_relative)
    else:
        thumb_path = os.path.join(THUMBNAILS_DIR, thumb_relative)

    if not os.path.exists(thumb_path):
        thumb_path = None

    game = session.get("game", "")
    tags = [game, game + " gameplay", "gaming"] if game else ["gaming"]

    # Generate publish_id and return immediately — upload runs in background
    publish_id = str(uuid.uuid4())
    publish_jobs[publish_id] = {"status": "uploading", "result": None, "error": None}
    print(f"📤 [Publish {publish_id}] Queued background upload")

    asyncio.create_task(_do_publish(
        publish_id=publish_id,
        video_path=video_path,
        title=title,
        description=description,
        thumbnail_path=thumb_path,
        tags=tags,
    ))

    return {"publish_id": publish_id}

async def _do_publish(publish_id: str, video_path: str, title: str, description: str, thumbnail_path: str | None, tags: list, on_done=None):
    """Run the actual YouTube upload in a background task."""
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            upload_video,
            video_path,
            title,
            description,
            thumbnail_path,
            "unlisted",
            tags,
        )
        publish_jobs[publish_id] = {"status": "done", "result": result, "error": None}
        print(f"✅ [Publish {publish_id}] Upload complete — video_id: {result.get('video_id', '?')}")
        if on_done:
            on_done()
    except Exception as e:
        print(f"❌ [Publish {publish_id}] Upload failed: {e}")
        publish_jobs[publish_id] = {"status": "failed", "result": None, "error": str(e)}
        if on_done:
            on_done()

@app.get("/api/thumbnail/publish/status/{publish_id}")
async def publish_status(publish_id: str):
    """Poll the status of a background publish job."""
    if publish_id not in publish_jobs:
        raise HTTPException(status_code=404, detail="Publish job not found")
    return publish_jobs[publish_id]

# ─── Session / Project listing ────────────────────────────────────────
SCHEDULED_PUBLISHES: Dict[str, Dict] = {}
SCHEDULES_FILE = "data/schedules.json"

def _save_schedules():
    try:
        with open(SCHEDULES_FILE, "w") as f:
            json.dump(SCHEDULED_PUBLISHES, f, indent=2, default=str)
    except Exception as e:
        print(f"⚠️ Failed to save schedules: {e}")

def _load_schedules():
    try:
        if os.path.exists(SCHEDULES_FILE):
            with open(SCHEDULES_FILE) as f:
                data = json.load(f)
            SCHEDULED_PUBLISHES.update(data)
            due = sum(1 for s in SCHEDULED_PUBLISHES.values() if s.get("status") == "pending")
            print(f"📅 Loaded {len(SCHEDULED_PUBLISHES)} scheduled publish(es) ({due} pendientes)")
    except Exception as e:
        print(f"⚠️ Failed to load schedules: {e}")

async def _check_due_publishes():
    """Background task: check every 30s for publishes due now."""
    while True:
        try:
            now = datetime.now().timestamp()
            for sid, sched in list(SCHEDULED_PUBLISHES.items()):
                if sched.get("status") != "pending":
                    continue
                if sched.get("scheduled_at", 0) <= now:
                    sched["status"] = "uploading"
                    _save_schedules()
                    publish_id = str(uuid.uuid4())
                    publish_jobs[publish_id] = {"status": "uploading", "result": None, "error": None}
                    sched["publish_id"] = publish_id
                    print(f"📅 [Schedule {sid}] Due! Launching publish {publish_id}")
                    _sid, _pid = sid, publish_id
                    asyncio.create_task(_do_publish(
                        publish_id=_pid,
                        video_path=sched["video_path"],
                        title=sched["title"],
                        description=sched["description"],
                        thumbnail_path=sched.get("thumbnail_path"),
                        tags=sched.get("tags", ["gaming"]),
                        on_done=lambda sid=_sid, pid=_pid: _on_schedule_done(sid, pid),
                    ))
        except Exception as e:
            print(f"⚠️ Schedule check error: {e}")
        await asyncio.sleep(30)

def _on_schedule_done(schedule_id: str, publish_id: str):
    """Called when a scheduled publish completes."""
    if schedule_id not in SCHEDULED_PUBLISHES:
        return
    job = publish_jobs.get(publish_id, {})
    SCHEDULED_PUBLISHES[schedule_id]["status"] = job.get("status", "failed")
    SCHEDULED_PUBLISHES[schedule_id]["result"] = job.get("result")
    SCHEDULED_PUBLISHES[schedule_id]["error"] = job.get("error")
    _save_schedules()
    print(f"📅 [Schedule {schedule_id}] Completed with status: {SCHEDULED_PUBLISHES[schedule_id]['status']}")

@app.get("/api/thumbnail/sessions")
async def list_sessions():
    """List all saved thumbnail sessions."""
    sessions = []
    for sid, session in thumbnail_sessions.items():
        sessions.append({
            "session_id": sid,
            "title": session.get("titles", [None])[0] if session.get("titles") else None,
            "game": session.get("game", ""),
            "context": session.get("context", "")[:120],
            "has_video": bool(session.get("video_path") and os.path.exists(session["video_path"])),
        })
    sessions.sort(key=lambda s: s["session_id"], reverse=True)
    return {"sessions": sessions}

@app.get("/api/thumbnail/session/{session_id}")
async def get_session(session_id: str):
    """Get full session data to resume a project."""
    if session_id not in thumbnail_sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    session = thumbnail_sessions[session_id]
    return {
        "session_id": session_id,
        "video_path": session.get("video_path"),
        "has_video": bool(session.get("video_path") and os.path.exists(session["video_path"])),
        "game": session.get("game", ""),
        "context": session.get("context", ""),
        "titles": session.get("titles", []),
        "language": session.get("language", "en"),
        "video_duration": session.get("video_duration", 0),
        "conversation": session.get("conversation", []),
    }

@app.delete("/api/thumbnail/session/{session_id}")
async def delete_session(session_id: str):
    """Delete a saved session."""
    if session_id in thumbnail_sessions:
        del thumbnail_sessions[session_id]
    sess_path = _session_path(session_id)
    if os.path.exists(sess_path):
        os.remove(sess_path)
    return {"deleted": True}

class SchedulePublishRequest(BaseModel):
    session_id: str
    title: str
    description: str
    thumbnail_url: str = ""
    scheduled_at: float

@app.post("/api/thumbnail/schedule")
async def schedule_publish(req: SchedulePublishRequest):
    """Schedule a video to be published at a specific time."""
    if not is_authenticated():
        raise HTTPException(status_code=401, detail="YouTube not connected")
    if req.session_id not in thumbnail_sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    session = thumbnail_sessions[req.session_id]
    video_path = session.get("video_path")
    if not video_path or not os.path.exists(video_path):
        raise HTTPException(status_code=404, detail="Video file not found")

    thumb_path = None
    if req.thumbnail_url:
        thumb_rel = req.thumbnail_url.lstrip("/")
        if thumb_rel.startswith("thumbnails/"):
            thumb_path = os.path.join(OUTPUT_DIR, thumb_rel)
        else:
            thumb_path = os.path.join(THUMBNAILS_DIR, thumb_rel)
        if not os.path.exists(thumb_path):
            thumb_path = None

    game = session.get("game", "")
    tags = [game, game + " gameplay", "gaming"] if game else ["gaming"]

    schedule_id = str(uuid.uuid4())
    SCHEDULED_PUBLISHES[schedule_id] = {
        "schedule_id": schedule_id,
        "session_id": req.session_id,
        "video_path": video_path,
        "title": req.title,
        "description": req.description,
        "thumbnail_path": thumb_path,
        "tags": tags,
        "scheduled_at": req.scheduled_at,
        "status": "pending",
        "publish_id": None,
        "result": None,
        "error": None,
        "created_at": datetime.now().isoformat(),
    }
    _save_schedules()
    when = datetime.fromtimestamp(req.scheduled_at).strftime("%Y-%m-%d %H:%M")
    print(f"📅 [Schedule {schedule_id}] Video scheduled for {when}")
    return {"schedule_id": schedule_id, "scheduled_at": req.scheduled_at}

@app.get("/api/thumbnail/schedules")
async def list_schedules():
    """List all scheduled publishes."""
    return {"schedules": list(SCHEDULED_PUBLISHES.values())}

@app.delete("/api/thumbnail/schedule/{schedule_id}")
async def delete_schedule(schedule_id: str):
    """Cancel a scheduled publish."""
    if schedule_id in SCHEDULED_PUBLISHES:
        del SCHEDULED_PUBLISHES[schedule_id]
        _save_schedules()
    return {"deleted": True}

# ============================================================
# Games Management API
# ============================================================

def _load_games():
    """Load game list from JSON file."""
    try:
        with open(GAMES_FILE, "r") as f:
            return json.load(f)
    except:
        return []

def _save_games(games):
    """Save game list to JSON file."""
    os.makedirs(os.path.dirname(GAMES_FILE), exist_ok=True)
    with open(GAMES_FILE, "w") as f:
        json.dump(games, f, indent=2)

@app.get("/api/games")
async def get_games():
    """List all saved games."""
    return {"games": _load_games()}

@app.post("/api/games")
async def add_game(name: str = Form(...)):
    """Add a new game to the list."""
    games = _load_games()
    if name not in games:
        games.append(name)
        _save_games(games)
    return {"games": games}

@app.delete("/api/games")
async def delete_game(name: str = Form(...)):
    """Remove a game from the list."""
    games = _load_games()
    if name in games:
        games.remove(name)
        _save_games(games)
    return {"games": games}
