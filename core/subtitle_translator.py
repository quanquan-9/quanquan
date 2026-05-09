"""
多语言字幕翻译与本地化引擎

功能：
- 自动字幕翻译（中文→英/日/韩/法/德/西...）
- 多格式导出（SRT/VTT/ASS/Bilingual）
- 术语表管理
- 翻译记忆库
"""

import asyncio
import json
import re
import logging
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class Language(Enum):
    ZH = "zh"    # 中文
    EN = "en"    # 英文
    JA = "ja"    # 日文
    KO = "ko"    # 韩文
    FR = "fr"    # 法文
    DE = "de"    # 德文
    ES = "es"    # 西班牙文
    PT = "pt"    # 葡萄牙文
    RU = "ru"    # 俄文
    AR = "ar"    # 阿拉伯文
    TH = "th"    # 泰文
    VI = "vi"    # 越南文
    ID = "id"    # 印尼文


LANGUAGE_NAMES = {
    Language.ZH: "中文", Language.EN: "English",
    Language.JA: "日本語", Language.KO: "한국어",
    Language.FR: "Français", Language.DE: "Deutsch",
    Language.ES: "Español", Language.PT: "Português",
    Language.RU: "Русский", Language.AR: "العربية",
    Language.TH: "ไทย", Language.VI: "Tiếng Việt",
    Language.ID: "Bahasa Indonesia",
}


@dataclass
class TranslationEntry:
    """翻译条目"""
    index: int
    source: str
    target: str
    source_lang: str
    target_lang: str
    confidence: float = 0.9


class SubtitleTranslator:
    """字幕翻译器 — 支持多后端"""

    def __init__(self, llm_client=None):
        self.llm = llm_client
        self._glossary: Dict[str, Dict[str, str]] = {}  # {source_lang: {term: translation}}
        self._translation_memory: List[TranslationEntry] = []

    def add_glossary(self, source_lang: str, terms: Dict[str, str]):
        """添加术语表"""
        self._glossary.setdefault(source_lang, {}).update(terms)

    async def translate_srt(
        self,
        srt_content: str,
        source_lang: Language = Language.ZH,
        target_lang: Language = Language.EN,
    ) -> str:
        """翻译 SRT 字幕文件"""
        # 解析 SRT
        entries = self._parse_srt(srt_content)
        if not entries:
            return srt_content

        # 批量翻译文本
        texts = [e["text"] for e in entries]
        translated = await self._translate_batch(
            texts, source_lang, target_lang)

        # 重新组合
        lines = []
        for i, entry in enumerate(entries):
            lines.append(str(entry["index"]))
            lines.append(f'{entry["start"]} --> {entry["end"]}')
            lines.append(translated[i] if i < len(translated) else entry["text"])
            lines.append("")

        return "\n".join(lines)

    async def translate_bilingual_srt(
        self,
        srt_content: str,
        source_lang: Language = Language.ZH,
        target_lang: Language = Language.EN,
    ) -> str:
        """生成双语字幕"""
        entries = self._parse_srt(srt_content)
        texts = [e["text"] for e in entries]
        translated = await self._translate_batch(texts, source_lang, target_lang)

        lines = []
        for i, entry in enumerate(entries):
            lines.append(str(entry["index"]))
            lines.append(f'{entry["start"]} --> {entry["end"]}')
            lines.append(entry["text"])
            if i < len(translated) and translated[i] != entry["text"]:
                lines.append(translated[i])
            lines.append("")

        return "\n".join(lines)

    async def _translate_batch(
        self,
        texts: List[str],
        source: Language,
        target: Language,
    ) -> List[str]:
        """批量翻译"""
        if not texts:
            return []

        source_name = LANGUAGE_NAMES.get(source, source.value)
        target_name = LANGUAGE_NAMES.get(target, target.value)

        # 如果有 LLM 客户端，使用 LLM 翻译
        if self.llm:
            prompt = (
                f"请将以下{source_name}字幕翻译为{target_name}。"
                f"保持原文语气和风格，每行独立翻译。\n\n"
                + "\n".join(f"{i+1}. {t}" for i, t in enumerate(texts))
            )

            try:
                response = await self.llm.chat(
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.3,
                )
                translated = self._parse_numbered_response(response)
                if len(translated) == len(texts):
                    return translated
            except Exception as e:
                logger.warning(f"LLM translation failed: {e}")

        # 回退：应用术语表
        glossary = self._glossary.get(source.value, {})
        return [
            self._apply_glossary(t, glossary) for t in texts
        ]

    def _apply_glossary(self, text: str, glossary: Dict[str, str]) -> str:
        """应用术语表"""
        result = text
        for term, translation in glossary.items():
            result = result.replace(term, f"{translation}({term})")
        return result

    def _parse_srt(self, content: str) -> List[dict]:
        """解析 SRT 格式"""
        entries = []
        blocks = content.strip().split("\n\n")
        for block in blocks:
            lines = block.strip().split("\n")
            if len(lines) >= 3:
                try:
                    index = int(lines[0])
                    time_part = lines[1]
                    text = "\n".join(lines[2:])
                    start, end = time_part.split(" --> ")
                    entries.append({
                        "index": index,
                        "start": start.strip(),
                        "end": end.strip(),
                        "text": text,
                    })
                except Exception:
                    continue
        return entries

    def _parse_numbered_response(self, response: str) -> List[str]:
        """解析编号翻译响应"""
        lines = response.strip().split("\n")
        result = []
        for line in lines:
            match = re.match(r"^\d+[\.\)、]\s*(.*)", line.strip())
            if match:
                result.append(match.group(1))
        return result

    async def translate_to_multiple(
        self,
        srt_content: str,
        source_lang: Language = Language.ZH,
        target_langs: List[Language] = None,
    ) -> Dict[str, str]:
        """翻译为多种语言"""
        if target_langs is None:
            target_langs = [Language.EN, Language.JA, Language.KO]

        tasks = [
            self.translate_srt(srt_content, source_lang, lang)
            for lang in target_langs
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        return {
            lang.value: (r if not isinstance(r, Exception) else srt_content)
            for lang, r in zip(target_langs, results)
        }
