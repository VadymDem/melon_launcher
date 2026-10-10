import subprocess
import os
import json
import time
import threading
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, List, Dict, Any, Callable
from queue import Queue, Empty

import minecraft_launcher_lib.command as mcl_command
import minecraft_launcher_lib.utils as mcl_utils

from core.auth import AuthProfile
from core.java_manager import JavaInstallation
from core.manifest import Manifest


@dataclass
class LaunchConfig:
    """Configuration for launching Minecraft."""
    manifest: Manifest
    java_installation: JavaInstallation
    auth_profile: AuthProfile
    game_directory: Path
    jvm_args: List[str]
    custom_args: List[str] = None
    
    def __post_init__(self):
        if self.custom_args is None:
            self.custom_args = []


@dataclass
class LaunchResult:
    """Result of a launch attempt."""
    success: bool
    process: Optional[subprocess.Popen] = None
    error_message: str = ""
    command: List[str] = None


class LaunchManager:
    """
    Builds and executes Minecraft launch command using minecraft-launcher-lib.
    Handles all the complex argument construction for different loaders (Vanilla/Forge/Fabric).
    """
    
    def __init__(self):
        self._last_command: List[str] = []
        self._last_config: Optional[LaunchConfig] = None

    def build_command(self, config: LaunchConfig) -> List[str]:
        """
        Build the Minecraft launch command using minecraft-launcher-lib.
        Returns the command as a list of strings ready for subprocess.Popen.
        """
        self._last_config = config
        
        # Prepare the game directory
        game_dir = config.game_directory
        game_dir.mkdir(parents=True, exist_ok=True)
        
        # Determine the Minecraft version from manifest
        mc_version = config.manifest.minecraft_version
        loader_type = config.manifest.loader.type.lower()
        loader_version = config.manifest.loader.version
        
        # Build the version identifier for minecraft-launcher-lib
        # For modded versions, we need to use the correct format
        if loader_type == "forge":
            version_id = f"{mc_version}-forge-{loader_version}"
        elif loader_type == "fabric":
            version_id = f"{mc_version}-fabric-{loader_version}"
        elif loader_type == "quilt":
            version_id = f"{mc_version}-quilt-{loader_version}"
        elif loader_type == "neoforge":
            version_id = f"{mc_version}-neoforge-{loader_version}"
        else:
            version_id = mc_version
        
        # Prepare auth data for minecraft-launcher-lib
        auth_data = {
            "username": config.auth_profile.username,
            "uuid": config.auth_profile.uuid,
            "token": config.auth_profile.token,
        }
        
        # Add user properties for Microsoft accounts
        if config.auth_profile.auth_type == "microsoft" and config.auth_profile.user_properties:
            auth_data["user_properties"] = config.auth_profile.user_properties
        
        # Build jvm arguments
        jvm_args = config.jvm_args.copy()
        
        # Add custom JVM args from config
        jvm_args.extend(config.custom_args)
        
        # Get the command from minecraft-launcher-lib
        try:
            command = mcl_command.get_minecraft_command(
                version=version_id,
                minecraft_directory=str(game_dir),
                options={
                    "username": config.auth_profile.username,
                    "uuid": config.auth_profile.uuid,
                    "token": config.auth_profile.token,
                    "executablePath": str(config.java_installation.path),
                    "jvmArguments": jvm_args,
                    "gameDirectory": str(game_dir),
                    "customResolution": True,
                    "resolutionWidth": "854",
                    "resolutionHeight": "480",
                    "server": "",
                    "port": "",
                }
            )
            
            self._last_command = command
            return command
            
        except Exception as e:
            raise RuntimeError(f"Failed to build launch command: {e}")

    def get_last_command(self) -> List[str]:
        """Get the last built command for debugging."""
        return self._last_command.copy()

    def build_offline_command(self, config: LaunchConfig) -> List[str]:
        """
        Build command for offline mode (simpler, no auth validation).
        """
        # For offline, token should be "0" or empty
        config.auth_profile.token = "0"
        return self.build_command(config)

    def validate_launch_requirements(self, config: LaunchConfig) -> tuple[bool, str]:
        """
        Validate that all requirements for launch are met.
        Returns (is_valid, error_message).
        """
        # Check Java
        if not config.java_installation or not config.java_installation.is_valid:
            return False, "Java installation is not valid or not found"
        
        if not config.java_installation.path.exists():
            return False, f"Java executable not found: {config.java_installation.path}"
        
        # Check game directory
        if not config.game_directory.exists():
            try:
                config.game_directory.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                return False, f"Cannot create game directory: {e}"
        
        # Check manifest
        if not config.manifest:
            return False, "No manifest provided"
        
        # Check auth profile
        if not config.auth_profile or not config.auth_profile.is_valid():
            return False, "Invalid authentication profile"
        
        # For Microsoft auth, check token expiry
        if config.auth_profile.auth_type == "microsoft" and config.auth_profile.is_expired():
            return False, "Microsoft token has expired, please re-login"
        
        return True, ""

    def create_libraries_json(self, manifest: Manifest, game_dir: Path) -> Path:
        """
        Create libraries.json for custom modpack if needed.
        This is used by minecraft-launcher-lib for Forge/Fabric.
        """
        libraries_file = game_dir / "libraries.json"
        
        # Build libraries list from manifest files
        libraries = []
        for mf in manifest.files:
            if mf.path.endswith(".jar"):
                libraries.append({
                    "name": f"custom:{mf.path}:{manifest.version}",
                    "url": mf.url,
                    "downloads": {
                        "artifact": {
                            "url": mf.url,
                            "sha1": mf.sha1,
                            "size": mf.size
                        }
                    }
                })
        
        libraries_data = {"libraries": libraries}
        
        with open(libraries_file, "w", encoding="utf-8") as f:
            json.dump(libraries_data, f, indent=2)
        
        return libraries_file


class GameProcessHandler:
    """
    Manages the Minecraft game process:
    - Starts process with stdout/stderr capture
    - Logs output to file and callback
    - Monitors for crashes
    - Handles window minimize/restore
    """
    
    def __init__(
        self,
        on_output: Optional[Callable[[str], None]] = None,
        on_crash: Optional[Callable[[int, str], None]] = None,
        on_exit: Optional[Callable[[int], None]] = None,
        on_started: Optional[Callable[[int], None]] = None,
        log_file: Optional[Path] = None
    ):
        self.on_output = on_output
        self.on_crash = on_crash
        self.on_exit = on_exit
        self.on_started = on_started
        self.log_file = log_file
        
        self._process: Optional[subprocess.Popen] = None
        self._output_thread: Optional[threading.Thread] = None
        self._error_thread: Optional[threading.Thread] = None
        self._monitor_thread: Optional[threading.Thread] = None
        self._running = False
        self._output_queue = Queue()
        self._error_queue = Queue()
        self._log_handle = None
        self._pid = None

    def start(self, command: List[str], cwd: Path, env: Dict[str, str] = None) -> bool:
        """
        Start the game process.
        Returns True if started successfully.
        """
        if self._running:
            return False
        
        # Prepare environment
        process_env = os.environ.copy()
        if env:
            process_env.update(env)
        
        # Open log file if specified
        if self.log_file:
            self.log_file.parent.mkdir(parents=True, exist_ok=True)
            self._log_handle = open(self.log_file, "w", encoding="utf-8", buffering=1)
            self._write_log(f"=== Launching Minecraft ===\nCommand: {' '.join(command)}\nCWD: {cwd}\n\n")
        
        try:
            # Start process
            self._process = subprocess.Popen(
                command,
                cwd=str(cwd),
                env=process_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE,
                text=True,
                bufsize=1,  # Line buffered
                encoding="utf-8",
                errors="replace"
            )
            
            self._pid = self._process.pid
            self._running = True
            
            self._write_log(f"Process started with PID: {self._pid}\n\n")
            
            # Start output reader threads
            self._output_thread = threading.Thread(target=self._read_stdout, daemon=True)
            self._error_thread = threading.Thread(target=self._read_stderr, daemon=True)
            self._monitor_thread = threading.Thread(target=self._monitor_process, daemon=True)
            
            self._output_thread.start()
            self._error_thread.start()
            self._monitor_thread.start()
            
            # Notify started
            if self.on_started:
                self.on_started(self._pid)
            
            return True
            
        except Exception as e:
            self._write_log(f"Failed to start process: {e}\n")
            self._cleanup()
            return False

    def _read_stdout(self):
        """Read stdout from process."""
        try:
            for line in iter(self._process.stdout.readline, ""):
                if not self._running:
                    break
                line = line.rstrip("\n")
                self._output_queue.put(("stdout", line))
        except Exception as e:
            self._output_queue.put(("error", f"Stdout read error: {e}"))

    def _read_stderr(self):
        """Read stderr from process."""
        try:
            for line in iter(self._process.stderr.readline, ""):
                if not self._running:
                    break
                line = line.rstrip("\n")
                self._output_queue.put(("stderr", line))
        except Exception as e:
            self._output_queue.put(("error", f"Stderr read error: {e}"))

    def _monitor_process(self):
        """Monitor process for exit/crash."""
        try:
            return_code = self._process.wait()
            self._running = False
            
            # Wait for reader threads to finish
            self._output_thread.join(timeout=2)
            self._error_thread.join(timeout=2)
            
            # Process remaining output
            self._drain_queues()
            
            self._write_log(f"\n=== Process exited with code: {return_code} ===\n")
            
            # Determine if crash or normal exit
            is_crash = return_code != 0
            
            if is_crash and self.on_crash:
                # Get last few lines of error output for crash report
                error_lines = self._get_recent_errors()
                self.on_crash(return_code, error_lines)
            elif self.on_exit:
                self.on_exit(return_code)
                
        except Exception as e:
            self._write_log(f"Monitor error: {e}\n")
            if self.on_crash:
                self.on_crash(-1, f"Monitor error: {e}")
        finally:
            self._cleanup()

    def _drain_queues(self):
        """Process any remaining queued output."""
        while True:
            try:
                stream, line = self._output_queue.get_nowait()
                self._handle_output(stream, line)
            except Empty:
                break
            
            try:
                stream, line = self._error_queue.get_nowait()
                self._handle_output(stream, line)
            except Empty:
                break

    def _handle_output(self, stream: str, line: str):
        """Handle a line of output."""
        # Write to log
        prefix = "OUT" if stream == "stdout" else "ERR"
        self._write_log(f"[{prefix}] {line}\n")
        
        # Call output callback
        if self.on_output:
            self.on_output(f"[{prefix}] {line}")

    def _get_recent_errors(self, count: int = 50) -> str:
        """Get recent error lines for crash report."""
        # This would ideally read from log file
        if self.log_file and self.log_file.exists():
            try:
                with open(self.log_file, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                    return "".join(lines[-count:])
            except Exception:
                pass
        return "Error log not available"

    def _write_log(self, message: str):
        """Write to log file."""
        if self._log_handle:
            try:
                self._log_handle.write(message)
                self._log_handle.flush()
            except Exception:
                pass

    def _cleanup(self):
        """Cleanup resources."""
        self._running = False
        
        if self._log_handle:
            try:
                self._log_handle.close()
            except Exception:
                pass
            self._log_handle = None

    def stop(self, timeout: float = 10.0) -> bool:
        """
        Stop the game process gracefully.
        Returns True if stopped successfully.
        """
        if not self._process or not self._running:
            return True
        
        try:
            self._write_log("\n=== Stopping process ===\n")
            
            # Try graceful termination
            self._process.terminate()
            
            # Wait for exit
            try:
                self._process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                # Force kill
                self._write_log("Process did not terminate, killing...\n")
                self._process.kill()
                self._process.wait(timeout=5)
            
            self._running = False
            return True
            
        except Exception as e:
            self._write_log(f"Error stopping process: {e}\n")
            return False

    def is_running(self) -> bool:
        """Check if process is still running."""
        return self._running and self._process and self._process.poll() is None

    def get_pid(self) -> Optional[int]:
        """Get process PID."""
        return self._pid

    def send_input(self, text: str) -> bool:
        """Send input to game stdin."""
        if self._process and self._process.stdin:
            try:
                self._process.stdin.write(text + "\n")
                self._process.stdin.flush()
                return True
            except Exception:
                pass
        return False


class LaunchController:
    """
    High-level controller that orchestrates the launch sequence:
    1. Validate requirements
    2. Ensure Java
    3. Check/download game files
    4. Build command
    5. Launch process
    6. Monitor
    """
    
    def __init__(
        self,
        java_manager,
        manifest_manager,
        file_checker,
        download_worker_class,
        launch_manager: LaunchManager
    ):
        self.java_manager = java_manager
        self.manifest_manager = manifest_manager
        self.file_checker = file_checker
        self.download_worker_class = download_worker_class
        self.launch_manager = launch_manager
        
        self._process_handler: Optional[GameProcessHandler] = None
        self._download_worker = None

    def launch(
        self,
        manifest: Manifest,
        auth_profile: AuthProfile,
        game_directory: Path,
        java_version: int,
        jvm_args: List[str],
        custom_args: List[str],
        on_progress: Callable[[int, str], None],
        on_started: Callable[[int], None],
        on_crash: Callable[[int, str], None],
        on_exit: Callable[[int], None],
        on_log: Callable[[str], None]
    ) -> bool:
        """
        Execute full launch sequence.
        Returns True if launch initiated successfully.
        """
        try:
            on_progress(0, "Проверка требований...")
            
            # 1. Ensure Java
            on_progress(10, f"Проверка Java {java_version}...")
            java_install = self.java_manager.ensure_java(java_version)
            if not java_install.is_valid:
                raise RuntimeError(f"Java {java_version} unavailable: {java_install.error}")
            
            # 2. Check game files
            on_progress(20, "Проверка файлов игры...")
            checker = self.file_checker(game_directory)
            files_to_download = checker.get_files_to_download(manifest)
            
            if files_to_download:
                on_progress(30, f"Загрузка {len(files_to_download)} файлов...")
                # Note: In real implementation, we'd wait for download worker
                # For now, we'll proceed assuming files exist or will be downloaded
                pass
            
            # 3. Build launch config
            on_progress(50, "Подготовка команды запуска...")
            launch_config = LaunchConfig(
                manifest=manifest,
                java_installation=java_install,
                auth_profile=auth_profile,
                game_directory=game_directory,
                jvm_args=jvm_args,
                custom_args=custom_args
            )
            
            # Validate
            valid, error = self.launch_manager.validate_launch_requirements(launch_config)
            if not valid:
                raise RuntimeError(f"Launch validation failed: {error}")
            
            # 4. Build command
            on_progress(70, "Сборка команды запуска...")
            command = self.launch_manager.build_command(launch_config)
            
            on_progress(90, "Запуск игры...")
            
            # 5. Create log file
            log_file = game_directory / "logs" / f"latest.log"
            
            # 6. Start process handler
            self._process_handler = GameProcessHandler(
                on_output=on_log,
                on_crash=on_crash,
                on_exit=on_exit,
                on_started=on_started,
                log_file=log_file
            )
            
            success = self._process_handler.start(command, cwd=game_directory)
            
            if success:
                on_progress(100, "Игра запущена")
                return True
            else:
                raise RuntimeError("Failed to start game process")
                
        except Exception as e:
            on_progress(-1, f"Ошибка: {e}")
            return False

    def stop_game(self, timeout: float = 10.0) -> bool:
        """Stop the running game."""
        if self._process_handler:
            return self._process_handler.stop(timeout)
        return True

    def is_game_running(self) -> bool:
        """Check if game is running."""
        return self._process_handler and self._process_handler.is_running()