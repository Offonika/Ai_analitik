from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

if __package__:
    from scripts.docs_metadata import load_frontmatter, load_yaml, string_list
else:
    from docs_metadata import load_frontmatter, load_yaml, string_list

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs" / "manifest.yml"
DOCS_INDEX = ROOT / "docs" / "index.md"
GENERATED_INDEX = ROOT / "docs" / "generated" / "ai-routing.jsonl"
GENERATED_BLOCK_START = "<!-- BEGIN GENERATED AI ROUTING -->"
GENERATED_BLOCK_END = "<!-- END GENERATED AI ROUTING -->"
CURRENT_STATUSES = {"accepted", "active", "implemented"}
WORD_RE = re.compile(r"[\w.-]+", re.UNICODE)


@dataclass(frozen=True)
class Anchor:
    path: str
    symbols: tuple[str, ...]


@dataclass(frozen=True)
class OperationalDoc:
    path: str
    summary: str


@dataclass(frozen=True)
class RouteRecord:
    path: str
    title: str
    doc_type: str
    status: str
    audience: tuple[str, ...]
    source_of_truth: bool
    truth_scope: str | None
    truth_priority: int | None
    summary: str
    read_when: str
    search_terms: tuple[str, ...]
    related_code: tuple[str, ...]
    related_tests: tuple[str, ...]
    contracts: tuple[str, ...]
    ai_sections: tuple[tuple[str, str], ...]
    code_anchors: tuple[Anchor, ...]
    test_anchors: tuple[Anchor, ...]
    operational_docs: tuple[OperationalDoc, ...]
    canonical: bool

    def searchable_text(self) -> str:
        values: list[str] = [
            self.path,
            self.title,
            self.doc_type,
            self.status,
            self.truth_scope or "",
            self.summary,
            self.read_when,
            *self.search_terms,
            *self.related_code,
            *self.related_tests,
            *self.contracts,
            *(key for key, _heading in self.ai_sections),
            *(heading for _key, heading in self.ai_sections),
            *(item.path for item in self.operational_docs),
        ]
        for anchor in (*self.code_anchors, *self.test_anchors):
            values.append(anchor.path)
            values.extend(anchor.symbols)
        return " ".join(values)

    def json_payload(self) -> dict[str, Any]:
        return {
            "aiSections": dict(self.ai_sections),
            "audience": list(self.audience),
            "canonical": self.canonical,
            "codeAnchors": [
                {"path": item.path, "symbols": list(item.symbols)}
                for item in self.code_anchors
            ],
            "contracts": list(self.contracts),
            "docType": self.doc_type,
            "path": self.path,
            "operationalDocs": [
                {"path": item.path, "summary": item.summary}
                for item in self.operational_docs
            ],
            "readWhen": self.read_when,
            "relatedCode": list(self.related_code),
            "relatedTests": list(self.related_tests),
            "searchTerms": list(self.search_terms),
            "sourceOfTruth": self.source_of_truth,
            "status": self.status,
            "summary": self.summary,
            "testAnchors": [
                {"path": item.path, "symbols": list(item.symbols)}
                for item in self.test_anchors
            ],
            "title": self.title,
            "truthPriority": self.truth_priority,
            "truthScope": self.truth_scope,
        }


def _string_mapping(value: Any) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, dict):
        return ()
    return tuple(
        (str(key), str(item))
        for key, item in value.items()
        if isinstance(key, str) and isinstance(item, str)
    )


def _anchors(value: Any) -> tuple[Anchor, ...]:
    if not isinstance(value, list):
        return ()
    anchors: list[Anchor] = []
    for item in value:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            continue
        symbols = tuple(string_list(item.get("symbols")))
        anchors.append(Anchor(path=item["path"], symbols=symbols))
    return tuple(anchors)


def _canonical_paths(records: list[dict[str, Any]]) -> set[str]:
    leaders: dict[str, dict[str, Any]] = {}
    for record in records:
        scope = record.get("truth_scope")
        priority = record.get("truth_priority")
        if (
            record.get("source_of_truth") is not True
            or not isinstance(scope, str)
            or not isinstance(priority, int)
            or isinstance(priority, bool)
        ):
            continue
        current = leaders.get(scope)
        if current is None or priority > current["truth_priority"]:
            leaders[scope] = record
    return {str(record["path"]) for record in leaders.values()}


def load_route_records(root: Path = ROOT) -> list[RouteRecord]:
    manifest = load_yaml(root / "docs" / "manifest.yml")
    raw_records = manifest.get("documents", []) if isinstance(manifest, dict) else []
    if not isinstance(raw_records, list):
        raise ValueError("docs/manifest.yml documents must be a list")
    records = [record for record in raw_records if isinstance(record, dict)]
    canonical_paths = _canonical_paths(records)
    records_by_path = {str(record.get("path", "")): record for record in records}
    result: list[RouteRecord] = []

    for record in records:
        rel_path = str(record.get("path", ""))
        metadata: dict[str, Any] = {}
        path = root / rel_path
        if path.suffix == ".md" and path.exists():
            metadata, _body = load_frontmatter(path)
        result.append(
            RouteRecord(
                path=rel_path,
                title=str(record.get("title", "")),
                doc_type=str(record.get("doc_type", "")),
                status=str(record.get("status", "")),
                audience=tuple(string_list(record.get("audience"))),
                source_of_truth=record.get("source_of_truth") is True,
                truth_scope=(
                    str(record["truth_scope"])
                    if isinstance(record.get("truth_scope"), str)
                    else None
                ),
                truth_priority=(
                    record["truth_priority"]
                    if isinstance(record.get("truth_priority"), int)
                    and not isinstance(record.get("truth_priority"), bool)
                    else None
                ),
                summary=str(record.get("summary", "")),
                read_when=str(record.get("read_when", "")),
                search_terms=tuple(string_list(record.get("search_terms"))),
                related_code=tuple(string_list(metadata.get("related_code"))),
                related_tests=tuple(string_list(metadata.get("related_tests"))),
                contracts=tuple(string_list(metadata.get("contracts"))),
                ai_sections=_string_mapping(metadata.get("ai_sections")),
                code_anchors=_anchors(metadata.get("code_anchors")),
                test_anchors=_anchors(metadata.get("test_anchors")),
                operational_docs=tuple(
                    OperationalDoc(
                        path=item,
                        summary=str(records_by_path[item].get("summary", "")),
                    )
                    for item in string_list(record.get("operational_docs"))
                    if item in records_by_path
                ),
                canonical=rel_path in canonical_paths,
            )
        )
    return result


def _normalized_words(value: str) -> list[str]:
    return [token.casefold() for token in WORD_RE.findall(value)]


def _tokens_match(left: str, right: str) -> bool:
    if left == right:
        return True
    if min(len(left), len(right)) < 5:
        return False
    prefix_length = min(7, len(left), len(right))
    return left[:prefix_length] == right[:prefix_length]


def query_score(record: RouteRecord, query: str) -> int:
    normalized_query = " ".join(_normalized_words(query))
    searchable = " ".join(_normalized_words(record.searchable_text()))
    if not normalized_query:
        return 0
    score = 30 if normalized_query in searchable else 0
    searchable_tokens = searchable.split()
    for query_token in normalized_query.split():
        if any(_tokens_match(query_token, token) for token in searchable_tokens):
            score += 5
    if record.canonical:
        score += 3
    if record.truth_scope and normalized_query == record.truth_scope.casefold():
        score += 40
    return score


def _current_records(
    records: Iterable[RouteRecord],
    *,
    include_supporting: bool,
    include_history: bool,
) -> list[RouteRecord]:
    result = []
    for record in records:
        if not include_supporting and not record.canonical:
            continue
        if not include_history and record.status not in CURRENT_STATUSES:
            continue
        result.append(record)
    return result


def find_routes(
    records: list[RouteRecord],
    *,
    query: str | None = None,
    scope: str | None = None,
    path: str | None = None,
    contract: str | None = None,
    include_supporting: bool = False,
    include_history: bool = False,
    limit: int = 3,
) -> list[tuple[int, RouteRecord]]:
    candidates = _current_records(
        records,
        include_supporting=include_supporting,
        include_history=include_history,
    )
    matches: list[tuple[int, RouteRecord]] = []
    normalized_path = path.removeprefix("./") if path else None

    for record in candidates:
        score = 0
        if query is not None:
            score = query_score(record, query)
        elif scope is not None:
            if record.truth_scope != scope:
                continue
            score = 100 if record.canonical else 50
        elif normalized_path is not None:
            paths = {
                record.path,
                *record.related_code,
                *record.related_tests,
                *(item.path for item in record.code_anchors),
                *(item.path for item in record.test_anchors),
                *(item.path for item in record.operational_docs),
            }
            if normalized_path not in paths:
                continue
            score = 100 if record.canonical else 50
        elif contract is not None:
            normalized_contracts = {item.casefold() for item in record.contracts}
            if contract.casefold() not in normalized_contracts:
                continue
            score = 100 if record.canonical else 50
        if score > 0:
            matches.append((score, record))

    matches.sort(key=lambda item: (-item[0], not item[1].canonical, item[1].path))
    return matches[: max(1, limit)]


def _compact_list(values: Iterable[str], *, verbose: bool, limit: int = 6) -> str:
    items = list(dict.fromkeys(values))
    if not items:
        return "—"
    if verbose or len(items) <= limit:
        return ", ".join(items)
    visible = ", ".join(items[:limit])
    return f"{visible} (+{len(items) - limit})"


def _render_anchors(anchors: tuple[Anchor, ...], *, verbose: bool) -> list[str]:
    visible = anchors if verbose else anchors[:4]
    lines = [
        f"  - {item.path} :: {_compact_list(item.symbols, verbose=verbose, limit=5)}"
        for item in visible
    ]
    if not verbose and len(anchors) > len(visible):
        lines.append(f"  - … (+{len(anchors) - len(visible)})")
    return lines


def render_route(score: int, record: RouteRecord, *, verbose: bool = False) -> str:
    lines = [
        f"scope: {record.truth_scope or 'supporting'}",
        f"path: {record.path}",
        f"status: {record.status}; canonical: {'yes' if record.canonical else 'no'}",
        f"summary: {record.summary}",
    ]
    if record.read_when:
        lines.append(f"read_when: {record.read_when}")
    if record.operational_docs:
        lines.append("operational_docs (verify current state):")
        lines.extend(
            f"  - {item.path} :: {item.summary}"
            for item in record.operational_docs
        )
    if record.ai_sections:
        sections = ", ".join(
            f"{key} -> {heading}" for key, heading in record.ai_sections
        )
        lines.append(f"sections: {sections}")
    if record.code_anchors:
        lines.append("code_anchors:")
        lines.extend(_render_anchors(record.code_anchors, verbose=verbose))
    else:
        lines.append(
            "related_code: "
            + _compact_list(record.related_code, verbose=verbose)
        )
    if record.test_anchors:
        lines.append("test_anchors:")
        lines.extend(_render_anchors(record.test_anchors, verbose=verbose))
    else:
        lines.append(
            "related_tests: "
            + _compact_list(record.related_tests, verbose=verbose)
        )
    if verbose:
        lines.append(f"contracts: {_compact_list(record.contracts, verbose=True)}")
        lines.append(
            f"search_terms: {_compact_list(record.search_terms, verbose=True)}"
        )
        lines.append(f"score: {score}")
    return "\n".join(lines)


def render_path_candidates(
    path: str,
    matches: list[tuple[int, RouteRecord]],
) -> str:
    normalized_path = path.removeprefix("./")
    lines = [
        f"path: {normalized_path}",
        f"matches: {len(matches)}",
        "scopes:",
    ]
    for _score, record in matches:
        canonical = ", canonical" if record.canonical else ""
        lines.append(
            f"  - {record.truth_scope or 'supporting'} -> {record.path} "
            f"[{record.status}{canonical}]"
        )
    lines.append(
        "next: rerun with --scope <scope>; use --verbose to expand every route"
    )
    return "\n".join(lines)


def render_generated_jsonl(records: list[RouteRecord]) -> str:
    lines = [
        json.dumps(record.json_payload(), ensure_ascii=False, sort_keys=True)
        for record in sorted(records, key=lambda item: item.path)
    ]
    return "\n".join(lines) + "\n"


def render_index_block(records: list[RouteRecord]) -> str:
    leaders = sorted(
        (record for record in records if record.canonical),
        key=lambda item: item.truth_scope or "",
    )
    lines = [
        GENERATED_BLOCK_START,
        "| Scope | Канонический документ | Приоритет | Статус | Когда читать |",
        "| --- | --- | ---: | --- | --- |",
    ]
    for record in leaders:
        read_when = record.read_when.replace("|", "\\|").replace("\n", " ")
        lines.append(
            f"| `{record.truth_scope}` | `{record.path}` | "
            f"{record.truth_priority} | {record.status} | {read_when} |"
        )
    lines.append(GENERATED_BLOCK_END)
    return "\n".join(lines)


def replace_index_block(index_text: str, block: str) -> str:
    start = index_text.find(GENERATED_BLOCK_START)
    end = index_text.find(GENERATED_BLOCK_END)
    if start < 0 or end < 0 or end < start:
        raise ValueError("docs/index.md generated routing markers are missing")
    end += len(GENERATED_BLOCK_END)
    return index_text[:start] + block + index_text[end:]


def write_generated(records: list[RouteRecord]) -> None:
    GENERATED_INDEX.parent.mkdir(parents=True, exist_ok=True)
    GENERATED_INDEX.write_text(render_generated_jsonl(records), encoding="utf-8")
    index_text = DOCS_INDEX.read_text(encoding="utf-8")
    DOCS_INDEX.write_text(
        replace_index_block(index_text, render_index_block(records)),
        encoding="utf-8",
    )


def check_generated(records: list[RouteRecord]) -> list[str]:
    failures: list[str] = []
    expected_jsonl = render_generated_jsonl(records)
    if not GENERATED_INDEX.exists():
        failures.append("docs/generated/ai-routing.jsonl is missing")
    elif GENERATED_INDEX.read_text(encoding="utf-8") != expected_jsonl:
        failures.append("docs/generated/ai-routing.jsonl is stale")

    if not DOCS_INDEX.exists():
        failures.append("docs/index.md is missing")
    else:
        index_text = DOCS_INDEX.read_text(encoding="utf-8")
        try:
            expected_index = replace_index_block(
                index_text,
                render_index_block(records),
            )
        except ValueError as exc:
            failures.append(str(exc))
        else:
            if expected_index != index_text:
                failures.append("docs/index.md generated AI routing block is stale")
    return failures


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Return a compact, source-of-truth-aware documentation route."
    )
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--query", help="Search routing metadata.")
    action.add_argument("--scope", help="Find an exact truth scope.")
    action.add_argument("--path", help="Find specs related to a code or test path.")
    action.add_argument("--contract", help="Find specs declaring a contract.")
    action.add_argument(
        "--write-generated",
        action="store_true",
        help="Rewrite the generated JSONL and docs/index.md routing block.",
    )
    action.add_argument(
        "--check-generated",
        action="store_true",
        help="Check generated JSONL and docs/index.md without writing.",
    )
    parser.add_argument(
        "--include-supporting",
        action="store_true",
        help="Include non-canonical documents.",
    )
    parser.add_argument(
        "--include-history",
        action="store_true",
        help="Include draft and superseded documents.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Maximum routes (default: one, or every exact --path match).",
    )
    parser.add_argument("--verbose", action="store_true", help="Show full lists.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        records = load_route_records()
    except (OSError, ValueError) as exc:
        print(f"Documentation routing failed: {exc}", file=sys.stderr)
        return 1

    if args.write_generated:
        write_generated(records)
        print("Generated AI documentation routing artifacts updated.")
        return 0
    if args.check_generated:
        failures = check_generated(records)
        if failures:
            print("AI documentation routing check failed:")
            for failure in failures:
                print(f"- {failure}")
            return 1
        print("AI documentation routing artifacts are current.")
        return 0

    route_limit = args.limit
    if route_limit is None:
        route_limit = len(records) if args.path else 1

    matches = find_routes(
        records,
        query=args.query,
        scope=args.scope,
        path=args.path,
        contract=args.contract,
        include_supporting=args.include_supporting,
        include_history=args.include_history,
        limit=route_limit,
    )
    if not matches:
        print("No documentation route found.", file=sys.stderr)
        return 1
    if args.path and args.limit is None and not args.verbose and len(matches) > 1:
        print(render_path_candidates(args.path, matches))
    else:
        rendered = (render_route(*item, verbose=args.verbose) for item in matches)
        print("\n\n".join(rendered))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
