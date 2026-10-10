from dataclasses import dataclass
from typing import List, Optional


@dataclass
class JVMConfig:
    """Configuration for JVM arguments."""
    java_path: str
    min_ram_mb: int
    max_ram_mb: int
    main_class: str
    classpath: List[str]
    jvm_args: List[str]
    mc_args: List[str]
    
    def to_command_list(self) -> List[str]:
        """Convert to command list for subprocess."""
        cmd = [self.java_path]
        cmd.extend(self.jvm_args)
        cmd.extend([
            f"-Xms{self.min_ram_mb}M",
            f"-Xmx{self.max_ram_mb}M"
        ])
        cmd.extend(["-cp", os.pathsep.join(self.classpath), self.main_class])
        cmd.extend(self.mc_args)
        return cmd
    
    def to_command_string(self) -> str:
        """Convert to command string for display."""
        import shlex
        return " ".join(shlex.quote(arg) for arg in self.to_command_list())


import os


class JVMConfigBuilder:
    """
    Builds JVM arguments for Minecraft launch.
    Includes memory settings, GC flags, and optimization flags.
    """
    
    # Default G1GC flags for Minecraft
    DEFAULT_G1GC_FLAGS = [
        "-XX:+UseG1GC",
        "-XX:+ParallelRefProcEnabled",
        "-XX:MaxGCPauseMillis=200",
        "-XX:+UnlockExperimentalVMOptions",
        "-XX:+DisableExplicitGC",
        "-XX:+AlwaysPreTouch",
        "-XX:G1NewSizePercent=30",
        "-XX:G1MaxNewSizePercent=40",
        "-XX:G1HeapRegionSize=8M",
        "-XX:G1ReservePercent=20",
        "-XX:G1HeapWastePercent=5",
        "-XX:G1MixedGCCountTarget=4",
        "-XX:InitiatingHeapOccupancyPercent=15",
        "-XX:G1MixedGCLiveThresholdPercent=90",
        "-XX:G1RSetUpdatingPauseTimePercent=5",
        "-XX:SurvivorRatio=32",
        "-XX:+PerfDisableSharedMem",
        "-XX:MaxTenuringThreshold=1",
    ]
    
    # Additional flags for better performance
    PERFORMANCE_FLAGS = [
        "-Dfml.ignoreInvalidMinecraftCertificates=true",
        "-Dfml.ignorePatchDiscrepancies=true",
        "-Djava.net.preferIPv4Stack=true",
    ]
    
    # Memory-related flags
    MEMORY_FLAGS_TEMPLATE = [
        "-Xms{min_ram}M",
        "-Xmx{max_ram}M",
    ]

    def __init__(
        self,
        min_ram_mb: int = 1024,
        max_ram_mb: int = 2048,
        use_g1gc: bool = True,
        custom_jvm_args: Optional[List[str]] = None
    ):
        self.min_ram_mb = min_ram_mb
        self.max_ram_mb = max_ram_mb
        self.use_g1gc = use_g1gc
        self.custom_jvm_args = custom_jvm_args or []

    def validate_ram(self, min_ram_mb: int, max_ram_mb: int, total_system_ram_mb: int) -> tuple[bool, str]:
        """
        Validate RAM settings.
        Returns (is_valid, error_message).
        """
        if min_ram_mb < 512:
            return False, "Минимальная память должна быть не менее 512 МБ"
        
        if max_ram_mb < min_ram_mb:
            return False, "Максимальная память должна быть больше или равна минимальной"
        
        if max_ram_mb > total_system_ram_mb * 0.9:
            return False, f"Максимальная память не должна превышать 90% системной памяти ({total_system_ram_mb} МБ)"
        
        if max_ram_mb > total_system_ram_mb - 1024:
            return False, f"Оставьте минимум 1 ГБ для системы (доступно: {total_system_ram_mb - 1024} МБ)"
        
        return True, ""

    def build_jvm_args(self, total_system_ram_mb: int = None) -> List[str]:
        """Build complete JVM argument list."""
        if total_system_ram_mb is None:
            import psutil
            total_system_ram_mb = psutil.virtual_memory().total // (1024 * 1024)
        
        # Validate
        valid, error = self.validate_ram(self.min_ram_mb, self.max_ram_mb, total_system_ram_mb)
        if not valid:
            raise ValueError(f"RAM validation failed: {error}")
        
        args = []
        
        # Memory flags
        args.append(f"-Xms{self.min_ram_mb}M")
        args.append(f"-Xmx{self.max_ram_mb}M")
        
        # GC flags
        if self.use_g1gc:
            args.extend(self.DEFAULT_G1GC_FLAGS)
        
        # Performance flags
        args.extend(self.PERFORMANCE_FLAGS)
        
        # Custom user args (added last to allow override)
        args.extend(self.custom_jvm_args)
        
        return args

    def build_config(
        self,
        java_path: str,
        main_class: str,
        classpath: List[str],
        mc_args: List[str],
        total_system_ram_mb: int = None
    ) -> JVMConfig:
        """Build complete JVMConfig."""
        jvm_args = self.build_jvm_args(total_system_ram_mb)
        
        return JVMConfig(
            java_path=java_path,
            min_ram_mb=self.min_ram_mb,
            max_ram_mb=self.max_ram_mb,
            main_class=main_class,
            classpath=classpath,
            jvm_args=jvm_args,
            mc_args=mc_args
        )

    @classmethod
    def from_config(cls, config, total_system_ram_mb: int = None) -> "JVMConfigBuilder":
        """Create builder from launcher config."""
        import psutil
        if total_system_ram_mb is None:
            total_system_ram_mb = psutil.virtual_memory().total // (1024 * 1024)
        
        # Clamp RAM to valid range
        max_allowed = int(total_system_ram_mb * 0.85)
        max_ram = min(config.ram_mb, max_allowed)
        min_ram = min(1024, max_ram // 2)
        
        return cls(
            min_ram_mb=min_ram,
            max_ram_mb=max_ram,
            use_g1gc=True
        )


def parse_jvm_args(args_string: str) -> List[str]:
    """Parse JVM args string into list, respecting quotes."""
    import shlex
    try:
        return shlex.split(args_string)
    except ValueError:
        # Fallback: simple split
        return args_string.split()


def format_jvm_args(args: List[str]) -> str:
    """Format JVM args list into string for display."""
    import shlex
    return " ".join(shlex.quote(arg) for arg in args)