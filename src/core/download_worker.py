import hashlib
import requests
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QThread, pyqtSignal

from core.manifest import Manifest, ManifestFile
from core.file_checker import FileChecker


class DownloadWorker(QThread):
    progress_changed = pyqtSignal(int)  # 0-100
    status_changed = pyqtSignal(str)
    file_progress = pyqtSignal(str, int, int)  # filename, current, total
    download_finished = pyqtSignal(bool, str)  # success, message
    error_occurred = pyqtSignal(str)

    def __init__(
        self,
        manifest: Manifest,
        base_path: Path,
        base_url: str = "",
        max_retries: int = 3,
        timeout: int = 30
    ):
        super().__init__()
        self.manifest = manifest
        self.base_path = Path(base_path)
        self.base_url = base_url
        self.max_retries = max_retries
        self.timeout = timeout
        self._cancelled = False
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "MelonLauncher/1.0"})
        self.file_checker = FileChecker(base_path)

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            self.status_changed.emit("Проверка файлов...")
            files_to_download = self.file_checker.get_files_to_download(self.manifest)

            if not files_to_download:
                self.progress_changed.emit(100)
                self.download_finished.emit(True, "Все файлы уже загружены")
                return

            total_files = len(files_to_download)
            total_size = sum(f.size for f in files_to_download)
            downloaded_size = 0

            self.status_changed.emit(f"Загрузка {total_files} файлов...")

            for i, manifest_file in enumerate(files_to_download):
                if self._cancelled:
                    self.download_finished.emit(False, "Загрузка отменена")
                    return

                self.status_changed.emit(f"[{i+1}/{total_files}] {manifest_file.path}")
                self.file_progress.emit(manifest_file.path, i, total_files)

                success = self._download_file(manifest_file)
                if not success:
                    self.download_finished.emit(False, f"Ошибка загрузки: {manifest_file.path}")
                    return

                downloaded_size += manifest_file.size
                progress = int((downloaded_size / total_size) * 100)
                self.progress_changed.emit(progress)

            # Verify all files after download
            self.status_changed.emit("Проверка целостности...")
            if self._verify_all():
                self.progress_changed.emit(100)
                self.download_finished.emit(True, "Загрузка завершена успешно")
            else:
                self.download_finished.emit(False, "Ошибка проверки файлов после загрузки")

        except Exception as e:
            self.error_occurred.emit(str(e))
            self.download_finished.emit(False, f"Критическая ошибка: {e}")

    def _download_file(self, manifest_file: ManifestFile) -> bool:
        local_path = self.base_path / manifest_file.path
        local_path.parent.mkdir(parents=True, exist_ok=True)

        url = manifest_file.url
        if not url.startswith(("http://", "https://")) and self.base_url:
            if self.base_url.endswith("/"):
                url = self.base_url + manifest_file.url
            else:
                url = self.base_url + "/" + manifest_file.url

        for attempt in range(self.max_retries):
            if self._cancelled:
                return False

            try:
                with self.session.get(url, stream=True, timeout=self.timeout) as response:
                    response.raise_for_status()

                    # Verify content length if provided
                    content_length = response.headers.get("Content-Length")
                    if content_length and int(content_length) != manifest_file.size:
                        self.status_changed.emit(
                            f"Предупреждение: размер не совпадает для {manifest_file.path}"
                        )

                    with open(local_path, "wb") as f:
                        for chunk in response.iter_content(chunk_size=8192):
                            if self._cancelled:
                                return False
                            if chunk:
                                f.write(chunk)

                # Verify SHA-1 after download
                if self._verify_file(local_path, manifest_file.sha1):
                    return True
                else:
                    self.status_changed.emit(
                        f"Хэш не совпадает, повторная попытка ({attempt + 1}/{self.max_retries})"
                    )
                    local_path.unlink(missing_ok=True)

            except requests.RequestException as e:
                self.status_changed.emit(
                    f"Ошибка сети ({attempt + 1}/{self.max_retries}): {e}"
                )
                if attempt == self.max_retries - 1:
                    return False

        return False

    def _verify_file(self, file_path: Path, expected_sha1: str) -> bool:
        try:
            actual_sha1 = self.file_checker.compute_sha1(file_path)
            return actual_sha1.lower() == expected_sha1.lower()
        except Exception:
            return False

    def _verify_all(self) -> bool:
        for manifest_file in self.manifest.files:
            local_path = self.base_path / manifest_file.path
            if not self._verify_file(local_path, manifest_file.sha1):
                return False
        return True