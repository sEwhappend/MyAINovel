from __future__ import annotations

from dataclasses import dataclass

from .llm import LLMClient, load_llm_config
from .pipeline import NovelPipeline
from .storage import NovelStore


APP_TITLE = "My AI Novel"


@dataclass
class ApplicationServices:
    store: NovelStore
    llm: LLMClient
    pipeline: NovelPipeline


def build_services(db_path: str | None = None) -> ApplicationServices:
    store = NovelStore(db_path) if db_path else NovelStore()
    llm = LLMClient(load_llm_config())
    pipeline = NovelPipeline(store, llm)
    return ApplicationServices(store=store, llm=llm, pipeline=pipeline)


class NovelApp:
    def __init__(self, services: ApplicationServices | None = None) -> None:
        self.title = APP_TITLE
        self.services = services or build_services()

    def run(self) -> None:
        try:
            from . import pyside_ui as pyside_entry
        except Exception:
            pyside_entry = None

        if pyside_entry is not None and getattr(pyside_entry, "PYSIDE6_AVAILABLE", False):
            print("[startup] Using PySide6 UI")
            pyside_entry.NovelDesktopUI(self.services, self.title).run()
            return

        print("[startup] Fallback to legacy tkinter UI")
        from .ui import NovelDesktopUI

        NovelDesktopUI(self.services, self.title).run()


def launch() -> None:
    NovelApp().run()
