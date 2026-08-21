"""Опросник для создания нового скила.

Запуск:  python tools\\new_skill.py
Результат: skills/<раздел>/<имя>/SKILL.md
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path

import questionary
import yaml
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
SKILLS_DIR = ROOT / "skills"
SCHEMA_PATH = ROOT / "schema" / "skill.schema.json"

NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
DESC_MIN, DESC_MAX = 40, 1024


def sections() -> list[str]:
    """Разделы = подпапки skills/. Новый раздел появляется вместе с папкой."""
    return sorted(p.name for p in SKILLS_DIR.iterdir() if p.is_dir())


def existing_names() -> dict[str, Path]:
    """Все занятые имена скилов по всему каталогу.

    Имя обязано быть уникальным глобально: при установке скилы кладутся
    в одну плоскую папку ~/.claude/skills, там разделов уже нет.
    """
    found: dict[str, Path] = {}
    for skill_md in SKILLS_DIR.glob("*/*/SKILL.md"):
        found[skill_md.parent.name] = skill_md.parent
    return found


def validate_name(value: str) -> bool | str:
    value = value.strip()
    if not NAME_RE.match(value):
        return "Только строчные буквы, цифры и дефисы. Пример: code-review"
    if len(value) > 64:
        return "Не длиннее 64 символов"
    taken = existing_names()
    if value in taken:
        return f"Имя уже занято: {taken[value].relative_to(ROOT)}"
    return True


def ask_lines(prompt: str, required: bool = True) -> list[str]:
    """Многострочный ввод: по одному пункту на строку, пустая строка завершает."""
    print(f"\n{prompt}")
    print("  (по одному пункту на строке; пустая строка — закончить)")
    lines: list[str] = []
    while True:
        line = input("  > ").strip()
        if not line:
            if lines or not required:
                return lines
            print("  Нужен хотя бы один пункт.")
            continue
        lines.append(line)


def build_description(what: str, when: str, when_not: str) -> str:
    parts = [what.rstrip(". ") + ".", "Use when " + when.rstrip(". ").lstrip("wWhen ") + "."]
    if when_not:
        parts.append("Do not use for " + when_not.rstrip(". ") + ".")
    return " ".join(parts)


def render_skill_md(front: dict, body: dict) -> str:
    frontmatter = yaml.safe_dump(
        front, allow_unicode=True, sort_keys=False, default_flow_style=False, width=10_000
    )
    out = ["---", frontmatter.rstrip(), "---", "", f"# {body['title']}", ""]

    out += ["## Когда применять", "", body["when"], ""]
    if body["when_not"]:
        out += [f"Не применять: {body['when_not']}", ""]

    out += ["## Порядок", ""]
    out += [f"{i}. {step}" for i, step in enumerate(body["steps"], 1)]
    out.append("")

    if body["output"]:
        out += ["## Формат ответа", "", body["output"], ""]

    if body["avoid"]:
        out += ["## Чего не делать", ""]
        out += [f"- {item}" for item in body["avoid"]]
        out.append("")

    return "\n".join(out)


def main() -> int:
    if not SKILLS_DIR.exists():
        print(f"Не найдена папка {SKILLS_DIR}. Запускай из корня репозитория.")
        return 1

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, format_checker=FormatChecker())

    print("Новый скил. Ctrl+C — отмена.\n")

    section = questionary.select("Раздел:", choices=sections()).ask()
    if section is None:
        return 1

    name = questionary.text(
        "Имя скила (kebab-case, оно же имя папки):", validate=validate_name
    ).ask()
    if name is None:
        return 1

    title = questionary.text("Заголовок для человека:", default=name.replace("-", " ").capitalize()).ask()

    print("\nСледующие два ответа — по-английски: из них собирается description,")
    print("единственное, что агент читает перед активацией скила.")
    what = questionary.text("Что скил делает (одно предложение, EN):").ask()
    when = questionary.text("Когда применять — триггеры, фразы пользователя (EN):").ask()
    when_not = questionary.text("Когда НЕ применять (EN, можно пропустить):", default="").ask()

    description = build_description(what, when, when_not)
    print(f"\nПолучилось описание ({len(description)} симв.):\n  {description}\n")
    if len(description) < DESC_MIN:
        print("Слишком коротко — агент не поймёт, когда грузить скил. Ответь подробнее.")
        return 1
    if len(description) > DESC_MAX:
        print(f"Длиннее {DESC_MAX} символов — не пройдёт валидацию. Сократи.")
        return 1
    if not questionary.confirm("Оставляем?", default=True).ask():
        print("Отменено. Запусти заново.")
        return 1

    tags_raw = questionary.text("Теги через запятую:", default="").ask()
    tags = [t.strip().lower() for t in tags_raw.split(",") if t.strip()][:10]

    when_ru = questionary.text("Когда применять — своими словами, по-русски:").ask()
    when_not_ru = questionary.text("Когда не применять (RU, можно пропустить):", default="").ask()
    steps = ask_lines("Шаги процедуры:")
    output = questionary.text("Формат ответа (можно пропустить):", default="").ask()
    avoid = ask_lines("Чего не делать:", required=False)

    status = questionary.select("Статус:", choices=["draft", "active"], default="draft").ask()

    front = {
        "name": name,
        "description": description,
        "metadata": {
            "section": section,
            "tags": tags,
            "version": "1.0",
            "author": "vladimir",
            "created": date.today().isoformat(),
            "status": status,
        },
    }
    if not tags:
        del front["metadata"]["tags"]

    errors = sorted(validator.iter_errors(front), key=lambda e: list(e.path))
    if errors:
        print("\nFrontmatter не проходит схему:")
        for err in errors:
            where = "/".join(str(p) for p in err.path) or "(корень)"
            print(f"  {where}: {err.message}")
        return 1

    body = {
        "title": title,
        "when": when_ru,
        "when_not": when_not_ru,
        "steps": steps,
        "output": output,
        "avoid": avoid,
    }

    skill_dir = SKILLS_DIR / section / name
    skill_dir.mkdir(parents=True, exist_ok=False)
    target = skill_dir / "SKILL.md"
    target.write_text(render_skill_md(front, body), encoding="utf-8", newline="\n")

    rel = target.relative_to(ROOT)
    print(f"\nСоздано: {rel}")
    print("\nДальше:")
    print(f"  code {rel}                      — дописать детали руками")
    print(f"  python tools\\validate.py        — проверить каталог")
    print(f'  git add . ; git commit -m "feat({section}): add {name}"')
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nОтменено.")
        sys.exit(1)
