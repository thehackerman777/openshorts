import os
import json
import re
import subprocess
from openai import OpenAI

class VideoEditor:
    def __init__(self, api_key):
        self.client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
        self.model_name = "deepseek-chat"

    def upload_video(self, video_path):
        """DeepSeek doesn't support video upload — returns a no-op placeholder."""
        print(f"ℹ️ DeepSeek: video upload not needed, using transcript-based processing")
        return video_path

    def get_ffmpeg_filter(self, video_file_obj, duration, fps=30, width=None, height=None, transcript=None):
        """Asks DeepSeek for a raw FFmpeg filter string based on transcript context."""
        if width is None or height is None:
            width, height = 1080, 1920
        
        transcript_text = json.dumps(transcript) if transcript else "Not available."

        prompt = f"""
        You are an expert FFmpeg video editor. Generate a complex video filter string to make a short video viral.
        
        Video Duration: {duration} seconds.
        Video FPS: {fps}
        Video Resolution (MUST KEEP EXACT): {width}x{height}
        
        TRANSCRIPT (Context of what is being said):
        {transcript_text}

        Goal: Enhance the video with dynamic zooms, cuts, and visual effects.

        Instructions:
        1. ANALYZE THE TRANSCRIPT to understand the mood and pacing.
        2. Apply effects only when relevant:
           - Use "punch-in" zooms (zoompan) to emphasize key points.
           - Use visual effects (contrast, saturation) to highlight mood changes.
           - If nothing significant, keep it simple.
        3. Create a single valid FFmpeg filter complex string.
        4. CRITICAL: DO NOT use comparison operators (<, >, <=, >=). Use expressions like between(x,a,b).
        5. Output ONLY valid JSON.

        Output JSON:
        {{
            "filter_string": "..."
        }}
        """

        print("🤖 Asking DeepSeek for FFmpeg filter...")
        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=[
                {"role": "system", "content": "You are an FFmpeg expert. Respond ONLY with valid JSON."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"}
        )
        
        text = response.choices[0].message.content
        print(f"🔍 DEBUG: DeepSeek Raw Response:\n{text}")

        try:
            if text.startswith("```json"):
                text = text[7:]
            elif text.startswith("```"):
                text = text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()
            start_idx = text.find('{')
            end_idx = text.rfind('}')
            if start_idx != -1 and end_idx != -1:
                text = text[start_idx:end_idx+1]
            return json.loads(text)
        except json.JSONDecodeError:
            print(f"❌ Failed to parse JSON: {text}")
            return None

    def get_effects_config(self, video_file_obj, duration, fps=30, width=None, height=None, transcript=None):
        """Asks DeepSeek for a structured EffectsConfig JSON for Remotion rendering."""
        if width is None or height is None:
            width, height = 1080, 1920

        transcript_text = json.dumps(transcript) if transcript else "Not available."

        prompt = f"""
        You are an expert video editor. Generate a JSON describing time-based effect segments for the full video.

        Video Duration: {duration} seconds.
        Video FPS: {fps}
        Video Resolution: {width}x{height}

        TRANSCRIPT:
        {transcript_text}

        Each segment has: startSec, endSec, zoom (1.0=normal, max 1.5), zoomCenterX (0-1), zoomCenterY (0-1),
        brightness (0.8-1.2), contrast (0.8-1.3), saturate (0.8-1.3).

        Cover the FULL duration. Use subtle effects. Output ONLY valid JSON.

        Output format:
        {{
            "segments": [
                {{"startSec": 0, "endSec": {duration}, "zoom": 1.0, "zoomCenterX": 0.5, "zoomCenterY": 0.5, "brightness": 1.0, "contrast": 1.0, "saturate": 1.0}}
            ]
        }}
        """

        print("🤖 Asking DeepSeek for Remotion effects config...")
        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=[
                {"role": "system", "content": "You are a video editor. Respond ONLY with valid JSON."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"}
        )

        text = response.choices[0].message.content
        print(f"🔍 DEBUG: DeepSeek Raw Response:\n{text}")

        try:
            if text.startswith("```json"):
                text = text[7:]
            elif text.startswith("```"):
                text = text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()
            start_idx = text.find('{')
            end_idx = text.rfind('}')
            if start_idx != -1 and end_idx != -1:
                text = text[start_idx:end_idx+1]
            return json.loads(text)
        except json.JSONDecodeError:
            print(f"❌ Failed to parse config JSON: {text}")
            return None

    @staticmethod
    def _split_filter_chain(filter_string: str) -> list[str]:
        parts: list[str] = []
        start = 0
        in_quote = False
        for i, ch in enumerate(filter_string):
            if ch == "'":
                in_quote = not in_quote
            elif ch == "," and not in_quote:
                parts.append(filter_string[start:i])
                start = i + 1
        parts.append(filter_string[start:])
        return parts

    @classmethod
    def _enforce_zoompan_output_size(cls, filter_string: str, width: int, height: int) -> str:
        parts = cls._split_filter_chain(filter_string)
        out_parts: list[str] = []
        for part in parts:
            if "zoompan=" in part:
                if re.search(r":s=\d+x\d+", part):
                    part = re.sub(r":s=\d+x\d+", f":s={width}x{height}", part)
                else:
                    part = f"{part}:s={width}x{height}"
            out_parts.append(part)
        return ",".join(out_parts)

    @staticmethod
    def _sanitize_filter_string(filter_string: str) -> str:
        s = filter_string
        patterns: list[tuple[re.Pattern[str], str]] = [
            (re.compile(r"(?<![A-Za-z0-9_])([A-Za-z_]\w*)\s*>=\s*(-?\d+(?:\.\d+)?)"), r"gte(\1,\2)"),
            (re.compile(r"(?<![A-Za-z0-9_])([A-Za-z_]\w*)\s*<=\s*(-?\d+(?:\.\d+)?)"), r"lte(\1,\2)"),
            (re.compile(r"(?<![A-Za-z0-9_])([A-Za-z_]\w*)\s*>\s*(-?\d+(?:\.\d+)?)"), r"gt(\1,\2)"),
            (re.compile(r"(?<![A-Za-z0-9_])([A-Za-z_]\w*)\s*<\s*(-?\d+(?:\.\d+)?)"), r"lt(\1,\2)"),
        ]
        for pat, repl in patterns:
            s = pat.sub(repl, s)
        return s

    def apply_edits(self, input_path, output_path, filter_data):
        if not filter_data or "filter_string" not in filter_data:
            print("⚠️ No filter string found. Copying original.")
            subprocess.run(['ffmpeg', '-y', '-i', input_path, '-c', 'copy', output_path])
            return

        filter_string = filter_data["filter_string"]
        
        try:
            probe_cmd = ['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=width,height', '-of', 'csv=s=x:p=0', input_path]
            res_out = subprocess.check_output(probe_cmd, env={**os.environ, "LANG": "C.UTF-8"}).decode().strip()
            w, h = map(int, res_out.split('x'))
        except Exception as e:
            print(f"⚠️ Could not probe resolution: {e}")
            w, h = None, None

        sanitized = self._sanitize_filter_string(filter_string)
        if sanitized != filter_string:
            print(f"🧼 Sanitized AI Filter")
            filter_string = sanitized

        if w and h:
            enforced = self._enforce_zoompan_output_size(filter_string, w, h)
            if enforced != filter_string:
                filter_string = enforced
            if "setsar=" not in filter_string:
                filter_string = f"{filter_string},setsar=1"

        print(f"🎬 Executing AI Filter: {filter_string}")
        
        cmd = [
            'ffmpeg', '-y',
            '-i', input_path,
            '-vf', filter_string,
            '-c:v', 'libx264', '-preset', 'fast', '-crf', '22',
            '-c:a', 'copy',
            output_path
        ]
        
        env = os.environ.copy()
        env["LANG"] = "C.UTF-8"
        env["LC_ALL"] = "C.UTF-8"
        
        try:
            cmd_bytes = []
            for arg in cmd:
                if isinstance(arg, str):
                    cmd_bytes.append(arg.encode('utf-8'))
                else:
                    cmd_bytes.append(arg)
            subprocess.run(cmd_bytes, check=True, env=env)
        except subprocess.CalledProcessError as e:
            print(f"❌ FFmpeg failed: {e}")
            raise e

if __name__ == "__main__":
    pass
