"""
Modrinth modpack catalog.

Thin client over the public Modrinth API v2 (https://docs.modrinth.com/) used
by the "Сборки" page to browse modpacks: tags (game versions, categories,
loaders), search and project details.

All network access is isolated behind :class:`ModrinthCatalogClient` so the UI
can be driven by a stub implementation in tests.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import requests


API_BASE = "https://api.modrinth.com/v2"
USER_AGENT = "MelonLauncher/0.1.0 (modpack browser)"
TIMEOUT = (10, 30)

# Modrinth reports loaders as regular categories too, so a modpack hit's loader
# is whichever of these names appears in its category list.
KNOWN_LOADERS = ("fabric", "forge", "neoforge", "quilt")

LOADER_LABELS = {
    "fabric": "Fabric",
    "forge": "Forge",
    "neoforge": "NeoForge",
    "quilt": "Quilt",
    "vanilla": "Vanilla",
}

# (value, human label) for the "sort by" selector.
SORT_OPTIONS = [
    ("relevance", "Релевантность"),
    ("downloads", "Загрузки"),
    ("follows", "Подписки"),
    ("newest", "Новые"),
    ("updated", "Обновлённые"),
]


class CatalogError(Exception):
    """Raised when the Modrinth API cannot be reached or returns an error."""


def _game_version_key(version: str) -> tuple:
    """Numeric sort key for Minecraft versions ("1.21.1", "26.3")."""
    parts = []
    for chunk in str(version).split("."):
        digits = "".join(ch for ch in chunk if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


@dataclass(frozen=True)
class ModpackTags:
    """Filter values offered by the catalog."""

    game_versions: List[str] = field(default_factory=list)
    categories: List[str] = field(default_factory=list)
    loaders: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class ModpackHit:
    """One modpack as it appears in the search results."""

    project_id: str
    slug: str
    title: str
    description: str
    author: str
    downloads: int
    follows: int
    icon_url: str
    categories: List[str]
    game_versions: List[str]
    loaders: List[str]
    latest_version: str
    date_updated: str
    color: Optional[int] = None

    @property
    def key(self) -> str:
        """Stable identifier (slug when present, id otherwise)."""
        return self.slug or self.project_id

    @property
    def primary_loader(self) -> str:
        for loader in KNOWN_LOADERS:
            if loader in self.loaders:
                return LOADER_LABELS.get(loader, loader.title())
        return "Vanilla"

    @property
    def latest_game_version(self) -> str:
        if not self.game_versions:
            return ""
        return max(self.game_versions, key=_game_version_key)

    @classmethod
    def from_hit(cls, hit: Dict[str, Any]) -> "ModpackHit":
        categories = list(hit.get("categories") or [])
        loaders = [c for c in categories if c in KNOWN_LOADERS]
        return cls(
            project_id=hit.get("project_id", ""),
            slug=hit.get("slug", ""),
            title=hit.get("title", ""),
            description=hit.get("description", ""),
            author=hit.get("author", ""),
            downloads=int(hit.get("downloads", 0) or 0),
            follows=int(hit.get("follows", 0) or 0),
            icon_url=hit.get("icon_url") or "",
            categories=categories,
            game_versions=list(hit.get("versions") or []),
            loaders=loaders,
            latest_version=hit.get("latest_version", ""),
            date_updated=hit.get("date_modified", ""),
            color=hit.get("color"),
        )


@dataclass(frozen=True)
class SearchResult:
    hits: List[ModpackHit] = field(default_factory=list)
    total: int = 0
    offset: int = 0


@dataclass(frozen=True)
class ModpackVersionInfo:
    """A single downloadable version of a modpack."""

    id: str
    name: str
    version_number: str
    version_type: str
    game_versions: List[str]
    loaders: List[str]
    date_published: str
    downloads: int
    files: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def loader_label(self) -> str:
        for loader in self.loaders:
            if loader in LOADER_LABELS:
                if loader == "vanilla" or loader in KNOWN_LOADERS:
                    return LOADER_LABELS[loader]
        return self.loaders[0].title() if self.loaders else "—"

    @property
    def primary_file(self) -> Optional[Dict[str, Any]]:
        for entry in self.files:
            if entry.get("primary"):
                return entry
        return self.files[0] if self.files else None

    @classmethod
    def from_version(cls, data: Dict[str, Any]) -> "ModpackVersionInfo":
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            version_number=data.get("version_number", ""),
            version_type=data.get("version_type", "release"),
            game_versions=list(data.get("game_versions") or []),
            loaders=list(data.get("loaders") or []),
            date_published=data.get("date_published", ""),
            downloads=int(data.get("downloads", 0) or 0),
            files=list(data.get("files") or []),
        )


@dataclass(frozen=True)
class ModpackDetail:
    """Full project description plus its version list."""

    project_id: str
    slug: str
    title: str
    description: str
    body: str
    icon_url: str
    downloads: int
    follows: int
    categories: List[str]
    loaders: List[str]
    game_versions: List[str]
    date_updated: str
    color: Optional[int] = None
    versions: List[ModpackVersionInfo] = field(default_factory=list)

    @classmethod
    def from_project(
        cls,
        project: Dict[str, Any],
        versions: Optional[List[ModpackVersionInfo]] = None,
    ) -> "ModpackDetail":
        categories = list(project.get("categories") or [])
        loaders = [c for c in categories if c in KNOWN_LOADERS]
        # The project endpoint exposes loaders explicitly as well.
        for loader in project.get("loaders") or []:
            if loader not in loaders:
                loaders.append(loader)
        return cls(
            project_id=project.get("id", ""),
            slug=project.get("slug", ""),
            title=project.get("title", ""),
            description=project.get("description", ""),
            body=project.get("body", ""),
            icon_url=project.get("icon_url") or "",
            downloads=int(project.get("downloads", 0) or 0),
            follows=int(project.get("followers", 0) or 0),
            categories=categories,
            loaders=loaders,
            game_versions=list(project.get("game_versions") or []),
            date_updated=project.get("updated", "") or project.get("date_modified", ""),
            color=project.get("color"),
            versions=list(versions or []),
        )


class ModrinthCatalogClient:
    """Read-only client for browsing Modrinth modpacks."""

    provider_name = "Modrinth"
    sort_options = SORT_OPTIONS

    def __init__(self, timeout=TIMEOUT):
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update(
            {"User-Agent": USER_AGENT, "Accept": "application/json"}
        )
        self._tags: Optional[ModpackTags] = None

    # ---------- low level ----------

    def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        try:
            response = self._session.get(
                API_BASE + path, params=params, timeout=self.timeout
            )
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            raise CatalogError(str(exc)) from exc
        except ValueError as exc:  # invalid JSON
            raise CatalogError(f"Некорректный ответ Modrinth: {exc}") from exc

    # ---------- catalog data ----------

    def get_tags(self, force: bool = False) -> ModpackTags:
        """Game versions / categories / loaders, cached for the session."""
        if self._tags is not None and not force:
            return self._tags

        raw_versions = self._get("/tag/game_version")
        raw_categories = self._get("/tag/category")
        raw_loaders = self._get("/tag/loader")

        releases = [v for v in raw_versions if v.get("version_type") == "release"]
        releases.sort(key=lambda v: v.get("date", ""), reverse=True)

        categories = sorted(
            {c["name"] for c in raw_categories if c.get("project_type") == "modpack"}
        )

        available = {
            l["name"]
            for l in raw_loaders
            if "modpack" in (l.get("supported_project_types") or [])
        }
        loaders = [name for name in KNOWN_LOADERS if name in available]

        self._tags = ModpackTags(
            game_versions=[v["version"] for v in releases],
            categories=categories,
            loaders=loaders,
        )
        return self._tags

    def search(
        self,
        query: str = "",
        game_version: str = "",
        category: str = "",
        loader: str = "",
        sort: str = "relevance",
        limit: int = 20,
        offset: int = 0,
        categories: Optional[List[str]] = None,
    ) -> SearchResult:
        """Search modpacks, filtered by game version, categories and loader.

        Multiple ``categories`` are OR-ed together (a modpack matches if it has
        any of them); the single ``category`` argument is kept for backwards
        compatibility.
        """
        selected = [c for c in (categories or []) if c]
        if not selected and category:
            selected = [category]

        facets = [["project_type:modpack"]]
        if game_version:
            facets.append([f"versions:{game_version}"])
        if selected:
            facets.append([f"categories:{c}" for c in selected])
        if loader:
            facets.append([f"categories:{loader}"])

        params: Dict[str, Any] = {
            "limit": min(limit, 100),
            "offset": max(offset, 0),
            "index": sort,
            "facets": json.dumps(facets),
        }
        if query:
            params["query"] = query

        data = self._get("/search", params)
        hits = [ModpackHit.from_hit(hit) for hit in data.get("hits", [])]
        return SearchResult(
            hits=hits,
            total=int(data.get("total_hits", len(hits)) or 0),
            offset=offset,
        )

    def get_project(self, project_id_or_slug: str) -> ModpackDetail:
        """Project description without its versions."""
        project = self._get(f"/project/{project_id_or_slug}")
        return ModpackDetail.from_project(project)

    def get_versions(
        self,
        project_id: str,
        game_version: str = "",
        loader: str = "",
    ) -> List[ModpackVersionInfo]:
        """Version list of a project, newest first."""
        params: Dict[str, Any] = {}
        if game_version:
            params["game_versions"] = json.dumps([game_version])
        if loader:
            params["loaders"] = json.dumps([loader])

        data = self._get(f"/project/{project_id}/version", params)
        versions = [ModpackVersionInfo.from_version(v) for v in data]
        versions.sort(key=lambda v: v.date_published, reverse=True)
        return versions

    def get_details(
        self,
        project_id_or_slug: str,
        game_version: str = "",
        loader: str = "",
    ) -> ModpackDetail:
        """Project description together with its versions (one background call)."""
        project = self._get(f"/project/{project_id_or_slug}")
        project_id = project.get("id") or project_id_or_slug

        params: Dict[str, Any] = {}
        if game_version:
            params["game_versions"] = json.dumps([game_version])
        if loader:
            params["loaders"] = json.dumps([loader])

        raw_versions = self._get(f"/project/{project_id}/version", params)
        versions = [ModpackVersionInfo.from_version(v) for v in raw_versions]
        versions.sort(key=lambda v: v.date_published, reverse=True)

        return ModpackDetail.from_project(project, versions)


def format_downloads(count: int) -> str:
    """Compact human readable download counter (1 234 -> '1,2 тыс.')."""
    if count >= 1_000_000:
        return f"{count / 1_000_000:.1f} млн".replace(".0 млн", " млн")
    if count >= 1_000:
        return f"{count / 1_000:.1f} тыс.".replace(".0 тыс.", " тыс.")
    return str(count)
