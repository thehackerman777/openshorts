import os
import uuid
import time
import json
from openai import OpenAI
from PIL import Image, ImageDraw, ImageFont


def analyze_video_for_titles(api_key, video_path, transcript=None, game=None):
    """
    Transcribes a video and uses DeepSeek to suggest viral YouTube titles.
    If transcript is provided, skips Whisper transcription.
    If game is provided, generates gaming-specific titles.
    Returns: { "titles": [...], "transcript_summary": "...", "language": "...", "segments": [...], "video_duration": ... }
    """
    if transcript is None:
        from main import transcribe_video
        print("🎬 [Thumbnail] Transcribing video...")
        transcript = transcribe_video(video_path)
    else:
        print("🎬 [Thumbnail] Using pre-computed transcript (Whisper already done)...")

    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")

    # Build game-specific context
    game_context = ""
    if game:
        game_context = f"""
VIDEO GAME: {game}
IMPORTANT: Titles MUST be about {game} gameplay, not general YouTube advice. Use gaming terminology relevant to {game}.

Examples of GOOD gaming titles:
- "INSANE {game.upper()} MOMENT YOU WON'T BELIEVE"
- "This {game} Strategy is BROKEN"
- "I Can't Believe I Pulled This Off in {game}"
- "{game} but I Only Use [Weapon/Strat]"
- "PRO PLAYER REACTS to {game} Clip"

"""
    else:
        game_context = """
IMPORTANT: Titles MUST be about actual gameplay or content, NOT general YouTube marketing advice. Never suggest "how to get views" or "YouTube algorithm" type titles.

"""

    prompt = f"""You are a YouTube title expert who creates viral, click-worthy titles.

Analyze this video and its transcript, then suggest 10 YouTube titles that would maximize CTR (click-through rate).

TRANSCRIPT:
{transcript['text']}
{game_context}
RULES:
- Titles must be under 70 characters
- Use power words, curiosity gaps, and emotional triggers
- Mix styles: how-to, listicle, story-driven, controversial, question-based
- Make them specific to the actual content, not generic
- Include numbers where appropriate
- Consider the language of the video (detected: {transcript['language']})
- Titles should be in the SAME LANGUAGE as the video transcript

Also provide a brief summary of the video content (2-3 sentences).

After generating all 10 titles, pick the TOP 2 you most recommend and explain concisely WHY (CTR potential, emotional hook, uniqueness, etc.). Reference them by their 0-based index in the titles array.

OUTPUT JSON:
{{
    "titles": ["title1", "title2", ...],
    "transcript_summary": "Brief summary of the video content...",
    "language": "{transcript['language']}",
    "recommended": [
        {{"index": 0, "reason": "Why this title is best..."}},
        {{"index": 3, "reason": "Why this title is second best..."}}
    ]
}}"""

    print("🤖 [Thumbnail] Asking DeepSeek for title suggestions...")
    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": "You are a YouTube title expert. Respond ONLY with valid JSON."},
            {"role": "user", "content": prompt}
        ],
        response_format={"type": "json_object"}
    )

    # Extract segments and duration from transcript for later use
    segments = transcript.get("segments", [])
    video_duration = segments[-1]["end"] if segments else 0

    try:
        text = response.choices[0].message.content.strip()
        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        start_idx = text.find('{')
        end_idx = text.rfind('}')
        if start_idx != -1 and end_idx != -1:
            text = text[start_idx:end_idx + 1]

        result = json.loads(text)
        result["transcript_summary"] = result.get("transcript_summary", "")
        result["language"] = result.get("language", transcript["language"])
        result["segments"] = segments
        result["video_duration"] = video_duration
        return result
    except json.JSONDecodeError:
        print(f"❌ [Thumbnail] Failed to parse titles JSON: {text}")
        return {
            "titles": ["Could not generate titles - please try again"],
            "transcript_summary": transcript["text"][:500],
            "language": transcript["language"],
            "segments": segments,
            "video_duration": video_duration
        }


def refine_titles(api_key, context, user_message, conversation_history=None):
    """
    Takes video context + user feedback and returns refined title suggestions.
    """
    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")

    history_text = ""
    if conversation_history:
        for msg in conversation_history:
            role = msg.get("role", "user")
            history_text += f"\n{role.upper()}: {msg['content']}"

    prompt = f"""You are a YouTube title expert. Based on the video context and the user's feedback, suggest 8 new refined YouTube titles.

VIDEO CONTEXT:
{context}

CONVERSATION HISTORY:{history_text}

USER'S NEW REQUEST:
{user_message}

RULES:
- Titles must be under 70 characters
- Incorporate the user's feedback/direction
- Keep titles viral and click-worthy
- If the user asks for a specific style, follow it
- Titles should be in the same language as the original content

OUTPUT JSON:
{{
    "titles": ["title1", "title2", ...]
}}"""

    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": "You are a YouTube title expert. Respond ONLY with valid JSON."},
            {"role": "user", "content": prompt}
        ],
        response_format={"type": "json_object"}
    )

    try:
        text = response.choices[0].message.content.strip()
        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        start_idx = text.find('{')
        end_idx = text.rfind('}')
        if start_idx != -1 and end_idx != -1:
            text = text[start_idx:end_idx + 1]

        return json.loads(text)
    except json.JSONDecodeError:
        print(f"❌ [Thumbnail] Failed to parse refined titles: {text}")
        return {"titles": ["Could not refine titles - please try again"]}


def generate_thumbnail(api_key, title, session_id, face_image_path=None, bg_image_path=None, extra_prompt="", count=3, video_context=""):
    """
    Genera thumbnails 100% locales con Pillow - sin AI, sin costos.
    Si se provee bg_image_path, lo usa como fondo.
    """
    output_dir = os.path.join("output", "thumbnails", session_id)
    os.makedirs(output_dir, exist_ok=True)

    words = title.split()
    if len(words) <= 4:
        overlay_text = title.upper()
    else:
        overlay_text = " ".join(words[:4]).upper()

    if extra_prompt and len(extra_prompt) > 3:
        overlay_text = extra_prompt.upper()[:30]

    themes = [
        {"bg": "#1a1a2e", "text": "#FFD700"},
        {"bg": "#16213e", "text": "#00FF88"},
        {"bg": "#0f3460", "text": "#FF6B6B"},
        {"bg": "#2d1b69", "text": "#FFD93D"},
        {"bg": "#1b1b2f", "text": "#E43A5F"},
    ]

    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 64)
        font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 28)
    except:
        font = ImageFont.load_default()
        font_small = ImageFont.load_default()

    thumbnails = []
    for i in range(count):
        theme = themes[i % len(themes)]
        hex_bg = theme["bg"].lstrip("#")
        hex_text = theme["text"].lstrip("#")
        bg_rgb = tuple(int(hex_bg[j:j+2], 16) for j in (0, 2, 4))
        text_rgb = tuple(int(hex_text[j:j+2], 16) for j in (0, 2, 4))

        try:
            if bg_image_path and os.path.exists(bg_image_path):
                bg_img = Image.open(bg_image_path).convert("RGB")
                bg_img = bg_img.resize((1280, 720), Image.LANCZOS)
                img = bg_img
            else:
                img = Image.new("RGB", (1280, 720), bg_rgb)
                draw = ImageDraw.Draw(img)
                for y in range(520, 720):
                    alpha = (y - 520) / 200
                    dark = tuple(int(c * (1 - alpha * 0.4)) for c in bg_rgb)
                    draw.line([(0, y), (1280, y)], fill=dark)

            draw = ImageDraw.Draw(img)

            text_lines = []
            words_in = overlay_text.split()
            if len(words_in) <= 2:
                text_lines = [overlay_text]
            else:
                mid = len(words_in) // 2
                text_lines = [" ".join(words_in[:mid]), " ".join(words_in[mid:])]

            y_offset = 540
            for line in text_lines:
                bbox = draw.textbbox((0, 0), line, font=font)
                tw = bbox[2] - bbox[0]
                x = (1280 - tw) // 2
                draw.text((x+3, y_offset+3), line, fill="black", font=font)
                draw.text((x, y_offset), line, fill=text_rgb, font=font)
                y_offset += 80

            num_text = f"#{i+1}"
            bbox = draw.textbbox((0, 0), num_text, font=font_small)
            tw = bbox[2] - bbox[0]
            draw.text((1240 - tw, 20), num_text, fill="white", font=font_small)

            filename = f"thumb_{i + 1}.jpg"
            filepath = os.path.join(output_dir, filename)
            img.save(filepath, quality=90)
            thumbnails.append(f"/thumbnails/{session_id}/{filename}")
            print(f"✅ [Thumbnail] Saved: {filepath}")
        except Exception as e:
            print(f"❌ [Thumbnail] Generation {i + 1} failed: {e}")

    if not thumbnails:
        raise RuntimeError("All thumbnail generations failed.")

    return thumbnails
def generate_youtube_description(api_key, title, transcript_segments, language, video_duration):
    """
    Uses DeepSeek to generate a YouTube description with chapter markers from transcript segments.
    Returns: { "description": "full description text with chapters" }
    """
    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")

    # Format segments for the prompt
    formatted_segments = []
    for seg in transcript_segments:
        start = seg.get("start", 0)
        mins = int(start // 60)
        secs = int(start % 60)
        timestamp = f"{mins}:{secs:02d}"
        formatted_segments.append(f"[{timestamp}] {seg.get('text', '').strip()}")

    segments_text = "\n".join(formatted_segments)

    # Format total duration
    dur_mins = int(video_duration // 60)
    dur_secs = int(video_duration % 60)
    duration_str = f"{dur_mins}:{dur_secs:02d}"

    prompt = f"""You are a YouTube SEO expert. Generate a complete YouTube video description for the following video.

VIDEO TITLE: "{title}"
VIDEO LANGUAGE: {language}
VIDEO DURATION: {duration_str}

TRANSCRIPT WITH TIMESTAMPS:
{segments_text}

REQUIREMENTS:
1. Write the description in the SAME LANGUAGE as the video ({language})
2. Start with a compelling 2-3 sentence summary/hook
3. Add relevant CTAs (subscribe, like, comment)
4. Generate YouTube CHAPTERS based on the transcript timestamps:
   - First chapter MUST start at 0:00
   - Minimum 3 chapters, each at least 10 seconds apart
   - Chapter titles should be concise and descriptive
   - Format: 0:00 Chapter Title
   - Place chapters in their own section with a blank line before and after
5. Add 5-10 relevant hashtags at the end
6. Keep the total description under 5000 characters

OUTPUT: Return ONLY the description text (no JSON wrapper, no markdown code blocks). The description should be ready to paste directly into YouTube."""

    print("🤖 [Thumbnail] Generating YouTube description with chapters...")
    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": "You are a YouTube SEO expert. Respond with the description text only, no markdown."},
            {"role": "user", "content": prompt}
        ]
    )

    description = response.choices[0].message.content.strip()
    # Clean up any accidental markdown wrappers
    if description.startswith("```"):
        lines = description.split("\n")
        description = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    return {"description": description}
