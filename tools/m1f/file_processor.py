"""
File processor module for gathering and filtering files.
"""

from __future__ import annotations

import asyncio
import glob
import os
from pathlib import Path
from typing import List, Tuple, Set, Optional

import pathspec

from .config import Config
from .constants import DEFAULT_EXCLUDED_DIRS, DEFAULT_EXCLUDED_FILES, MAX_SYMLINK_DEPTH
from .exceptions import FileNotFoundError, ValidationError
from .logging import LoggerManager
from .utils import is_binary_file, is_hidden_path, get_relative_path, format_file_size


class FileProcessor:
    """Handles file discovery and filtering."""

    def __init__(self, config: Config, logger_manager: LoggerManager):
        self.config = config
        self.logger = logger_manager.get_logger(__name__)
        self._symlink_visited: Set[str] = set()
        self._processed_files: Set[str] = set()

        # Build exclusion sets
        self._build_exclusion_sets()

    def _build_exclusion_sets(self) -> None:
        """Build the exclusion sets from configuration."""
        # Directory exclusions
        self.excluded_dirs = set()
        if not self.config.filter.no_default_excludes:
            self.excluded_dirs = {d.lower() for d in DEFAULT_EXCLUDED_DIRS}

        # Add user-specified exclusions
        for pattern in self.config.filter.exclude_patterns:
            if "/" not in pattern and "*" not in pattern and "?" not in pattern:
                self.excluded_dirs.add(pattern.lower())

        # File exclusions
        self.excluded_files = set()
        if not self.config.filter.no_default_excludes:
            self.excluded_files = DEFAULT_EXCLUDED_FILES.copy()

        # Load exclusions from file
        self.exact_excludes = set()
        self.gitignore_spec = None

        if self.config.filter.exclude_paths_file:
            self._load_exclude_patterns()

        # Build gitignore spec from command-line patterns
        self._build_gitignore_spec()

    def _load_exclude_patterns(self) -> None:
        """Load exclusion patterns from file."""
        exclude_file = self.config.filter.exclude_paths_file

        if not exclude_file.exists():
            self.logger.warning(f"Exclude file not found: {exclude_file}")
            return

        try:
            with open(exclude_file, "r", encoding="utf-8") as f:
                lines = [
                    line.strip()
                    for line in f
                    if line.strip() and not line.strip().startswith("#")
                ]

            # Detect if it's gitignore format
            is_gitignore = exclude_file.name == ".gitignore" or any(
                any(ch in line for ch in ["*", "?", "!"]) or line.endswith("/")
                for line in lines
            )

            if is_gitignore:
                self.logger.info(f"Processing {exclude_file} as gitignore format")
                self.gitignore_spec = pathspec.PathSpec.from_lines(
                    "gitwildmatch", lines
                )
            else:
                self.logger.info(f"Processing {exclude_file} as exact path list")
                self.exact_excludes = {Path(line) for line in lines}

        except Exception as e:
            self.logger.error(f"Error loading exclude patterns: {e}")

    def _build_gitignore_spec(self) -> None:
        """Build gitignore spec from command-line patterns."""
        patterns = []

        for pattern in self.config.filter.exclude_patterns:
            if any(ch in pattern for ch in ["*", "?", "!"]) or pattern.endswith("/"):
                patterns.append(pattern)

        if patterns:
            try:
                spec = pathspec.PathSpec.from_lines("gitwildmatch", patterns)
                if self.gitignore_spec:
                    # Combine with existing spec
                    all_patterns = list(self.gitignore_spec.patterns) + list(
                        spec.patterns
                    )
                    self.gitignore_spec = pathspec.PathSpec(all_patterns)
                else:
                    self.gitignore_spec = spec
            except Exception as e:
                self.logger.error(f"Error building gitignore spec: {e}")

    async def gather_files(self) -> List[Tuple[Path, str]]:
        """Gather all files to process based on configuration."""
        files_to_process = []

        if self.config.input_file:
            # Process from input file
            input_paths = await self._process_input_file()
            files_to_process = await self._gather_from_paths(input_paths)
        elif self.config.source_directory:
            # Process from source directory
            files_to_process = await self._gather_from_directory(
                self.config.source_directory
            )
        else:
            raise ValidationError("No source directory or input file specified")

        # Sort by relative path
        files_to_process.sort(key=lambda x: x[1].lower())

        return files_to_process

    async def _process_input_file(self) -> List[Path]:
        """Process input file and return list of paths."""
        input_file = self.config.input_file
        paths = []

        base_dir = self.config.source_directory or input_file.parent

        try:
            with open(input_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue

                    # Handle glob patterns
                    if any(ch in line for ch in ["*", "?", "["]):
                        pattern_path = Path(line)
                        if not pattern_path.is_absolute():
                            pattern_path = base_dir / pattern_path

                        matches = glob.glob(str(pattern_path), recursive=True)
                        paths.extend(Path(m).resolve() for m in matches)
                    else:
                        path = Path(line)
                        if not path.is_absolute():
                            path = base_dir / path
                        paths.append(path.resolve())

            # Deduplicate paths
            paths = self._deduplicate_paths(paths)

            self.logger.info(f"Found {len(paths)} paths from input file")
            return paths

        except Exception as e:
            raise FileNotFoundError(f"Error processing input file: {e}")

    def _deduplicate_paths(self, paths: List[Path]) -> List[Path]:
        """Remove paths that are children of other paths in the list."""
        if not paths:
            return []

        # Sort by path depth
        paths.sort(key=lambda p: len(p.parts))

        # Keep only paths that aren't children of others
        keep_paths = set(paths)

        for i, path in enumerate(paths):
            if path not in keep_paths:
                continue

            for other_path in paths[i + 1 :]:
                try:
                    if other_path.is_relative_to(path):
                        keep_paths.discard(other_path)
                except (ValueError, RuntimeError):
                    continue

        return sorted(keep_paths)

    async def _gather_from_paths(self, paths: List[Path]) -> List[Tuple[Path, str]]:
        """Gather files from a list of paths."""
        files = []

        for path in paths:
            if not path.exists():
                self.logger.warning(f"Path not found: {path}")
                continue

            if path.is_file():
                if await self._should_include_file(path, explicitly_included=True):
                    rel_path = get_relative_path(
                        path, self.config.source_directory or path.parent
                    )
                    files.append((path, rel_path))
            elif path.is_dir():
                dir_files = await self._gather_from_directory(
                    path, explicitly_included=True
                )
                files.extend(dir_files)

        return files

    async def _gather_from_directory(
        self, directory: Path, explicitly_included: bool = False
    ) -> List[Tuple[Path, str]]:
        """Recursively gather files from a directory."""
        files = []

        # Use os.walk for efficiency
        for root, dirs, filenames in os.walk(
            directory, followlinks=self.config.filter.include_symlinks
        ):
            root_path = Path(root)

            # Filter directories
            dirs[:] = await self._filter_directories(root_path, dirs)

            # Process files
            for filename in filenames:
                file_path = root_path / filename

                if await self._should_include_file(file_path, explicitly_included):
                    rel_path = get_relative_path(
                        file_path, self.config.source_directory or directory
                    )

                    # Check for duplicates
                    dedup_key = str(file_path.resolve())
                    if dedup_key not in self._processed_files:
                        files.append((file_path, rel_path))
                        self._processed_files.add(dedup_key)

        return files

    async def _filter_directories(self, root: Path, dirs: List[str]) -> List[str]:
        """Filter directories based on exclusion rules."""
        filtered = []

        for dirname in dirs:
            dir_path = root / dirname

            # Check if directory is excluded
            if dirname.lower() in self.excluded_dirs:
                continue

            # Check dot directories
            if not self.config.filter.include_dot_paths and dirname.startswith("."):
                continue

            # Check symlinks
            if dir_path.is_symlink():
                if not self.config.filter.include_symlinks:
                    continue

                # Check for cycles
                if self._detect_symlink_cycle(dir_path):
                    self.logger.warning(f"Skipping symlink cycle: {dir_path}")
                    continue

            filtered.append(dirname)

        return filtered

    async def _should_include_file(
        self, file_path: Path, explicitly_included: bool = False
    ) -> bool:
        """Check if a file should be included based on filters."""
        # Check if file exists
        if not file_path.exists():
            return False

        # Check exact excludes
        if str(file_path) in self.exact_excludes:
            return False

        # Check filename excludes
        if file_path.name in self.excluded_files:
            return False

        # Check gitignore patterns
        if self.gitignore_spec:
            rel_path = get_relative_path(
                file_path, self.config.source_directory or file_path.parent
            )
            if self.gitignore_spec.match_file(rel_path):
                return False

        # Check dot files
        if not explicitly_included and not self.config.filter.include_dot_paths:
            if is_hidden_path(file_path):
                return False

        # Check binary files
        if not self.config.filter.include_binary_files:
            if is_binary_file(file_path):
                return False

        # Check extensions
        if self.config.filter.include_extensions:
            if file_path.suffix.lower() not in self.config.filter.include_extensions:
                return False

        if self.config.filter.exclude_extensions:
            if file_path.suffix.lower() in self.config.filter.exclude_extensions:
                return False

        # Check symlinks
        if file_path.is_symlink():
            if not self.config.filter.include_symlinks:
                return False

            if self._detect_symlink_cycle(file_path):
                return False

        # Check file size limit
        if self.config.filter.max_file_size is not None:
            try:
                file_size = file_path.stat().st_size
                if file_size > self.config.filter.max_file_size:
                    self.logger.info(
                        f"Skipping {file_path.name} due to size limit: "
                        f"{format_file_size(file_size)} > {format_file_size(self.config.filter.max_file_size)}"
                    )
                    return False
            except OSError as e:
                self.logger.warning(f"Could not check size of {file_path}: {e}")
                return False

        return True

    def _detect_symlink_cycle(self, path: Path) -> bool:
        """Detect if following a symlink would create a cycle."""
        try:
            current = path
            depth = 0
            visited = self._symlink_visited.copy()

            while current.is_symlink() and depth < MAX_SYMLINK_DEPTH:
                target = current.readlink()
                if not target.is_absolute():
                    target = current.parent / target
                target = target.resolve(strict=False)

                target_str = str(target)
                if target_str in visited:
                    return True

                # Check if target is ancestor
                try:
                    if current.parent.resolve(strict=False).is_relative_to(target):
                        return True
                except (ValueError, AttributeError):
                    # Not an ancestor or method not available
                    pass

                if target.is_symlink():
                    visited.add(target_str)

                current = target
                depth += 1

            if depth >= MAX_SYMLINK_DEPTH:
                return True

            # Update global visited set
            self._symlink_visited.update(visited)
            return False

        except (OSError, RuntimeError):
            return True
