from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from nonebot.log import logger


@dataclass
class MemberSkill:
    uid: str
    nick: str
    style: str = ""
    topics: list[str] | None = None
    traits: list[str] | None = None
    notes: list[str] | None = None
    summary: str = ""


class SkillLoader:
    """群友 skill 文件加载器。

    MVP 递归读取 exports_dir 下的 .skill/.md/.txt 文件，尝试从文件名或正文提取 QQ 号。
    """

    UID_RE = re.compile(r"(\d{5,12})")

    def __init__(self, exports_dir: str):
        self.exports_dir = Path(exports_dir)
        self.skills: dict[str, MemberSkill] = {}
        self.load_all()

    def load_all(self) -> None:
        self.skills.clear()
        if not self.exports_dir.exists():
            return

        try:
            for path in self.exports_dir.rglob("*"):
                if not path.is_file() or path.suffix.lower() not in {".skill", ".md", ".txt"}:
                    continue
                skill = self._load_one(path)
                if skill and skill.uid:
                    self.skills[skill.uid] = skill
        except Exception:
            logger.exception("SkillLoader: failed to load skills: %s", self.exports_dir)

    def _load_one(self, path: Path) -> Optional[MemberSkill]:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore").strip()
            if not text:
                return None

            uid = self._extract_uid(path.name, text)
            if not uid:
                return None

            nick = path.stem
            nick = self.UID_RE.sub("", nick).strip(" ()（）-_") or uid
            summary = text[:3000]
            return MemberSkill(uid=uid, nick=nick, summary=summary, topics=[], traits=[], notes=[])
        except Exception:
            logger.exception("SkillLoader: failed to load skill file: %s", path)
            return None

    def _extract_uid(self, filename: str, text: str) -> str:
        m = self.UID_RE.search(filename)
        if m:
            return m.group(1)
        for line in text.splitlines()[:20]:
            m = self.UID_RE.search(line)
            if m:
                return m.group(1)
        return ""

    def get(self, uid: str) -> Optional[MemberSkill]:
        return self.skills.get(str(uid))

    def reload(self) -> None:
        self.load_all()

    def generate_from_db(self, store) -> None:
        """第二阶段占位：后续迁移现有 member_skill cron。"""
        logger.debug("SkillLoader.generate_from_db placeholder store=%s", store)
