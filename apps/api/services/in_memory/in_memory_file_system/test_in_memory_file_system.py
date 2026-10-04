import pytest

from apps.api.services.in_memory.in_memory_file_system.in_memory_file_system import (
    DuplicateFileError,
    FileDoesNotExistError,
    InMemoryFileSystem,
    InvalidFilePathError,
    ValidationError,
)


@pytest.fixture
def service():
    return InMemoryFileSystem()


@pytest.mark.parametrize(
    "file_path",
    [
        "/",
        "home/file",
        "/home/",
        "file",
        "file/",
        "",
        "   ",
        " /home/abc  ",
        "//file",
        "/a//b",
        "/a/./b",
        "/a/../b",
    ],
)
@pytest.mark.parametrize("operation", ["add_file", "get_file", "remove_file"])
def test_invalid_paths(service, file_path, operation):
    service.add_file("/existing/file")
    with pytest.raises(ValidationError):
        getattr(service, operation)(file_path)
    assert service.list_files() == ["/existing/file"]


def test_add_file_raise_duplicate_file_error(
    service,
):
    service.add_file("/home")

    with pytest.raises(DuplicateFileError):
        service.add_file("/home")


@pytest.mark.parametrize(
    "file_path",
    ["/home", "/home/file1"],
)
def test_add_file(service, file_path):

    assert service.add_file(file_path) == file_path


def test_add_file_add_parent(service):
    service.add_file("/home/file1")

    with pytest.raises(InvalidFilePathError):
        service.add_file("/home")
    assert service.get_file("/home/file1") == "/home/file1"


def test_add_file_to_file(service):
    service.add_file("/home/file1")

    with pytest.raises(InvalidFilePathError):
        service.add_file("/home/file1/file2")


@pytest.mark.parametrize(
    "file_path",
    [
        "/home/file2",
        "/home1/file1",
    ],
)
def test_get_file_raises_file_does_not_exist(service, file_path):
    service.add_file("/home/file1")

    with pytest.raises(FileDoesNotExistError):
        service.get_file(file_path)


def test_get_file(service):

    service.add_file("/home/file1")

    assert service.get_file("/home/file1") == "/home/file1"


def test_list_files(service):
    assert service.list_files() == []

    for path in ["/z/file", "/home/file2", "/home/file1", "/a"]:
        service.add_file(path)

    assert service.list_files() == ["/a", "/home/file1", "/home/file2", "/z/file"]


def test_remove_file(service):
    with pytest.raises(FileDoesNotExistError):
        service.remove_file("/home")

    service.add_file("/home")
    assert service.list_files() == ["/home"]
    service.remove_file("/home")
    assert service.list_files() == []

    service.add_file("/home/dir1/file1")
    service.add_file("/home/dir1/file2")
    with pytest.raises(InvalidFilePathError):
        service.remove_file("/home")

    service.remove_file("/home/dir1/file1")
    assert service.list_files() == ["/home/dir1/file2"]


@pytest.mark.parametrize("operation", ["get_file", "remove_file"])
def test_directory_is_not_a_file(service, operation):
    service.add_file("/home/file1")
    with pytest.raises(InvalidFilePathError):
        getattr(service, operation)("/home")
    assert service.get_file("/home/file1") == "/home/file1"


@pytest.mark.parametrize("operation", ["add_file", "get_file", "remove_file"])
def test_cannot_traverse_file(service, operation):
    service.add_file("/home")
    with pytest.raises(InvalidFilePathError):
        getattr(service, operation)("/home/new/deep/file")
    assert service.list_files() == ["/home"]


def test_remove_preserves_directory_and_allows_recreation(service):
    service.add_file("/home/file1")
    service.remove_file("/home/file1")
    assert service.list_files() == []
    with pytest.raises(FileDoesNotExistError):
        service.get_file("/home/file1")
    with pytest.raises(FileDoesNotExistError):
        service.remove_file("/home/file1")
    with pytest.raises(InvalidFilePathError):
        service.add_file("/home")
    assert service.add_file("/home/file1") == "/home/file1"
