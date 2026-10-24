"""Folders and files: open, find, recent, tidy Downloads, big files, delete to Recycle Bin."""

from __future__ import annotations

import logging
import os
import re
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterator

from rapidfuzz import fuzz

from winauto.adapters.winos.folders import folder as known_folder
from winauto.adapters.winos.shell import move_to_trash, open_target
from winauto.core.context import Context
from winauto.core.matching import normalize
from winauto.core.skill import (
    QuickRule,
    Risk,
    Skill,
    Suggestion,
    ToolResult,
    fail,
    ok,
    tool,
)
from winauto.skills.shared.format import human_size

log = logging.getLogger(__name__)

KINDS: dict[str, set[str]] = {
    "image": {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".heic", ".svg", ".tif", ".tiff", ".ico", ".raw"},
    "video": {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".webm", ".flv", ".m4v"},
    "audio": {".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".wma"},
    "pdf": {".pdf"},
    "document": {".pdf", ".doc", ".docx", ".txt", ".rtf", ".odt", ".md", ".pages"},
    "spreadsheet": {".xls", ".xlsx", ".xlsm", ".csv", ".ods", ".numbers"},
    "presentation": {".ppt", ".pptx", ".odp", ".key"},
    "archive": {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".iso"},
    "installer": {".exe", ".msi", ".msix", ".appx", ".appxbundle", ".msixbundle"},
    "code": {".py", ".js", ".ts", ".html", ".css", ".java", ".c", ".cpp", ".h", ".cs", ".go", ".rs", ".json",
             ".xml", ".yml", ".yaml", ".ipynb", ".sh", ".bat", ".ps1", ".sql", ".php", ".rb", ".kt", ".swift"},
}
KIND_WORDS = {
    "photo": "image", "photos": "image", "picture": "image", "pictures": "image", "image": "image", "images": "image",
    "screenshot": "image", "video": "video", "videos": "video", "movie": "video", "song": "audio", "songs": "audio",
    "music": "audio", "audio": "audio", "pdf": "pdf", "pdfs": "pdf", "document": "document", "documents": "document",
    "doc": "document", "docs": "document", "spreadsheet": "spreadsheet", "excel": "spreadsheet", "sheet": "spreadsheet",
    "presentation": "presentation", "slides": "presentation", "ppt": "presentation", "zip": "archive",
    "installer": "installer", "setup": "installer", "code": "code",
}
SORT_FOLDERS = [("Images", "image"), ("Videos", "video"), ("Music", "audio"), ("Documents", "document"),
                ("Documents", "spreadsheet"), ("Documents", "presentation"), ("Archives", "archive"),
                ("Installers", "installer"), ("Code", "code")]
FOLDER_WORDS = {
    "desktop": "desktop", "download": "downloads", "downloads": "downloads", "document": "documents",
    "documents": "documents", "my documents": "documents", "picture": "pictures", "pictures": "pictures",
    "photos": "pictures", "music": "music", "video": "videos", "videos": "videos", "screenshots": "screenshots",
    "onedrive": "onedrive", "home": "home", "temp": "temp", "appdata": "appdata",
}
SKIP_DIRS = {"node_modules", ".git", "__pycache__", "appdata", "$recycle.bin", "venv", ".venv", "site-packages",
             "windows", "program files", "program files (x86)", "programdata", ".cache", ".gradle", ".m2",
             "system volume information", "dist", "build", ".idea", ".vscode"}
PARTIAL = {".crdownload", ".part", ".tmp", ".download", ".partial"}


def kind_of(path: Path) -> str:
    ext = path.suffix.lower()
    for kind in ("image", "video", "audio", "spreadsheet", "presentation", "archive", "installer", "code", "document"):
        if ext in KINDS[kind]:
            return kind
    return "other"


def _when(ts: float) -> str:
    d = datetime.fromtimestamp(ts)
    days = (datetime.now().date() - d.date()).days
    if days == 0:
        return "today " + d.strftime("%H:%M")
    if days == 1:
        return "yesterday"
    if days < 7:
        return d.strftime("%A")
    return d.strftime("%d %b %Y")


class FilesSkill(Skill):
    name = "files"
    icon = "folder"
    description = "Open folders, find and open files, tidy Downloads."
    keywords = (r"\b(files?|folders?|downloads?|documents?|desktop|pictures?|photos?|videos?|pdfs?|resume|cv|"
                r"screenshots?|recent|organi[sz]e|tidy|space|biggest|largest|delete|trash|recycle)\b")
    prompt_hint = "Files: find_files searches your folders by name; open_file opens the best match."

    def __init__(self, ctx: Context, roots: list[Path] | None = None, opener: Callable[[str], Any] | None = None,
                 trash: Callable[[str], Any] | None = None):
        super().__init__(ctx)
        self._roots = roots
        self._open = opener or open_target
        self._trash = trash or move_to_trash

    # ----- helpers -----

    def roots(self) -> list[Path]:
        if self._roots is not None:
            return self._roots
        out: list[Path] = []
        for name in ("desktop", "documents", "downloads", "pictures", "videos", "music", "onedrive"):
            p = known_folder(name)
            if p and p.exists() and not any(_inside(p, r) for r in out):
                out.append(p)
        return out or [Path.home()]

    def _folder(self, name: str) -> Path | None:
        key = name.strip().lower().removesuffix(" folder").strip()
        key = re.sub(r"^(?:my|the)\s+", "", key)
        if key in FOLDER_WORDS:
            if self._roots is not None:  # tests
                for r in self._roots:
                    if r.name.lower() == FOLDER_WORDS[key]:
                        return r
            return known_folder(FOLDER_WORDS[key])
        path = Path(os.path.expandvars(name.strip().strip('"'))).expanduser()
        if path.is_absolute() and path.exists():
            return path
        return None

    def walk(self, roots: list[Path], max_depth: int = 6, budget_s: float = 6.0,
             max_entries: int = 80000) -> Iterator[tuple[Path, os.stat_result]]:
        """Files under roots, skipping system and dev clutter, within a time budget."""
        deadline = time.time() + budget_s
        seen = 0
        stack = [(r, 0) for r in roots]
        while stack:
            current, depth = stack.pop()
            try:
                with os.scandir(current) as it:
                    for entry in it:
                        seen += 1
                        if seen > max_entries or time.time() > deadline:
                            return
                        try:
                            if entry.is_dir(follow_symlinks=False):
                                if depth < max_depth and entry.name.lower() not in SKIP_DIRS and not entry.name.startswith("."):
                                    stack.append((Path(entry.path), depth + 1))
                            elif entry.is_file(follow_symlinks=False):
                                yield Path(entry.path), entry.stat()
                        except OSError:
                            continue
            except OSError:
                continue

    def search(self, query: str, kind: str = "", folder: str = "", limit: int = 10) -> list[tuple[Path, os.stat_result, float]]:
        roots = [self._folder(folder)] if folder and self._folder(folder) else self.roots()
        words = [w for w in re.findall(r"[\w]+", query.lower()) if w not in ("my", "the", "a", "file", "files")]
        allowed = KINDS.get(kind) if kind else None
        found = []
        for path, st in self.walk(roots):
            if allowed and path.suffix.lower() not in allowed:
                continue
            name = path.stem.lower()
            if not words:
                score = 50.0
            elif all(w in name for w in words):
                score = 90.0 + 10.0 * len(" ".join(words)) / max(len(name), 1)
            else:
                partial = fuzz.partial_ratio(" ".join(words), name)
                if partial < 85:
                    continue
                score = partial * 0.9
            # Newer files win ties.
            age_days = max(0.0, (time.time() - st.st_mtime) / 86400)
            score += max(0.0, 5.0 - age_days / 30)
            found.append((path, st, score))
        found.sort(key=lambda x: -x[2])
        return found[:limit]

    # ----- tools -----

    @tool("Open a folder in File Explorer.",
          params={"folder": "desktop, downloads, documents, pictures, music, videos, screenshots, or a full path"},
          hides_popup=True)
    def open_folder(self, folder: str) -> ToolResult:
        if folder.strip().lower() in ("recycle bin", "trash", "bin"):
            self._open("shell:RecycleBinFolder")
            return ok("Opened the Recycle Bin.")
        path = self._folder(folder)
        if path is None:
            # Maybe it's a folder name somewhere in the usual places.
            q = folder.strip().lower()
            for root in self.roots():
                for p in root.glob("*"):
                    if p.is_dir() and p.name.lower() == q:
                        path = p
                        break
                if path:
                    break
        if path is None or not path.exists():
            return fail(f"I couldn't find a folder called '{folder}'.", fallback=True)
        self._open(str(path))
        return ok(f"Opened {path.name or path}.")

    @tool(
        "Find files by name in your usual folders (Desktop, Documents, Downloads, Pictures, Videos, Music, OneDrive).",
        params={"query": "Words from the file name", "kind": "Optional: image, video, audio, pdf, document, spreadsheet, presentation, archive, installer, code",
                "folder": "Optional folder to look in, e.g. downloads"},
    )
    def find_files(self, query: str, kind: str = "", folder: str = "") -> ToolResult:
        kind = KIND_WORDS.get(kind.lower(), kind.lower()) if kind else ""
        results = self.search(query, kind, folder)
        if not results:
            return ok(f"I couldn't find any {kind or 'file'}s matching “{query}”.", data={"files": []})
        lines = [f"{i}. **{p.name}** — {p.parent} ({human_size(st.st_size)}, {_when(st.st_mtime)})"
                 for i, (p, st, _) in enumerate(results, 1)]
        return ok("Found:\n" + "\n".join(lines), data={"files": [str(p) for p, _, _ in results]})

    @tool("Open a file with its usual app. Takes a full path or words from the file name.",
          params={"file": "Full path, or words from the name", "kind": "Optional kind to narrow the search"},
          hides_popup=True)
    def open_file(self, file: str, kind: str = "") -> ToolResult:
        path = Path(os.path.expandvars(file.strip().strip('"'))).expanduser()
        if not (path.is_absolute() and path.exists()):
            kind = KIND_WORDS.get(kind.lower(), kind.lower()) if kind else ""
            results = self.search(file, kind, limit=3)
            if not results:
                return fail(f"I couldn't find a file matching “{file}”.", fallback=True)
            path = results[0][0]
        self._open(str(path))
        return ok(f"Opened {path.name}.", data={"path": str(path)})

    @tool("Show recently used files, or the newest files in a folder.",
          params={"folder": "Optional folder (e.g. downloads) to list newest files from", "limit": "How many"})
    def recent_files(self, folder: str = "", limit: int = 10) -> ToolResult:
        limit = max(1, min(limit, 30))
        if folder:
            base = self._folder(folder)
            if base is None:
                return fail(f"I don't know the folder '{folder}'.")
            entries = [(p, p.stat()) for p in base.iterdir() if p.is_file() and p.suffix.lower() not in PARTIAL]
        else:
            base = known_folder("recent") if self._roots is None else self._roots[0]
            if base is None or not base.exists():
                return fail("I can't find your recent files list.")
            entries = [(p, p.stat()) for p in base.iterdir() if p.is_file() and p.suffix.lower() == ".lnk"]
        entries.sort(key=lambda x: -x[1].st_mtime)
        if not entries:
            return ok("Nothing there yet.")
        lines = [f"{i}. **{p.stem if p.suffix == '.lnk' else p.name}** ({_when(st.st_mtime)})"
                 for i, (p, st) in enumerate(entries[:limit], 1)]
        title = f"Newest in {base.name}" if folder else "Recent files"
        return ok(f"{title}:\n" + "\n".join(lines), data={"files": [str(p) for p, _ in entries[:limit]]})

    def _sort_plan(self) -> tuple[Path | None, dict[str, list[Path]]]:
        downloads = self._folder("downloads")
        plan: dict[str, list[Path]] = {}
        if downloads is None or not downloads.exists():
            return None, plan
        for p in downloads.iterdir():
            if not p.is_file() or p.suffix.lower() in PARTIAL or p.name.lower() == "desktop.ini":
                continue
            kind = kind_of(p)
            target = next((name for name, k in SORT_FOLDERS if k == kind), "Other")
            plan.setdefault(target, []).append(p)
        return downloads, plan

    @tool("Tidy the Downloads folder into subfolders by type (Images, Documents, Videos, Music, Archives, Installers, Code, Other).",
          risk=Risk.CONFIRM, confirm_label="Tidy up")
    def organize_downloads(self) -> ToolResult:
        downloads, plan = self._sort_plan()
        if downloads is None:
            return fail("I can't find your Downloads folder.")
        moved = 0
        for target, files in plan.items():
            dest_dir = downloads / target
            dest_dir.mkdir(exist_ok=True)
            for f in files:
                dest = _free_name(dest_dir / f.name)
                try:
                    shutil.move(str(f), str(dest))
                    moved += 1
                except OSError as exc:
                    log.info("couldn't move %s: %s", f, exc)
        if not moved:
            return ok("Downloads is already tidy.")
        summary = ", ".join(f"{len(v)} → {k}" for k, v in sorted(plan.items()))
        return ok(f"Moved {moved} file(s): {summary}.")

    @tool("List the biggest files in a folder (to free up space).",
          params={"folder": "Folder name or path (default downloads)", "limit": "How many"})
    def largest_files(self, folder: str = "downloads", limit: int = 10) -> ToolResult:
        base = self._folder(folder)
        if base is None:
            return fail(f"I don't know the folder '{folder}'.")
        files = sorted(((p, st) for p, st in self.walk([base], budget_s=8)), key=lambda x: -x[1].st_size)[:max(1, min(limit, 30))]
        if not files:
            return ok(f"{base.name} is empty.")
        total = sum(st.st_size for _, st in files)
        lines = [f"{i}. **{p.name}** — {human_size(st.st_size)} ({p.parent.name})" for i, (p, st) in enumerate(files, 1)]
        return ok(f"Biggest files in {base.name} ({human_size(total)} together):\n" + "\n".join(lines),
                  data={"files": [str(p) for p, _ in files]})

    @tool("Move a file or folder to the Recycle Bin. Needs a full path (use find_files first).",
          params={"path": "Full path"}, risk=Risk.CONFIRM, confirm_label="Move to Recycle Bin")
    def delete_file(self, path: str) -> ToolResult:
        p = Path(os.path.expandvars(path.strip().strip('"'))).expanduser()
        if not p.is_absolute() or not p.exists():
            return fail(f"I need the full path of an existing file, not '{path}'. Try find_files first.")
        protected = {Path.home()} | {known_folder(n) for n in ("desktop", "documents", "downloads", "pictures")}
        if p.resolve() in {q.resolve() for q in protected if q} or p.parent == p:
            return fail(f"I won't delete {p}; it's one of your main folders.")
        try:
            self._trash(str(p))
        except Exception as exc:
            return fail(f"Couldn't delete {p.name}: {exc}")
        return ok(f"Moved {p.name} to the Recycle Bin.")

    @tool("Create a new folder.", params={"name": "Folder name", "location": "Where (default desktop)"})
    def create_folder(self, name: str, location: str = "desktop") -> ToolResult:
        base = self._folder(location)
        if base is None:
            return fail(f"I don't know the folder '{location}'.")
        clean = re.sub(r'[<>:"/\\|?*]', "", name).strip()
        if not clean:
            return fail("That folder name isn't allowed.")
        target = base / clean
        if target.exists():
            return ok(f"{clean} already exists in {base.name}.")
        target.mkdir(parents=True)
        return ok(f"Created {clean} in {base.name}.", data={"path": str(target)})

    def preview(self, tool_name: str, args: dict[str, Any]) -> str | None:
        if tool_name == "organize_downloads":
            downloads, plan = self._sort_plan()
            if not plan:
                return "Downloads looks tidy already."
            return "Move files in Downloads into:\n" + "\n".join(f"- {k}: {len(v)} file(s)" for k, v in sorted(plan.items()))
        if tool_name == "delete_file":
            p = Path(str(args.get("path", "")))
            size = human_size(p.stat().st_size) if p.is_file() else "folder"
            return f"Move {p.name} ({size}) to the Recycle Bin?\n{p}"
        return None

    def suggest(self, query: str) -> list[Suggestion]:
        q = query.strip()
        out = []
        if q.startswith("/") and len(q) > 2:
            out.append(Suggestion(title=f"Find files named “{q[1:].strip()}”", subtitle="Desktop, Documents, Downloads…",
                                  tool="find_files", args={"query": q[1:].strip()}, kind="Files", icon="search", score=97))
        key = normalize(re.sub(r"^(?:open\s+)?(?:my\s+)?", "", q.lower())).removesuffix(" folder")
        if len(key) >= 3:
            for word, target in FOLDER_WORDS.items():
                if word.startswith(key) and word == target:
                    out.append(Suggestion(title=f"{target.title()} folder", subtitle="Open in File Explorer", tool="open_folder",
                                          args={"folder": target}, kind="Folder", icon="folder", score=88 if word == key else 78))
        return out

    def quick_rules(self) -> list[QuickRule]:
        folders = r"desktop|downloads?|documents?|my documents|pictures|photos|music|videos?|screenshots|onedrive|recycle bin|trash"

        return [
            QuickRule(rf"(?:open|show|go to)\s+(?:me\s+)?(?:my\s+|the\s+)?(?P<f>{folders})(?:\s+folder)?",
                      lambda m: ("open_folder", {"folder": m["f"]}), priority=35),
            QuickRule(r"(?:find|search\s+for|locate|where\s+is|where's)\s+(?:my\s+|the\s+)?(?P<q>.+?)\s+"
                      r"(?P<k>file|files|document|documents|doc|pdf|pdfs|photo|photos|picture|pictures|image|images|video|videos|song|songs|spreadsheet|presentation)",
                      lambda m: ("find_files", {"query": m["q"], **({"kind": KIND_WORDS[m["k"].lower()]}
                                                                      if m["k"].lower() not in ("file", "files") else {})}), priority=45),
            QuickRule(r"search\s+(?:my\s+)?(?:files|computer|pc|documents|downloads)\s+for\s+(?P<q>.+)",
                      lambda m: ("find_files", {"query": m["q"]}), priority=45),
            QuickRule(r"(?:find|locate)\s+(?:the\s+)?files?\s+(?:named|called)\s+(?P<q>.+)",
                      lambda m: ("find_files", {"query": m["q"]}), priority=45),
            QuickRule(r"(?:show\s+)?(?:my\s+)?recent(?:ly used)?\s+(?:files|documents)", lambda m: ("recent_files", {})),
            QuickRule(r"(?:show\s+)?(?:my\s+)?(?:recent|latest|newest)\s+downloads", lambda m: ("recent_files", {"folder": "downloads"})),
            QuickRule(r"(?:organi[sz]e|clean\s+up|tidy(?:\s+up)?|sort)\s+(?:my\s+|the\s+)?downloads?(?:\s+folder)?",
                      lambda m: ("organize_downloads", {})),
            QuickRule(r"(?:what(?:'s| is)\s+)?(?:taking\s+up|using)\s+(?:the\s+most\s+|so\s+much\s+)?space(?:\s+in\s+(?:my\s+)?(?P<f>\w+))?"
                      r"|(?:biggest|largest)\s+files(?:\s+in\s+(?:my\s+)?(?P<f2>\w+))?",
                      lambda m: ("largest_files", {"folder": m["f"] or m["f2"] or "downloads"})),
        ]


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _free_name(path: Path) -> Path:
    if not path.exists():
        return path
    for i in range(1, 1000):
        candidate = path.with_name(f"{path.stem} ({i}){path.suffix}")
        if not candidate.exists():
            return candidate
    return path.with_name(f"{path.stem} ({int(time.time())}){path.suffix}")




