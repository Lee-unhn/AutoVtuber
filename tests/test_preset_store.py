"""PresetStore 測試 — list / save / load / duplicate / delete / import / export。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from autovtuber.pipeline.job_spec import (
    EyeShape,
    FormInput,
    HairLength,
    HairStyle,
    JobResult,
    JobSpec,
    Personality,
    StyleGenre,
)
from autovtuber.presets.preset_store import PresetStore, PresetSummary


def make_form(nickname: str = "test") -> FormInput:
    return FormInput(
        nickname=nickname,
        hair_color_hex="#AABBCC",
        hair_length=HairLength.LONG,
        hair_style=HairStyle.STRAIGHT,
        eye_color_hex="#112233",
        eye_shape=EyeShape.ALMOND,
        style=StyleGenre.ANIME_MODERN,
        personality=Personality.CALM_INTROVERTED,
        extra_freeform="",
        base_model_id="AvatarSample_A",
    )


def make_result(nickname: str = "test", succeeded: bool = True) -> JobResult:
    spec = JobSpec(form=make_form(nickname))
    return JobResult(
        spec=spec,
        succeeded=succeeded,
        output_vrm_path=f"/fake/{nickname}.vrm",
    )


def test_save_then_list_and_load(tmp_path: Path):
    store = PresetStore(tmp_path)
    result = make_result("mira")
    saved_path = store.save(result)
    assert saved_path.exists()

    summaries = store.list_summaries()
    assert len(summaries) == 1
    assert summaries[0].nickname == "mira"
    assert summaries[0].succeeded is True

    loaded = store.load(saved_path)
    assert loaded.spec.form.nickname == "mira"


def test_load_spec_returns_jobspec(tmp_path: Path):
    store = PresetStore(tmp_path)
    saved = store.save(make_result("alice"))
    spec = store.load_spec(saved)
    assert isinstance(spec, JobSpec)
    assert spec.form.nickname == "alice"


def test_duplicate_creates_new_jobspec_with_new_id(tmp_path: Path):
    store = PresetStore(tmp_path)
    saved = store.save(make_result("bob"))
    new_spec = store.duplicate(saved)
    assert new_spec.form.nickname == "bob_copy"
    # 不同 job_id（新生成）
    assert new_spec.job_id != JobResult.model_validate_json(saved.read_text(encoding="utf-8")).spec.job_id


def test_delete_removes_file(tmp_path: Path):
    store = PresetStore(tmp_path)
    saved = store.save(make_result("charlie"))
    assert saved.exists()
    assert store.delete(saved) is True
    assert not saved.exists()
    assert store.delete(saved) is False  # 已刪 → False


def test_list_skips_invalid_json(tmp_path: Path):
    store = PresetStore(tmp_path)
    store.save(make_result("good"))
    # 寫一個壞 JSON
    bad = tmp_path / "bad.preset.json"
    bad.write_text("{not valid json", encoding="utf-8")

    summaries = store.list_summaries()
    # 應只列 good，跳過 bad
    assert len(summaries) == 1
    assert summaries[0].nickname == "good"


def test_export_preset_copies_file(tmp_path: Path):
    src_dir = tmp_path / "src"
    out_dir = tmp_path / "out"
    src_dir.mkdir()
    out_dir.mkdir()

    store = PresetStore(src_dir)
    saved = store.save(make_result("alice"))
    target = out_dir / "shared_alice.preset.json"

    store.export_preset(saved, target)
    assert target.exists()
    # 內容相同
    assert target.read_text(encoding="utf-8") == saved.read_text(encoding="utf-8")


def test_import_preset_brings_file_into_store(tmp_path: Path):
    a_dir = tmp_path / "a"  # alice 的機器
    b_dir = tmp_path / "b"  # bob 接收的機器
    a_dir.mkdir()
    b_dir.mkdir()

    a_store = PresetStore(a_dir)
    b_store = PresetStore(b_dir)
    alice_preset = a_store.save(make_result("alice"))

    # bob 從 alice 接收 preset
    imported = b_store.import_preset(alice_preset)
    assert imported.exists()
    assert imported.parent == b_dir

    summaries = b_store.list_summaries()
    assert len(summaries) == 1
    assert summaries[0].nickname == "alice"


def test_import_preset_with_new_nickname(tmp_path: Path):
    a_dir = tmp_path / "a"
    b_dir = tmp_path / "b"
    a_dir.mkdir()
    b_dir.mkdir()

    a_store = PresetStore(a_dir)
    b_store = PresetStore(b_dir)
    alice_preset = a_store.save(make_result("alice"))

    imported = b_store.import_preset(alice_preset, new_nickname="bob_renamed_alice")
    summaries = b_store.list_summaries()
    assert len(summaries) == 1
    assert summaries[0].nickname == "bob_renamed_alice"


def test_import_preset_handles_filename_conflict(tmp_path: Path):
    a_dir = tmp_path / "a"
    b_dir = tmp_path / "b"
    a_dir.mkdir()
    b_dir.mkdir()
    a_store = PresetStore(a_dir)
    b_store = PresetStore(b_dir)
    alice_preset = a_store.save(make_result("alice"))

    # 先 import 一次
    b_store.import_preset(alice_preset)
    # 再 import 應自動加 _imported1 後綴
    second = b_store.import_preset(alice_preset)
    assert "_imported" in second.name
    summaries = b_store.list_summaries()
    assert len(summaries) == 2


def test_import_preset_rejects_invalid_json(tmp_path: Path):
    store = PresetStore(tmp_path)
    bad = tmp_path / "bad.preset.json"
    bad.write_text("not json", encoding="utf-8")
    with pytest.raises(ValueError, match="無效"):
        store.import_preset(bad)


def test_export_preset_raises_on_missing_source(tmp_path: Path):
    store = PresetStore(tmp_path)
    with pytest.raises(FileNotFoundError):
        store.export_preset(tmp_path / "doesnt_exist.json", tmp_path / "out.json")
