#!/usr/bin/env python3
"""Build tests/fixtures/wow/corpus.json from markdown article files."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ARTICLES_DIR = ROOT / "articles"

CORPUS = {
    "corpus_id": "wow-test-corpus-v1",
    "language": "ru",
    "tenant_slug": "demo",
    "category": {
        "name": "Лор Warcraft",
        "slug": "warcraft-lore",
    },
    "corpus_tag": {
        "name": "wow-test-corpus-v1",
        "slug": "wow-test-corpus-v1",
    },
    "articles": [
        {
            "id": "azeroth",
            "file": "azeroth.md",
            "title": "История Азерота: древние эпохи и возникновение основных конфликтов",
            "tags": ["azeroth", "history", "lore"],
            "unique_markers": [
                "Источник Вечности",
                "Раскол мира",
                "Война Древних",
                "Чёрная Империя",
                "Пантеон титанов",
            ],
            "related_article_ids": ["alliance-horde", "orcs-draenor", "illidan"],
        },
        {
            "id": "alliance-horde",
            "file": "alliance-horde.md",
            "title": "Альянс и Орда: происхождение и ключевые конфликты",
            "tags": ["alliance", "horde", "war"],
            "unique_markers": [
                "Оргриммар",
                "Штормград",
                "Первая война",
                "Вторая война",
            ],
            "related_article_ids": ["azeroth", "jaina", "orcs-draenor"],
        },
        {
            "id": "arthas",
            "file": "arthas.md",
            "title": "Артас Менетил: от принца Лордерона до Короля-лича",
            "tags": ["arthas", "lordaeron", "frostmourne", "lich-king"],
            "unique_markers": [
                "Ледяная Скорбь",
                "Мал'Ганис",
                "Стратхольм",
                "Падение Лордерона",
                "Утер Светоносный",
            ],
            "related_article_ids": ["nerzhul", "sylvanas", "jaina"],
        },
        {
            "id": "nerzhul",
            "file": "nerzhul.md",
            "title": "Нер'зул, Плеть и создание Короля-лича",
            "tags": ["nerzhul", "scourge", "lich-king", "icecrown"],
            "unique_markers": [
                "Ледяной Трон",
                "Плеть",
                "Кил'джеден",
            ],
            "related_article_ids": ["arthas", "orcs-draenor", "azeroth"],
        },
        {
            "id": "orcs-draenor",
            "file": "orcs-draenor.md",
            "title": "Орки Дренора и Пылающий Легион",
            "tags": ["draenor", "orcs", "guldan", "burning-legion"],
            "unique_markers": [
                "Гул'дан",
                "Тёмный портал",
                "Маннорот",
                "Кровавый пакт",
                "Совет Теней",
            ],
            "related_article_ids": ["nerzhul", "alliance-horde", "azeroth"],
        },
        {
            "id": "illidan",
            "file": "illidan.md",
            "title": "Иллидан Ярость Бури и Иллидари",
            "tags": ["illidan", "illidari", "demon-hunters"],
            "unique_markers": [
                "Иллидари",
                "Черный храм",
                "охотники на демонов",
                "Кель'данас",
            ],
            "related_article_ids": ["azeroth", "orcs-draenor"],
        },
        {
            "id": "jaina",
            "file": "jaina.md",
            "title": "Джайна Праудмур и Кирин-Тор",
            "tags": ["jaina", "dalaran", "kirin-tor"],
            "unique_markers": [
                "Терамор",
                "Антонидас",
                "Кирин-Тор",
                "Даларан",
                "Кул-Тирас",
            ],
            "related_article_ids": ["alliance-horde", "arthas"],
        },
        {
            "id": "sylvanas",
            "file": "sylvanas.md",
            "title": "Сильвана Ветрокрылая и Отрекшиеся",
            "tags": ["sylvanas", "forsaken", "banshee"],
            "unique_markers": [
                "Отрекшиеся",
                "Луносвет",
                "Тёмный бастион",
                "Кель'Талас",
            ],
            "related_article_ids": ["arthas", "nerzhul", "alliance-horde"],
        },
    ],
}


def _main_body(markdown: str) -> str:
    marker = "\n## См. также"
    if marker in markdown:
        return markdown.split(marker, 1)[0]
    return markdown


def main() -> None:
    articles_out = []
    for spec in CORPUS["articles"]:
        path = ARTICLES_DIR / spec["file"]
        body = path.read_text(encoding="utf-8").strip() + "\n"
        title_line = body.splitlines()[0].lstrip("# ").strip()
        if title_line != spec["title"]:
            raise SystemExit(
                f"{spec['id']}: markdown H1 {title_line!r} != spec title {spec['title']!r}"
            )
        word_count = len(body.split())
        if word_count < 700 or word_count > 1500:
            raise SystemExit(
                f"{spec['id']}: word_count {word_count} outside 700-1500"
            )
        main = _main_body(body)
        for marker in spec["unique_markers"]:
            if marker not in main:
                raise SystemExit(f"{spec['id']}: missing unique marker {marker!r}")
        articles_out.append(
            {
                "id": spec["id"],
                "title": spec["title"],
                "identity_tag": f"wow-{spec['id']}",
                "tags": spec["tags"],
                "unique_markers": spec["unique_markers"],
                "related_article_ids": spec["related_article_ids"],
                "word_count": word_count,
                "body_format": "markdown",
                "body": body,
            }
        )

    for article in articles_out:
        for marker in article["unique_markers"]:
            owners = [
                other["id"]
                for other in articles_out
                if marker in _main_body(other["body"])
            ]
            if owners != [article["id"]]:
                raise SystemExit(
                    f"Unique marker {marker!r} expected only in {article['id']}, "
                    f"found in {owners}"
                )

    payload = {
        "corpus_id": CORPUS["corpus_id"],
        "language": CORPUS["language"],
        "tenant_slug": CORPUS["tenant_slug"],
        "category": CORPUS["category"],
        "corpus_tag": CORPUS["corpus_tag"],
        "change_summary": "wow-test-corpus-v1 seed",
        "visibility": "company",
        "articles": articles_out,
    }
    out = ROOT / "corpus.json"
    out.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {out}")
    for article in articles_out:
        print(f"  {article['id']:16} words={article['word_count']}")


if __name__ == "__main__":
    main()
