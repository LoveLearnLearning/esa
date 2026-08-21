"""Bounded, auditable preview derivation for personal Office documents."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote


@dataclass(frozen=True, slots=True)
class LibreOfficePreviewConverter:
    """Convert one Office source to PDF without a shell or shared profile."""

    binary: Path
    timeout_seconds: int = 120
    max_output_bytes: int = 64 * 1024 * 1024

    def __post_init__(self) -> None:
        binary = self.binary.expanduser().resolve(strict=True)
        if not binary.is_file() or not os.access(binary, os.X_OK):
            raise ValueError("LibreOffice preview binary is not executable")
        if self.timeout_seconds <= 0 or self.max_output_bytes <= 0:
            raise ValueError("Office preview limits must be positive")
        object.__setattr__(self, "binary", binary)

    @property
    def configuration_fingerprint(self) -> str:
        stat = self.binary.stat()
        payload = (
            f"{self.binary}:{stat.st_size}:{stat.st_mtime_ns}:"
            f"{self.timeout_seconds}:{self.max_output_bytes}"
        )
        return hashlib.sha256(payload.encode()).hexdigest()

    def convert(self, source: Path, work_root: Path) -> Path:
        source = source.resolve(strict=True)
        work_root.mkdir(mode=0o700)
        output_root = work_root / "output"
        profile_root = work_root / "profile"
        output_root.mkdir(mode=0o700)
        profile_root.mkdir(mode=0o700)
        profile_uri = f"file://{quote(str(profile_root), safe='/')}"
        command = [
            str(self.binary),
            "--headless",
            "--nologo",
            "--nodefault",
            "--nolockcheck",
            "--nofirststartwizard",
            f"-env:UserInstallation={profile_uri}",
            "--convert-to",
            "pdf",
            "--outdir",
            str(output_root),
            str(source),
        ]
        try:
            completed = subprocess.run(
                command,
                cwd=work_root,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=self.timeout_seconds,
                env={
                    "LANG": "C.UTF-8",
                    "LC_ALL": "C.UTF-8",
                    "PATH": f"{self.binary.parent}:/usr/bin:/bin",
                    "TMPDIR": str(work_root),
                    "XDG_CACHE_HOME": str(profile_root),
                    "XDG_CONFIG_HOME": str(profile_root),
                },
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("Office preview conversion timed out") from exc
        if completed.returncode != 0:
            raise RuntimeError(
                f"Office preview conversion failed with code {completed.returncode}"
            )
        expected = output_root / f"{source.stem}.pdf"
        candidates = list(output_root.iterdir())
        if candidates != [expected] or expected.is_symlink() or not expected.is_file():
            raise RuntimeError("Office preview converter produced unexpected output")
        size = expected.stat().st_size
        if size <= 0 or size > self.max_output_bytes:
            raise RuntimeError("Office preview PDF exceeds its output limit")
        with expected.open("rb") as stream:
            if not stream.read(8).startswith(b"%PDF-"):
                raise RuntimeError("Office preview converter output is not PDF")
        os.chmod(expected, 0o600)
        return expected

    @staticmethod
    def commit(converted: Path, destination: Path) -> None:
        """Copy a verified conversion into the ingestion artifact atomically."""

        temporary = destination.with_name(f".{destination.name}.partial")
        try:
            with converted.open("rb") as source, temporary.open("xb") as target:
                os.chmod(temporary, 0o600)
                shutil.copyfileobj(source, target, 1024 * 1024)
                target.flush()
                os.fsync(target.fileno())
            os.replace(temporary, destination)
        finally:
            if temporary.exists():
                temporary.unlink()
