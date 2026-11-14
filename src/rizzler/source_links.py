"""Pinned public-HTTPS source retrieval.

Pre-resolves all addresses and denies private/reserved IPs; connects to the
validated address while preserving TLS SNI and hostname verification.
Never forwards user cookies, credentials, or arbitrary request headers.
"""
from __future__ import annotations
import http.client
import ipaddress
import re
import socket
import ssl
from html.parser import HTMLParser
from urllib.parse import urlsplit, urljoin

MAX_DOWNLOAD=8_000_000
MAX_REDIRECTS=2

class VisibleHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ignored=0
        self.chunks=[]
        self.length=0
    def handle_starttag(self,tag,attrs):
        if tag in ("script","style","noscript","svg","template"):
            self.ignored+=1
        if tag in ("p","div","article","h1","h2","h3","li","tr","br") and not self.ignored:
            self.chunks.append("\n")
    def handle_endtag(self,tag):
        if tag in ("script","style","noscript","svg","template") and self.ignored:self.ignored-=1
    def handle_data(self,data):
        if not self.ignored and self.length<1_500_000:
            self.chunks.append(data);self.length+=len(data)

def _address(host):
    try:
        infos=socket.getaddrinfo(host,443,type=socket.SOCK_STREAM)
    except OSError:raise ValueError("Source hostname unavailable") from None
    if not infos:raise ValueError("Source hostname unavailable")
    ips=sorted({info[4][0] for info in infos})
    if len(ips)>16 or any(not ipaddress.ip_address(x).is_global for x in ips):
        raise ValueError("Private or reserved source address refused")
    return ips[0]

def _validate(url):
    if not isinstance(url,str) or not 1<=len(url)<=2000:
        raise ValueError("Invalid source URL")
    parsed=urlsplit(url)
    if parsed.scheme!="https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Only public HTTPS URLs supported")
    try:port=parsed.port
    except ValueError:raise ValueError("Invalid source URL port") from None
    if port not in (None,443):raise ValueError("Nonstandard URL port refused")
    if parsed.fragment:raise ValueError("Remove fragment identifiers")
    return parsed

class _PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self,host,ip):
        super().__init__(host,443,timeout=8,context=ssl.create_default_context())
        self.ip=ip
    def connect(self):
        sock=socket.create_connection((self.ip,443),timeout=self.timeout)
        try:self.sock=self._context.wrap_socket(sock,server_hostname=self.host)
        except BaseException:
            sock.close()
            raise

def download(url):
    seen=set()
    for _ in range(MAX_REDIRECTS+1):
        parts=_validate(url)
        if url in seen:raise ValueError("Redirect loop refused")
        seen.add(url)
        ip=_address(parts.hostname)
        conn=_PinnedHTTPS(parts.hostname,ip)
        try:
            target=(parts.path or "/")+("?" + parts.query if parts.query else "")
            conn.request("GET",target,headers={
                "Host":parts.hostname,"User-Agent":"RizzlerSourceIndexer/1.0",
                "Accept":"text/html,text/plain,text/markdown,application/json,application/pdf,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "Accept-Encoding":"identity","Connection":"close"})
            response=conn.getresponse()
            if response.status in (301,302,303,307,308):
                location=response.getheader("Location","")
                if not location:raise ValueError("Redirect target missing")
                url=urljoin(url,location)
                continue
            if response.status!=200:raise ValueError("Source returned HTTP "+str(response.status))
            size=response.getheader("Content-Length","")
            if size.isdigit() and int(size)>MAX_DOWNLOAD:raise ValueError("Source exceeds 8 MB limit")
            mime=response.getheader("Content-Type","").split(";",1)[0].lower().strip()
            accepted={
                "text/html":".txt","application/xhtml+xml":".txt",
                "text/plain":".txt","text/markdown":".md","application/json":".json",
                "text/csv":".csv","application/pdf":".pdf",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":".xlsx",
            }
            if mime not in accepted:raise ValueError("Unsupported source content type")
            body=response.read(MAX_DOWNLOAD+1)
            if len(body)>MAX_DOWNLOAD:raise ValueError("Source exceeds 8 MB limit")
            if mime in ("text/html","application/xhtml+xml"):
                parser=VisibleHTML()
                parser.feed(body.decode("utf-8-sig",errors="replace"))
                body=re.sub(r"\n{3,}","\n\n","".join(parser.chunks)).encode("utf-8")[:MAX_DOWNLOAD]
            return {"url":url,"data":body,"extension":accepted[mime],"content_type":mime}
        except (ssl.SSLError,TimeoutError,OSError,http.client.HTTPException) as exc:
            raise ValueError("Source network or TLS request failed") from exc
        finally:conn.close()
    raise ValueError("Too many source redirects")
