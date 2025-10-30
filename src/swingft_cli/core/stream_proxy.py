"""
StreamProxy 클래스 정의

Proxy file-like object that forwards writes/flushes to the current echo object
stored in the shared holder dict. This allows redirect_stdout to remain bound to
a stable proxy while the prompt provider swaps which echo object is the active
target (include vs exclude) at runtime.
"""

from .tui import get_tui, progress_bar, _maybe_raise
import logging

# shared TUI instance (singleton)
tui = get_tui()


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
        # 1) pre-scan output to decide whether to switch to exclude echo
        try:
            text = data if isinstance(data, str) else str(data)
        except (UnicodeError, TypeError, ValueError) as e:
            logging.trace("StreamProxy.write: to-string failed: %s", e)
            _maybe_raise(e)
            # if conversion failed, give up early
            return

        lowered = text.lower()
        trigger = (
            ("exclude candidates overlap" in lowered)
            or ("candidates:" in lowered)
            or ("exclude candidate detected" in lowered)
            or ("exclude this identifier" in lowered)
        )

        if trigger:
            # guard against repeated creation
            if self._holder.get("exclude") is None:
                try:
                    include_header = ""
                    exclude_header = f"Preflight: {progress_bar(0,1)}  - | Current: Checking Exclude List"
                    try:
                        # best-effort status update for TUI panel using shared instance
                        tui.set_status([include_header, exclude_header, ""])  # isolated call
                    except (OSError, UnicodeEncodeError) as e:
                        logging.trace("StreamProxy.write: set_status failed: %s", e)
                        _maybe_raise(e)
                    # create exclude echo then immediately switch current so upcoming lines go to exclude
                    try:
                        excl = tui.make_stream_echo(header=exclude_header, tail_len=10)
                        self._holder["exclude"] = excl
                    except (OSError, UnicodeEncodeError) as e:
                        logging.warning("StreamProxy.write: make_stream_echo failed: %s", e)
                        _maybe_raise(e)
                    # copy prior include tail for context
                    try:
                        inc = self._holder.get("include")
                        if inc is not None and hasattr(inc, "_tail") and hasattr(excl, "_tail"):
                            for line in list(inc._tail):
                                try:
                                    excl._tail.append(line)
                                except (AttributeError) as e:
                                    logging.trace("StreamProxy.write: tail append failed: %s", e)
                                    _maybe_raise(e)
                    except AttributeError as e:
                        logging.trace("StreamProxy.write: tail copy failed: %s", e)
                        _maybe_raise(e)
                    # switch current before forwarding this write so Candidates go to exclude tail
                    if self._holder.get("proxy") is not None:
                        self._holder["current"] = "exclude"
                except (OSError, UnicodeEncodeError, AttributeError) as e:
                    logging.trace("StreamProxy.write: exclude-switch block failed: %s", e)
                    _maybe_raise(e)

        # 2) forward the actual write to the selected target
        cur = self._holder.get("current", "include")
        target = self._holder.get(cur)
        if target is not None:
            try:
                target.write(data)
            except (OSError, UnicodeEncodeError) as e:
                logging.warning("StreamProxy.write: target write failed: %s", e)
                _maybe_raise(e)
            
    def flush(self):
        cur = self._holder.get("current", "include")
        target = self._holder.get(cur)
        if target is not None:
            try:
                target.flush()
            except OSError as e:
                logging.warning("StreamProxy.flush: target flush failed: %s", e)
                _maybe_raise(e)
