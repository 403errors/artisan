"""Parity guard between the Python `TicketDoc`/`TicketStatus` contract and the dashboard's
TypeScript mirror in `dashboard/src/types/ticket.ts`.

The dashboard's `TicketDoc` is deliberately a *view subset* (it never exposes internal fields
like `processed_delivery_ids`), so parity means:

- every field the TS interface declares must exist in the Python model (no phantom fields —
  a Python-side rename/removal must fail here, not at runtime in the dashboard), and
- the `TicketStatus` union must match exactly on both sides.

Skips when the dashboard source isn't present (e.g. the package built standalone).
"""

import re
from pathlib import Path
from typing import get_args

import pytest
from artisan_shared.firestore_schema import TicketDoc, TicketStatus

TS_TYPES = Path(__file__).parents[3] / "dashboard" / "src" / "types" / "ticket.ts"

pytestmark = pytest.mark.skipif(not TS_TYPES.exists(), reason="dashboard source not present")


def _snake_to_camel(name: str) -> str:
    head, *rest = name.split("_")
    return head + "".join(part.capitalize() for part in rest)


def _ts_block(source: str, start_marker: str) -> str:
    start = source.index(start_marker)
    end = source.index("\n}", start)
    return source[start:end]


def _ts_interface_fields(source: str, interface: str) -> set[str]:
    block = _ts_block(source, f"export interface {interface} {{")
    return set(re.findall(r"^\s*(\w+)\??:", block, flags=re.MULTILINE))


def _ts_union_members(source: str, type_name: str) -> set[str]:
    start = source.index(f"export type {type_name} =")
    end = source.index(";", start)
    return set(re.findall(r'"(\w+)"', source[start:end]))


def test_ts_ticket_doc_has_no_phantom_fields() -> None:
    python_fields = {_snake_to_camel(f) for f in TicketDoc.model_fields}
    # `id` is the Firestore doc key, not a stored field — legitimately TS-only.
    ts_fields = _ts_interface_fields(TS_TYPES.read_text(), "TicketDoc") - {"id"}

    phantom = ts_fields - python_fields
    assert not phantom, (
        f"dashboard TicketDoc declares fields with no Python counterpart: {sorted(phantom)}. "
        "Add them to artisan_shared.firestore_schema.TicketDoc or remove them from the TS mirror."
    )


def test_ticket_status_union_matches() -> None:
    python_statuses = set(get_args(TicketStatus))
    ts_statuses = _ts_union_members(TS_TYPES.read_text(), "TicketStatus")

    assert ts_statuses == python_statuses, (
        f"TicketStatus drift — TS-only: {sorted(ts_statuses - python_statuses)}, "
        f"Python-only: {sorted(python_statuses - ts_statuses)}"
    )
