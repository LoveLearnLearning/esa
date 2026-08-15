# backend/agent/mm/parser.py

"""单文件 MinerU → 自包含 DocIR bundle。"""

from __future__ import annotations

import hashlib
import json
import mimetypes
import shutil
import subprocess
import tempfile
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path

import httpx

from backend.agent.DocIR.adapters.mineru import convert_bundle, load_bundle
from backend.agent.DocIR.tools.batch_corpus import (
    find_parse_dir,
    link_or_copy,
    materialize_visual_assets,
    source_metadata,
)

from .contracts import ParsedAttachment
from backend.core.log.logger import get_pipeline_logger


logger = get_pipeline_logger("DOCIR", __name__)


@dataclass(frozen=True)
class MinerUDocumentParser:
    """封装 `MinerUDocumentParser` 的状态与行为。"""
    command: Path
    timeout_seconds: int = 7200
    attempts: int = 2
    api_url: str | None = None

    @property
    def configuration_fingerprint(self) -> str:
        """处理 `configuration_fingerprint` 相关逻辑。"""
        payload = json.dumps(
            {
                "adapter": "mineru-docir-0.1",
                "command": str(self.command),
                "api_url": self.api_url,
                "backend": "pipeline",
                "method": "auto",
                "language": "ch",
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode()).hexdigest()

    def parse(self, source: Path, document_root: Path) -> ParsedAttachment:
        """解析 `parse` 相关数据。

        Args:
            source: Path => `source` 参数。
            document_root: Path => `document_root` 参数。

        Returns:
            ParsedAttachment => 处理结果。
        """
        source = Path(source).resolve(strict=True)
        if self.api_url is None and not self.command.is_file():
            raise FileNotFoundError(f"MinerU command not found: {self.command}")
        raw_root = document_root / "mineru"
        raw_root.mkdir(parents=True, exist_ok=True)
        log_path = document_root / "mineru.log"
        failures: list[str] = []
        logger.info("MinerU parse started source=%s", source.name)
        for attempt in range(1, self.attempts + 1):
            with log_path.open("a", encoding="utf-8") as stream:
                stream.write(f"\n=== attempt {attempt}/{self.attempts} ===\n")
                started = time.monotonic()
                try:
                    if self.api_url is not None:
                        self._parse_with_api(source, raw_root)
                        exit_code = 0
                    else:
                        result = subprocess.run(
                            self._cli_command(source, raw_root),
                            stdout=stream,
                            stderr=subprocess.STDOUT,
                            timeout=self.timeout_seconds,
                            check=False,
                        )
                        exit_code = result.returncode
                except (httpx.HTTPError, OSError, ValueError, zipfile.BadZipFile) as exc:
                    failures.append(
                        f"attempt {attempt}: {type(exc).__name__}"
                    )
                    logger.warning(
                        "MinerU attempt failed attempt=%d error_type=%s",
                        attempt,
                        type(exc).__name__,
                    )
                    continue
                except subprocess.TimeoutExpired:
                    failures.append(f"attempt {attempt}: timeout")
                    logger.warning(
                        "MinerU attempt timed out attempt=%d max_attempts=%d",
                        attempt,
                        self.attempts,
                    )
                    continue
                if exit_code == 0:
                    logger.info(
                        "MinerU attempt completed attempt=%d elapsed_seconds=%.3f",
                        attempt,
                        time.monotonic() - started,
                    )
                    break
                failures.append(f"attempt {attempt}: exit_code={exit_code}")
                logger.warning(
                    "MinerU attempt failed attempt=%d exit_code=%d",
                    attempt,
                    exit_code,
                )
                stream.write(f"elapsed_seconds={time.monotonic() - started:.3f}\n")
        else:
            logger.error("MinerU parse failed failures=%s", "; ".join(failures))
            raise RuntimeError("MinerU failed: " + "; ".join(failures))

        parse_dir = find_parse_dir(raw_root)
        bundle = load_bundle(parse_dir)
        metadata = source_metadata(source)
        document = convert_bundle(
            bundle,
            source,
            source_page_count=metadata.page_count,
            strict=False,
        )
        (document_root / "assets").mkdir(parents=True, exist_ok=True)
        (document_root / "raw").mkdir(parents=True, exist_ok=True)
        link_or_copy(source, document_root / "assets" / source.name)
        for raw in (
            bundle.middle_path,
            bundle.content_v2_path,
            bundle.content_list_path,
            bundle.model_path,
        ):
            if raw is not None:
                link_or_copy(raw, document_root / "raw" / raw.name)
        materialize_visual_assets(document, bundle, document_root)
        logger.info(
            "DocIR conversion completed document_id=%s elements=%d assets=%d",
            document.document_id,
            len(document.elements),
            len(document.assets),
        )
        return ParsedAttachment(document=document, document_root=document_root)

    def _cli_command(self, source: Path, raw_root: Path) -> list[str]:
        """处理 `_cli_command` 相关逻辑。"""
        return [
            str(self.command),
            "-p",
            str(source),
            "-o",
            str(raw_root),
            "-b",
            "pipeline",
            "-m",
            "auto",
            "-l",
            "ch",
        ]

    def _parse_with_api(self, source: Path, raw_root: Path) -> None:
        """Use the process-resident MinerU API and materialize its ZIP bundle."""

        assert self.api_url is not None
        form = {
            "lang_list": "ch",
            "backend": "pipeline",
            "parse_method": "auto",
            "return_md": "true",
            "return_middle_json": "true",
            "return_model_output": "true",
            "return_content_list": "true",
            "return_images": "true",
            "response_format_zip": "true",
        }
        media_type = mimetypes.guess_type(source.name)[0] or "application/octet-stream"
        timeout = httpx.Timeout(float(self.timeout_seconds), connect=10.0)
        with tempfile.TemporaryDirectory(
            prefix=".mineru-api-", dir=raw_root.parent
        ) as temporary:
            temporary_root = Path(temporary)
            zip_path = temporary_root / "result.zip"
            extract_root = temporary_root / "result"
            extract_root.mkdir()
            with source.open("rb") as source_stream, httpx.Client(
                timeout=timeout,
                trust_env=False,
            ) as client:
                with client.stream(
                    "POST",
                    f"{self.api_url}/file_parse",
                    data=form,
                    files={"files": (source.name, source_stream, media_type)},
                ) as response:
                    response.raise_for_status()
                    with zip_path.open("wb") as zip_stream:
                        for chunk in response.iter_bytes():
                            zip_stream.write(chunk)
            _safe_extract_zip(zip_path, extract_root)
            find_parse_dir(extract_root)
            if raw_root.exists():
                shutil.rmtree(raw_root)
            shutil.move(extract_root, raw_root)


def _safe_extract_zip(archive: Path, destination: Path) -> None:
    """处理 `_safe_extract_zip` 相关逻辑。"""
    destination = destination.resolve()
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.infolist():
            target = (destination / member.filename).resolve()
            if target != destination and destination not in target.parents:
                raise ValueError("MinerU ZIP contains an unsafe path")
        bundle.extractall(destination)
