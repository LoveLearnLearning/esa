"""Inspect raw MinerU bundles without loading Adapter production models.

The census deliberately reads JSON with :mod:`json` instead of calling
``adapters.mineru.load_bundle``.  Office output is one of the inputs this tool
must describe, and that output does not satisfy the current strict raw models.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass, field
import json
from pathlib import Path
import re
from typing import Any


JSON_ARTIFACTS = {
    "middle": "_middle.json",
    "content_list": "_content_list.json",
    "content_list_v2": "_content_list_v2.json",
    "model": "_model.json",
}
PIPELINE_FORMATS = frozenset({"PDF", "PNG", "JPG"})
OFFICE_FORMATS = frozenset({"DOCX", "PPTX", "XLSX"})
DEFAULT_FIXTURES = (
    ("PDF", "pdf_mixed", "pdf_mixed.pdf"),
    ("DOCX", "docx_mixed", "docx_mixed.docx"),
    ("PPTX", "pptx_mixed", "pptx_mixed.pptx"),
    ("XLSX", "xlsx_mixed", "xlsx_mixed.xlsx"),
    ("PNG", "image_document", "image_document.png"),
    ("JPG", "image_scan", "image_scan.jpg"),
)
_HEX_64 = re.compile(r"(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])", re.IGNORECASE)


def json_type(value: Any) -> str:
    """Return JSON-oriented type names (with bool distinct from int)."""

    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    raise TypeError(f"not a JSON value: {type(value).__name__}")


def _example(value: Any) -> Any:
    if isinstance(value, str):
        stable = _HEX_64.sub("<sha256>", value).replace("\n", "\\n")
        return stable if len(stable) <= 120 else stable[:117] + "..."
    if isinstance(value, list):
        return [] if not value else f"<array length={len(value)}>"
    if isinstance(value, dict):
        if not value:
            return {}
        keys = ",".join(sorted(map(str, value))[:8])
        return f"<object keys={keys}>"
    return value


@dataclass
class _Observed:
    count: int = 0
    types: Counter[str] = field(default_factory=Counter)
    examples: list[Any] = field(default_factory=list)
    null_count: int = 0
    empty_string_count: int = 0
    empty_array_count: int = 0
    empty_object_count: int = 0

    def add(self, value: Any) -> None:
        self.count += 1
        self.types[json_type(value)] += 1
        self.null_count += int(value is None)
        self.empty_string_count += int(value == "")
        self.empty_array_count += int(isinstance(value, list) and not value)
        self.empty_object_count += int(isinstance(value, dict) and not value)
        example = _example(value)
        if example not in self.examples and len(self.examples) < 3:
            self.examples.append(example)


@dataclass
class ScanResult:
    observations: dict[str, _Observed] = field(default_factory=dict)
    object_instances: Counter[str] = field(default_factory=Counter)
    array_instances: Counter[str] = field(default_factory=Counter)
    nonempty_arrays: Counter[str] = field(default_factory=Counter)

    def _parent_count(self, path: str) -> tuple[int, int]:
        if path == "$":
            return 1, 1
        if path.endswith("[]"):
            parent = path[:-2] or "$"
            return self.array_instances[parent], self.nonempty_arrays[parent]
        parent = path.rsplit(".", 1)[0] if "." in path else "$"
        count = self.object_instances[parent]
        observed = self.observations.get(path)
        return count, observed.count if observed else 0

    def materialize(self, path: str) -> dict[str, Any]:
        observed = self.observations.get(path, _Observed())
        parent_count, present_parent_count = self._parent_count(path)
        return {
            "count": observed.count,
            "parent_count": parent_count,
            "present_parent_count": present_parent_count,
            "missing_count": max(0, parent_count - present_parent_count),
            "presence_ratio": (
                round(present_parent_count / parent_count, 6)
                if parent_count
                else None
            ),
            "types": dict(sorted(observed.types.items())),
            "multiple_types": len(observed.types) > 1,
            "examples": observed.examples,
            "null_count": observed.null_count,
            "empty_string_count": observed.empty_string_count,
            "empty_array_count": observed.empty_array_count,
            "empty_object_count": observed.empty_object_count,
        }


def scan_value(value: Any) -> ScanResult:
    """Recursively collect canonical paths, using ``[]`` for array items."""

    result = ScanResult()

    def visit(item: Any, path: str) -> None:
        result.observations.setdefault(path, _Observed()).add(item)
        if isinstance(item, dict):
            result.object_instances[path] += 1
            for key, child in item.items():
                child_path = str(key) if path == "$" else f"{path}.{key}"
                visit(child, child_path)
        elif isinstance(item, list):
            result.array_instances[path] += 1
            result.nonempty_arrays[path] += int(bool(item))
            child_path = "[]" if path == "$" else f"{path}[]"
            for child in item:
                visit(child, child_path)

    visit(value, "$")
    return result


@dataclass(frozen=True)
class Fixture:
    format: str
    name: str
    source_filename: str
    bundle: Path


def _exactly_one(root: Path, suffix: str) -> Path:
    matches = sorted(root.rglob(f"*{suffix}"))
    if len(matches) != 1:
        raise ValueError(f"expected one *{suffix} below {root}, got {matches}")
    return matches[0]


def default_fixtures(fixture_root: Path) -> tuple[Fixture, ...]:
    fixtures: list[Fixture] = []
    for format_name, case_name, source_filename in DEFAULT_FIXTURES:
        case_root = fixture_root / case_name
        bundle = _exactly_one(case_root, "_middle.json").parent
        fixtures.append(Fixture(format_name, case_name, source_filename, bundle))
    return tuple(fixtures)


def parse_bundle_arguments(values: list[str]) -> tuple[Fixture, ...]:
    fixtures: list[Fixture] = []
    for value in values:
        try:
            format_name, raw_path = value.split("=", 1)
        except ValueError as exc:
            raise ValueError("--bundle must be FORMAT=/path/to/bundle") from exc
        bundle = Path(raw_path).resolve()
        middle = _exactly_one(bundle, "_middle.json")
        name = middle.name.removesuffix("_middle.json")
        fixtures.append(Fixture(format_name.upper(), name, "unknown", bundle))
    return tuple(fixtures)


def _artifact_kind(path: Path, fixture_name: str) -> str:
    name = path.name
    if name.endswith("_content_list_v2.json"):
        return "content_list_v2.json"
    if name.endswith("_content_list.json"):
        return "content_list.json"
    if name.endswith("_middle.json"):
        return "middle.json"
    if name.endswith("_model.json"):
        return "model.json"
    if name.endswith("_layout.pdf"):
        return "layout.pdf"
    if name.endswith("_span.pdf"):
        return "span.pdf"
    if "_origin." in name:
        return "origin" + path.suffix.lower()
    if path.suffix.lower() == ".md":
        return "markdown"
    if "images" in path.parts:
        return "image_asset" + path.suffix.lower()
    return "other" + path.suffix.lower()


def _inventory(fixtures: tuple[Fixture, ...]) -> dict[str, Any]:
    files_by_format: dict[str, list[dict[str, Any]]] = {}
    kinds: dict[str, dict[str, int]] = defaultdict(dict)
    for fixture in fixtures:
        records: list[dict[str, Any]] = []
        counts: Counter[str] = Counter()
        for path in sorted(value for value in fixture.bundle.rglob("*") if value.is_file()):
            kind = _artifact_kind(path, fixture.name)
            counts[kind] += 1
            records.append(
                {
                    "relative_path": path.relative_to(fixture.bundle).as_posix(),
                    "artifact": kind,
                    "suffix": path.suffix.lower(),
                    "size_bytes": path.stat().st_size,
                    "empty": path.stat().st_size == 0,
                }
            )
        files_by_format[fixture.format] = records
        for kind, count in counts.items():
            kinds[kind][fixture.format] = count

    formats = [fixture.format for fixture in fixtures]
    matrix: dict[str, Any] = {}
    for kind in sorted(kinds):
        present = sorted(kinds[kind])
        present_set = set(present)
        matrix[kind] = {
            "counts": {name: kinds[kind].get(name, 0) for name in formats},
            "present_formats": present,
            "all_formats": present_set == set(formats),
            "pipeline_only": bool(present_set) and present_set <= PIPELINE_FORMATS,
            "office_only": bool(present_set) and present_set <= OFFICE_FORMATS,
        }
    return {"files_by_format": files_by_format, "matrix": matrix}


def _shape(value: Any, artifact: str) -> dict[str, Any]:
    shape: dict[str, Any] = {"root_type": json_type(value)}
    if isinstance(value, list):
        shape["root_length"] = len(value)
        shape["root_item_types"] = sorted({json_type(item) for item in value})
    if artifact == "middle" and isinstance(value, dict):
        groups = value.get("pdf_info")
        shape["group_container"] = json_type(groups)
        if isinstance(groups, list):
            shape["group_count"] = len(groups)
            shape["group_item_types"] = sorted({json_type(item) for item in groups})
            shape["group_key_sets"] = [
                list(keys)
                for keys in sorted(
                    {tuple(sorted(item)) for item in groups if isinstance(item, dict)}
                )
            ]
            blocks = [
                block
                for group in groups
                if isinstance(group, dict)
                for block in group.get("para_blocks", [])
                if isinstance(block, dict)
            ]
            shape["block_count"] = len(blocks)
            shape["blocks_with_page_idx"] = sum("page_idx" in block for block in blocks)
    elif artifact == "content_list" and isinstance(value, list):
        shape["flat_block_count"] = sum(isinstance(item, dict) for item in value)
        shape["blocks_with_page_idx"] = sum(
            isinstance(item, dict) and "page_idx" in item for item in value
        )
    elif artifact == "content_list_v2" and isinstance(value, list):
        shape["group_count"] = len(value)
        shape["group_item_types"] = sorted({json_type(item) for item in value})
        blocks = [
            block
            for group in value
            if isinstance(group, list)
            for block in group
            if isinstance(block, dict)
        ]
        shape["block_count"] = len(blocks)
        shape["blocks_with_page_idx"] = sum("page_idx" in block for block in blocks)
    elif artifact == "model" and isinstance(value, list):
        shape["group_count"] = len(value)
        shape["group_item_types"] = sorted({json_type(item) for item in value})
    return shape


def _blocks(value: Any, artifact: str) -> list[dict[str, Any]]:
    if artifact == "middle" and isinstance(value, dict):
        return [
            block
            for group in value.get("pdf_info", [])
            if isinstance(group, dict)
            for key in ("para_blocks", "discarded_blocks")
            for block in group.get(key, [])
            if isinstance(block, dict)
        ]
    if artifact == "content_list" and isinstance(value, list):
        return [block for block in value if isinstance(block, dict)]
    if artifact == "content_list_v2" and isinstance(value, list):
        return [
            block
            for group in value
            if isinstance(group, list)
            for block in group
            if isinstance(block, dict)
        ]
    return []


def _strip_block_path(path: str) -> str:
    if path == "[]":
        return "$"
    return path.removeprefix("[].")


def _block_profile(blocks: list[dict[str, Any]]) -> dict[str, Any]:
    by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for block in blocks:
        block_type = block.get("type")
        by_type[str(block_type) if block_type is not None else "<missing>"].append(block)
    output: dict[str, Any] = {}
    for block_type, values in sorted(by_type.items()):
        scan = scan_value(values)
        fields = {
            _strip_block_path(path): scan.materialize(path)
            for path in sorted(scan.observations)
            if path not in {"$", "[]"}
        }
        combinations = Counter("|".join(sorted(value)) for value in values)
        output[block_type] = {
            "count": len(values),
            "fields": fields,
            "top_level_field_combinations": dict(sorted(combinations.items())),
        }
    return output


def _aggregate_paths(
    scans: dict[str, ScanResult], formats: list[str]
) -> dict[str, Any]:
    all_paths = sorted(
        set().union(*(set(scan.observations) for scan in scans.values()))
    )
    output: dict[str, Any] = {}
    for path in all_paths:
        per_format = {name: scans[name].materialize(path) for name in formats}
        present = [name for name in formats if per_format[name]["count"] > 0]
        type_names = sorted(
            {
                type_name
                for stats in per_format.values()
                for type_name in stats["types"]
            }
        )
        present_set = set(present)
        output[path] = {
            "present_formats": present,
            "format_presence_ratio": round(len(present) / len(formats), 6),
            "observed_types": type_names,
            "multiple_types": len(type_names) > 1,
            "pipeline_only": bool(present_set) and present_set <= PIPELINE_FORMATS,
            "office_only": bool(present_set) and present_set <= OFFICE_FORMATS,
            "formats": per_format,
        }
    return output


def _aggregate_block_profiles(
    profiles: dict[str, dict[str, Any]], formats: list[str]
) -> dict[str, Any]:
    block_types = sorted(set().union(*(set(profile) for profile in profiles.values())))
    output: dict[str, Any] = {}
    for block_type in block_types:
        all_fields = sorted(
            set().union(
                *(
                    set(profiles[name].get(block_type, {}).get("fields", {}))
                    for name in formats
                )
            )
        )
        formats_output: dict[str, Any] = {}
        for name in formats:
            profile = profiles[name].get(block_type)
            if profile is None:
                formats_output[name] = {
                    "count": 0,
                    "fields": {},
                    "top_level_field_combinations": {},
                }
                continue
            count = profile["count"]
            fields = dict(profile["fields"])
            for field_name in all_fields:
                fields.setdefault(
                    field_name,
                    {
                        "count": 0,
                        "parent_count": count,
                        "present_parent_count": 0,
                        "missing_count": count,
                        "presence_ratio": 0.0,
                        "types": {},
                        "multiple_types": False,
                        "examples": [],
                        "null_count": 0,
                        "empty_string_count": 0,
                        "empty_array_count": 0,
                        "empty_object_count": 0,
                    },
                )
            formats_output[name] = {**profile, "fields": dict(sorted(fields.items()))}
        output[block_type] = {"formats": formats_output, "all_fields": all_fields}
    return output


def build_census(fixtures: tuple[Fixture, ...]) -> dict[str, Any]:
    """Build a deterministic machine-readable census for raw bundle fixtures."""

    if not fixtures:
        raise ValueError("at least one MinerU bundle is required")
    formats = [fixture.format for fixture in fixtures]
    if len(set(formats)) != len(formats):
        raise ValueError("fixture format labels must be unique")

    values: dict[str, dict[str, Any]] = defaultdict(dict)
    scans: dict[str, dict[str, ScanResult]] = defaultdict(dict)
    shapes: dict[str, dict[str, Any]] = defaultdict(dict)
    block_profiles: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    backend_profiles: dict[str, str | None] = {}
    for fixture in fixtures:
        for artifact, suffix in JSON_ARTIFACTS.items():
            path = _exactly_one(fixture.bundle, suffix)
            value = json.loads(path.read_text(encoding="utf-8"))
            values[artifact][fixture.format] = value
            scans[artifact][fixture.format] = scan_value(value)
            shapes[artifact][fixture.format] = _shape(value, artifact)
            if artifact != "model":
                block_profiles[artifact][fixture.format] = _block_profile(
                    _blocks(value, artifact)
                )
        middle = values["middle"][fixture.format]
        backend_profiles[fixture.format] = (
            middle.get("_backend") if isinstance(middle, dict) else None
        )

    versions = sorted(
        {
            str(value.get("_version_name"))
            for value in values["middle"].values()
            if isinstance(value, dict) and value.get("_version_name") is not None
        }
    )
    return {
        "schema_version": 1,
        "mineru_versions_observed": versions,
        "formats": formats,
        "fixtures": {
            fixture.format: {
                "name": fixture.name,
                "source_filename": fixture.source_filename,
                "bundle_profile": fixture.bundle.name,
                "reported_backend": backend_profiles[fixture.format],
            }
            for fixture in fixtures
        },
        "backend_profiles": {
            "pipeline": sorted(
                name for name, backend in backend_profiles.items() if backend == "pipeline"
            ),
            "office": sorted(
                name for name, backend in backend_profiles.items() if backend == "office"
            ),
        },
        "artifact_inventory": _inventory(fixtures),
        "shapes": {
            artifact: {name: shapes[artifact][name] for name in formats}
            for artifact in JSON_ARTIFACTS
        },
        "json_paths": {
            artifact: _aggregate_paths(scans[artifact], formats)
            for artifact in JSON_ARTIFACTS
        },
        "block_types": {
            artifact: _aggregate_block_profiles(block_profiles[artifact], formats)
            for artifact in ("middle", "content_list", "content_list_v2")
        },
    }


def markdown_summary(census: dict[str, Any]) -> str:
    """Render compact inventory/shape tables; full path data remains in JSON."""

    formats = census["formats"]
    lines = [
        "# MinerU cross-format schema census summary",
        "",
        "Machine-readable recursive path and block-field statistics are in the JSON baseline.",
        "",
        "## Artifact inventory",
        "",
        "| Artifact | " + " | ".join(formats) + " | Profile |",
        "| --- | " + " | ".join("---:" for _ in formats) + " | --- |",
    ]
    for artifact, row in census["artifact_inventory"]["matrix"].items():
        profile = (
            "pipeline-only"
            if row["pipeline_only"]
            else "office-only"
            if row["office_only"]
            else "common/mixed"
        )
        lines.append(
            "| "
            + artifact
            + " | "
            + " | ".join(str(row["counts"][name]) for name in formats)
            + f" | {profile} |"
        )
    lines.extend(["", "## JSON shapes", ""])
    for artifact, values in census["shapes"].items():
        lines.extend(
            [
                f"### {artifact}",
                "",
                "| Format | Root | Root items | Group items | Blocks with page_idx |",
                "| --- | --- | ---: | --- | ---: |",
            ]
        )
        for name in formats:
            shape = values[name]
            lines.append(
                f"| {name} | {shape['root_type']} | {shape.get('root_length', '')} | "
                f"{','.join(shape.get('group_item_types', []))} | "
                f"{shape.get('blocks_with_page_idx', '')} |"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect raw MinerU JSON schemas")
    parser.add_argument(
        "--fixture-root",
        type=Path,
        default=(
            Path(__file__).resolve().parents[1]
            / "tests/fixtures/mineru_adapter/outputs"
        ),
    )
    parser.add_argument(
        "--bundle",
        action="append",
        default=[],
        metavar="FORMAT=PATH",
        help="scan explicit bundle(s) instead of the six fixed fixtures",
    )
    parser.add_argument("--output", type=Path, help="write canonical JSON baseline")
    parser.add_argument("--markdown", type=Path, help="write compact Markdown summary")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    fixtures = (
        parse_bundle_arguments(arguments.bundle)
        if arguments.bundle
        else default_fixtures(arguments.fixture_root)
    )
    census = build_census(fixtures)
    serialized = json.dumps(census, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if arguments.output:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(serialized, encoding="utf-8")
    else:
        print(serialized, end="")
    if arguments.markdown:
        arguments.markdown.parent.mkdir(parents=True, exist_ok=True)
        arguments.markdown.write_text(markdown_summary(census), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
