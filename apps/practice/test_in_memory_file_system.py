from copy import deepcopy

import pytest

from apps.practice.in_memory_file_system import FileSystem


@pytest.mark.parametrize("capacity", [True, False, 1.5, "5", None])
def test_capacity_requires_an_integer(capacity):
    with pytest.raises(TypeError, match="capacity must be an integer"):
        FileSystem(capacity)


def test_capacity_cannot_be_negative():
    with pytest.raises(ValueError, match="capacity must be non-negative"):
        FileSystem(-1)


def test_zero_capacity_keeps_root_empty():
    fs = FileSystem(0)
    assert fs.add_file("/file") is None
    assert fs.add_file("/parent/file") is None
    assert fs.list_dir("/") == []


@pytest.mark.parametrize(
    "path", ["", "file", "//file", "/a/", "/a//b", "/./b", "/a/../b"]
)
def test_invalid_paths_do_not_mutate_tree(path):
    fs = FileSystem()
    fs.add_file("/existing/file")
    before = deepcopy(fs.root)
    assert fs.add_file(path) is None
    assert fs.list_dir(path) is None
    assert fs.root == before


def test_nested_creation_and_sorted_listing():
    fs = FileSystem()
    assert fs.add_file("/a/b/z.txt") == "/a/b/z.txt"
    assert fs.add_file("/a/b/a.txt") == "/a/b/a.txt"
    assert fs.list_dir("/") == ["a"]
    assert fs.list_dir("/a") == ["b"]
    assert fs.list_dir("/a/b") == ["a.txt", "z.txt"]
    assert fs.list_dir("/missing") is None
    assert fs.list_dir("/a/b/z.txt") is None
    assert fs.list_dir("/a/b/z.txt/child") is None


@pytest.mark.parametrize(
    ("name", "duplicate"),
    [
        ("file", "file (1)"),
        ("file.txt", "file (1).txt"),
        ("archive.tar.gz", "archive.tar (1).gz"),
        (".env", ".env (1)"),
        (".env.local", ".env (1).local"),
        ("file.", "file (1)."),
        ("file (1).txt", "file (2).txt"),
        ("file(1).txt", "file (2).txt"),
        ("file (9).txt", "file (10).txt"),
        ("file (draft).txt", "file (draft) (1).txt"),
    ],
)
def test_duplicate_naming(name, duplicate):
    fs = FileSystem()
    assert fs.add_file(f"/dir/{name}") == f"/dir/{name}"
    assert fs.add_file(f"/dir/{name}") == f"/dir/{duplicate}"


def test_duplicate_suffix_increments_highest_file_or_directory_suffix():
    fs = FileSystem(6)
    fs.add_file("/file.txt")
    fs.add_file("/file (1).txt/child")
    fs.add_file("/file (3).txt")
    assert fs.add_file("/file.txt") == "/file (4).txt"
    assert fs.add_file("/file.txt") == "/file (5).txt"
    assert fs.list_dir("/file (1).txt") == ["child"]


def test_capacity_is_per_directory_and_counts_directories():
    fs = FileSystem(2)
    assert fs.add_file("/a/one") == "/a/one"
    assert fs.add_file("/two") == "/two"
    # A full root still permits additions inside existing directories.
    assert fs.add_file("/a/two") == "/a/two"
    before = deepcopy(fs.root)
    for path in ["/three", "/new/deep/file", "/a/three", "/a/one"]:
        assert fs.add_file(path) is None
        assert fs.root == before


def test_numbered_duplicate_uses_latest_suffix_in_same_family():
    fs = FileSystem(10)
    for name in ["file.txt", "file (1).txt", "file(9).txt", "file (20).text"]:
        fs.add_file(f"/{name}")
    assert fs.add_file("/file (1).txt") == "/file (10).txt"
    assert fs.add_file("/file.txt") == "/file (11).txt"
    assert fs.add_file("/file (20).text") == "/file (21).text"


def test_unused_numbered_name_is_preserved():
    fs = FileSystem()
    fs.add_file("/file (9).txt")
    assert fs.add_file("/file (1).txt") == "/file (1).txt"
    assert fs.add_file("/file.txt") == "/file.txt"


def test_conflicts_leave_existing_tree_intact():
    fs = FileSystem()
    fs.add_file("/dir/file")
    before = deepcopy(fs.root)
    for path in ["/", "/dir", "/dir/file/child", "/dir/file/new/deep/child"]:
        assert fs.add_file(path) is None
        assert fs.root == before


def test_instances_are_independent():
    first, second = FileSystem(), FileSystem()
    first.add_file("/a/file")
    assert second.list_dir("/") == []
