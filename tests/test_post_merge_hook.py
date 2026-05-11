"""Tests for agents.post_merge_hook."""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def test_updates_components_when_py_changed(monkeypatch, tmp_path):
    import runner.components as comp_mod
    import config.settings as settings_mod
    called = []
    monkeypatch.setattr(comp_mod, "generate", lambda path: called.append(path) or True)
    monkeypatch.setattr(settings_mod, "KB_ENABLED", False)

    from agents.post_merge_hook import run
    run(str(tmp_path), ["agents/foo.py", "README.md"])

    assert len(called) == 1
    assert called[0] == str(tmp_path)


def test_skips_components_when_no_py_files(monkeypatch, tmp_path):
    import runner.components as comp_mod
    import config.settings as settings_mod
    called = []
    monkeypatch.setattr(comp_mod, "generate", lambda path: called.append(path) or True)
    monkeypatch.setattr(settings_mod, "KB_ENABLED", False)

    from agents.post_merge_hook import run
    run(str(tmp_path), ["README.md", "docs/notes.txt"])

    assert len(called) == 0


def test_reindexes_when_kb_enabled(monkeypatch, tmp_path):
    import runner.components as comp_mod
    import config.settings as settings_mod
    import agents.indexer as indexer_mod
    indexed = []
    monkeypatch.setattr(comp_mod, "generate", lambda path: True)
    monkeypatch.setattr(settings_mod, "KB_ENABLED", True)
    monkeypatch.setattr(settings_mod, "GITHUB_REPO", "test/repo")
    monkeypatch.setattr(indexer_mod, "index_file",
                        lambda rp, f, proj: indexed.append((rp, f, proj)) or 1)

    from agents.post_merge_hook import run
    run(str(tmp_path), ["agents/foo.py"])

    assert len(indexed) == 1
    assert indexed[0] == (str(tmp_path), "agents/foo.py", "test/repo")


def test_skips_reindex_when_kb_disabled(monkeypatch, tmp_path):
    import runner.components as comp_mod
    import config.settings as settings_mod
    import agents.indexer as indexer_mod
    indexed = []
    monkeypatch.setattr(comp_mod, "generate", lambda path: True)
    monkeypatch.setattr(settings_mod, "KB_ENABLED", False)
    monkeypatch.setattr(indexer_mod, "index_file",
                        lambda rp, f, proj: indexed.append((rp, f, proj)) or 1)

    from agents.post_merge_hook import run
    run(str(tmp_path), ["agents/foo.py"])

    assert len(indexed) == 0


def test_swallows_components_exception(monkeypatch, tmp_path):
    import runner.components as comp_mod
    import config.settings as settings_mod
    monkeypatch.setattr(comp_mod, "generate", lambda path: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(settings_mod, "KB_ENABLED", False)

    from agents.post_merge_hook import run
    run(str(tmp_path), ["foo.py"])  # must not raise


def test_swallows_reindex_exception(monkeypatch, tmp_path):
    import runner.components as comp_mod
    import config.settings as settings_mod
    import agents.indexer as indexer_mod
    monkeypatch.setattr(comp_mod, "generate", lambda path: True)
    monkeypatch.setattr(settings_mod, "KB_ENABLED", True)
    monkeypatch.setattr(settings_mod, "GITHUB_REPO", "test/repo")
    monkeypatch.setattr(indexer_mod, "index_file",
                        lambda rp, f, proj: (_ for _ in ()).throw(RuntimeError("kb down")))

    from agents.post_merge_hook import run
    run(str(tmp_path), ["foo.py"])  # must not raise


def test_empty_changed_files(monkeypatch, tmp_path):
    import runner.components as comp_mod
    import config.settings as settings_mod
    called = []
    monkeypatch.setattr(comp_mod, "generate", lambda path: called.append(path) or True)
    monkeypatch.setattr(settings_mod, "KB_ENABLED", False)

    from agents.post_merge_hook import run
    run(str(tmp_path), [])

    assert len(called) == 0
