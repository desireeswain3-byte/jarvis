"""Read one public web page as plain text. Standard library only.

Never opens anything on her own computer or home network (localhost, 192.168.x.x and the like), including through
a redirect, so a page can't trick JARVIS into poking at his own server or her router."""
import html
import ipaddress
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

MAX_BYTES = 3 * 1024 * 1024
MAX_CHARS = 14000


class PageError(Exception):
    pass


def _public(url):
    u = urllib.parse.urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise PageError("Only http and https links.")
    try:
        infos = socket.getaddrinfo(u.hostname, u.port or (443 if u.scheme == "https" else 80))
    except socket.gaierror:
        raise PageError("That website could not be found.")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            raise PageError("That link points inside your own network, so I will not open it.")


class _Redirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _public(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class _Text(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "nav", "footer", "header", "form", "aside"}
    BLOCK = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "tr", "section", "article", "table"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.skip, self.title, self._in_title = [], 0, "", False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        if tag == "title":
            self._in_title = True
        if tag in self.BLOCK:
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip:
            self.skip -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self.skip:
            self.out.append(data)


def read(url):
    url = (url or "").strip()
    _public(url)
    opener = urllib.request.build_opener(_Redirects)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (JARVIS local assistant)", "Accept": "text/html,text/plain;q=0.9"})
    try:
        with opener.open(req, timeout=20) as r:
            ctype = r.headers.get("Content-Type", "")
            raw = r.read(MAX_BYTES)
    except urllib.error.HTTPError as e:
        raise PageError("The site answered %d." % e.code)
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        raise PageError("Could not reach the site: %s" % getattr(e, "reason", e))
    if not any(t in ctype for t in ("html", "text/plain", "xml")) and ctype:
        raise PageError("That link is not a web page (%s)." % ctype.split(";")[0])
    m = re.search(r"charset=([\w-]+)", ctype)
    text = raw.decode(m.group(1) if m else "utf-8", "replace")
    if "html" in ctype or "<html" in text[:500].lower():
        p = _Text()
        try:
            p.feed(text)
        except Exception:  # noqa: BLE001
            pass
        title, text = " ".join(p.title.split()), "".join(p.out)
    else:
        title = ""
    text = re.sub(r"[ \t\r\f\v]+", " ", html.unescape(text))
    text = re.sub(r"\n\s*\n+", "\n\n", text).strip()
    if len(text) < 80:
        raise PageError("The page had almost no readable text (it may need a browser to load).")
    return title, text[:MAX_CHARS]
