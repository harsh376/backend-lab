from dataclasses import dataclass, field

type FilePath = str


@dataclass(frozen=True)
class Node:
    children: dict[str, "Node"] = field(default_factory=dict)
    is_file: bool = False


class ValidationError(Exception):
    pass


class DuplicateFileError(Exception):
    pass


class FileDoesNotExistError(Exception):
    pass


class InvalidFilePathError(Exception):
    pass


class InMemoryFileSystem:
    """An absolute-path file tree with automatically created directories.

    Files cannot contain children. Empty, '.' and '..' path components are
    invalid. Removing a file preserves its parent directories.
    """

    def __init__(self):
        self.root = Node(children={})

    def _validate_file_path(self, file_path: FilePath) -> list[str]:

        if (
            not file_path.startswith("/")
            or file_path == "/"
            or file_path.endswith("/")
            or file_path.strip() == ""
            or len(file_path) != len(file_path.strip(" "))
        ):
            raise ValidationError
        parts = file_path.split("/")[1:]
        if any(part in ("", ".", "..") for part in parts):
            raise ValidationError
        return parts

    def _traverse_directories(
        self, parts: list[str], *, create_missing: bool = False
    ) -> Node:
        """Resolve validated directory components, optionally creating missing ones."""
        node = self.root
        for part in parts:
            child = node.children.get(part)
            if child is None:
                if not create_missing:
                    raise FileDoesNotExistError
                child = Node()
                node.children[part] = child
            if child.is_file:
                raise InvalidFilePathError
            node = child
        return node

    def add_file(self, file_path: FilePath) -> FilePath:
        parts = self._validate_file_path(file_path)

        node = self._traverse_directories(parts[:-1], create_missing=True)

        file_name = parts[-1]
        file = node.children.get(file_name)
        if file is not None:
            if file.is_file:
                raise DuplicateFileError
            else:
                raise InvalidFilePathError
        node.children[file_name] = Node(children={}, is_file=True)
        return file_path

    def get_file(self, file_path: FilePath) -> FilePath:
        parts = self._validate_file_path(file_path)

        node = self._traverse_directories(parts[:-1])

        file_name = parts[-1]
        file = node.children.get(file_name)
        if file is None:
            raise FileDoesNotExistError
        if not file.is_file:
            raise InvalidFilePathError

        return file_path

    def list_files(self) -> list[FilePath]:
        files: list[list[str]] = []
        stack = [(self.root, [])]

        while stack:
            item, path = stack.pop()

            if item.is_file:
                files.append(path)

            for child in item.children:
                stack.append((item.children[child], path + [child]))

        files_formatted = ["/" + "/".join(file_parts) for file_parts in files]
        return sorted(files_formatted)

    def remove_file(self, file_path: FilePath) -> None:
        parts = self._validate_file_path(file_path)

        node = self._traverse_directories(parts[:-1])

        file_name = parts[-1]
        file = node.children.get(file_name)
        if file is None:
            raise FileDoesNotExistError

        if not file.is_file:
            raise InvalidFilePathError

        del node.children[file_name]
