"""Remote skill discovery and caching."""

from __future__ import annotations

from pathlib import Path
from typing import Any, List
from urllib.parse import urljoin

import httpx

from ..core.global_paths import GlobalPath
from ..util.log import Log

log = Log.create({"service": "skill.discovery"})


class Discovery:
    """Download skills from remote index endpoints."""

    @staticmethod
    def cache_dir() -> Path:
        return Path(GlobalPath.cache()) / "skills"

    @classmethod
    async def _download_text(cls, client: httpx.AsyncClient, url: str, dest: Path) -> bool:
        if dest.exists():
            return True

        try:
            response = await client.get(url)
        except Exception as e:
            log.error("failed to download", {"url": url, "error": str(e)})
            return False

        if not response.is_success:
            log.error("failed to download", {"url": url, "status": response.status_code})
            return False

        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(response.text, encoding="utf-8")
            return True
        except Exception as e:
            log.error("failed to write downloaded skill file", {"path": str(dest), "error": str(e)})
            return False

    @classmethod
    async def pull(cls, url: str) -> List[str]:
        """Pull skills from a remote ``.well-known/skills`` endpoint."""
        result: List[str] = []
        base = url if url.endswith("/") else f"{url}/"
        index_url = urljoin(base, "index.json")
        cache_root = cls.cache_dir()
        cache_root.mkdir(parents=True, exist_ok=True)

        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                try:
                    response = await client.get(index_url)
                except Exception as e:
                    log.error("failed to fetch index", {"url": index_url, "error": str(e)})
                    return result

                if not response.is_success:
                    log.error("failed to fetch index", {"url": index_url, "status": response.status_code})
                    return result

                try:
                    data: Any = response.json()
                except Exception as e:
                    log.error("failed to parse index", {"url": index_url, "error": str(e)})
                    return result

                skills = data.get("skills") if isinstance(data, dict) else None
                if not isinstance(skills, list):
                    log.warn("invalid index format", {"url": index_url})
                    return result

                for skill in skills:
                    if not isinstance(skill, dict):
                        continue
                    name = skill.get("name")
                    files = skill.get("files")
                    if not isinstance(name, str) or not isinstance(files, list):
                        log.warn("invalid skill entry", {"url": index_url, "skill": skill})
                        continue

                    skill_root = cache_root / name
                    skill_root.mkdir(parents=True, exist_ok=True)
                    for file in files:
                        if not isinstance(file, str):
                            continue
                        rel = Path(file)
                        if rel.is_absolute() or ".." in rel.parts:
                            continue
                        dest = skill_root / rel
                        file_url = urljoin(urljoin(base, f"{name}/"), file)
                        await cls._download_text(client, file_url, dest)

                    skill_md = skill_root / "SKILL.md"
                    if skill_md.is_file():
                        result.append(str(skill_root.resolve()))
        except Exception as e:
            log.error("failed pulling remote skills", {"url": url, "error": str(e)})
            return result

        return result
