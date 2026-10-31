from __future__ import annotations

import pytest

from shared.path_utils import paths_overlap

pytestmark = pytest.mark.unit


def test_paths_overlap_detects_same_and_nested_paths(tmp_path) -> None:
    child = tmp_path / 'a' / 'b'
    child.mkdir(parents=True)

    assert paths_overlap(tmp_path, tmp_path)
    assert paths_overlap(tmp_path, child)
    assert paths_overlap(child, tmp_path)


def test_paths_overlap_allows_sibling_paths(tmp_path) -> None:
    first = tmp_path / 'input'
    second = tmp_path / 'output'
    first.mkdir()
    second.mkdir()

    assert not paths_overlap(first, second)
    # 前方一致だけの別フォルダは内包関係ではない。
    assert not paths_overlap(tmp_path / 'input', tmp_path / 'input_backup')
