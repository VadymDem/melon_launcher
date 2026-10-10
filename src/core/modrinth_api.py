import requests
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Union
from urllib.parse import urljoin
import json


@dataclass
class ModrinthProject:
    id: str
    slug: str
    title: str
    description: str
    categories: List[str]
    client_side: str
    server_side: str
    project_type: str
    downloads: int
    follows: int
    icon_url: str = ""
    license: str = ""
    authors: List[str] = field(default_factory=list)
    versions: List[str] = field(default_factory=list)
    loaders: List[str] = field(default_factory=list)

    @classmethod
    def from_api(cls, data: Dict[str, Any]) -> "ModrinthProject":
        return cls(
            id=data["id"],
            slug=data["slug"],
            title=data["title"],
            description=data["description"],
            categories=data.get("categories", []),
            client_side=data.get("client_side", "optional"),
            server_side=data.get("server_side", "optional"),
            project_type=data.get("project_type", "mod"),
            downloads=data.get("downloads", 0),
            follows=data.get("follows", 0),
            icon_url=data.get("icon_url", ""),
            license=data.get("license", {}).get("id", "") if isinstance(data.get("license"), dict) else str(data.get("license", "")),
            authors=[a.get("username", "") for a in data.get("team", []) if a.get("role") == "owner"],
            versions=data.get("versions", []),
            loaders=data.get("loaders", [])
        )


@dataclass
class ModrinthVersion:
    id: str
    project_id: str
    name: str
    version_number: str
    game_versions: List[str]
    loaders: List[str]
    files: List[Dict[str, Any]]
    date_published: str
    changelog: str = ""
    version_type: str = "release"
    dependencies: List[Dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_api(cls, data: Dict[str, Any]) -> "ModrinthVersion":
        return cls(
            id=data["id"],
            project_id=data["project_id"],
            name=data["name"],
            version_number=data["version_number"],
            game_versions=data.get("game_versions", []),
            loaders=data.get("loaders", []),
            files=data.get("files", []),
            date_published=data.get("date_published", ""),
            changelog=data.get("changelog", ""),
            version_type=data.get("version_type", "release"),
            dependencies=data.get("dependencies", [])
        )


@dataclass
class ModrinthFile:
    project_id: str
    version_id: str
    filename: str
    url: str
    hashes: Dict[str, str]
    size: int
    primary: bool = False

    @classmethod
    def from_api(cls, data: Dict[str, Any], project_id: str, version_id: str) -> "ModrinthFile":
        return cls(
            project_id=project_id,
            version_id=version_id,
            filename=data["filename"],
            url=data["url"],
            hashes=data["hashes"],
            size=data["size"],
            primary=data.get("primary", False)
        )


class ModrinthAPI:
    """
    Client for Modrinth API v2.
    https://docs.modrinth.com/
    """
    
    BASE_URL = "https://api.modrinth.com/v2"
    USER_AGENT = "MelonLauncher/1.0 (https://github.com/melon-launcher)"
    
    def __init__(self, timeout: int = 30):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": self.USER_AGENT,
            "Accept": "application/json"
        })
        self.timeout = timeout

    def _get(self, endpoint: str, params: Dict = None) -> Dict:
        url = urljoin(self.BASE_URL, endpoint)
        response = self.session.get(url, params=params, timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def _post(self, endpoint: str, json_data: Dict = None) -> Dict:
        url = urljoin(self.BASE_URL, endpoint)
        response = self.session.post(url, json=json_data, timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def search_projects(
        self,
        query: str = "",
        limit: int = 20,
        offset: int = 0,
        facets: List[List[str]] = None,
        index: str = "relevance"
    ) -> List[ModrinthProject]:
        """
        Search for projects on Modrinth.
        
        Args:
            query: Search query string
            limit: Number of results (max 100)
            offset: Pagination offset
            facets: List of facet filters, e.g., [["project_type:modpack"], ["versions:1.20.4"]]
            index: Sort index (relevance, downloads, follows, newest, updated)
        """
        params = {
            "limit": min(limit, 100),
            "offset": offset,
            "index": index
        }
        
        if query:
            params["query"] = query
        
        if facets:
            params["facets"] = json.dumps(facets)
        
        data = self._get("/search", params)
        return [ModrinthProject.from_api(hit) for hit in data.get("hits", [])]

    def search_modpacks(
        self,
        query: str = "",
        game_versions: List[str] = None,
        loaders: List[str] = None,
        limit: int = 20
    ) -> List[ModrinthProject]:
        """Search specifically for modpacks with version/loader filters."""
        facets = [["project_type:modpack"]]
        
        if game_versions:
            facets.append([f"versions:{v}" for v in game_versions])
        
        if loaders:
            facets.append([f"categories:{l}" for l in loaders])
        
        return self.search_projects(
            query=query,
            limit=limit,
            facets=facets,
            index="relevance"
        )

    def get_project(self, project_id_or_slug: str) -> ModrinthProject:
        """Get a single project by ID or slug."""
        data = self._get(f"/project/{project_id_or_slug}")
        return ModrinthProject.from_api(data)

    def get_project_versions(
        self,
        project_id: str,
        game_versions: List[str] = None,
        loaders: List[str] = None,
        version_type: str = None,
        featured: bool = False
    ) -> List[ModrinthVersion]:
        """Get versions for a project."""
        params = {}
        if game_versions:
            params["game_versions"] = json.dumps(game_versions)
        if loaders:
            params["loaders"] = json.dumps(loaders)
        if version_type:
            params["version_type"] = version_type
        if featured:
            params["featured"] = "true"
        
        data = self._get(f"/project/{project_id}/version", params)
        return [ModrinthVersion.from_api(v) for v in data]

    def get_version(self, version_id: str) -> ModrinthVersion:
        """Get a specific version by ID."""
        data = self._get(f"/version/{version_id}")
        return ModrinthVersion.from_api(data)

    def get_version_files(self, version_id: str) -> List[ModrinthFile]:
        """Get files for a specific version."""
        version = self.get_version(version_id)
        files = []
        for f in version.files:
            files.append(ModrinthFile.from_api(f, version.project_id, version.id))
        return files

    def download_file(self, file: ModrinthFile, dest_path: Path, progress_callback=None) -> bool:
        """Download a file from Modrinth CDN."""
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            with self.session.get(file.url, stream=True, timeout=self.timeout) as response:
                response.raise_for_status()
                
                total_size = int(response.headers.get("content-length", file.size))
                downloaded = 0
                
                with open(dest_path, "wb") as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            if progress_callback:
                                progress_callback(downloaded, total_size)
                
                return True
        except Exception as e:
            print(f"Download failed: {e}")
            return False

    def get_multiple_projects(self, project_ids: List[str]) -> List[ModrinthProject]:
        """Get multiple projects by IDs (batch request)."""
        if not project_ids:
            return []
        
        data = self._post("/projects", {"ids": project_ids})
        return [ModrinthProject.from_api(p) for p in data.get("projects", [])]


class ModrinthManifestBuilder:
    """Builds our manifest format from Modrinth modpack data."""
    
    @staticmethod
    def build_manifest(
        project: ModrinthProject,
        version: ModrinthVersion,
        files: List[ModrinthFile]
    ) -> Dict[str, Any]:
        """Convert Modrinth modpack to our manifest format."""
        
        # Determine loader type and version
        loader_type = "vanilla"
        loader_version = ""
        
        for loader in version.loaders:
            if loader in ("fabric", "quilt"):
                loader_type = loader
            elif loader == "forge":
                loader_type = "forge"
            elif loader == "neoforge":
                loader_type = "neoforge"
        
        # Try to get loader version from dependencies
        for dep in version.dependencies:
            if dep.get("dependency_type") == "required" and dep.get("project_id"):
                dep_id = dep["project_id"]
                if "fabric" in dep_id.lower():
                    loader_type = "fabric"
                    loader_version = dep.get("version_id", "")
                elif "forge" in dep_id.lower():
                    loader_type = "forge"
                    loader_version = dep.get("version_id", "")
        
        # Build file list - only primary files or all files
        manifest_files = []
        for f in files:
            # Determine destination path based on file type
            dest_path = f"mods/{f.filename}"
            if f.filename.endswith(".jar"):
                dest_path = f"mods/{f.filename}"
            elif f.filename.endswith(".toml") or f.filename.endswith(".json"):
                dest_path = f"config/{f.filename}"
            
            manifest_files.append({
                "path": dest_path,
                "url": f.url,
                "sha1": f.hashes.get("sha1", ""),
                "size": f.size
            })
        
        # Determine Java version
        java_version = 17
        mc_version = version.game_versions[0] if version.game_versions else "1.20.1"
        if mc_version.startswith("1.18") or mc_version.startswith("1.19") or mc_version.startswith("1.20"):
            java_version = 17
        elif mc_version.startswith("1.16") or mc_version.startswith("1.17"):
            java_version = 8
        elif mc_version.startswith("1.21"):
            java_version = 21
        
        return {
            "id": f"modrinth-{project.slug}-{version.version_number}",
            "name": project.title,
            "version": version.version_number,
            "minecraftVersion": mc_version,
            "loader": {
                "type": loader_type,
                "version": loader_version
            },
            "javaVersion": java_version,
            "iconUrl": project.icon_url,
            "description": project.description,
            "minRamMb": 4096,
            "recommendedRamMb": 6144,
            "files": manifest_files
        }


class CurseForgeAPI:
    """
    Client for CurseForge API.
    Requires API key from https://console.curseforge.com/
    """
    
    BASE_URL = "https://api.curseforge.com/v1"
    
    def __init__(self, api_key: str = "", timeout: int = 30):
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/json",
            "User-Agent": "MelonLauncher/1.0"
        })
        if api_key:
            self.session.headers["x-api-key"] = api_key
        self.timeout = timeout

    def _get(self, endpoint: str, params: Dict = None) -> Dict:
        url = urljoin(self.BASE_URL, endpoint)
        response = self.session.get(url, params=params, timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def search_modpacks(
        self,
        game_id: int = 432,  # Minecraft
        category_id: int = 0,
        game_version: str = "",
        mod_loader: int = 0,
        search_filter: str = "",
        sort_field: int = 2,  # Popularity
        sort_order: str = "desc",
        page_size: int = 20,
        index: int = 0
    ) -> Dict:
        """Search for modpacks on CurseForge."""
        params = {
            "gameId": game_id,
            "categoryId": category_id,
            "gameVersion": game_version,
            "modLoaderType": mod_loader,
            "searchFilter": search_filter,
            "sortField": sort_field,
            "sortOrder": sort_order,
            "pageSize": page_size,
            "index": index
        }
        return self._get("/mods/search", params)

    def get_modpack(self, modpack_id: int) -> Dict:
        """Get a specific modpack by ID."""
        return self._get(f"/mods/{modpack_id}")

    def get_modpack_files(self, modpack_id: int) -> List[Dict]:
        """Get files for a modpack."""
        return self._get(f"/mods/{modpack_id}/files")

    def get_file(self, file_id: int) -> Dict:
        """Get file details including download URL."""
        return self._get(f"/mods/files/{file_id}")