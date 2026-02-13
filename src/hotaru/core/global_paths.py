"""Global XDG-compliant directory paths for Hotaru Code.

This module manages application directories following XDG Base Directory specifications,
with automatic directory creation and cache versioning.
"""

import os
import shutil
from pathlib import Path
from platformdirs import user_data_dir, user_cache_dir, user_config_dir, user_state_dir

APP_NAME = "hotaru-code"
CACHE_VERSION = "1"


class GlobalPath:
    """Global path management for Hotaru Code directories."""

    _initialized = False

    @classmethod
    def home(cls) -> str:
        """Get user home directory, with override for testing."""
        return os.environ.get("HOTARU_TEST_HOME", str(Path.home()))

    @classmethod
    def data(cls) -> str:
        """Application data directory."""
        return user_data_dir(APP_NAME)

    @classmethod
    def bin(cls) -> str:
        """Binary/executable storage directory."""
        return str(Path(cls.data()) / "bin")

    @classmethod
    def log(cls) -> str:
        """Log file directory."""
        return str(Path(cls.data()) / "log")

    @classmethod
    def cache(cls) -> str:
        """Cache directory."""
        return user_cache_dir(APP_NAME)

    @classmethod
    def config(cls) -> str:
        """Configuration directory."""
        return user_config_dir(APP_NAME)

    @classmethod
    def state(cls) -> str:
        """State/runtime data directory."""
        return user_state_dir(APP_NAME)

    @classmethod
    def initialize(cls) -> None:
        """Create all required directories and handle cache versioning."""
        if cls._initialized:
            return

        # Create all directories
        for path in [cls.data(), cls.config(), cls.state(), cls.log(), cls.bin()]:
            Path(path).mkdir(parents=True, exist_ok=True)

        # Handle cache versioning - clear old cache if version changed
        cache_path = Path(cls.cache())
        cache_path.mkdir(parents=True, exist_ok=True)

        version_file = cache_path / "version"
        try:
            current_version = version_file.read_text().strip()
        except FileNotFoundError:
            current_version = "0"

        if current_version != CACHE_VERSION:
            # Clear old cache contents
            for item in cache_path.iterdir():
                try:
                    if item.is_file():
                        item.unlink()
                    elif item.is_dir():
                        shutil.rmtree(item)
                except Exception:
                    pass

            # Write new version
            version_file.write_text(CACHE_VERSION)

        cls._initialized = True


# Initialize directories on module import
GlobalPath.initialize()
