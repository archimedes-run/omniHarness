"""Skill frontmatter validation utilities.

Pure-logic validation of SKILL.md frontmatter — no FastAPI or HTTP dependencies.
"""

import re
from pathlib import Path

import yaml

from omniharness.skills.parser import parse_allowed_tools
from omniharness.skills.types import SKILL_MD_FILE

# Size limits for a custom skill (review round 2, 2026-10-20). Every version
# stores the skill's whole text (config_versions), and SKILL.md's description
# is shown to the model on every run, so both are kept small:
#   SKILL.md      at most 64 KiB (UTF-8 bytes)
#   files         at most 50 per skill, SKILL.md included
#   total         at most 2 MiB across the skill's files
MAX_SKILL_MD_BYTES = 64 * 1024
MAX_SKILL_FILES = 50
MAX_SKILL_TOTAL_BYTES = 2 * 1024 * 1024


class SkillLimitError(ValueError):
    """A skill over its size or file-count limits, in words the user can act on."""


def check_skill_limits(name: str, sizes: dict[str, int]) -> None:
    """Refuse a skill whose files ({relative path: bytes}) break a limit."""
    if len(sizes) > MAX_SKILL_FILES:
        raise SkillLimitError(f"skill '{name}' would have {len(sizes)} files; a skill may have at most {MAX_SKILL_FILES}, {SKILL_MD_FILE} included")
    skill_md = sizes.get(SKILL_MD_FILE, 0)
    if skill_md > MAX_SKILL_MD_BYTES:
        raise SkillLimitError(f"{SKILL_MD_FILE} of skill '{name}' is {skill_md:,} bytes; it may be at most {MAX_SKILL_MD_BYTES:,} (64 KiB). Move detail into references/ files.")
    total = sum(sizes.values())
    if total > MAX_SKILL_TOTAL_BYTES:
        raise SkillLimitError(f"skill '{name}' would hold {total:,} bytes; a skill may hold at most {MAX_SKILL_TOTAL_BYTES:,} (2 MiB)")


def skill_dir_sizes(skill_dir: Path) -> dict[str, int]:
    """{relative path: bytes} for every file under a skill directory."""
    return {path.relative_to(skill_dir).as_posix(): path.stat().st_size for path in skill_dir.rglob("*") if path.is_file()}


# Allowed properties in SKILL.md frontmatter
ALLOWED_FRONTMATTER_PROPERTIES = {"name", "description", "license", "allowed-tools", "metadata", "compatibility", "version", "author"}


def _validate_skill_frontmatter(skill_dir: Path) -> tuple[bool, str, str | None]:
    """Validate a skill directory's SKILL.md frontmatter.

    Args:
        skill_dir: Path to the skill directory containing SKILL.md.

    Returns:
        Tuple of (is_valid, message, skill_name).
    """
    skill_md = skill_dir / SKILL_MD_FILE
    if not skill_md.exists():
        return False, f"{SKILL_MD_FILE} not found", None

    content = skill_md.read_text(encoding="utf-8")
    if not content.startswith("---"):
        return False, "No YAML frontmatter found", None

    # Extract frontmatter
    match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
    if not match:
        return False, "Invalid frontmatter format", None

    frontmatter_text = match.group(1)

    # Parse YAML frontmatter
    try:
        frontmatter = yaml.safe_load(frontmatter_text)
        if not isinstance(frontmatter, dict):
            return False, "Frontmatter must be a YAML dictionary", None
    except yaml.YAMLError as e:
        return False, f"Invalid YAML in frontmatter: {e}", None

    # Check for unexpected properties
    unexpected_keys = set(frontmatter.keys()) - ALLOWED_FRONTMATTER_PROPERTIES
    if unexpected_keys:
        return False, f"Unexpected key(s) in SKILL.md frontmatter: {', '.join(sorted(unexpected_keys))}", None

    # Check required fields
    if "name" not in frontmatter:
        return False, "Missing 'name' in frontmatter", None
    if "description" not in frontmatter:
        return False, "Missing 'description' in frontmatter", None

    # Validate name
    name = frontmatter.get("name", "")
    if not isinstance(name, str):
        return False, f"Name must be a string, got {type(name).__name__}", None
    name = name.strip()
    if not name:
        return False, "Name cannot be empty", None

    # Check naming convention (hyphen-case: lowercase with hyphens)
    if not re.match(r"^[a-z0-9-]+$", name):
        return False, f"Name '{name}' should be hyphen-case (lowercase letters, digits, and hyphens only)", None
    if name.startswith("-") or name.endswith("-") or "--" in name:
        return False, f"Name '{name}' cannot start/end with hyphen or contain consecutive hyphens", None
    if len(name) > 64:
        return False, f"Name is too long ({len(name)} characters). Maximum is 64 characters.", None

    # Validate description
    description = frontmatter.get("description", "")
    if not isinstance(description, str):
        return False, f"Description must be a string, got {type(description).__name__}", None
    description = description.strip()
    if description:
        if "<" in description or ">" in description:
            return False, "Description cannot contain angle brackets (< or >)", None
        if len(description) > 1024:
            return False, f"Description is too long ({len(description)} characters). Maximum is 1024 characters.", None

    try:
        parse_allowed_tools(frontmatter.get("allowed-tools"), skill_md)
    except ValueError as e:
        return False, str(e).replace(str(skill_md), SKILL_MD_FILE), None

    return True, "Skill is valid!", name
