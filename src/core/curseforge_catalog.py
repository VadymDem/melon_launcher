"""
CurseForge modpack catalog.

Thin client over the official CurseForge API (https://docs.curseforge.com/)
used by the "Сборки" page. It exposes the exact same surface as
:class:`core.modrinth_catalog.ModrinthCatalogClient` (``get_tags`` / ``search``
/ ``get_details``) so the catalog UI can be reused unchanged, mapping the
CurseForge payloads onto the shared dataclasses.

The API requires an ``x-api-key`` header. The key can be supplied explicitly,
via the ``CURSEFORGE_API_KEY`` environment variable, or falls back to the
bundled default.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

import requests

from core.modrinth_catalog import (
    CatalogError,
    ModpackDetail,
    ModpackHit,
    ModpackTags,
    ModpackVersionInfo,
    SearchResult,
    _game_version_key,
)

API_BASE = "https://api.curseforge.com"
USER_AGENT = "MelonLauncher/0.1.0 (modpack browser)"
TIMEOUT = (10, 30)

# Bundled key; override with the CURSEFORGE_API_KEY env var or an explicit arg.
DEFAULT_API_KEY = "$2a$10$wq65c/lRHr.X5vvn1ORE6.QLQeE/.Tj2Jdmz6lSsFTj.X1mVyUBXe"

GAME_ID_MINECRAFT = 432
CLASS_ID_MODPACKS = 4471

# CurseForge mod loader enum -> our shared lowercase loader names.
MODLOADER_TYPES = {"forge": 1, "fabric": 4, "quilt": 5, "neoforge": 6}
LOADER_LABELS_BY_NAME = {
    "forge": "forge",
    "fabric": "fabric",
    "quilt": "quilt",
    "neoforge": "neoforge",
}

# (value, label) for the sort selector; the value maps onto a CurseForge
# sortField below.
SORT_OPTIONS = [
    ("popularity", "Популярность"),
    ("downloads", "Загрузки"),
    ("updated", "Обновлённые"),
    ("newest", "Новые"),
]

# CurseForge sortField values: 2=Popularity, 6=TotalDownloads, 3=LastUpdated,
# 11=ReleasedDate. Everything here is "best first".
_SORT_FIELDS = {
    "popularity": (2, "desc"),
    "downloads": (6, "desc"),
    "updated": (3, "desc"),
    "newest": (11, "desc"),
}

# CurseForge file releaseType -> Modrinth-style version_type.
_RELEASE_TYPES = {1: "release", 2: "beta", 3: "alpha"}


def _logo_url(mod: Dict[str, Any]) -> str:
    logo = mod.get("logo") or {}
    return logo.get("thumbnailUrl") or logo.get("url") or ""


def _split_game_versions(values: List[str]) -> Tuple[List[str], List[str]]:
    """Separate a CurseForge ``gameVersions`` array into MC versions + loaders."""
    game_versions: List[str] = []
    loaders: List[str] = []
    for value in values or []:
        name = LOADER_LABELS_BY_NAME.get(str(value).lower())
        if name:
            if name not in loaders:
                loaders.append(name)
        elif value not in game_versions:
            game_versions.append(value)
    return game_versions, loaders


def _collect_from_files(files):
    """Pull (game_versions, loaders) out of a list of CurseForge file dicts."""
    game_versions: List[str] = []
    loaders: List[str] = []
    for entry in files or []:
        gvs, lds = _split_game_versions(entry.get("gameVersions") or [])
        for version in gvs:
            if version not in game_versions:
                game_versions.append(version)
        for loader in lds:
            if loader not in loaders:
                loaders.append(loader)
    return game_versions, loaders


class CurseForgeCatalogClient:
    """Read-only client for browsing CurseForge modpacks."""

    provider_name = "CurseForge"
    sort_options = SORT_OPTIONS

    def __init__(self, api_key: str = "", timeout=TIMEOUT):
        self.api_key = (
            api_key or os.environ.get("CURSEFORGE_API_KEY") or DEFAULT_API_KEY
        )
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": USER_AGENT,
                "Accept": "application/json",
                "x-api-key": self.api_key,
            }
        )
        self._tags: Optional[ModpackTags] = None
        self._category_ids: Dict[str, int] = {}

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
            raise CatalogError(f"Некорректный ответ CurseForge: {exc}") from exc

    # ---------- catalog data ----------

    def get_tags(self, force: bool = False) -> ModpackTags:
        """Game versions / categories / loaders, cached for the session."""
        if self._tags is not None and not force:
            return self._tags

        raw_versions = self._get("/v1/minecraft/version").get("data", [])
        # The endpoint bundles stable releases with snapshots/prereleases; keep
        # only proper releases (they have no "snapshot"/"pre"/"rc" marker).
        rejected = ("snapshot", "pre", "rc", "beta", "alpha")
        releases = [
            v.get("versionString", "")
            for v in raw_versions
            if v.get("versionString")
            and not any(tag in v.get("versionString", "").lower() for tag in rejected)
        ]
        releases.sort(key=_game_version_key, reverse=True)
        game_versions = releases[:100]

        raw_categories = self._get(
            "/v1/categories", {"gameId": GAME_ID_MINECRAFT}
        ).get("data", [])
        pack_categories = [c for c in raw_categories if c.get("classId") == CLASS_ID_MODPACKS]
        pack_categories.sort(key=lambda c: c.get("name", "").lower())
        categories = [c.get("name", "") for c in pack_categories]
        self._category_ids = {
            c.get("name", ""): int(c.get("id", 0)) for c in pack_categories
        }

        loaders = list(MODLOADER_TYPES.keys())

        self._tags = ModpackTags(
            game_versions=game_versions,
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
        sort: str = "popularity",
        limit: int = 20,
        offset: int = 0,
        categories: Optional[List[str]] = None,
    ) -> SearchResult:
        """Search modpacks, filtered by game version, category and loader.

        CurseForge accepts a single ``categoryId`` per request, so the first of
        ``categories`` wins; the ``category`` argument is kept for compatibility.
        """
        chosen = next((c for c in (categories or []) if c), category)
        params: Dict[str, Any] = {
            "gameId": GAME_ID_MINECRAFT,
            "classId": CLASS_ID_MODPACKS,
            "index": max(offset, 0),
            "pageSize": min(max(limit, 1), 50),
        }
        if query:
            params["searchFilter"] = query
        if game_version:
            params["gameVersion"] = game_version
        loader_key = (loader or "").lower()
        if loader_key in MODLOADER_TYPES:
            params["modLoaderType"] = MODLOADER_TYPES[loader_key]
        if chosen and chosen in self._category_ids:
            params["categoryId"] = self._category_ids[chosen]

        field, order = _SORT_FIELDS.get(sort, _SORT_FIELDS["popularity"])
        params["sortField"] = field
        params["sortOrder"] = order

        data = self._get("/v1/mods/search", params)
        mods = data.get("data", [])
        pagination = data.get("pagination", {}) or {}
        total = int(pagination.get("totalCount", len(mods)) or 0)
        hits = [self._hit_from_mod(mod) for mod in mods]
        return SearchResult(hits=hits, total=total, offset=offset)

    def get_details(
        self,
        project_id_or_slug: str,
        game_version: str = "",
        loader: str = "",
    ) -> ModpackDetail:
        """Project description together with its version list."""
        project = self._get(f"/v1/mods/{project_id_or_slug}").get("data", {})
        mod_id = project.get("id") or project_id_or_slug

        try:
            body = self._get(f"/v1/mods/{mod_id}/description").get("data", "")
        except CatalogError:
            body = ""

        raw_files = self._get(
            f"/v1/mods/{mod_id}/files", {"pageSize": 50}
        ).get("data", [])
        versions = [self._version_from_file(entry) for entry in raw_files]

        return self._detail_from_mod(project, body=body, versions=versions)

    # ---------- mapping ----------

    def _hit_from_mod(self, mod: Dict[str, Any]) -> ModpackHit:
        files = mod.get("latestFiles") or []
        game_versions, loaders = _collect_from_files(files)
        authors = mod.get("authors") or []
        latest = files[0].get("displayName", "") if files else ""

        return ModpackHit(
            project_id=str(mod.get("id", "")),
            slug=mod.get("slug", ""),
            title=mod.get("name", ""),
            description=mod.get("summary", ""),
            author=authors[0].get("name", "") if authors else "",
            downloads=int(mod.get("downloadCount", 0) or 0),
            follows=int(mod.get("thumbsUpCount", 0) or 0),
            icon_url=_logo_url(mod),
            categories=[c.get("name", "") for c in mod.get("categories") or []],
            game_versions=game_versions,
            loaders=loaders,
            latest_version=latest,
            date_updated=mod.get("dateModified", "") or "",
            color=None,
        )

    def _detail_from_mod(
        self,
        mod: Dict[str, Any],
        body: str = "",
        versions: Optional[List[ModpackVersionInfo]] = None,
    ) -> ModpackDetail:
        files = mod.get("latestFiles") or []
        game_versions, loaders = _collect_from_files(files)
        if versions:
            for entry in versions:
                for version in entry.game_versions:
                    if version not in game_versions:
                        game_versions.append(version)
                for loader in entry.loaders:
                    if loader not in loaders:
                        loaders.append(loader)

        return ModpackDetail(
            project_id=str(mod.get("id", "")),
            slug=mod.get("slug", ""),
            title=mod.get("name", ""),
            description=mod.get("summary", ""),
            body=body or "",
            icon_url=_logo_url(mod),
            downloads=int(mod.get("downloadCount", 0) or 0),
            follows=int(mod.get("thumbsUpCount", 0) or 0),
            categories=[c.get("name", "") for c in mod.get("categories") or []],
            loaders=loaders,
            game_versions=game_versions,
            date_updated=mod.get("dateModified", "") or "",
            color=None,
            versions=list(versions or []),
        )

    def _version_from_file(self, entry: Dict[str, Any]) -> ModpackVersionInfo:
        game_versions, loaders = _split_game_versions(
            entry.get("gameVersions") or []
        )
        file_id = entry.get("id")
        return ModpackVersionInfo(
            id=str(file_id) if file_id is not None else "",
            name=entry.get("displayName", "") or entry.get("fileName", ""),
            version_number=entry.get("displayName", "") or entry.get("fileName", ""),
            version_type=_RELEASE_TYPES.get(entry.get("releaseType"), "release"),
            game_versions=game_versions,
            loaders=loaders,
            date_published=entry.get("fileDate", "") or "",
            downloads=int(entry.get("downloadCount", 0) or 0),
            files=[
                {
                    "id": file_id,
                    "url": entry.get("downloadUrl"),
                    "filename": entry.get("fileName", ""),
                    "primary": True,
                    "size": entry.get("fileLength", 0),
                }
            ],
        )
