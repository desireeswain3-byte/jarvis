"""Find YouTube videos and read what is said in them. No key needed.
The model cannot watch video, so 'watching' means reading the captions (transcript) as text."""
import html
import json
import re
import urllib.parse
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
      "Accept-Language": "en-US,en;q=0.9"}
ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


class VideoError(Exception):
    pass


def _get(url, timeout=15):
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", "replace")
    except Exception as e:
        raise VideoError("Could not reach YouTube: %s" % e)


def video_id(s):
    """An 11 character id, or the id inside any youtube link. None if it is neither."""
    s = (s or "").strip()
    if ID.match(s):
        return s
    m = re.search(r"(?:v=|youtu\.be/|/embed/|/shorts/|/live/)([A-Za-z0-9_-]{11})", s)
    return m.group(1) if m else None


def _text(node):
    if not isinstance(node, dict):
        return ""
    if "simpleText" in node:
        return node["simpleText"]
    return "".join(r.get("text", "") for r in node.get("runs", []))


def search(query, limit=6):
    page = _get("https://www.youtube.com/results?search_query=" + urllib.parse.quote(query) + "&sp=EgIQAQ%253D%253D")
    m = re.search(r"var ytInitialData\s*=\s*(\{.*?\});</script>", page, re.S)
    if not m:
        raise VideoError("YouTube did not return a list I could read.")
    try:
        data = json.loads(m.group(1))
    except ValueError:
        raise VideoError("YouTube sent something I could not read.")
    out = []

    def walk(n):
        if len(out) >= limit:
            return
        if isinstance(n, dict):
            vr = n.get("videoRenderer")
            if vr and ID.match(str(vr.get("videoId", ""))):
                out.append({"id": vr["videoId"], "title": _text(vr.get("title")), "channel": _text(vr.get("ownerText")),
                            "length": _text(vr.get("lengthText")), "views": _text(vr.get("viewCountText"))})
            else:
                for v in n.values():
                    walk(v)
        elif isinstance(n, list):
            for v in n:
                walk(v)
    walk(data)
    return out[:limit]


def transcript(vid, max_chars=11000):
    """(title, text). Raises VideoError when the video has no readable captions."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi   # optional, more reliable when installed
        try:
            t = YouTubeTranscriptApi().fetch(vid)
            text = " ".join(s.text for s in t)
        except AttributeError:
            text = " ".join(s["text"] for s in YouTubeTranscriptApi.get_transcript(vid))
        return "", _shrink(text, max_chars)
    except ImportError:
        pass
    except Exception as e:
        raise VideoError("This video has no captions I can read (%s)." % type(e).__name__)
    page = _get("https://www.youtube.com/watch?v=" + vid)
    tm = re.search(r"<title>(.*?)</title>", page, re.S)
    title = html.unescape(tm.group(1)).replace(" - YouTube", "").strip() if tm else ""
    cm = re.search(r'"captionTracks":(\[.*?\])', page, re.S)
    if not cm:
        raise VideoError("This video has no captions I can read.")
    try:
        tracks = json.loads(cm.group(1))
    except ValueError:
        raise VideoError("I could not read this video's caption list.")
    pick = next((t for t in tracks if t.get("languageCode", "").startswith("en") and t.get("kind") != "asr"), None) or \
        next((t for t in tracks if t.get("languageCode", "").startswith("en")), None) or tracks[0]
    xml = _get(pick["baseUrl"].replace("\\u0026", "&"))
    parts = [html.unescape(re.sub(r"<[^>]+>", "", x)) for x in re.findall(r"<text[^>]*>(.*?)</text>", xml, re.S)]
    text = " ".join(" ".join(parts).split())
    if not text:
        raise VideoError("The captions came back empty. YouTube may be limiting requests.")
    return title, _shrink(text, max_chars)


def _shrink(text, n):
    text = " ".join(text.split())
    if len(text) <= n:
        return text
    # keep the start, the middle and the end so the summary covers the whole video
    k = n // 3
    mid = len(text) // 2
    return text[:k] + " [...] " + text[mid - k // 2: mid + k // 2] + " [...] " + text[-k:]
