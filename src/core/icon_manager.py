import requests
from pathlib import Path
from typing import Optional, Callable
from PyQt6.QtGui import QPixmap, QImage
from PyQt6.QtCore import QThread, pyqtSignal, QByteArray
import hashlib


class IconManager:
    """
    Manages downloading and caching of icons for builds/profiles.
    """
    
    def __init__(self, cache_dir: Path):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "MelonLauncher/1.0"})
        self._memory_cache = {}  # url -> QPixmap

    def get_icon_path(self, url: str) -> Path:
        """Get local cache path for icon URL."""
        # Create deterministic filename from URL
        url_hash = hashlib.sha256(url.encode()).hexdigest()[:16]
        ext = Path(url).suffix or ".png"
        return self.cache_dir / f"{url_hash}{ext}"

    def download_icon(self, url: str, progress_callback: Optional[Callable[[int, int], None]] = None) -> Optional[Path]:
        """Download icon to cache. Returns local path or None on failure."""
        if not url:
            return None
        
        local_path = self.get_icon_path(url)
        
        # Return cached if exists
        if local_path.exists():
            return local_path
        
        try:
            response = self.session.get(url, stream=True, timeout=30)
            response.raise_for_status()
            
            total_size = int(response.headers.get("content-length", 0))
            downloaded = 0
            
            with open(local_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if progress_callback:
                            progress_callback(downloaded, total_size)
            
            return local_path
            
        except Exception as e:
            print(f"Failed to download icon: {e}")
            if local_path.exists():
                local_path.unlink(missing_ok=True)
            return None

    def load_icon(self, url: str, size: tuple = (180, 180)) -> Optional[QPixmap]:
        """Load icon from cache or download, return QPixmap."""
        if not url:
            return None
        
        # Check memory cache first
        cache_key = f"{url}_{size[0]}x{size[1]}"
        if cache_key in self._memory_cache:
            return self._memory_cache[cache_key]
        
        local_path = self.get_icon_path(url)
        
        # Download if not cached
        if not local_path.exists():
            local_path = self.download_icon(url)
            if not local_path:
                return None
        
        # Load and scale
        try:
            pixmap = QPixmap(str(local_path))
            if pixmap.isNull():
                return None
            
            # Scale maintaining aspect ratio
            scaled = pixmap.scaled(
                size[0], size[1],
                aspectRatioMode=1,  # Qt.KeepAspectRatio
                transformMode=1  # Qt.SmoothTransformation
            )
            
            self._memory_cache[cache_key] = scaled
            return scaled
            
        except Exception as e:
            print(f"Failed to load icon: {e}")
            return None

    def load_icon_async(self, url: str, size: tuple, callback: Callable[[Optional[QPixmap]], None]):
        """Load icon in background thread."""
        worker = IconDownloadWorker(self, url, size)
        worker.finished.connect(callback)
        worker.start()


class IconDownloadWorker(QThread):
    """Worker thread for downloading and loading icons."""
    
    finished = pyqtSignal(object)  # QPixmap or None
    
    def __init__(self, icon_manager: IconManager, url: str, size: tuple):
        super().__init__()
        self.setObjectName(f"IconDownloadWorker-{url}")
        self.icon_manager = icon_manager
        self.url = url
        self.size = size
    
    def run(self):
        pixmap = self.icon_manager.load_icon(self.url, self.size)
        self.finished.emit(pixmap)


class BuildIconWidget:
    """Mixin/widget for displaying build icons with async loading."""
    
    def __init__(self, icon_manager: IconManager):
        self.icon_manager = icon_manager
        self._current_url = ""
        self._target_size = (180, 180)
    
    def set_icon(self, url: str, placeholder: Optional[QPixmap] = None):
        """Set icon URL and start async load."""
        self._current_url = url
        
        # Set placeholder immediately
        if placeholder:
            self._set_pixmap(placeholder)
        else:
            self._set_placeholder()
        
        if not url:
            return
        
        # Load asynchronously
        self.icon_manager.load_icon_async(
            url, 
            self._target_size,
            self._on_icon_loaded
        )
    
    def _on_icon_loaded(self, pixmap: Optional[QPixmap]):
        """Callback when icon is loaded."""
        if pixmap and self._current_url == self.url:
            self._set_pixmap(pixmap)
    
    def _set_pixmap(self, pixmap: QPixmap):
        """Override in subclass to set pixmap on actual widget."""
        pass
    
    def _set_placeholder(self):
        """Override in subclass to show placeholder."""
        pass


def create_placeholder_icon(size: tuple = (180, 180), text: str = "ICON") -> QPixmap:
    """Create a placeholder icon with text."""
    from PyQt6.QtGui import QPixmap, QPainter, QColor, QFont
    from PyQt6.QtCore import Qt
    
    w, h = size
    pixmap = QPixmap(w, h)
    pixmap.fill(QColor("#313244"))
    
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QColor("#6c7086"))
    painter.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
    painter.drawText(0, 0, w, h, Qt.AlignmentFlag.AlignCenter, text)
    painter.end()
    
    return pixmap