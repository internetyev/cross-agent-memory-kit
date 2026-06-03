from __future__ import annotations

import os
import re
from pathlib import Path

from distill.logs import Logger, null_logger

# Optional, opt-in client/project registry. Point MCP_MEMORY_CLIENTS_YAML at a
# YAML file and the distiller will tag each memory with a canonical slug. When
# the env var is unset, distillation runs with an empty registry and uses
# "unknown" for the client_or_project field.
#
# Expected shape:
#   clients:
#     - id: my-app
#       display_name: "My App"
#       aliases: ["myapp", "the app"]
#       domains:
#         - host: myapp.com
#           slug: myapp
#           primary: true
#   projects:
#     - id: internal-tool
#       display_name: "Internal Tool"


def clients_yaml_path() -> Path | None:
    raw = os.environ.get("MCP_MEMORY_CLIENTS_YAML")
    return Path(raw).expanduser() if raw else None


def load_registry(logger: Logger = null_logger) -> tuple[list[dict], list[dict]]:
    path = clients_yaml_path()
    if path is None:
        return [], []
    if not path.exists():
        logger(f"clients.yaml not found at {path}")
        return [], []

    try:
        import yaml

        data = yaml.safe_load(path.read_text()) or {}
        clients = data.get("clients", []) or []
        projects = data.get("projects", []) or []
        return _normalize(clients), _normalize(projects)
    except Exception as exc:
        logger(f"  yaml parse failed ({exc}); falling back to regex extraction")

    text = path.read_text()
    return _extract_section(text, "clients"), _extract_section(text, "projects")


def format_registry_for_prompt(clients: list[dict], projects: list[dict]) -> str:
    return _format_entries(clients, "CLIENTS") + "\n\n" + _format_entries(projects, "PROJECTS")


def _normalize(entries: list[dict]) -> list[dict]:
    normalized = []
    for entry in entries:
        entry_id = entry.get("id", "?")
        domains_raw = entry.get("domains") or []
        domains: list[dict] = []
        for d in domains_raw:
            if isinstance(d, str):
                # Bare-string form: "example.com"
                host = d.strip().lower()
                slug = host.split(".")[0] if host else ""
                domains.append({"host": host, "slug": slug, "primary": False})
            elif isinstance(d, dict):
                host = str(d.get("host", "")).strip().lower()
                slug = str(d.get("slug") or (host.split(".")[0] if host else "")).strip()
                domains.append({
                    "host": host,
                    "slug": slug,
                    "primary": bool(d.get("primary", False)),
                    "status": d.get("status", "active"),
                    "notes": d.get("notes", ""),
                })
        # If no entry is explicitly primary, mark the first one.
        if domains and not any(d["primary"] for d in domains):
            domains[0]["primary"] = True

        normalized.append({
            "id": entry_id,
            # `slug` defaults to `id` so consumers always have a non-empty label.
            "slug": str(entry.get("slug") or entry_id),
            "display_name": entry.get("display_name", ""),
            "aliases": list(entry.get("aliases") or []),
            "domains": domains,
        })
    return normalized


def _format_entries(entries: list[dict], label: str) -> str:
    lines = [f"{label}:"]
    for entry in entries:
        # Format: "  - <slug> (<display_name>) [domains: host->slug, ...] [aliases: ...]"
        slug = entry["slug"]
        line = f"  - {slug} ({entry['display_name']})"
        if entry["domains"]:
            domain_strs = []
            for d in entry["domains"][:6]:
                marker = "*" if d.get("primary") else ""
                pair = f"{d['host']}->{d['slug']}"
                if marker:
                    pair = f"{pair}{marker}"
                domain_strs.append(pair)
            line += f" [domains: {', '.join(domain_strs)}]"
        if entry["aliases"]:
            aliases = ", ".join(entry["aliases"][:6])
            line += f" [aliases: {aliases}]"
        lines.append(line)
    return "\n".join(lines)


def _extract_section(text: str, name: str) -> list[dict]:
    match = re.search(rf"^{name}:\s*$", text, re.M)
    if not match:
        return []

    start = match.end()
    end_match = re.search(r"\n([a-z_]+):\s*$", text[start:], re.M)
    section = text[start: start + end_match.start()] if end_match else text[start:]
    entries = []

    for block in re.split(r"\n  - id:", section)[1:]:
        id_match = re.match(r"\s*([a-z0-9_-]+)", block)
        slug_match = re.search(r'\n    slug:\s*"?([^"\n]+)"?', block)
        display_match = re.search(r'\n    display_name:\s*"?([^"\n]+)"?', block)
        aliases_match = re.search(r"\n    aliases:\s*(\[[^\]]*\]|\n(?:      -.+\n)+)", block)
        aliases: list[str] = []

        if aliases_match:
            raw = aliases_match.group(1)
            if raw.startswith("["):
                aliases = [a.strip().strip("\"'") for a in raw[1:-1].split(",") if a.strip()]
            else:
                aliases = [
                    line.strip().lstrip("-").strip().strip("\"'")
                    for line in raw.split("\n")
                    if line.strip().startswith("-")
                ]

        # Best-effort domain extraction from the regex fallback path. We only
        # parse the structured mapping form; the bare-string form is rare in
        # practice. This is a fallback - the YAML loader is the canonical path.
        domains: list[dict] = []
        for dmatch in re.finditer(
            r"\n      - host:\s*([^\s\n]+)(?:\n        slug:\s*([^\s\n]+))?(?:\n        primary:\s*(true|false))?",
            block,
        ):
            host = dmatch.group(1).strip().strip('"').lower()
            slug = (dmatch.group(2) or host.split(".")[0]).strip().strip('"')
            primary = dmatch.group(3) == "true"
            domains.append({"host": host, "slug": slug, "primary": primary})
        if domains and not any(d["primary"] for d in domains):
            domains[0]["primary"] = True

        entry_id = id_match.group(1) if id_match else "?"
        entries.append({
            "id": entry_id,
            "slug": (slug_match.group(1).strip() if slug_match else entry_id),
            "display_name": display_match.group(1).strip() if display_match else "",
            "aliases": aliases,
            "domains": domains,
        })

    return entries
