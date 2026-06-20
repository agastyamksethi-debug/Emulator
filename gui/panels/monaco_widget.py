"""
Monaco Editor widget — embeds the real VS Code editor engine via QWebEngineView.

Public API (mirrors what EditorPanel previously expected from _CodeEditor):
  widget.set_text(text)      — load content into the editor
  widget.get_text(callback)  — async: callback(text: str) called with content
  widget.set_read_only(bool) — toggle read-only
  widget.focus()             — focus the editor
"""
from __future__ import annotations
import os

from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore    import QWebEngineSettings, QWebEnginePage
from PyQt6.QtCore             import QUrl, pyqtSignal, QObject
from PyQt6.QtWidgets          import QWidget, QVBoxLayout


# ── paths ─────────────────────────────────────────────────────────────────────

_ASSETS  = os.path.join(os.path.dirname(__file__), "..", "assets")
_HTML    = os.path.abspath(os.path.join(_ASSETS, "monaco.html"))
_VS_DIR  = os.path.abspath(os.path.join(_ASSETS, "monaco", "vs"))
_LOADER  = os.path.join(_VS_DIR, "loader.js")
_CSS     = os.path.join(_VS_DIR, "editor", "editor.main.css")


def _make_html() -> str:
    """Stamp local file:// paths into the HTML template."""
    with open(_HTML) as f:
        html = f.read()
    loader_url = QUrl.fromLocalFile(_LOADER).toString()
    vs_url     = QUrl.fromLocalFile(_VS_DIR).toString()
    css_url    = QUrl.fromLocalFile(_CSS).toString()
    html = html.replace("__LOADER__", loader_url)
    html = html.replace("__VS__",     vs_url)
    html = html.replace("__CSS__",    css_url)
    return html


# ── silent page (suppress JS console noise) ───────────────────────────────────

class _SilentPage(QWebEnginePage):
    def javaScriptConsoleMessage(self, level, message, line, source):
        # only surface errors, not info/warnings from Monaco internals
        if level == QWebEnginePage.JavaScriptConsoleMessageLevel.ErrorMessageLevel:
            print(f"[Monaco JS error] {source}:{line} {message}")


# ── Monaco widget ─────────────────────────────────────────────────────────────

class MonacoWidget(QWidget):
    """
    Drop-in replacement for the old _CodeEditor QPlainTextEdit.
    Wraps a QWebEngineView hosting Monaco Editor (VS Code's editor engine).
    """

    ready = pyqtSignal()          # emitted once Monaco finishes loading

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ready  = False
        self._queue: list[str] = []   # JS to run once ready

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._view = QWebEngineView()
        self._view.setPage(_SilentPage(self._view))

        # enable local file access & JS
        settings = self._view.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled,          True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.ScrollAnimatorEnabled,      True)

        self._view.loadFinished.connect(self._on_load_finished)
        layout.addWidget(self._view)

        # load the HTML (base URL = assets dir so local file:// loads work)
        html    = _make_html()
        baseUrl = QUrl.fromLocalFile(os.path.abspath(_ASSETS) + "/")
        self._view.setHtml(html, baseUrl)

    # ── internal ──────────────────────────────────────────────────────────────

    def _on_load_finished(self, ok: bool):
        if not ok:
            print("[MonacoWidget] page load failed")
            return
        # Monaco init is async inside the page — poll until window._ed exists
        self._poll_ready()

    def _poll_ready(self):
        self._view.page().runJavaScript(
            "typeof window._ed !== 'undefined'",
            self._check_ready,
        )

    def _check_ready(self, result):
        if result:
            self._ready = True
            for js in self._queue:
                self._view.page().runJavaScript(js)
            self._queue.clear()
            self.ready.emit()
        else:
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(100, self._poll_ready)

    def _run(self, js: str):
        """Run JS immediately if ready, otherwise queue it."""
        if self._ready:
            self._view.page().runJavaScript(js)
        else:
            self._queue.append(js)

    # ── public API ────────────────────────────────────────────────────────────

    def set_text(self, text: str):
        import json
        self._run(f"window.__setContent({json.dumps(text)})")

    def get_text(self, callback):
        """Async — calls callback(str) with the current editor content."""
        self._view.page().runJavaScript("window.__getContent()", callback)

    def set_read_only(self, read_only: bool):
        self._run(f"window.__setReadOnly({'true' if read_only else 'false'})")

    def focus(self):
        self._run("window.__focus()")
        self._view.setFocus()
