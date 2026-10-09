"""Small, read-only helpers for displaying historical payroll snapshots."""


_BASIS_LABELS = {
    "HOURLY": "Hourly",
    "DAILY": "Daily",
    "MONTHLY": "Monthly",
}


def snapshot_pay_basis(snapshot):
    """Return a trustworthy historical pay-basis label for a statement."""
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    direct = str(snapshot.get("pay_basis") or "").strip().upper()
    if direct in _BASIS_LABELS:
        return _BASIS_LABELS[direct]

    bases = set()
    for key in ("compensation_versions", "rate_versions"):
        versions = snapshot.get(key)
        if not isinstance(versions, dict):
            continue
        for version in versions.values():
            if not isinstance(version, dict):
                continue
            basis = str(version.get("basis") or "").strip().upper()
            if basis in _BASIS_LABELS:
                bases.add(basis)
    if len(bases) == 1:
        return _BASIS_LABELS[next(iter(bases))]
    if len(bases) > 1:
        return "Mixed"
    return "Pay basis not recorded"


def snapshot_pay_basis_with_suffix(snapshot):
    return f"{snapshot_pay_basis(snapshot)} pay"
