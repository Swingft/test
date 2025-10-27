"""
StreamProxy 클래스 정의

Proxy file-like object that forwards writes/flushes to the current echo object
stored in the shared holder dict. This allows redirect_stdout to remain bound to
a stable proxy while the prompt provider swaps which echo object is the active
target (include vs exclude) at runtime.
"""

from .tui import TUI, progress_bar

# shared TUI instance
tui = TUI()


class StreamProxy:
    """Proxy file-like object that forwards writes/flushes to the current echo object
    stored in the shared holder dict. This allows redirect_stdout to remain bound to
    a stable proxy while the prompt provider swaps which echo object is the active
    target (include vs exclude) at runtime.
    """
    def __init__(self, holder: dict):
        self._holder = holder
        
    def write(self, data):
        # forward writes to the currently selected echo target
        try:
            # if the preflight output contains indicators that an exclude phase is
            # starting (e.g. a candidate list or an explicit exclude-detected line),
            # create the exclude echo and switch the current proxy target so the
            # TUI shows the Include header above the Exclude header immediately.
            try:
                text = data if isinstance(data, str) else str(data)
                lowered = text.lower()
                trigger = False
                # trigger as early as possible, before the candidates list prints
                if ("exclude candidates overlap" in lowered or
                    "candidates:" in lowered or
                    "exclude candidate detected" in lowered or
                    "exclude this identifier" in lowered):
                    trigger = True
                if trigger:
                    # guard against repeated creation
                    if self._holder.get("exclude") is None:
                        try:
                            include_header = ""
                            exclude_header = f"Preflight: {progress_bar(0,1)}  - | Current: Checking Exclude List"
                            try:
                                tui.set_status([include_header, exclude_header, ""])
                            except Exception:
                                try:
                                    tui.set_status([exclude_header])
                                except Exception:
                                    pass
                            # create exclude echo then immediately switch current so upcoming lines go to exclude
                            excl = tui.make_stream_echo(header=exclude_header, tail_len=10)
                            self._holder["exclude"] = excl
                            # copy prior include tail for context, but do not duplicate current line to include
                            try:
                                inc = self._holder.get("include")
                                if inc is not None and hasattr(inc, "_tail") and hasattr(excl, "_tail"):
                                    for line in list(inc._tail):
                                        try:
                                            excl._tail.append(line)
                                        except Exception:
                                            pass
                            except Exception:
                                pass
                            # switch current before forwarding this write so Candidates go to exclude tail
                            if self._holder.get("proxy") is not None:
                                self._holder["current"] = "exclude"
                        except Exception:
                            pass
            except Exception:
                # non-fatal, continue to forward as usual
                pass

            cur = self._holder.get("current", "include")
            target = self._holder.get(cur)
            if target is not None:
                target.write(data)
        except Exception:
            pass
            
    def flush(self):
        try:
            cur = self._holder.get("current", "include")
            target = self._holder.get(cur)
            if target is not None:
                target.flush()
        except Exception:
            pass
