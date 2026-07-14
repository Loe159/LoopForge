"""Metrics aggregation service for LoopForge run records."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from loopforge.engine.storage import JsonStore


class MetricsService:
    """Read run metrics and build summaries without treating unknowns as zero."""

    def __init__(self, store: JsonStore, *, record_file: str = "record.json") -> None:
        self.store = store
        self.record_file = record_file

    @staticmethod
    def metric_number(value: object) -> int | float | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)) and value >= 0:
            return value
        return None

    @classmethod
    def summarize_number_series(
        cls,
        records: list[dict[str, Any]],
        values: list[object],
    ) -> dict[str, Any]:
        known = [number for number in (cls.metric_number(value) for value in values) if number is not None]
        total = sum(known) if known else None
        return {
            "known_count": len(known),
            "unknown_count": len(records) - len(known),
            "min": min(known) if known else None,
            "max": max(known) if known else None,
            "sum": total,
            "average": (total / len(known)) if known else None,
        }

    @staticmethod
    def count_values(values: list[object]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for value in values:
            key = str(value) if value is not None else "unknown"
            counts[key] = counts.get(key, 0) + 1
        return dict(sorted(counts.items()))

    def summarize_token_field(self, records: list[dict[str, Any]], field: str) -> dict[str, Any]:
        return self.summarize_number_series(
            records,
            [
                record.get("tokens", {}).get(field)
                if isinstance(record.get("tokens"), dict)
                else None
                for record in records
            ],
        )

    def summarize_costs(self, records: list[dict[str, Any]]) -> dict[str, Any]:
        totals_by_currency: dict[str, int] = {}
        known = 0
        for record in records:
            cost = record.get("cost")
            if not isinstance(cost, dict):
                continue
            amount = self.metric_number(cost.get("amount_microunits"))
            currency = cost.get("currency")
            if not isinstance(amount, int) or not isinstance(currency, str) or not currency:
                continue
            known += 1
            totals_by_currency[currency] = totals_by_currency.get(currency, 0) + amount
        return {
            "known_count": known,
            "unknown_count": len(records) - known,
            "amount_microunits_by_currency": dict(sorted(totals_by_currency.items())),
        }

    def build_summary(self, records: list[dict[str, Any]]) -> dict[str, Any]:
        rows = []
        for record in records:
            timing = record.get("timing") if isinstance(record.get("timing"), dict) else {}
            patch = record.get("patch") if isinstance(record.get("patch"), dict) else {}
            verification = (
                record.get("verification") if isinstance(record.get("verification"), dict) else {}
            )
            final = (
                record.get("final_disposition")
                if isinstance(record.get("final_disposition"), dict)
                else {}
            )
            attempts = record.get("attempts") if isinstance(record.get("attempts"), dict) else {}
            rows.append(
                {
                    "run_id": record.get("run_id"),
                    "duration_seconds": timing.get("duration_seconds"),
                    "attempt_count": attempts.get("count"),
                    "patch_size_bytes": patch.get("size_bytes"),
                    "verification": verification.get("status"),
                    "final_disposition": final.get("status"),
                }
            )
        return {
            "metrics_version": 1,
            "record_count": len(records),
            "duration_seconds": self.summarize_number_series(
                records,
                [
                    record.get("timing", {}).get("duration_seconds")
                    if isinstance(record.get("timing"), dict)
                    else None
                    for record in records
                ],
            ),
            "attempt_count": self.summarize_number_series(
                records,
                [
                    record.get("attempts", {}).get("count")
                    if isinstance(record.get("attempts"), dict)
                    else None
                    for record in records
                ],
            ),
            "patch_size_bytes": self.summarize_number_series(
                records,
                [
                    record.get("patch", {}).get("size_bytes")
                    if isinstance(record.get("patch"), dict)
                    else None
                    for record in records
                ],
            ),
            "tokens": {
                "input_tokens": self.summarize_token_field(records, "input_tokens"),
                "output_tokens": self.summarize_token_field(records, "output_tokens"),
                "total_tokens": self.summarize_token_field(records, "total_tokens"),
            },
            "cost": self.summarize_costs(records),
            "verification_results": self.count_values(
                [
                    record.get("verification", {}).get("status")
                    if isinstance(record.get("verification"), dict)
                    else None
                    for record in records
                ]
            ),
            "final_dispositions": self.count_values(
                [
                    record.get("final_disposition", {}).get("status")
                    if isinstance(record.get("final_disposition"), dict)
                    else None
                    for record in records
                ]
            ),
            "runs": rows,
        }

    def load_records(self, run_root: Path) -> tuple[list[dict[str, Any]], list[str]]:
        records: list[dict[str, Any]] = []
        blockers: list[str] = []
        if not run_root.exists():
            return records, blockers
        for path in sorted(run_root.glob(f"*/metrics/{self.record_file}")):
            try:
                records.append(self.store.read_object(path))
            except (OSError, ValueError, json.JSONDecodeError) as error:
                blockers.append(f"could not read metrics record {path}: {error}")
        return records, blockers
