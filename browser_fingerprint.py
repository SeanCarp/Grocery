"""Dump the browser fingerprint this machine presents, for comparison.

Runs one isolated SeleniumBase CDP session against a neutral page, reads the
values anti-bot services commonly score, and writes them to a text file. Run it
on two machines and diff the output to see what actually differs between them.

This measures the local browser only. It does not contact, probe, or interact
with any anti-bot service.
"""

from __future__ import annotations

import argparse
import platform
import socket
import time
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from food_search import SearchError, resolve_browser_launch

NEUTRAL_URL = "https://example.com"

FINGERPRINT_SCRIPT = r"""
(() => {
  const safe = (fn, fallback = null) => {
    try {
      const value = fn();
      return value === undefined ? fallback : value;
    } catch (error) {
      return `<error: ${error.message}>`;
    }
  };

  const glInfo = (contextName) => safe(() => {
    const canvas = document.createElement('canvas');
    const gl = canvas.getContext(contextName);
    if (!gl) return null;
    const debug = gl.getExtension('WEBGL_debug_renderer_info');
    return {
      vendor: gl.getParameter(gl.VENDOR),
      renderer: gl.getParameter(gl.RENDERER),
      unmasked_vendor: debug ? gl.getParameter(debug.UNMASKED_VENDOR_WEBGL) : null,
      unmasked_renderer: debug ? gl.getParameter(debug.UNMASKED_RENDERER_WEBGL) : null,
      version: gl.getParameter(gl.VERSION),
      shading_language: gl.getParameter(gl.SHADING_LANGUAGE_VERSION),
      max_texture_size: gl.getParameter(gl.MAX_TEXTURE_SIZE),
      extension_count: (gl.getSupportedExtensions() || []).length
    };
  });

  const canvasHash = safe(() => {
    const canvas = document.createElement('canvas');
    canvas.width = 240;
    canvas.height = 60;
    const context = canvas.getContext('2d');
    context.textBaseline = 'top';
    context.font = '14px Arial';
    context.fillStyle = '#f60';
    context.fillRect(10, 10, 100, 30);
    context.fillStyle = '#069';
    context.fillText('fingerprint-probe', 12, 14);
    const data = canvas.toDataURL();
    let hash = 0;
    for (let index = 0; index < data.length; index++) {
      hash = ((hash << 5) - hash + data.charCodeAt(index)) | 0;
    }
    return (hash >>> 0).toString(16);
  });

  const fonts = safe(() => {
    const candidates = [
      'Arial', 'Helvetica', 'Times New Roman', 'Courier New', 'Georgia',
      'Segoe UI', 'Calibri', 'Cantarell', 'DejaVu Sans', 'Liberation Sans',
      'Ubuntu', 'Noto Sans', 'Roboto', 'SF Pro Text'
    ];
    return candidates.filter(name => document.fonts.check(`12px "${name}"`));
  }, []);

  return {
    navigator: {
      webdriver: safe(() => navigator.webdriver),
      user_agent: safe(() => navigator.userAgent),
      platform: safe(() => navigator.platform),
      vendor: safe(() => navigator.vendor),
      languages: safe(() => (navigator.languages || []).join(',')),
      hardware_concurrency: safe(() => navigator.hardwareConcurrency),
      device_memory: safe(() => navigator.deviceMemory),
      max_touch_points: safe(() => navigator.maxTouchPoints),
      pdf_viewer_enabled: safe(() => navigator.pdfViewerEnabled),
      plugin_count: safe(() => navigator.plugins.length),
      mime_type_count: safe(() => navigator.mimeTypes.length),
      webgpu_present: safe(() => Boolean(navigator.gpu)),
      ua_data: safe(() => navigator.userAgentData ? {
        mobile: navigator.userAgentData.mobile,
        platform: navigator.userAgentData.platform,
        brands: navigator.userAgentData.brands
          .map(brand => `${brand.brand} ${brand.version}`).join(' | ')
      } : null)
    },
    window: {
      chrome_object: safe(() => Boolean(window.chrome)),
      chrome_runtime: safe(() => Boolean(window.chrome && window.chrome.runtime)),
      device_pixel_ratio: safe(() => window.devicePixelRatio),
      inner_size: safe(() => `${window.innerWidth}x${window.innerHeight}`),
      outer_size: safe(() => `${window.outerWidth}x${window.outerHeight}`),
      screen_size: safe(() => `${screen.width}x${screen.height}`),
      screen_avail: safe(() => `${screen.availWidth}x${screen.availHeight}`),
      color_depth: safe(() => screen.colorDepth),
      pixel_depth: safe(() => screen.pixelDepth)
    },
    locale: {
      timezone: safe(() => Intl.DateTimeFormat().resolvedOptions().timeZone),
      timezone_offset: safe(() => new Date().getTimezoneOffset()),
      prefers_dark: safe(() => matchMedia('(prefers-color-scheme: dark)').matches),
      prefers_reduced_motion: safe(
        () => matchMedia('(prefers-reduced-motion: reduce)').matches
      )
    },
    webgl: glInfo('webgl'),
    webgl2: glInfo('webgl2'),
    canvas_hash: canvasHash,
    fonts_detected: fonts
  };
})()
"""

SOFTWARE_RENDERERS = ("swiftshader", "llvmpipe", "software", "mesa offscreen")


def flatten(value: Any, prefix: str = "") -> list[tuple[str, str]]:
    """Flatten the nested probe result into sorted key/value text rows."""
    rows: list[tuple[str, str]] = []
    if isinstance(value, dict):
        for key, nested in value.items():
            rows.extend(flatten(nested, f"{prefix}.{key}" if prefix else str(key)))
    elif isinstance(value, list):
        rows.append((prefix, ", ".join(str(item) for item in value) or "<empty>"))
    else:
        rows.append((prefix, "<null>" if value is None else str(value)))
    return rows


def assess(data: dict[str, Any]) -> list[str]:
    """Report the values most often scored as automation signals."""
    notes: list[str] = []
    navigator = data.get("navigator") or {}
    webgl = data.get("webgl") or {}

    if navigator.get("webdriver"):
        notes.append("navigator.webdriver is true (automation is being advertised)")
    if "HeadlessChrome" in str(navigator.get("user_agent", "")):
        notes.append("User agent reports HeadlessChrome")
    if not navigator.get("chrome_object", True) and not (
        data.get("window") or {}
    ).get("chrome_object"):
        notes.append("window.chrome is missing")

    renderer = str(webgl.get("unmasked_renderer") or webgl.get("renderer") or "")
    if not renderer:
        notes.append("No WebGL renderer available (GPU stack unavailable)")
    elif any(marker in renderer.lower() for marker in SOFTWARE_RENDERERS):
        notes.append(f"Software rendering in use: {renderer}")
    else:
        notes.append(f"Hardware rendering in use: {renderer}")

    if navigator.get("plugin_count") == 0:
        notes.append("navigator.plugins is empty")
    if not navigator.get("webgpu_present"):
        notes.append("WebGPU unavailable (often accompanies software rendering)")
    return notes


def capture(url: str, browser_mode: str) -> tuple[dict[str, Any], Any]:
    """Collect one fingerprint sample from an isolated browser session."""
    try:
        from seleniumbase import SB
    except ImportError as exc:
        raise SearchError("SeleniumBase is not installed. Run `uv sync` first.") from exc

    plan = resolve_browser_launch(browser_mode)
    with TemporaryDirectory(prefix="grocery-fingerprint-") as profile_directory:
        options: dict[str, Any] = {
            "uc": True,
            "locale_code": "en-US",
            "window_size": "1280,900",
            "user_data_dir": profile_directory,
            "do_not_track": True,
        }
        if plan.headed:
            options["headed"] = True
            if plan.chromium_arg:
                options["chromium_arg"] = plan.chromium_arg
        else:
            options["headless2"] = True

        try:
            with SB(**options) as sb:
                sb.activate_cdp_mode(url)
                time.sleep(2)
                data = sb.cdp.evaluate(FINGERPRINT_SCRIPT)
        except Exception as exc:
            raise SearchError(f"Fingerprint capture failed: {exc}") from exc

    if not isinstance(data, dict):
        raise SearchError("The browser returned an unexpected fingerprint payload.")
    return data, plan


def render_report(data: dict[str, Any], plan: Any, url: str) -> str:
    """Build the diff-friendly text report."""
    lines = [
        "# Browser fingerprint report",
        "",
        f"captured_at      : {datetime.now(UTC).isoformat()}",
        f"hostname         : {socket.gethostname()}",
        f"operating_system : {platform.system()} {platform.release()}",
        f"probe_url        : {url}",
        f"launch_backend   : {plan.backend}",
        f"launch_headed    : {plan.headed}",
        f"chromium_arg     : {plan.chromium_arg or '<none>'}",
        "",
        "## Assessment",
        "",
    ]
    lines.extend(f"- {note}" for note in assess(data))
    lines.extend(["", "## Measured values", ""])

    rows = flatten(data)
    width = max(len(key) for key, _ in rows)
    lines.extend(f"{key.ljust(width)} : {value}" for key, value in rows)
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Dump this machine's browser fingerprint to a text file."
    )
    parser.add_argument("--url", default=NEUTRAL_URL, help="neutral page to probe")
    parser.add_argument("--output", help="output text file path")
    parser.add_argument("--headed", action="store_true", help="force a headed browser")
    parser.add_argument(
        "--headless", action="store_true", help="force a headless browser"
    )
    arguments = parser.parse_args()

    if arguments.headed and arguments.headless:
        parser.error("Use either --headed or --headless, not both.")
    mode = "headed" if arguments.headed else "headless" if arguments.headless else "auto"

    try:
        data, plan = capture(arguments.url, mode)
    except SearchError as error:
        print(f"Error: {error}")
        return 1

    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    default_name = f"fingerprint_{socket.gethostname()}_{plan.backend}_{timestamp}.txt"
    output_path = Path(arguments.output or Path("diagnostics") / default_name)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_report(data, plan, arguments.url), encoding="utf-8")

    print(f"Saved fingerprint report to {output_path}")
    for note in assess(data):
        print(f"  - {note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
