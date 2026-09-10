"""Prepare AMPL analysis results for the admin display."""


def _visible_value(value):
    if isinstance(value, dict):
        return {key: _visible_value(item) for key, item in value.items() if key.lower() != "path"}
    if isinstance(value, list):
        return [_visible_value(item) for item in value]
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if value in (None, ""):
        return "Not recorded"
    return value


def _flatten_rows(value, prefix=""):
    rows = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key.lower() == "path":
                continue
            label = f"{prefix} / {key}" if prefix else key
            rows.extend(_flatten_rows(child, label))
    elif isinstance(value, list):
        rows.append({"label": prefix, "value": ", ".join(str(item) for item in value) or "None"})
    else:
        rows.append({"label": prefix, "value": _visible_value(value)})
    return rows


def build_analysis_sections(run):
    """Return readable statistics and diagnostics without displaying path fields."""
    sections = []
    statistics = run.get("statistics") or {}
    diagnostics = statistics.get("diagnostics") if isinstance(statistics, dict) else None
    visible_statistics = {
        key: value for key, value in statistics.items() if key != "diagnostics"
    } if isinstance(statistics, dict) else statistics
    for value, title in ((visible_statistics, "Statistics"), (diagnostics, "Diagnostics")):
        rows = _flatten_rows(value)
        if rows:
            sections.append({"title": title, "rows": rows})
    return sections
