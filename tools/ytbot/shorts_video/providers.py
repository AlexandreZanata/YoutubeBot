"""Modular AI video provider abstraction for YouTube Shorts."""

from __future__ import annotations

import json
import os
import shutil
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .. import config
from ..accounts_store import read_private
from . import credits, flow_browser
from .models import (
    ProviderAuthRequiredError,
    ProviderUnavailableError,
    SceneSpec,
)
from .settings import VALID_MODELS
from .validator import validate_clip


class VideoGenerationProvider:
    """Base interface for Shorts video clip providers."""

    name: str = "base"

    def is_paid_api(self) -> bool:
        return False

    def supported_models(self) -> tuple[str, ...]:
        return VALID_MODELS

    def check_availability(self, settings: dict[str, Any]) -> dict[str, Any]:
        return {
            "provider": self.name,
            "available": False,
            "paid_api": self.is_paid_api(),
            "state": "unknown",
            "detail": "",
        }

    def estimate_credits(
        self, scene_count: int, model: str, settings: dict[str, Any]
    ) -> dict[str, Any]:
        return credits.estimate_short_cost(scene_count, self.name, model, settings)

    def reconcile_scene(
        self, scene: SceneSpec, run_dir: Path, settings: dict[str, Any]
    ) -> Path | None:
        """Inspect local or pending remote state before starting a retry."""
        local_clip = run_dir / "clips" / f"{scene.scene_id}.mp4"
        if local_clip.is_file() and validate_clip(local_clip).valid:
            return local_clip
        return None

    def generate_scene(
        self, scene: SceneSpec, run_dir: Path, settings: dict[str, Any]
    ) -> tuple[Path, float]:
        raise NotImplementedError


def _stage_clip_to_run(source: Path, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.resolve() != destination.resolve():
        shutil.copy2(source, destination)
    destination.chmod(0o600)
    return destination


def _find_staged_import(directories: list[Path], scene: SceneSpec) -> Path | None:
    candidates = [
        f"{scene.scene_id}.mp4",
        f"scene_{scene.scene_index}.mp4",
        f"scene-{scene.scene_index}.mp4",
        f"{scene.scene_index:02d}.mp4",
        f"{scene.scene_index}.mp4",
    ]
    for directory in directories:
        if not directory.is_dir():
            continue
        for name in candidates:
            candidate = directory / name
            if candidate.is_file() and not candidate.is_symlink():
                return candidate
    return None


class ManualVideoImportProvider(VideoGenerationProvider):
    """Zero-credit provider that imports user-supplied clips from local run folders."""

    name = "manual-import"

    def import_root(self, channel_slug: str, run_slug: str) -> Path:
        return config.ROOT / ".local" / "video-providers" / "manual-import" / channel_slug / run_slug

    def check_availability(self, settings: dict[str, Any]) -> dict[str, Any]:
        return {
            "provider": self.name,
            "available": True,
            "paid_api": False,
            "state": "ready",
            "detail": "Imports validated local MP4 scene clips without spending credits.",
        }

    def reconcile_scene(
        self, scene: SceneSpec, run_dir: Path, settings: dict[str, Any]
    ) -> Path | None:
        channel_slug = settings.get("channel") or (config.CHANNEL.slug if config.CHANNEL else "default")
        staged = _find_staged_import(
            [run_dir / "clips", self.import_root(str(channel_slug), run_dir.name)],
            scene,
        )
        if staged and validate_clip(staged).valid:
            return _stage_clip_to_run(staged, run_dir / "clips" / f"{scene.scene_id}.mp4")
        return None

    def generate_scene(
        self, scene: SceneSpec, run_dir: Path, settings: dict[str, Any]
    ) -> tuple[Path, float]:
        found = self.reconcile_scene(scene, run_dir, settings)
        if not found:
            raise ProviderUnavailableError(
                f"No valid imported clip found for {scene.scene_id}. "
                f"Place {scene.scene_id}.mp4 inside the run's clips/ folder."
            )
        return found, 0.0


class GoogleFlowProvider(VideoGenerationProvider):
    """Google AI Pro / Google Flow provider via isolated browser + assisted import workflow.

    Google Flow (flow.google / labs.google/fx/tools/flow) has no public developer API.
    This provider prioritizes:
      1. Reusing/importing clips already downloaded into `clips/` or Flow's `imports/<slug>/`.
      2. Checking the isolated Google Flow browser session when browser automation is active,
         pausing cleanly with `needs-login.json` if authentication expired.
      3. Preparing `flow-prompts.md` for assisted completion when automated Flow submission is
         unavailable or blocked by dynamic UI/challenge checks.
    """

    name = "google-flow"

    def __init__(self, store: flow_browser.FlowStore | None = None):
        self.store = store

    def _store(self) -> flow_browser.FlowStore:
        return self.store or flow_browser.FlowStore()

    def check_availability(self, settings: dict[str, Any]) -> dict[str, Any]:
        readiness = flow_browser.check_flow_readiness(self._store(), probe_browser=False)
        available = readiness["state"] in {"ready", "login_pending", "unknown"} or readiness["configured"]
        return {
            "provider": self.name,
            "available": bool(available),
            "paid_api": False,
            "state": readiness["state"],
            "credits_reported": readiness.get("credits_reported"),
            "detail": readiness["detail"],
        }

    def reconcile_scene(
        self, scene: SceneSpec, run_dir: Path, settings: dict[str, Any]
    ) -> Path | None:
        store = self._store()
        staged = _find_staged_import(
            [run_dir / "clips", store.imports_dir(run_dir.name), store.imports_dir()],
            scene,
        )
        if staged and validate_clip(staged).valid:
            return _stage_clip_to_run(staged, run_dir / "clips" / f"{scene.scene_id}.mp4")
        return None

    def _submit_via_browser(
        self, scene: SceneSpec, run_dir: Path, settings: dict[str, Any]
    ) -> Path | None:
        """Attempt compliant browser interaction on the authenticated Google Flow session."""
        from playwright.sync_api import sync_playwright

        store = self._store()
        if not (store.profile / "Default").is_dir():
            entry = flow_browser.record_flow_login_needed(
                "Google Flow profile is not signed in yet", store
            )
            raise ProviderAuthRequiredError(
                f"Google Flow login required ({entry['detail']}); connect in visible browser."
            )

        flow_browser.ensure_hidden_flow_browser(store)
        clips_dir = run_dir / "clips"
        clips_dir.mkdir(parents=True, exist_ok=True)
        dest = clips_dir / f"{scene.scene_id}.mp4"

        with sync_playwright() as playwright:
            browser = playwright.chromium.connect_over_cdp(
                f"http://127.0.0.1:{flow_browser.FLOW_CDP_PORT}"
            )
            context = browser.contexts[0]
            page = context.new_page()
            try:
                page.goto(flow_browser.FLOW_URL, timeout=45000, wait_until="domcontentloaded")
                page.wait_for_timeout(3000)
                state = flow_browser.inspect_flow_page(page)
                if state["state"] == "login_required":
                    flow_browser.record_flow_login_needed("Google Flow session expired", store)
                    raise ProviderAuthRequiredError(
                        "Google Flow session expired; sign in manually in the visible browser."
                    )
                if state["state"] == "challenge_required":
                    flow_browser.record_flow_login_needed(
                        "Google Flow requested verification challenge", store
                    )
                    raise ProviderAuthRequiredError(
                        "Google Flow presented a verification challenge; complete it manually in the visible browser."
                    )
                if state["state"] != "ready":
                    return None

                composer = page.locator('textarea, [contenteditable="true"]').first
                if not composer.is_visible(timeout=2000):
                    return None
                composer.click()
                composer.fill(scene.generation_prompt)

                # Prefer 9:16 portrait option when present in Flow UI.
                aspect_btn = page.locator('button:has-text("9:16"), [aria-label*="9:16" i]').first
                try:
                    if aspect_btn.is_visible(timeout=1000):
                        aspect_btn.click()
                except Exception:
                    pass

                submit_btn = page.locator(
                    'button[aria-label*="Generate" i], button[aria-label*="Create" i], '
                    'button:has-text("Create"), button:has-text("Generate")'
                ).first
                if not submit_btn.is_visible(timeout=2000):
                    return None
                submit_btn.click()

                deadline = time.time() + float(settings.get("flow_timeout_sec", 240))
                while time.time() < deadline:
                    download_btn = page.locator(
                        'a[download], button[aria-label*="Download" i], button:has-text("Download")'
                    ).last
                    try:
                        if download_btn.is_visible(timeout=1000):
                            with page.expect_download(timeout=30000) as download_info:
                                download_btn.click()
                            download = download_info.value
                            download.save_as(str(dest))
                            if validate_clip(dest).valid:
                                return dest
                    except Exception:
                        pass
                    page.wait_for_timeout(4000)
                return None
            finally:
                page.close()

    def generate_scene(
        self, scene: SceneSpec, run_dir: Path, settings: dict[str, Any]
    ) -> tuple[Path, float]:
        existing = self.reconcile_scene(scene, run_dir, settings)
        if existing:
            return existing, 0.0

        if bool(settings.get("flow_browser_submit", False)):
            generated = self._submit_via_browser(scene, run_dir, settings)
            if generated:
                return generated, credits.estimate_scene_cost(self.name, scene.model, settings)

        raise ProviderUnavailableError(
            "Google Flow automated clip capture is unavailable or waiting for assisted import. "
            f"Use {run_dir.name}/flow-prompts.md in Google Flow and place {scene.scene_id}.mp4 "
            "into clips/ (or enable static fallback)."
        )


class GeminiVideoAPIProvider(VideoGenerationProvider):
    """Official paid Gemini / Veo API provider. Disabled by default and never auto-enabled."""

    name = "gemini-api"
    BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
    MODEL_IDS = {
        "veo-2-fast": "veo-2.0-generate-001",
        "veo-2-quality": "veo-2.0-generate-001",
        "veo-3-fast": "veo-3.0-fast-generate-001",
        "veo-3-quality": "veo-3.0-generate-001",
    }

    def is_paid_api(self) -> bool:
        return True

    @staticmethod
    def config_path() -> Path:
        return config.ROOT / ".local" / "video-providers" / "gemini-api" / "config.json"

    def _api_key(self) -> str:
        payload = read_private(self.config_path(), {}) or {}
        key = str(payload.get("api_key") or os.environ.get("GEMINI_API_KEY") or "").strip()
        return key

    def check_availability(self, settings: dict[str, Any]) -> dict[str, Any]:
        if not settings.get("allow_paid_api", False):
            return {
                "provider": self.name,
                "available": False,
                "paid_api": True,
                "state": "disabled",
                "detail": "Paid Gemini Video API is disabled by default; explicit owner approval is required.",
            }
        has_key = bool(self._api_key())
        return {
            "provider": self.name,
            "available": has_key,
            "paid_api": True,
            "state": "ready" if has_key else "missing_api_key",
            "detail": (
                "Paid Gemini Video API explicitly approved and configured."
                if has_key
                else "Gemini API key missing in .local/video-providers/gemini-api/config.json."
            ),
        }

    def _http_json(
        self, url: str, *, payload: dict[str, Any] | None = None, api_key: str
    ) -> dict[str, Any]:
        headers = {"x-goog-api-key": api_key, "Content-Type": "application/json"}
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            if error.code in (401, 403):
                raise ProviderAuthRequiredError("Gemini Video API key was rejected.") from error
            raise ProviderUnavailableError(f"Gemini Video API HTTP error {error.code}") from error
        except (OSError, urllib.error.URLError, ValueError) as error:
            raise ProviderUnavailableError(f"Gemini Video API request failed: {error}") from error

    def _download_video(self, uri: str, dest: Path, api_key: str) -> Path:
        dest.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(uri, headers={"x-goog-api-key": api_key})
        with urllib.request.urlopen(req, timeout=60) as response:
            dest.write_bytes(response.read())
        dest.chmod(0o600)
        return dest

    def _poll_operation(
        self, operation_name: str, dest: Path, api_key: str, *, timeout_sec: float
    ) -> Path | None:
        deadline = time.time() + timeout_sec
        op_url = f"{self.BASE_URL}/{operation_name.lstrip('/')}"
        while time.time() < deadline:
            body = self._http_json(op_url, api_key=api_key)
            if body.get("error"):
                raise ProviderUnavailableError(
                    str(body["error"].get("message") or "Gemini Video operation failed")
                )
            if body.get("done"):
                response = body.get("response") or {}
                samples = (
                    (response.get("generateVideoResponse") or {}).get("generatedSamples")
                    or response.get("generatedVideos")
                    or []
                )
                for sample in samples:
                    video_uri = (sample.get("video") or {}).get("uri") or sample.get("uri")
                    if video_uri:
                        return self._download_video(str(video_uri), dest, api_key)
                return None
            time.sleep(5)
        return None

    def reconcile_scene(
        self, scene: SceneSpec, run_dir: Path, settings: dict[str, Any]
    ) -> Path | None:
        local = super().reconcile_scene(scene, run_dir, settings)
        if local:
            return local
        if not scene.operation_name or not settings.get("allow_paid_api", False):
            return None
        api_key = self._api_key()
        if not api_key:
            return None
        dest = run_dir / "clips" / f"{scene.scene_id}.mp4"
        found = self._poll_operation(scene.operation_name, dest, api_key, timeout_sec=10.0)
        if found and validate_clip(found).valid:
            return found
        return None

    def generate_scene(
        self, scene: SceneSpec, run_dir: Path, settings: dict[str, Any]
    ) -> tuple[Path, float]:
        if not settings.get("allow_paid_api", False):
            raise ProviderUnavailableError(
                "Paid Gemini Video API is disabled by default; approve paid billing explicitly before use."
            )
        if float(settings.get("max_credits_per_short", 0.0)) <= 0 or float(
            settings.get("max_credits_per_batch", 0.0)
        ) <= 0:
            raise ProviderUnavailableError(
                "A positive spending limit is required before calling the paid Gemini Video API."
            )
        api_key = self._api_key()
        if not api_key:
            raise ProviderAuthRequiredError(
                "Gemini Video API key missing in .local/video-providers/gemini-api/config.json."
            )

        dest = run_dir / "clips" / f"{scene.scene_id}.mp4"
        reconciled = self.reconcile_scene(scene, run_dir, settings)
        if reconciled:
            return reconciled, 0.0

        api_model = self.MODEL_IDS.get(scene.model, "veo-2.0-generate-001")
        url = f"{self.BASE_URL}/models/{api_model}:predictLongRunning"
        payload = {
            "instances": [{"prompt": scene.generation_prompt}],
            "parameters": {
                "aspectRatio": "9:16",
                "durationSeconds": int(max(5, min(8, round(scene.duration_sec)))),
            },
        }
        started = self._http_json(url, payload=payload, api_key=api_key)
        op_name = str(started.get("name") or "")
        if not op_name:
            raise ProviderUnavailableError("Gemini Video API did not return an operation ID")
        scene.operation_name = op_name
        downloaded = self._poll_operation(
            op_name, dest, api_key, timeout_sec=float(settings.get("api_timeout_sec", 240.0))
        )
        if not downloaded:
            raise ProviderUnavailableError(
                f"Gemini Video operation {op_name} is still pending; reconcile before retrying."
            )
        return downloaded, credits.estimate_scene_cost(self.name, scene.model, settings)


def get_provider(name: str) -> VideoGenerationProvider:
    mapping: dict[str, type[VideoGenerationProvider]] = {
        "google-flow": GoogleFlowProvider,
        "gemini-api": GeminiVideoAPIProvider,
        "manual-import": ManualVideoImportProvider,
    }
    cls = mapping.get(name)
    if cls is None:
        raise ValueError(f"Unsupported Shorts video provider: {name!r}")
    return cls()
