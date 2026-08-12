"""单文件 MinerU → 自包含 DocIR bundle。"""

from __future__ import annotations

import hashlib
import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

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
    command: Path
    timeout_seconds: int = 7200
    attempts: int = 2

    @property
    def configuration_fingerprint(self) -> str:
        payload = json.dumps(
            {
                "adapter": "mineru-docir-0.1",
                "command": str(self.command),
                "backend": "pipeline",
                "method": "auto",
                "language": "ch",
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode()).hexdigest()

    def parse(self, source: Path, document_root: Path) -> ParsedAttachment:
        source = Path(source).resolve(strict=True)
        if not self.command.is_file():
            raise FileNotFoundError(f"MinerU command not found: {self.command}")
        raw_root = document_root / "mineru"
        raw_root.mkdir(parents=True, exist_ok=True)
        log_path = document_root / "mineru.log"
        command = [
            str(self.command), "-p", str(source), "-o", str(raw_root),
            "-b", "pipeline", "-m", "auto", "-l", "ch",
        ]
        failures: list[str] = []
        logger.info("MinerU parse started source=%s", source.name)
        for attempt in range(1, self.attempts + 1):
            with log_path.open("a", encoding="utf-8") as stream:
                stream.write(f"\n=== attempt {attempt}/{self.attempts} ===\n")
                started = time.monotonic()
                try:
                    result = subprocess.run(
                        command,
                        stdout=stream,
                        stderr=subprocess.STDOUT,
                        timeout=self.timeout_seconds,
                        check=False,
                    )
                except subprocess.TimeoutExpired:
                    failures.append(f"attempt {attempt}: timeout")
                    logger.warning(
                        "MinerU attempt timed out attempt=%d max_attempts=%d",
                        attempt,
                        self.attempts,
                    )
                    continue
                if result.returncode == 0:
                    logger.info(
                        "MinerU attempt completed attempt=%d elapsed_seconds=%.3f",
                        attempt,
                        time.monotonic() - started,
                    )
                    break
                failures.append(f"attempt {attempt}: exit_code={result.returncode}")
                logger.warning(
                    "MinerU attempt failed attempt=%d exit_code=%d",
                    attempt,
                    result.returncode,
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
