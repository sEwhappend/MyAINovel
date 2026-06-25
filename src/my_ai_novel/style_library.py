"""全局、文件式的文风库：styles/<名字>/，独立于具体小说项目。

每个文风是一个目录：
    styles/<safe-name>/
        style.json                 # 元信息（name）
        samples/<id>.json          # 样本元信息
        samples/<id>.clean.txt     # 清洗后文本
        style_profile.json         # 文风画像（分析产物）

不使用数据库，全部为人可直接打开的文件，和项目存储理念一致。
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Mapping

from .project_files import sanitize_filename

DEFAULT_STYLES_ROOT = Path("styles")
_META_FILE = "style.json"
_PROFILE_FILE = "style_profile.json"
_SAMPLES_DIR = "samples"


def _style_dir(name: str, root: Path) -> Path:
    return Path(root) / sanitize_filename(name, fallback="style", max_length=80)


def _samples_dir(name: str, root: Path) -> Path:
    return _style_dir(name, root) / _SAMPLES_DIR


def create_style(name: str, root: Path = DEFAULT_STYLES_ROOT) -> str:
    base = _style_dir(name, root)
    (base / _SAMPLES_DIR).mkdir(parents=True, exist_ok=True)
    meta_path = base / _META_FILE
    if not meta_path.exists():
        _write_json(meta_path, {"name": str(name)})
    return str(name)


def delete_style(name: str, root: Path = DEFAULT_STYLES_ROOT) -> None:
    base = _style_dir(name, root)
    if base.exists():
        try:
            shutil.rmtree(base)
        except OSError:
            pass


def list_styles(root: Path = DEFAULT_STYLES_ROOT) -> list[dict[str, Any]]:
    root = Path(root)
    if not root.exists():
        return []
    styles: list[dict[str, Any]] = []
    for base in sorted(root.iterdir()):
        if not base.is_dir():
            continue
        meta = _read_json(base / _META_FILE)
        name = str(meta.get("name") or base.name)
        styles.append(
            {
                "name": name,
                "dir": base.name,
                "sample_count": len(_sample_meta_paths(base)),
                "has_profile": (base / _PROFILE_FILE).exists(),
            }
        )
    return styles


def write_style_sample(
    name: str,
    sample: Mapping[str, Any],
    clean_text: str,
    root: Path = DEFAULT_STYLES_ROOT,
) -> Path:
    target = _samples_dir(name, root)
    target.mkdir(parents=True, exist_ok=True)
    sample_id = sanitize_filename(sample.get("id"), fallback="sample", max_length=60)
    text_name = f"{sample_id}.clean.txt"
    payload = {**dict(sample), "id": sample_id, "text_path": f"{_SAMPLES_DIR}/{text_name}"}
    _write_text(target / text_name, str(clean_text or ""))
    return _write_json(target / f"{sample_id}.json", payload)


def load_style_samples(name: str, root: Path = DEFAULT_STYLES_ROOT) -> list[dict[str, Any]]:
    base = _style_dir(name, root)
    if not base.exists():
        return []
    samples: list[dict[str, Any]] = []
    for path in _sample_meta_paths(base):
        meta = _read_json(path)
        if meta:
            samples.append(meta)
    return samples


def load_style_sample_text(name: str, sample_id: str, root: Path = DEFAULT_STYLES_ROOT) -> str:
    base = _samples_dir(name, root)
    safe_id = sanitize_filename(sample_id, fallback="sample", max_length=60)
    path = base / f"{safe_id}.clean.txt"
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").removesuffix("\n")


def delete_style_sample(name: str, sample_id: str, root: Path = DEFAULT_STYLES_ROOT) -> None:
    base = _samples_dir(name, root)
    safe_id = sanitize_filename(sample_id, fallback="sample", max_length=60)
    for suffix in (".json", ".clean.txt"):
        path = base / f"{safe_id}{suffix}"
        if path.exists():
            try:
                path.unlink()
            except OSError:
                continue


def write_style_profile(name: str, profile: Mapping[str, Any], root: Path = DEFAULT_STYLES_ROOT) -> Path:
    base = _style_dir(name, root)
    base.mkdir(parents=True, exist_ok=True)
    return _write_json(base / _PROFILE_FILE, profile)


def load_style_profile(name: str, root: Path = DEFAULT_STYLES_ROOT) -> dict[str, Any]:
    path = _style_dir(name, root) / _PROFILE_FILE
    return _read_json(path) if path.exists() else {}


def _sample_meta_paths(base: Path) -> list[Path]:
    samples_dir = base / _SAMPLES_DIR
    if not samples_dir.exists():
        return []
    return sorted(samples_dir.glob("*.json"))


def _write_json(path: Path, data: Mapping[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(dict(data), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _write_text(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")
    return path


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}
