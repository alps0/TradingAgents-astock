"""Software license protection for TradingAgents-Astock.

Adapted from ai-surveillance's license mechanism. Provides:

- Hardware fingerprint generation (cross-platform: Linux / macOS / Windows)
- RSA-signed license certificate verification
- License status query and feature gating
- File-watch based hot reload of imported certificates

License certificate is a JSON file signed with RSA-PKCS1v15-SHA256.
The matching public key is bundled with the package at
``tradingagents/data/keys/public_key.pem`` for verification.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
import subprocess
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ── Feature catalog ──────────────────────────────────────────────────────────

# Features that require a valid license to use.
LICENSED_FEATURES: list[str] = [
    "stock_analysis",        # 启动新的多 Agent 分析任务
    "pdf_export",            # 导出 PDF 研报
    "history_view",          # 浏览完整历史分析详情
    "bull_bear_debate",      # 多空辩论
    "risk_debate",           # 三方风险辩论
    "policy_analysis",       # 政策分析师
    "hot_money_tracking",    # 游资追踪
    "lockup_monitoring",     # 解禁监控
    "fundamentals_analysis", # 基本面分析
    "news_analysis",         # 新闻分析
    "social_media_analysis", # 情绪分析
    "market_analysis",       # 市场面分析
]

# Features always available (regardless of license status).
ALWAYS_AVAILABLE: list[str] = [
    "system_settings",       # 系统设置
    "license_management",    # 授权管理本身
    "live_preview",          # 实时预览 / 欢迎页
]


# ── Hardware fingerprint ─────────────────────────────────────────────────────


class HardwareFingerprint:
    """Manage a stable machine identifier for license fingerprinting.

    Strategy:
    1. On first run, read the OS-provided machine ID:
       - Linux: ``/etc/machine-id`` or ``/var/lib/dbus/machine-id``
       - macOS: ``IOPlatformUUID`` (via ``ioreg``)
       - Windows: ``MachineGuid`` (via ``reg query``)
    2. If the system machine ID is available, use it as the stored identifier
       (stronger hardware binding).
    3. If it is unavailable (or the OS is unknown), fall back to a generated
       UUID-4 (auxiliary identifier — still stable, but not hardware-bound).
    4. The chosen identifier is persisted to ``~/.tradingagents/machine_id``
       (JSON) so it survives Docker container rebuilds when the
       ``tradingagents-data`` volume is mounted (see ``docker-compose.yml``).

    On bare metal / VM, the system machine ID provides real hardware binding.
    In Docker, the system machine ID is captured on first run and then persists
    in the volume — so the fingerprint stays stable across container rebuilds
    even if ``/etc/machine-id`` would change.
    """

    @staticmethod
    def _try_read_file(path: str) -> str | None:
        """Read a short text file, returning None on failure."""
        try:
            with open(path, "r") as f:
                value = f.read().strip()
                return value or None
        except Exception:
            return None

    @staticmethod
    def _try_run_cmd(cmd: list[str], timeout: int = 5) -> str | None:
        """Run a command and return its stdout, or None on failure."""
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout, check=False
            )
            return result.stdout.strip() or None
        except Exception:
            return None

    @staticmethod
    def _read_system_machine_id() -> str | None:
        """Read the OS-provided machine ID. Returns None if unavailable.

        - Linux: ``/etc/machine-id`` (or ``/var/lib/dbus/machine-id``)
        - macOS: ``IOPlatformUUID`` via ``ioreg``
        - Windows: ``MachineGuid`` from the Windows registry
        """
        system = platform.system().lower()
        try:
            if system == "linux":
                return (
                    HardwareFingerprint._try_read_file("/etc/machine-id")
                    or HardwareFingerprint._try_read_file("/var/lib/dbus/machine-id")
                )
            elif system == "darwin":
                ioreg = HardwareFingerprint._try_run_cmd(
                    ["ioreg", "-d2", "-c", "IOPlatformExpertDevice"]
                )
                if ioreg:
                    for line in ioreg.splitlines():
                        if "IOPlatformUUID" in line and "=" in line:
                            return line.split("=", 1)[-1].strip().strip('"') or None
                return None
            elif system == "windows":
                reg = HardwareFingerprint._try_run_cmd(
                    ["reg", "query", r"HKLM\SOFTWARE\Microsoft\Cryptography",
                     "/v", "MachineGuid"]
                )
                if reg:
                    for line in reg.splitlines():
                        if "MachineGuid" in line:
                            parts = line.split()
                            if parts:
                                return parts[-1]
                return None
        except Exception as exc:
            logger.warning(f"Failed to read system machine ID: {exc}")
        return None

    @staticmethod
    def _stable_id_path() -> Path:
        """Return the path to the stable machine identity file."""
        home = os.path.expanduser("~")
        return Path(home) / ".tradingagents" / "machine_id"

    @staticmethod
    def _get_or_create_stable_identity() -> tuple[str, str, str]:
        """Return ``(machine_id, source, hostname)``, creating on first call.

        On first invocation:
        1. Try to read the OS-provided machine ID (e.g. ``/etc/machine-id``).
        2. If available, use it as the stored identifier (``source="system"``).
        3. If not, generate a UUID-4 as an auxiliary identifier
           (``source="uuid"``).
        4. Persist the identifier + source + hostname to
           ``~/.tradingagents/machine_id`` (JSON).

        On subsequent calls, reads from the file — so the identity survives
        container rebuilds, package upgrades, and machine migrations (as long
        as the directory is preserved via a Docker named volume).
        """
        id_path = HardwareFingerprint._stable_id_path()
        id_path.parent.mkdir(parents=True, exist_ok=True)

        # Diagnostic logging (DEBUG level) — helps debug fingerprint
        # instability in Docker. Enable via logging level DEBUG.
        home_env = os.environ.get("HOME", "<unset>")
        etc_machine_id = HardwareFingerprint._try_read_file("/etc/machine-id")
        logger.debug(
            f"[fingerprint-diag] HOME={home_env!r} "
            f"id_path={id_path} exists={id_path.exists()} "
            f"/etc/machine-id={etc_machine_id!r}"
        )

        if id_path.exists():
            try:
                data = json.loads(id_path.read_text(encoding="utf-8"))
                machine_id = data.get("machine_id", "")
                source = data.get("source", "unknown")
                hostname = data.get("hostname", "")
                if machine_id:
                    logger.debug(
                        f"[fingerprint-diag] using stored identity "
                        f"machine_id={machine_id!r} source={source!r} "
                        f"hostname={hostname!r}"
                    )
                    return machine_id, source, hostname
                logger.warning(
                    "[fingerprint-diag] stored machine_id file is "
                    "missing the 'machine_id' field — regenerating"
                )
            except Exception as exc:
                logger.warning(
                    f"[fingerprint-diag] failed to parse stored "
                    f"machine_id file ({exc}) — regenerating"
                )
                # fall through to generate a new one

        # First run: prefer system machine ID, fall back to UUID
        system_id = HardwareFingerprint._read_system_machine_id()
        if system_id:
            machine_id = system_id
            source = "system"
        else:
            machine_id = str(uuid.uuid4())
            source = "uuid"
        hostname = platform.node()

        # Atomic write: write to a temp file then rename. This avoids
        # partial-write corruption if the process is killed mid-write or
        # the volume runs out of space (which could leave an empty/corrupt
        # file that would force a different fingerprint on next start).
        tmp_path = id_path.with_suffix(".tmp")
        try:
            tmp_path.write_text(
                json.dumps({
                    "machine_id": machine_id,
                    "source": source,
                    "hostname": hostname,
                }, indent=2),
                encoding="utf-8",
            )
            tmp_path.replace(id_path)
        except Exception as exc:
            logger.error(
                f"[fingerprint-diag] failed to persist machine identity "
                f"to {id_path}: {exc}"
            )
            # Don't re-raise: returning the in-memory value is still useful
            # for the current process. The next start will regenerate.
        logger.info(
            f"[fingerprint-diag] generated new stable identity "
            f"machine_id={machine_id!r} source={source!r} "
            f"hostname={hostname!r} -> {id_path}"
        )
        return machine_id, source, hostname

    @staticmethod
    def collect_hardware_info() -> dict[str, str]:
        """Return a dict with the stable machine ID and metadata.

        Keys:
            ``machine_id`` — the identifier used for fingerprinting.
            ``source`` — ``"system"`` (OS-provided) or ``"uuid"`` (fallback).
            ``hostname`` — the hostname captured when the ID was first created.
        """
        machine_id, source, hostname = (
            HardwareFingerprint._get_or_create_stable_identity()
        )
        return {
            "machine_id": machine_id,
            "source": source,
            "hostname": hostname,
        }

    @staticmethod
    def generate_fingerprint(hardware_info: dict[str, str] | None = None) -> str:
        """Compute a SHA-256 fingerprint from the stable machine ID.

        The fingerprint is stable across Docker container rebuilds because
        it's derived from an identifier persisted in the volume.
        """
        if hardware_info is None:
            hardware_info = HardwareFingerprint.collect_hardware_info()
        machine_id = hardware_info.get("machine_id", "")
        return hashlib.sha256(machine_id.encode("utf-8")).hexdigest()

    @staticmethod
    def export_fingerprint(fingerprint: str, output_path: str | Path) -> None:
        """Write the fingerprint, timestamp, and hostname to a JSON file.

        The hostname is read from the stable identity file so it stays
        consistent across container rebuilds (rather than reflecting the
        ephemeral container ID).
        """
        _, _, hostname = HardwareFingerprint._get_or_create_stable_identity()
        data = {
            "fingerprint": fingerprint,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "hostname": hostname,
        }
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)


# ── License certificate validator ────────────────────────────────────────────


def _default_public_key_path() -> Path:
    """Return the path to the bundled public key.

    The public key is shipped as package data at
    ``tradingagents/data/keys/public_key.pem``.
    """
    return Path(__file__).parent / "data" / "keys" / "public_key.pem"


def _default_license_dir() -> Path:
    """Return the default license storage directory.

    Stored under ``~/.tradingagents/licenses/`` so it persists across
    container restarts and reinstalls.
    """
    home = os.path.expanduser("~")
    return Path(home) / ".tradingagents" / "licenses"


class LicenseValidator:
    """Verify a license certificate's signature, fingerprint, and expiry."""

    PUBLIC_KEY_PATH: Path = _default_public_key_path()

    def _verify_signature(self, license_info: dict[str, Any]) -> bool:
        cert_data = {k: v for k, v in license_info.items() if k != "signature"}
        signature_hex = license_info.get("signature", "")
        if not signature_hex:
            return False

        if not self.PUBLIC_KEY_PATH.exists():
            logger.warning(
                f"Public key not found at {self.PUBLIC_KEY_PATH}, "
                "skipping signature verification"
            )
            return True

        try:
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import padding

            public_pem = self.PUBLIC_KEY_PATH.read_bytes()
            public_key = serialization.load_pem_public_key(public_pem)

            signature = bytes.fromhex(signature_hex)
            message = json.dumps(cert_data, sort_keys=True, ensure_ascii=False).encode("utf-8")

            public_key.verify(signature, message, padding.PKCS1v15(), hashes.SHA256())
            return True
        except Exception as exc:
            logger.error(f"License signature verification failed: {exc}")
            return False

    def validate_certificate(
        self, license_info: dict[str, Any], current_fingerprint: str
    ) -> dict[str, str]:
        result: dict[str, str] = {"valid": "false", "reason": ""}

        if not self._verify_signature(license_info):
            result["reason"] = "invalid_signature"
            return result

        cert_fingerprint = license_info.get("fingerprint", "")
        if cert_fingerprint != current_fingerprint:
            result["reason"] = "fingerprint_mismatch"
            return result

        expires_at = license_info.get("expires_at")
        if expires_at:
            expires_at_dt = self._parse_dt(expires_at)
            if expires_at_dt is not None and datetime.now(timezone.utc) > expires_at_dt:
                result["reason"] = "expired"
                return result

        result["valid"] = "true"
        return result

    def check_expiry(self, license_info: dict[str, Any]) -> str:
        expires_at = license_info.get("expires_at")
        if not expires_at:
            return "unknown"

        expires_at_dt = self._parse_dt(expires_at)
        if expires_at_dt is None:
            return "unknown"

        now = datetime.now(timezone.utc)
        days_remaining = (expires_at_dt - now).days

        if days_remaining <= 0:
            return "expired"
        if days_remaining <= 30:
            return "expiring_soon"
        return "valid"

    @staticmethod
    def _parse_dt(value: Any) -> datetime | None:
        if isinstance(value, datetime):
            dt = value
        elif isinstance(value, str):
            try:
                dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return None
        else:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt


# ── License service (singleton) ──────────────────────────────────────────────


class LicenseService:
    """Manage license loading, validation, and status queries.

    Usage::

        from tradingagents.license_service import license_service

        status = license_service.get_license_status()
        if not status["is_licensed"]:
            # restrict features
            ...
    """

    EXPIRING_WARN_DAYS: int = 30
    # Background monitor checks once per day. Hardcoded (not configurable via
    # env) so that the check cadence can't be weakened at runtime.
    CHECK_INTERVAL_SECONDS: int = 86400  # 1 day

    def __init__(self, license_dir: Path | str | None = None) -> None:
        self._fingerprint: str | None = None
        self._hardware_info: dict[str, str] | None = None
        self._license_info: dict[str, Any] | None = None
        self._last_file_mtime: float | None = None
        self._license_dir: Path = Path(license_dir) if license_dir else _default_license_dir()
        self._previous_status: str | None = None
        self._loaded: bool = False
        # Background monitor state
        self._monitor_thread: threading.Thread | None = None
        self._monitor_stop: threading.Event | None = None
        self._monitor_interval: int = LicenseService.CHECK_INTERVAL_SECONDS
        self._lock: threading.Lock = threading.Lock()

    # ── Public API ─────────────────────────────────────────────────────────

    def get_fingerprint(self) -> str:
        if self._fingerprint is None:
            self._fingerprint = HardwareFingerprint.generate_fingerprint()
        return self._fingerprint

    def get_hardware_info(self) -> dict[str, str]:
        if self._hardware_info is None:
            self._hardware_info = HardwareFingerprint.collect_hardware_info()
        return self._hardware_info

    def export_fingerprint(self, output_path: str | Path) -> str:
        fp = self.get_fingerprint()
        HardwareFingerprint.export_fingerprint(fp, output_path)
        return fp

    def get_license_status(self) -> dict[str, Any]:
        """Return the current license status as a dict.

        Shape::

            {
                "is_licensed": bool,
                "license_type": str | None,
                "features": list[str],   # available features
                "expires_at": str | None,
                "days_remaining": int | None,
                "fingerprint": str,
                "status": str,            # valid|expiring_soon|expired|unlicensed|...
                "customer_name": str | None,
                "issuer": str | None,
            }

        Also lazily starts the background monitor thread on first call — this
        means the monitor runs regardless of whether ``web/app.py`` invokes
        ``start_monitor()`` explicitly (defense against tampering with the
        plaintext ``app.py`` after Cython compilation).
        """
        self.ensure_loaded()
        self._ensure_monitor_running()
        fp = self.get_fingerprint()

        if self._license_info is None:
            return {
                "is_licensed": False,
                "license_type": None,
                "features": list(ALWAYS_AVAILABLE),
                "expires_at": None,
                "days_remaining": None,
                "fingerprint": fp,
                "status": "unlicensed",
                "customer_name": None,
                "issuer": None,
            }

        validator = LicenseValidator()
        validation = validator.validate_certificate(self._license_info, fp)

        if validation["valid"] != "true":
            status = validation["reason"]
            if status == "fingerprint_mismatch":
                grace_end = self._license_info.get("grace_period_end")
                if grace_end:
                    grace_end_dt = LicenseValidator._parse_dt(grace_end)
                    if grace_end_dt is not None and datetime.now(timezone.utc) < grace_end_dt:
                        status = "grace_period"
            return {
                "is_licensed": False,
                "license_type": self._license_info.get("license_type"),
                "features": list(ALWAYS_AVAILABLE),
                "expires_at": self._license_info.get("expires_at"),
                "days_remaining": None,
                "fingerprint": fp,
                "status": status,
                "customer_name": self._license_info.get("customer_name"),
                "issuer": self._license_info.get("issuer"),
            }

        expiry_status = validator.check_expiry(self._license_info)
        expires_at = self._license_info.get("expires_at")
        days_remaining: int | None = None
        expires_at_dt = LicenseValidator._parse_dt(expires_at)
        if expires_at_dt is not None:
            days_remaining = (expires_at_dt - datetime.now(timezone.utc)).days

        features = set(ALWAYS_AVAILABLE)
        licensed = self._license_info.get("features", [])
        if licensed:
            features.update(licensed)
        else:
            features.update(LICENSED_FEATURES)

        return {
            "is_licensed": True,
            "license_type": self._license_info.get("license_type"),
            "features": sorted(features),
            "expires_at": expires_at,
            "days_remaining": days_remaining,
            "fingerprint": fp,
            "status": expiry_status,
            "customer_name": self._license_info.get("customer_name"),
            "issuer": self._license_info.get("issuer"),
        }

    def is_feature_enabled(self, feature: str) -> bool:
        status = self.get_license_status()
        return feature in status.get("features", ALWAYS_AVAILABLE)

    def import_license(self, cert_data: dict[str, Any]) -> None:
        """Load a license dict into memory (does not persist to disk)."""
        self._license_info = cert_data
        self._previous_status = None  # force re-evaluation

    def import_license_bytes(self, content: bytes, filename: str = "license.json") -> Path:
        """Validate and persist a license file to disk, then load it.

        Returns the path to the saved file. Raises ``ValueError`` on invalid
        certificate content or fingerprint mismatch.
        """
        try:
            cert_data = json.loads(content.decode("utf-8"))
        except Exception as exc:
            raise ValueError(f"证书文件不是合法的 JSON: {exc}") from exc

        if "fingerprint" not in cert_data or "signature" not in cert_data:
            raise ValueError("证书缺少必需字段 (fingerprint / signature)")

        fp = self.get_fingerprint()
        if cert_data.get("fingerprint") != fp:
            raise ValueError("证书与当前硬件指纹不匹配")

        self._license_dir.mkdir(parents=True, exist_ok=True)
        target = self._license_dir / filename
        counter = 1
        while target.exists():
            target = self._license_dir / f"{Path(filename).stem}_{counter}{Path(filename).suffix}"
            counter += 1
        target.write_bytes(content)
        logger.info(f"License file saved to {target}")

        self.import_license(cert_data)
        self._last_file_mtime = target.stat().st_mtime
        return target

    def load_from_directory(self, directory: Path | str | None = None) -> bool:
        """Load the most recent .json license from ``directory``.

        Returns True if a license was loaded.
        """
        if directory is not None:
            self._license_dir = Path(directory)
        license_dir = self._license_dir
        if not license_dir.is_dir():
            self._loaded = True
            return False

        json_files = sorted(
            license_dir.glob("*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for json_file in json_files:
            try:
                cert_data = json.loads(json_file.read_text(encoding="utf-8"))
                if "fingerprint" in cert_data and "signature" in cert_data:
                    self._license_info = cert_data
                    self._last_file_mtime = json_file.stat().st_mtime
                    self._loaded = True
                    logger.info(f"License loaded from {json_file}")
                    return True
            except Exception as exc:
                logger.warning(f"Failed to load license from {json_file}: {exc}")

        self._loaded = True
        return False

    def ensure_loaded(self) -> None:
        """Load from default directory once (idempotent)."""
        if self._loaded:
            return
        self.load_from_directory(self._license_dir)

    def reload(self) -> None:
        """Force reload from disk."""
        self._loaded = False
        self._license_info = None
        self.load_from_directory(self._license_dir)

    def get_license_dir(self) -> Path:
        return self._license_dir

    # ── Periodic monitor ─────────────────────────────────────────────────

    def _check_file_changed(self) -> bool:
        """Return True if license files on disk have changed since last load.

        Detects:
        - new .json files added to the directory
        - existing files modified (mtime increased)
        - all files removed while a license was previously loaded

        Tolerates races where a file is deleted between ``glob()`` and
        ``stat()`` — such files are silently skipped.
        """
        license_dir = self._license_dir
        if not license_dir.is_dir():
            # Directory gone — treat as "changed" if we previously had a license
            return self._license_info is not None

        json_files = list(license_dir.glob("*.json"))
        if not json_files:
            # No license files — treat as "changed" if we previously had one
            return self._license_info is not None

        # Gather mtimes, tolerating files that vanish mid-scan
        mtimes: list[float] = []
        for f in json_files:
            try:
                mtimes.append(f.stat().st_mtime)
            except FileNotFoundError:
                # Race: file deleted between glob and stat — skip it
                continue
        if not mtimes:
            return self._license_info is not None
        latest_mtime = max(mtimes)

        # If we have a loaded license and its mtime is current → no change
        if (
            self._last_file_mtime is not None
            and latest_mtime <= self._last_file_mtime
        ):
            return False

        # If we have NO loaded license but files exist → need to load
        if self._license_info is None:
            return True

        # License is loaded and the file mtime increased → file was modified
        return latest_mtime > (self._last_file_mtime or 0.0)

    def periodic_check(self) -> dict[str, Any]:
        """Run one check cycle. Reloads files if changed and logs status transitions.

        Safe to call from a background thread or directly. Returns the current
        status dict (same shape as ``get_license_status()``).
        """
        with self._lock:
            if self._check_file_changed():
                logger.info("License file change detected, reloading...")
                # Reset _loaded so ensure_loaded() will actually read the directory,
                # then drop the in-memory cert so load_from_directory() re-reads.
                self._loaded = False
                self._license_info = None
                self.load_from_directory(self._license_dir)

            status = self.get_license_status()

        current_status = status.get("status", "unknown")
        if current_status != self._previous_status:
            self._log_status_transition(current_status, status, self._previous_status)
            self._previous_status = current_status

        return status

    @staticmethod
    def _log_status_transition(
        current: str, status: dict[str, Any], previous: str | None
    ) -> None:
        """Emit the right log level when license status changes."""
        if current == "expired":
            logger.error("License EXPIRED! Licensed features are no longer available.")
        elif current == "expiring_soon":
            days = status.get("days_remaining", 0)
            logger.warning(f"License expiring in {days} days! Please renew.")
        elif current == "invalid_signature":
            logger.error("License signature INVALID! Possible tampering detected.")
        elif current == "fingerprint_mismatch":
            logger.error(
                "License fingerprint MISMATCH! Hardware changed or wrong certificate."
            )
        elif current == "grace_period":
            logger.warning(
                "License in grace period. Please import a valid certificate."
            )
        elif current == "valid" and previous in (
            None,
            "unlicensed",
            "expired",
            "grace_period",
        ):
            logger.info(
                f"License activated: type={status.get('license_type')}, "
                f"expires={status.get('expires_at')}"
            )
        elif current == "unlicensed" and previous in (
            "valid",
            "expiring_soon",
            "grace_period",
        ):
            logger.warning("License revoked or removed — system is now unlicensed.")

    def start_monitor(self, interval_seconds: int | None = None) -> None:
        """Start a daemon thread that calls ``periodic_check()`` every interval.

        Idempotent: calling again while the thread is alive is a no-op.
        ``interval_seconds`` overrides the default only on first start.
        """
        if self._monitor_thread is not None and self._monitor_thread.is_alive():
            return

        if interval_seconds is not None and interval_seconds > 0:
            self._monitor_interval = interval_seconds

        self._monitor_stop = threading.Event()
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            daemon=True,
            name="license-monitor",
        )
        self._monitor_thread.start()
        logger.info(
            f"License monitor started (interval={self._monitor_interval}s)"
        )

    def _ensure_monitor_running(self) -> None:
        """Lazily start the background monitor if not already running.

        Called from ``get_license_status()`` so that any caller — including
        compiled .so modules like ``web/runner.py`` and
        ``tradingagents/graph/trading_graph.py`` — triggers the monitor to
        start, independent of whether ``web/app.py`` calls ``start_monitor()``.
        """
        if self._monitor_thread is None or not self._monitor_thread.is_alive():
            self.start_monitor()

    def _monitor_loop(self) -> None:
        """Background loop: wait, then check, repeat until stop event set."""
        # First check runs immediately so we capture the initial status for logging.
        try:
            self.periodic_check()
        except Exception as exc:
            logger.error(f"License monitor initial check failed: {exc}")

        while self._monitor_stop is not None and not self._monitor_stop.wait(
            self._monitor_interval
        ):
            try:
                self.periodic_check()
            except Exception as exc:
                logger.error(f"License monitor error: {exc}")

    def stop_monitor(self, timeout: float = 5.0) -> None:
        """Signal the monitor thread to stop and join it."""
        if self._monitor_stop is not None:
            self._monitor_stop.set()
        if self._monitor_thread is not None and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=timeout)
        self._monitor_thread = None
        self._monitor_stop = None

    def is_monitor_running(self) -> bool:
        return (
            self._monitor_thread is not None
            and self._monitor_thread.is_alive()
        )


# Module-level singleton, mirroring the ai-surveillance pattern.
license_service = LicenseService()


class LicenseError(Exception):
    """Raised when a required license feature is not available.

    Thrown by ``require_license()`` from compiled code paths
    (``web/runner.py``, ``tradingagents/graph/trading_graph.py``) so that
    license enforcement survives even if ``web/app.py`` is tampered with
    after Cython compilation.
    """


def require_license(feature: str) -> None:
    """Raise :class:`LicenseError` if ``feature`` is not enabled.

    Designed to be called from compiled (.so) code paths so that license
    enforcement cannot be bypassed by editing the plaintext ``web/app.py``::

        # inside tradingagents/graph/trading_graph.py (compiled to .so)
        from tradingagents.license_service import require_license

        def propagate(self, ...):
            require_license("stock_analysis")
            ...

    The check runs on every call — no caching — so a revoked or expired
    license is enforced as soon as the next analysis attempt is made.
    """
    status = license_service.get_license_status()
    if not status.get("is_licensed"):
        raise LicenseError(
            f"软件未授权 — 无法使用功能 '{feature}'。"
            f"当前状态: {status.get('status', 'unknown')}。"
            "请在系统设置中导入有效的授权证书。"
        )
    if feature not in status.get("features", []):
        raise LicenseError(
            f"当前授权不包含功能 '{feature}'"
            f" (授权类型: {status.get('license_type')})。"
        )


__all__ = [
    "ALWAYS_AVAILABLE",
    "LICENSED_FEATURES",
    "HardwareFingerprint",
    "LicenseError",
    "LicenseService",
    "LicenseValidator",
    "license_service",
    "require_license",
]
