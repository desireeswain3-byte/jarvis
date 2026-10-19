"""Folders into a searchable graph. Read-only: this module never writes."""
import math
import os
import re
import zlib
from collections import Counter, defaultdict
from pathlib import Path

SKIP_DIRS = {"node_modules", ".git"}
MAX_BYTES = 2 * 1024 * 1024
EXTS = {".md", ".markdown", ".txt", ".pdf"}
WIKI = re.compile(r"\[\[([^\]\|#]+)(?:#[^\]\|]*)?(?:\|[^\]]*)?\]\]")
WORD = re.compile(r"[a-z0-9£]+")
STOP = set(
    "a an the is are was were be been of to in on for and or but with at by from it this that these those "
    "my me i you your our we what who when where why how do does did can could should would about any "
    "there their they them as if so than then not no yes tell show give get".split()
)
FOLDER_TYPES = [("invoice", "invoice"), ("client", "client"), ("project", "project"), ("meeting", "meeting"),
                ("people", "person"), ("person", "person"), ("idea", "idea"), ("process", "process"),
                ("memory", "memory"), ("hub", "hub")]
FRONT = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.S)


def _tokens(text):
    return [t for t in WORD.findall(text.lower()) if t not in STOP]


def _stem(w):
    return w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w


def norm(text):
    """Lowercase words with a trailing plural s dropped, so 'retainer' finds 'Retainers'."""
    return " ".join(_stem(w) for w in WORD.findall(text.lower()))


def pdf_text(data):
    """Best-effort PDF text with the standard library only. Scanned PDFs yield nothing."""
    out = []
    for m in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", data, re.S):
        raw = m.group(1)
        try:
            raw = zlib.decompress(raw)
        except Exception:
            pass
        for t in re.finditer(rb"\[(.*?)\]\s*TJ|\((.*?)(?<!\\)\)\s*Tj", raw, re.S):
            if t.group(1) is not None:
                out.append(b"".join(re.findall(rb"\((.*?)(?<!\\)\)", t.group(1), re.S)))
            else:
                out.append(t.group(2))
    text = b" ".join(out)
    text = re.sub(rb"\\([()\\])", rb"\1", text)
    return text.decode("latin-1", "replace")


class Vault:
    def __init__(self, roots):
        self.roots = roots
        self.refresh()

    # ---------- build ----------
    def refresh(self):
        notes = []
        seen_labels = Counter()
        for label, root in self.roots:
            seen_labels[label] += 1
            tag = label if seen_labels[label] == 1 else "%s%d" % (label, seen_labels[label])
            for dirpath, dirnames, filenames in os.walk(root):
                dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
                for fn in sorted(filenames):
                    p = Path(dirpath) / fn
                    if p.suffix.lower() not in EXTS:
                        continue
                    try:
                        if p.stat().st_size > MAX_BYTES:
                            continue
                        if p.suffix.lower() == ".pdf":
                            text = pdf_text(p.read_bytes())
                        else:
                            text = p.read_text(encoding="utf-8", errors="replace")
                    except OSError:
                        continue
                    notes.append(self._parse(tag, root, p, text))
        self.notes = notes
        self.by_id = {n["id"]: i for i, n in enumerate(notes)}
        names = {}
        for i, n in enumerate(notes):
            names.setdefault(n["title"].lower(), i)
            names.setdefault(Path(n["path"]).stem.lower(), i)
        edges = set()
        self.adj = [set() for _ in notes]
        self.back = [set() for _ in notes]
        for i, n in enumerate(notes):
            for target in n["links_raw"]:
                j = names.get(target.lower().strip())
                if j is None or j == i:
                    continue
                self.adj[i].add(j)
                self.adj[j].add(i)
                self.back[j].add(i)
                edges.add((min(i, j), max(i, j)))
        self.edges = sorted(edges)
        self._index()

    def _parse(self, tag, root, p, text):
        meta = {}
        body = text
        m = FRONT.match(text)
        if m:
            for line in m.group(1).splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    meta[k.strip().lower()] = v.strip()
            body = text[m.end():]
        title = p.stem
        for line in body.splitlines():
            if line.startswith("# "):
                title = line[2:].strip()
                break
        rel = str(p.relative_to(root))
        ntype = meta.get("type", "").lower()
        if not ntype:
            low = rel.lower()
            ntype = "document" if p.suffix.lower() == ".pdf" else "note"
            for key, val in FOLDER_TYPES:
                if key in low:
                    ntype = val
                    break
        return {
            "id": tag + "/" + rel,
            "title": title,
            "type": ntype,
            "path": rel,
            "file": p.name,
            "text": body,
            "meta": meta,
            "links_raw": [x for x in WIKI.findall(body)],
        }

    def _index(self):
        self.tf = []
        df = Counter()
        total = 0
        for n in self.notes:
            toks = _tokens(n["title"]) * 3 + _tokens(n["text"])
            c = Counter(toks)
            self.tf.append((c, len(toks)))
            total += len(toks)
            df.update(c.keys())
        self.N = max(1, len(self.notes))
        self.avgdl = total / self.N if total else 1
        self.idf = {t: math.log(1 + (self.N - d + 0.5) / (d + 0.5)) for t, d in df.items()}

    # ---------- queries ----------
    def search(self, query, k=5):
        q = list(dict.fromkeys(_tokens(query)))
        if not q:
            return []
        hits = []
        for i, (c, dl) in enumerate(self.tf):
            score = 0.0
            matched = 0
            for t in q:
                f = c.get(t, 0)
                if not f:
                    continue
                matched += 1
                score += self.idf.get(t, 0) * (f * 2.5) / (f + 1.5 * (0.25 + 0.75 * dl / self.avgdl))
            if score > 0:
                hits.append((score, matched / len(q), i))
        hits.sort(reverse=True)
        out = []
        for score, cov, i in hits[:k]:
            n = self.notes[i]
            out.append({
                "id": n["id"], "title": n["title"], "type": n["type"], "file": n["file"], "path": n["path"],
                "score": round(score, 2), "coverage": round(cov, 2), "snippet": self._snippet(n["text"], q),
            })
        return out

    @staticmethod
    def _snippet(text, q):
        best, best_n = "", -1
        for line in text.splitlines():
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            n = sum(1 for t in q if t in s.lower())
            if n > best_n:
                best, best_n = s, n
        return best[:240]

    def find(self, query, k=5):
        """Find a note by what the user called it. Returns {"open": note or None, "choices": [...]}.
        A note opens only when the name is unambiguous. Otherwise the candidates come back so
        the caller can ask which one, instead of guessing and opening the wrong file."""
        q = norm(query)
        qt = [_stem(t) for t in _tokens(query)]
        if not q:
            return {"open": None, "choices": []}
        scored = []
        for i, n in enumerate(self.notes):
            title = norm(n["title"])
            stem = norm(Path(n["path"]).stem.replace("-", " "))
            tt = set(title.split())
            if q == title or q == stem:
                s = 100
            elif title.startswith(q + " "):
                s = 85
            elif (" " + q + " ") in (" " + title + " "):
                s = 80
            elif qt and all(t in tt for t in qt):
                s = 70 - 2 * max(0, len(tt) - len(qt))
            elif len(qt) >= 2 and sum(t in tt for t in qt) / len(qt) >= 0.6:
                s = 40
            else:
                continue
            scored.append((s, len(self.adj[i]), i))
        scored.sort(key=lambda x: (-x[0], -x[1], self.notes[x[2]]["title"]))
        if scored and (scored[0][0] >= 100 and (len(scored) == 1 or scored[1][0] < 100)
                       or len(scored) == 1 and scored[0][0] >= 70):
            return {"open": self.notes[scored[0][2]], "choices": []}
        choices = [self.notes[i] for _, _, i in scored[:k]]
        if not choices:
            hits = [h for h in self.search(query, k) if h["coverage"] >= 0.5]
            choices = [self.notes[self.by_id[h["id"]]] for h in hits]
        return {"open": None, "choices": choices}

    def mentions(self, term, limit=3):
        term = term.lower().strip()
        if len(term) < 3:
            return []
        order = {"client": 0, "person": 1, "project": 2}
        found = [n for n in self.notes if term in n["text"].lower() or term == n["title"].lower()]
        found.sort(key=lambda n: (order.get(n["type"], 5), n["title"]))
        return [{"title": n["title"], "file": n["file"], "type": n["type"]} for n in found[:limit]]

    def note(self, nid):
        i = self.by_id.get(nid)
        if i is None:
            return None
        n = self.notes[i]
        ref = lambda j: {"id": self.notes[j]["id"], "title": self.notes[j]["title"], "type": self.notes[j]["type"]}
        return {
            "id": n["id"], "title": n["title"], "type": n["type"], "path": n["path"],
            "text": n["text"][:60000], "meta": n["meta"],
            "links": [ref(j) for j in sorted(self.adj[i], key=lambda j: self.notes[j]["title"])],
            "backlinks": [ref(j) for j in sorted(self.back[i], key=lambda j: self.notes[j]["title"])],
        }

    def meta_of(self, title):
        for n in self.notes:
            if n["title"].lower() == title.lower():
                return n["meta"]
        return {}

    def graph(self):
        return {
            "nodes": [{"id": n["id"], "title": n["title"], "type": n["type"]} for n in self.notes],
            "edges": [list(e) for e in self.edges],
        }

    def stats(self):
        return {"notes": len(self.notes), "edges": len(self.edges), "roots": [str(r) for _, r in self.roots]}
