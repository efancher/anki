"""Run the WK Anki add-ons' logic headlessly against a real Collection.

The add-ons in anki_addon/ are written as thin aqt (GUI) wrappers around
plain functions that take a Collection. This installs a minimal fake `aqt`
module — just enough surface (mw.col, mw.reset, mw.pm.profileFolder,
gui_hooks.*.append, QAction/QFileDialog, show*/tooltip) for those wrapper
functions to run — then calls the add-on's real entry point directly.
Nothing about the add-ons' logic is duplicated or reimplemented here.

Precedent: tests/test_anki25_collection_compat.py stubs aqt the same way
to test wk_deck_options against a real Collection.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from anki.collection import Collection

REPO_ROOT = Path(__file__).resolve().parent.parent
ADDON_DIR = REPO_ROOT / "anki_addon"


class _Blackhole:
    """Swallows any attribute access/call. Used for aqt surface the add-ons
    reference but never invoke in a headless run (e.g. mw.form.menuTools —
    only touched inside menu-setup functions we never call)."""

    def __getattr__(self, _name: str) -> "_Blackhole":
        return _Blackhole()

    def __call__(self, *_args, **_kwargs) -> "_Blackhole":
        return _Blackhole()

    def __bool__(self) -> bool:
        return False


class _NoopHookList(list):
    def append(self, *_args, **_kwargs) -> None:
        return None


class _HookNamespace:
    def __getattr__(self, _name: str) -> _NoopHookList:
        return _NoopHookList()


class _MessageRecorder:
    """Stands in for showInfo/showWarning/showText/tooltip: records the
    message text instead of popping a dialog, so callers can recover the
    summary text add-ons normally only show inside Anki's GUI."""

    def __init__(self) -> None:
        self.messages: List[str] = []

    def __call__(self, *args, **_kwargs) -> None:
        if args:
            self.messages.append(str(args[0]))


def _install_aqt_stubs(col: Collection, profile_dir: Path, recorder: _MessageRecorder) -> None:
    mw = types.SimpleNamespace()
    mw.col = col
    mw.reset = lambda *a, **k: None
    mw.pm = types.SimpleNamespace(profileFolder=lambda: str(profile_dir))
    mw.form = _Blackhole()

    aqt_module = types.ModuleType("aqt")
    aqt_module.mw = mw
    aqt_module.gui_hooks = _HookNamespace()
    sys.modules["aqt"] = aqt_module

    class _QFileDialogStub:
        # Headless stand-in for a "user cancelled the file picker" — add-ons
        # only reach this when none of their well-known config paths exist.
        @staticmethod
        def getOpenFileName(*_args, **_kwargs):
            return "", ""

    qt_module = types.ModuleType("aqt.qt")
    qt_module.QAction = object
    qt_module.QFileDialog = _QFileDialogStub
    sys.modules["aqt.qt"] = qt_module

    utils_module = types.ModuleType("aqt.utils")
    for name in ("showInfo", "showWarning", "showText", "showCritical", "tooltip", "askUser"):
        setattr(utils_module, name, recorder)
    sys.modules["aqt.utils"] = utils_module


def _load_addon_module(addon_name: str, module_id: str):
    addon_path = ADDON_DIR / addon_name / "__init__.py"
    if not addon_path.is_file():
        raise RuntimeError(f"add-on not found: {addon_path}")
    # Loaded as a package (submodule_search_locations) so the add-on's own
    # `from .logic import ...` relative imports resolve correctly.
    spec = importlib.util.spec_from_file_location(
        module_id, addon_path, submodule_search_locations=[str(addon_path.parent)]
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load add-on module: {addon_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_id] = module
    spec.loader.exec_module(module)
    return module


@dataclass
class AddonRunResult:
    operation: str
    summary: str
    details: dict = field(default_factory=dict)


def run_apply_deck_options(col: Collection, profile_dir: Path) -> AddonRunResult:
    recorder = _MessageRecorder()
    _install_aqt_stubs(col, profile_dir, recorder)
    module = _load_addon_module("wk_deck_options", "wk_deck_options_headless")
    module.apply_deck_options()
    return AddonRunResult(
        operation="apply-deck-options",
        summary="\n".join(recorder.messages) or "(no output)",
    )


def run_unlock_pass(col: Collection, profile_dir: Path) -> AddonRunResult:
    recorder = _MessageRecorder()
    _install_aqt_stubs(col, profile_dir, recorder)
    module = _load_addon_module("wk_unlock", "wk_unlock_headless")
    unlocked, updated = module.run_unlock_pass(quiet=True)
    return AddonRunResult(
        operation="unlock-pass",
        summary=f"Unsuspended {unlocked} card(s); {updated} note(s)/hints updated.",
        details={"unlocked": unlocked, "updated": updated},
    )


def run_adjust_new_limits(col: Collection, profile_dir: Path) -> AddonRunResult:
    recorder = _MessageRecorder()
    _install_aqt_stubs(col, profile_dir, recorder)
    module = _load_addon_module("wk_adaptive_new", "wk_adaptive_new_headless")
    budget, summary_lines = module.adjust_new_limits(quiet=True)
    return AddonRunResult(
        operation="adjust-new-limits",
        summary="\n".join(summary_lines),
        details={"budget": budget},
    )


def run_health_check(col: Collection, profile_dir: Path) -> AddonRunResult:
    recorder = _MessageRecorder()
    _install_aqt_stubs(col, profile_dir, recorder)
    module = _load_addon_module("wk_health_check", "wk_health_check_headless")
    module.run_health_check(save_after=True)
    return AddonRunResult(
        operation="health-check",
        summary="\n".join(recorder.messages) or "(no output)",
    )


OPERATIONS = {
    "apply-deck-options": run_apply_deck_options,
    "unlock-pass": run_unlock_pass,
    "adjust-new-limits": run_adjust_new_limits,
    "health-check": run_health_check,
}
