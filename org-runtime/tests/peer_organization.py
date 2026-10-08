"""A peer organization materialized for a test: its own kernel, emitters and ledgers.

Adapted from StegVerse-org/.github@6674994 tests/peer_organization.py. The
kernel records every crossing it consumes or publishes on its own
organization's ledgers, through the emitters of the repository it lives in,
and refuses a dispatch root that is not that repository. A peer therefore
cannot be a bare directory handed to SV-LLM's kernel: that would be SV-LLM's
emitter writing a receipt in another organization's name. Each peer gets a
copy of the kernel, the two emitters and the ledger contracts, rewritten to its
own name; its organization chain is opened by a declared genesis, as SV-LLM's
is; and it publishes and consumes through its own kernel into ledger and node
state roots supplied to it, as a materializer would.

Not a test module; loaded by path from the tests that need a peer.
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CONTRACT = "docs/CANONICAL_NODE_INGRESS_CONTRACT_001.json"
COPIED = (
    "org-kernel/kernel.py",
    "org-kernel/node_store.py",
    "resident-runtime/ledger_store.py",
    "resident-runtime/aggregate_repo_transition.py",
    ".stegverse/transition-ledger/emit.py",
    "org-boundary/runtime/manifest_selection.py",
    "org-boundary/runtime/node_standing.py",
    CONTRACT,
)


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Peer:
    def __init__(self, root: Path, state: Path, organization: str):
        self.root = root
        self.organization = organization
        self.repo_ledger = state / "repo-ledger"
        self.org_ledger = state / "org-ledger"
        self.node_state = state / "node"
        tag = organization.replace("-", "_").lower() + "_" + root.name
        self.kernel = _load("peer_kernel_" + tag, root / "org-kernel/kernel.py")

    def ledgers(self):
        return {"repo_ledger_root": self.repo_ledger, "org_ledger_root": self.org_ledger}

    def open_ledger(self):
        """The peer's own declared genesis, appended through its own emitters."""
        emitter = self.kernel._own_module("crossing_repository_ledger", ".stegverse/transition-ledger/emit.py")
        organization = self.kernel._own_module("crossing_organization_ledger",
                                               "resident-runtime/aggregate_repo_transition.py")
        subject = emitter.sha({"intended_action": "OPEN_ORGANIZATION_LEDGER", "organization": self.organization})
        outcome = emitter.sha({"disposition": "ALLOW", "organization": self.organization})
        receipt = emitter.append("ORGANIZATION_LEDGER_OPENED:" + outcome[7:31], "ORGANIZATION_LEDGER_OPENED",
                                 subject, outcome, {"disposition": "ALLOW"}, "NONE", hb_epoch=32,
                                 store=emitter.ledger_store.PosixLedgerStore(self.repo_ledger))
        return organization.append(receipt, "ORGANIZATION_LEDGER_OPENED", organization.GENESIS,
                                   receipt["receipt_sha256"], {"disposition": "ALLOW"}, "NONE", hb_epoch=32,
                                   store=emitter.ledger_store.PosixLedgerStore(self.org_ledger))

    def custody(self):
        return self.kernel.crossing_custody(self.root, **self.ledgers())

    def publish(self, packet, *, mesh_root, **options):
        return self.kernel.publish_packet(packet, root=mesh_root, custody=self.custody(), **options)

    def consume(self, *, mesh_root, **options):
        options.setdefault("node_state_root", self.node_state)
        return self.kernel.consume_and_respond(self.root, mesh_root=mesh_root, **self.ledgers(), **options)

    def consume_addressed(self, *, mesh_root, **options):
        return self.kernel.consume_addressed_frames(self.root, mesh_root=mesh_root, **self.ledgers(), **options)

    def receipts(self, level="org"):
        root = self.org_ledger if level == "org" else self.repo_ledger
        return [json.loads(p.read_text(encoding="utf-8")) for p in (root / "receipts").glob("*.json")] \
            if (root / "receipts").is_dir() else []


def materialize(base: Path | None, organization: str, services: list, *, extra=(), registry_extra=None,
                open_ledger=True) -> Peer:
    """A peer node for `organization` serving `services`, under `base` (a fresh temp dir if None)."""
    base = Path(tempfile.mkdtemp()) if base is None else Path(base)
    slug = "".join(ch.lower() if ch.isalnum() else "-" for ch in organization).strip("-")
    root = base / ("peer-" + slug)
    state = base / ("peer-" + slug + "-state")
    for relative in tuple(COPIED) + tuple(extra):
        (root / relative).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO / relative, root / relative)
    repository = json.loads((REPO / ".stegverse/transition-ledger/contract.json").read_text())
    repository["repository"] = organization + "/.github"
    (root / ".stegverse/transition-ledger/contract.json").write_text(json.dumps(repository))
    org_contract = json.loads((REPO / ".stegverse/transition-ledger/org-contract.json").read_text())
    org_contract["organization"] = organization
    (root / ".stegverse/transition-ledger/org-contract.json").write_text(json.dumps(org_contract))
    (root / "org-boundary/registry").mkdir(parents=True, exist_ok=True)
    (root / "org-boundary/registry/services.json").write_text(json.dumps({
        "schema_version": "stegverse.org-boundary-registry.v1", "organization": organization,
        "services": services, **(registry_extra or {})}))
    peer = Peer(root, state, organization)
    if open_ledger:
        peer.open_ledger()
    return peer
