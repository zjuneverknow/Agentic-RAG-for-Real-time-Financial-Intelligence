from __future__ import annotations

import argparse
import os
from pathlib import Path


def configure_local_cache(project_root: Path) -> None:
    hf_home = project_root / ".hf-cache"
    os.environ["HF_HOME"] = str(hf_home)
    os.environ["HF_HUB_CACHE"] = str(hf_home / "hub")
    os.environ["TRANSFORMERS_CACHE"] = str(hf_home / "transformers")
    os.environ["XDG_CACHE_HOME"] = str(project_root / ".cache")
    for path in (hf_home, hf_home / "hub", hf_home / "transformers", project_root / ".cache", project_root / "models"):
        path.mkdir(parents=True, exist_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Download Qwen2.5-7B-Instruct into the project-local models folder.")
    parser.add_argument("--format", choices=["gguf", "awq"], default="gguf")
    parser.add_argument("--repo", default="", help="Override Hugging Face repo id.")
    parser.add_argument("--include", action="append", default=[], help="Allow pattern. Can be passed multiple times.")
    parser.add_argument("--local-dir", default="", help="Override target directory under project root or absolute path.")
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parents[1]
    configure_local_cache(project_root)

    if args.format == "gguf":
        repo_id = args.repo or "Qwen/Qwen2.5-7B-Instruct-GGUF"
        allow_patterns = args.include or ["qwen2.5-7b-instruct-q4_k_m*.gguf", "README.md", "LICENSE"]
        local_dir = Path(args.local_dir) if args.local_dir else project_root / "models" / "Qwen2.5-7B-Instruct-GGUF"
    else:
        repo_id = args.repo or "Qwen/Qwen2.5-7B-Instruct-AWQ"
        allow_patterns = args.include or ["*.safetensors", "*.json", "*.py", "tokenizer*", "README.md", "LICENSE", "*.model"]
        local_dir = Path(args.local_dir) if args.local_dir else project_root / "models" / "Qwen2.5-7B-Instruct-AWQ"

    if not local_dir.is_absolute():
        local_dir = project_root / local_dir
    local_dir.mkdir(parents=True, exist_ok=True)

    print(f"Repo: {repo_id}")
    print(f"Target: {local_dir}")
    print(f"HF_HOME: {os.environ['HF_HOME']}")
    print(f"Patterns: {allow_patterns}")

    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        raise SystemExit("Missing dependency: huggingface_hub. Run `uv add huggingface-hub` or install it in your current env.") from exc

    snapshot_download(
        repo_id=repo_id,
        local_dir=str(local_dir),
        cache_dir=os.environ["HF_HUB_CACHE"],
        allow_patterns=allow_patterns,
        local_dir_use_symlinks=False,
        resume_download=True,
    )
    print("Download complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())