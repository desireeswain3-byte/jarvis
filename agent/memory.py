"""Writes to memory/ and nowhere else. One dated markdown file per fact."""
import datetime
import re
from pathlib import Path

MEM = Path(__file__).resolve().parent.parent / "memory"
MAX_FACT = 600


def write(fact):
    fact = " ".join(fact.split())[:MAX_FACT]
    if not fact:
        raise ValueError("Nothing to remember.")
    MEM.mkdir(exist_ok=True)
    today = datetime.date.today().isoformat()
    words = re.sub(r"[^a-z0-9 ]+", "", fact.lower()).split()[:6]
    base = "%s-%s" % (today, "-".join(words) or "note")
    path = MEM / (base + ".md")
    n = 2
    while path.exists():
        path = MEM / ("%s-%d.md" % (base, n))
        n += 1
    if path.resolve().parent != MEM.resolve():
        raise ValueError("Refusing to write outside memory/.")
    path.write_text("---\ndate: %s\ntype: memory\n---\n# %s\n\n%s\n" % (today, " ".join(words).capitalize() or "Note", fact), encoding="utf-8")
    return {"file": path.name, "fact": fact}


def listing():
    if not MEM.exists():
        return []
    out = []
    for p in sorted(MEM.glob("*.md"), reverse=True):
        body = p.read_text(encoding="utf-8", errors="replace").split("---")[-1].strip()
        lines = [l for l in body.splitlines() if l and not l.startswith("#")]
        out.append({"file": p.name, "text": lines[0] if lines else ""})
    return out
