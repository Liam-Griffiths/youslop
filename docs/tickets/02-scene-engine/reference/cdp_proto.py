import fcntl, base64, itertools, json, os, queue, subprocess, sys, tempfile, threading, time

class Cdp:
    def __init__(self, w, r):
        self.w, self.r = w, r
        self.ids = itertools.count(1); self.waiting = {}; self.events = []
        self.lock = threading.Lock()
        threading.Thread(target=self._read, daemon=True).start()
    def _read(self):
        buf = b""
        while True:
            chunk = os.read(self.r, 1 << 20)
            if not chunk: break
            buf += chunk
            while b"\0" in buf:
                raw, buf = buf.split(b"\0", 1)
                self.route(json.loads(raw))
    def route(self, msg):
        if "id" in msg:
            q = self.waiting.pop(msg["id"], None)
            if q: q.put(msg)
        else:
            self.events.append(msg); self.events[:] = self.events[-200:]
    def send(self, method, params=None, session=None, timeout=8):
        i = next(self.ids); q = queue.Queue(1); self.waiting[i] = q
        msg = {"id": i, "method": method, "params": params or {}}
        if session: msg["sessionId"] = session
        with self.lock: os.write(self.w, json.dumps(msg).encode() + b"\0")
        rep = q.get(timeout=timeout)
        if "error" in rep: raise RuntimeError(f"{method}: {rep['error']}")
        return rep.get("result", {})
    def wait_event(self, method, timeout=8):
        end = time.time() + timeout
        while time.time() < end:
            for e in self.events:
                if e.get("method") == method:
                    self.events.remove(e); return e
            time.sleep(0.01)
        raise TimeoutError(method)

def launch(exe, prof):
    # Parent ends: we write to_child_w, read from_child_r.
    to_child_r, to_child_w = os.pipe()
    from_child_r, from_child_w = os.pipe()
    def wire():                         # runs in the child before exec
        # Move both ends above 4 first so dup2 onto 3/4 can never clobber one another.
        # F_DUPFD with a floor of 5 gives two fresh, distinct fds above 4, so the
        # dup2 onto 3 and 4 below can never overwrite the other end.
        a = fcntl.fcntl(to_child_r, fcntl.F_DUPFD, 5)
        b = fcntl.fcntl(from_child_w, fcntl.F_DUPFD, 5)
        os.dup2(a, 3); os.dup2(b, 4)
    proc = subprocess.Popen(
        [exe, "--headless=new", "--remote-debugging-pipe", f"--user-data-dir={prof}",
         "--no-first-run", "--no-default-browser-check", "--disable-extensions",
         "--hide-scrollbars", "--force-color-profile=srgb", "--mute-audio", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        pass_fds=(3, 4), preexec_fn=wire)
    os.close(to_child_r); os.close(from_child_w)
    return proc, Cdp(to_child_w, from_child_r)

if __name__ == "__main__":
    W, H = int(sys.argv[1]), int(sys.argv[2])
    with tempfile.TemporaryDirectory() as prof:
        proc, c = launch("/usr/bin/chromium", prof)
        try:
            print(c.send("Browser.getVersion")["product"])
            t = next(t for t in c.send("Target.getTargets")["targetInfos"] if t["type"] == "page")
            s = c.send("Target.attachToTarget", {"targetId": t["targetId"], "flatten": True})["sessionId"]
            c.send("Page.enable", session=s); c.send("Runtime.enable", session=s)
            c.send("Emulation.setDeviceMetricsOverride", {"width": W, "height": H, "deviceScaleFactor": 1, "mobile": False}, session=s)
            html = "<html><body style='margin:0;background:#111'><div id=b style='position:absolute;width:200px;height:200px;background:#FF5A1F'></div><script>window.__seek=t=>{b.style.left=(t*300)+'px';return new Promise(r=>requestAnimationFrame(()=>r()))}</script></body></html>"
            c.send("Page.navigate", {"url": "data:text/html;base64," + base64.b64encode(html.encode()).decode()}, session=s)
            c.wait_event("Page.loadEventFired")
            t0 = time.time(); shots = []
            for i in range(30):
                c.send("Runtime.evaluate", {"expression": f"window.__seek({i/30})", "awaitPromise": True}, session=s)
                shots.append(base64.b64decode(c.send("Page.captureScreenshot", {"format": "png", "fromSurface": True}, session=s)["data"]))
            dt = time.time() - t0
            a = c.send("Runtime.evaluate", {"expression": "window.__seek(0.5)", "awaitPromise": True}, session=s)
            one = base64.b64decode(c.send("Page.captureScreenshot", {"format": "png"}, session=s)["data"])
            two = base64.b64decode(c.send("Page.captureScreenshot", {"format": "png"}, session=s)["data"])
            print(f"{W}x{H}: 30 frames in {dt:.2f}s = {30/dt:.1f} fps; png {len(shots[0])} bytes; repeat identical: {one == two}; frame15==seek0.5: {shots[15] == one}")
        finally:
            proc.terminate(); proc.wait(timeout=10)
