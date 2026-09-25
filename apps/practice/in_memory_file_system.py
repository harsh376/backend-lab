import re
from dataclasses import dataclass, field


@dataclass
class Node:
    is_file: bool = False
    children: dict[str, "Node"] = field(default_factory=dict)


class FileSystem:
    """A file-name tree with a fixed limit on each directory's direct children.

    Paths must be absolute and cannot contain empty, '.' or '..' components.
    Invalid paths and operation conflicts return None. Files store no content.
    """

    def __init__(self, capacity: int = 5) -> None:
        if isinstance(capacity, bool) or not isinstance(capacity, int):
            raise TypeError("capacity must be an integer")
        if capacity < 0:
            raise ValueError("capacity must be non-negative")

        self.root = Node()
        self.capacity = capacity

    def _parse(self, path: str) -> list[str] | None:
        if not path.startswith("/"):
            return None
        if path == "/":
            return []

        parts = path[1:].split("/")
        if any(part in ("", ".", "..") for part in parts):
            return None
        return parts

    def _split_name(self, name: str) -> tuple[str, int, str]:
        """Extract the base, numeric suffix (or zero), and last extension."""
        # Treat a leading dot alone as part of the name, not an extension.
        dot = name.rfind(".")
        if dot > 0:
            base, extension = name[:dot], name[dot:]
        else:
            base, extension = name, ""

        # Accept both 'file (1)' and the previously generated 'file(1)'.
        match = re.fullmatch(r"(.+?) ?\(([0-9]+)\)", base)
        if match:
            return match[1], int(match[2]), extension
        return base, 0, extension

    def _available_name(self, parent: Node, name: str) -> str:
        """Keep an unused name; on collision, increment the family's max suffix."""
        if name not in parent.children:
            return name

        base, latest_suffix, extension = self._split_name(name)
        for sibling in parent.children:
            sibling_base, suffix, sibling_extension = self._split_name(sibling)
            if sibling_base == base and sibling_extension == extension:
                latest_suffix = max(latest_suffix, suffix)

        return f"{base} ({latest_suffix + 1}){extension}"

    def _can_add_file(self, parts: list[str]) -> bool:
        """Check a nonempty parsed path without changing the tree."""
        parent = self.root
        for name in parts[:-1]:
            child = parent.children.get(name)
            if child is None:
                # The remaining directories will be new, each with one child.
                # Space here also guarantees capacity is at least one.
                return len(parent.children) < self.capacity
            if child.is_file:
                return False
            parent = child

        existing = parent.children.get(parts[-1])
        if existing is not None and not existing.is_file:
            return False
        return len(parent.children) < self.capacity

    def _create_parent_directories(self, directory_names: list[str]) -> Node:
        """Create missing directories after validation and return the parent."""
        parent = self.root
        for name in directory_names:
            if name not in parent.children:
                parent.children[name] = Node()
            parent = parent.children[name]
        return parent

    def add_file(self, path: str) -> str | None:
        """Create a file and missing parents, returning its actual absolute path.

        Duplicates increment the highest ' (n)' suffix for the same base/extension.
        Directories cannot be replaced by files or traversed through files.
        Capacity counts both files and directories; failure leaves the tree intact.
        """
        parts = self._parse(path)
        if not parts or not self._can_add_file(parts):
            return None

        parent = self._create_parent_directories(parts[:-1])
        actual_name = self._available_name(parent, parts[-1])
        parent.children[actual_name] = Node(is_file=True)

        return "/" + "/".join(parts[:-1] + [actual_name])

    def list_dir(self, path: str) -> list[str] | None:
        """Return sorted child names, or None for an invalid/non-directory path."""
        parts = self._parse(path)
        if parts is None:
            return None

        node = self.root
        for name in parts:
            if node.is_file:
                return None
            child = node.children.get(name)
            if child is None:
                return None
            node = child

        if node.is_file:
            return None

        return sorted(node.children)
