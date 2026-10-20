import logging
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.gateway.authz import permission_dependency
from app.gateway.deps import get_config
from app.gateway.path_utils import resolve_thread_virtual_path
from omniharness.agents.lead_agent.prompt import refresh_skills_system_prompt_cache_async
from omniharness.config import config_versions
from omniharness.config.app_config import AppConfig
from omniharness.config.extensions_config import ExtensionsConfig, SkillStateConfig, get_extensions_config, reload_extensions_config
from omniharness.runtime.user_context import get_effective_user_id
from omniharness.skills import Skill
from omniharness.skills.installer import SkillAlreadyExistsError
from omniharness.skills.security_scanner import scan_skill_content
from omniharness.skills.storage import get_or_new_skill_storage
from omniharness.skills.types import SKILL_MD_FILE, SkillCategory

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["skills"])


class SkillResponse(BaseModel):
    """Response model for skill information."""

    name: str = Field(..., description="Name of the skill")
    description: str = Field(..., description="Description of what the skill does")
    license: str | None = Field(None, description="License information")
    category: SkillCategory = Field(..., description="Category of the skill (public or custom)")
    enabled: bool = Field(default=True, description="Whether this skill is enabled")


class SkillsListResponse(BaseModel):
    """Response model for listing all skills."""

    skills: list[SkillResponse]


class SkillUpdateRequest(BaseModel):
    """Request model for updating a skill."""

    enabled: bool = Field(..., description="Whether to enable or disable the skill")


class SkillInstallRequest(BaseModel):
    """Request model for installing a skill from a .skill file."""

    thread_id: str = Field(..., description="The thread ID where the .skill file is located")
    path: str = Field(..., description="Virtual path to the .skill file (e.g., mnt/user-data/outputs/my-skill.skill)")


class SkillInstallResponse(BaseModel):
    """Response model for skill installation."""

    success: bool = Field(..., description="Whether the installation was successful")
    skill_name: str = Field(..., description="Name of the installed skill")
    message: str = Field(..., description="Installation result message")


class CustomSkillContentResponse(SkillResponse):
    content: str = Field(..., description="Raw SKILL.md content")
    version: int = Field(0, description="Current version in the versioned store (0: none yet); send it back as base_version")


class SkillVersionSummary(BaseModel):
    version: int
    at: str
    who: str
    source: str
    changed: list[str]
    deleted: bool


class SkillVersionsResponse(BaseModel):
    name: str
    current: int
    versions: list[SkillVersionSummary]


class SkillUndoRequest(BaseModel):
    to_version: int = Field(..., ge=1)
    base_version: int = Field(..., ge=0)


class CustomSkillUpdateRequest(BaseModel):
    content: str = Field(..., description="Replacement SKILL.md content")
    base_version: int | None = Field(None, description="The version this edit was made from; refused when it is no longer current")
    source: Literal["manual", "draft"] = Field("manual", description="manual, or draft when a one-sentence draft filled it")


class CustomSkillHistoryResponse(BaseModel):
    history: list[dict]


class SkillRollbackRequest(BaseModel):
    history_index: int = Field(default=-1, description="History entry index to restore from, defaulting to the latest change.")


def _skill_to_response(skill: Skill) -> SkillResponse:
    """Convert a Skill object to a SkillResponse."""
    return SkillResponse(
        name=skill.name,
        description=skill.description,
        license=skill.license,
        category=skill.category,
        enabled=skill.enabled,
    )


@router.get(
    "/skills",
    response_model=SkillsListResponse,
    summary="List All Skills",
    description="Retrieve a list of all available skills from both public and custom directories.",
)
async def list_skills(config: AppConfig = Depends(get_config)) -> SkillsListResponse:
    try:
        skills = get_or_new_skill_storage(app_config=config).load_skills(enabled_only=False)
        return SkillsListResponse(skills=[_skill_to_response(skill) for skill in skills])
    except Exception as e:
        logger.error(f"Failed to load skills: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to load skills: {str(e)}")


@router.post(
    "/skills/install",
    response_model=SkillInstallResponse,
    summary="Install Skill",
    description="Install a skill from a .skill file (ZIP archive) located in the thread's user-data directory.",
)
async def install_skill(request: SkillInstallRequest, config: AppConfig = Depends(get_config)) -> SkillInstallResponse:
    try:
        skill_file_path = resolve_thread_virtual_path(request.thread_id, request.path)
        storage = get_or_new_skill_storage(app_config=config)
        result = await storage.ainstall_skill_from_archive(skill_file_path)
        # The archive is unpacked by the installer (its own path checks); the
        # result is then recorded as a version, so it shows in history and
        # can be undone like any other change.
        config_versions.record_installed(result["skill_name"], who="user:" + get_effective_user_id(), storage=storage)
        await refresh_skills_system_prompt_cache_async()
        return SkillInstallResponse(**result)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except SkillAlreadyExistsError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to install skill: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to install skill: {str(e)}")


@router.get("/skills/custom", response_model=SkillsListResponse, summary="List Custom Skills")
async def list_custom_skills(config: AppConfig = Depends(get_config)) -> SkillsListResponse:
    try:
        skills = [skill for skill in get_or_new_skill_storage(app_config=config).load_skills(enabled_only=False) if skill.category == SkillCategory.CUSTOM]
        return SkillsListResponse(skills=[_skill_to_response(skill) for skill in skills])
    except Exception as e:
        logger.error("Failed to list custom skills: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to list custom skills: {str(e)}")


class CustomSkillCreateRequest(BaseModel):
    name: str = Field(..., description="Hyphen-case skill name; must match the SKILL.md frontmatter")
    content: str = Field(..., description="Full SKILL.md content, frontmatter included")
    source: Literal["manual", "draft"] = Field("manual", description="manual, or draft when a one-sentence draft filled it")


class SkillFile(BaseModel):
    path: str = Field(..., description="Path relative to the skill directory")
    size: int = Field(..., description="Size in bytes")


class SkillFilesResponse(BaseModel):
    skill_name: str
    files: list[SkillFile]


class SkillFileWriteRequest(BaseModel):
    path: str = Field(..., description="references/, templates/, scripts/ or assets/ path inside the skill")
    content: str = Field(..., max_length=512_000, description="Text content")
    base_version: int | None = Field(None, description="The version this was added from; refused when it is no longer current")


@router.post("/skills/custom", response_model=CustomSkillContentResponse, status_code=201, summary="Create Custom Skill")
async def create_custom_skill(request: CustomSkillCreateRequest, config: AppConfig = Depends(get_config)) -> CustomSkillContentResponse:
    """Skill Studio's "+ New skill": the same checks the skill_manage tool's
    create runs (frontmatter, name match, security scan, history)."""
    try:
        storage = get_or_new_skill_storage(app_config=config)
        name = storage.validate_skill_name(request.name)
        if storage.custom_skill_exists(name) or storage.public_skill_exists(name):
            raise HTTPException(status_code=409, detail=f"A skill named '{name}' already exists")
        storage.validate_skill_markdown_content(name, request.content)
        scan = await scan_skill_content(request.content, executable=False, location=f"{name}/{SKILL_MD_FILE}", app_config=config)
        if scan.decision == "block":
            raise HTTPException(status_code=400, detail=f"Security scan blocked the skill: {scan.reason}")
        config_versions.write_skill(
            name,
            {SKILL_MD_FILE: request.content},
            who="user:" + get_effective_user_id(),
            source=request.source,
            base_version=None,
            extra={
                "action": "human_create",
                "author": "human",
                "thread_id": None,
                "file_path": SKILL_MD_FILE,
                "prev_content": None,
                "new_content": request.content,
                "scanner": {"decision": scan.decision, "reason": scan.reason},
            },
            storage=storage,
        )
        await refresh_skills_system_prompt_cache_async()
        return await get_custom_skill(name, config)
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("Failed to create custom skill %s: %s", request.name, e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to create custom skill: {str(e)}")


@router.get("/skills/custom/{skill_name}/files", response_model=SkillFilesResponse, summary="List a Custom Skill's Files")
async def list_custom_skill_files(skill_name: str, config: AppConfig = Depends(get_config)) -> SkillFilesResponse:
    storage = get_or_new_skill_storage(app_config=config)
    try:
        name = storage.validate_skill_name(skill_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not storage.custom_skill_exists(name):
        raise HTTPException(status_code=404, detail=f"Custom skill '{name}' not found")
    root = storage.get_custom_skill_dir(name)
    files = [
        SkillFile(path=str(path.relative_to(root)), size=path.stat().st_size) for path in sorted(root.rglob("*")) if path.is_file() and path.name != SKILL_MD_FILE and not any(part.startswith(".") for part in path.relative_to(root).parts)
    ]
    return SkillFilesResponse(skill_name=name, files=files)


@router.post("/skills/custom/{skill_name}/files", response_model=SkillFilesResponse, summary="Add a File to a Custom Skill")
async def write_custom_skill_file(skill_name: str, request: SkillFileWriteRequest, config: AppConfig = Depends(get_config)) -> SkillFilesResponse:
    """A script, reference or template next to SKILL.md. Scripts are scanned as
    executable; a blocked scan writes nothing."""
    storage = get_or_new_skill_storage(app_config=config)
    try:
        name = storage.validate_skill_name(skill_name)
        storage.ensure_custom_skill_is_editable(name)
        target = storage.ensure_safe_support_path(name, request.path)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    executable = request.path.startswith("scripts/")
    scan = await scan_skill_content(request.content, executable=executable, location=f"{name}/{request.path}", app_config=config)
    if scan.decision == "block":
        raise HTTPException(status_code=400, detail=f"Security scan blocked the file: {scan.reason}")
    prev = target.read_text(encoding="utf-8") if target.exists() else None
    try:
        _write_file_version(name, request, prev, scan, storage)
    except config_versions.StaleWriteError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return await list_custom_skill_files(name, config)


def _write_file_version(name: str, request: SkillFileWriteRequest, prev: str | None, scan, storage) -> None:
    config_versions.write_skill(
        name,
        {request.path: request.content},
        who="user:" + get_effective_user_id(),
        source="manual",
        base_version=request.base_version,
        extra={
            "action": "human_file",
            "author": "human",
            "thread_id": None,
            "file_path": request.path,
            "prev_content": prev,
            "new_content": request.content,
            "scanner": {"decision": scan.decision, "reason": scan.reason},
        },
        storage=storage,
    )


@router.get("/skills/custom/{skill_name}", response_model=CustomSkillContentResponse, summary="Get Custom Skill Content")
async def get_custom_skill(skill_name: str, config: AppConfig = Depends(get_config)) -> CustomSkillContentResponse:
    try:
        skill_name = skill_name.replace("\r\n", "").replace("\n", "")
        skills = get_or_new_skill_storage(app_config=config).load_skills(enabled_only=False)
        skill = next((s for s in skills if s.name == skill_name and s.category == SkillCategory.CUSTOM), None)
        if skill is None:
            raise HTTPException(status_code=404, detail=f"Custom skill '{skill_name}' not found")
        storage = get_or_new_skill_storage(app_config=config)
        return CustomSkillContentResponse(**_skill_to_response(skill).model_dump(), content=storage.read_custom_skill(skill_name), version=config_versions.skill_version(skill_name, storage))
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get custom skill %s: %s", skill_name, e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get custom skill: {str(e)}")


@router.put("/skills/custom/{skill_name}", response_model=CustomSkillContentResponse, summary="Edit Custom Skill")
async def update_custom_skill(skill_name: str, request: CustomSkillUpdateRequest, config: AppConfig = Depends(get_config)) -> CustomSkillContentResponse:
    try:
        skill_name = skill_name.replace("\r\n", "").replace("\n", "")
        storage = get_or_new_skill_storage(app_config=config)
        storage.ensure_custom_skill_is_editable(skill_name)
        storage.validate_skill_markdown_content(skill_name, request.content)
        scan = await scan_skill_content(request.content, executable=False, location=f"{skill_name}/{SKILL_MD_FILE}", app_config=config)
        if scan.decision == "block":
            raise HTTPException(status_code=400, detail=f"Security scan blocked the edit: {scan.reason}")
        prev_content = storage.read_custom_skill(skill_name)
        config_versions.write_skill(
            skill_name,
            {SKILL_MD_FILE: request.content},
            who="user:" + get_effective_user_id(),
            source=request.source,
            base_version=request.base_version,
            extra={
                "action": "human_edit",
                "author": "human",
                "thread_id": None,
                "file_path": SKILL_MD_FILE,
                "prev_content": prev_content,
                "new_content": request.content,
                "scanner": {"decision": scan.decision, "reason": scan.reason},
            },
            storage=storage,
        )
        await refresh_skills_system_prompt_cache_async()
        return await get_custom_skill(skill_name, config)
    except HTTPException:
        raise
    except config_versions.StaleWriteError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("Failed to update custom skill %s: %s", skill_name, e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to update custom skill: {str(e)}")


@router.delete("/skills/custom/{skill_name}", summary="Delete Custom Skill", dependencies=[Depends(permission_dependency("threads", "delete"))])
async def delete_custom_skill(skill_name: str, config: AppConfig = Depends(get_config)) -> dict[str, bool]:
    try:
        skill_name = skill_name.replace("\r\n", "").replace("\n", "")
        storage = get_or_new_skill_storage(app_config=config)
        storage.ensure_custom_skill_is_editable(skill_name)
        # A version too: a deleted skill can be brought back with undo.
        config_versions.write_skill(
            skill_name,
            None,
            who="user:" + get_effective_user_id(),
            source="manual",
            extra={
                "action": "human_delete",
                "author": "human",
                "thread_id": None,
                "file_path": SKILL_MD_FILE,
                "prev_content": storage.read_custom_skill(skill_name),
                "new_content": None,
                "scanner": {"decision": "allow", "reason": "Deletion requested."},
            },
            storage=storage,
        )
        await refresh_skills_system_prompt_cache_async()
        return {"success": True}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("Failed to delete custom skill %s: %s", skill_name, e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to delete custom skill: {str(e)}")


@router.get("/skills/custom/{skill_name}/history", response_model=CustomSkillHistoryResponse, summary="Get Custom Skill History")
async def get_custom_skill_history(skill_name: str, config: AppConfig = Depends(get_config)) -> CustomSkillHistoryResponse:
    try:
        skill_name = skill_name.replace("\r\n", "").replace("\n", "")
        storage = get_or_new_skill_storage(app_config=config)
        if not storage.custom_skill_exists(skill_name) and not storage.get_skill_history_file(skill_name).exists():
            raise HTTPException(status_code=404, detail=f"Custom skill '{skill_name}' not found")
        return CustomSkillHistoryResponse(history=storage.read_history(skill_name))
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to read history for %s: %s", skill_name, e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to read history: {str(e)}")


@router.post("/skills/custom/{skill_name}/rollback", response_model=CustomSkillContentResponse, summary="Rollback Custom Skill")
async def rollback_custom_skill(skill_name: str, request: SkillRollbackRequest, config: AppConfig = Depends(get_config)) -> CustomSkillContentResponse:
    try:
        storage = get_or_new_skill_storage(app_config=config)
        if not storage.custom_skill_exists(skill_name) and not storage.get_skill_history_file(skill_name).exists():
            raise HTTPException(status_code=404, detail=f"Custom skill '{skill_name}' not found")
        history = storage.read_history(skill_name)
        if not history:
            raise HTTPException(status_code=400, detail=f"Custom skill '{skill_name}' has no history")
        record = history[request.history_index]
        target_content = record.get("prev_content")
        if target_content is None:
            raise HTTPException(status_code=400, detail="Selected history entry has no previous content to roll back to")
        storage.validate_skill_markdown_content(skill_name, target_content)
        scan = await scan_skill_content(target_content, executable=False, location=f"{skill_name}/{SKILL_MD_FILE}", app_config=config)
        skill_file = storage.get_custom_skill_file(skill_name)
        current_content = skill_file.read_text(encoding="utf-8") if skill_file.exists() else None
        history_entry = {
            "action": "rollback",
            "author": "human",
            "thread_id": None,
            "file_path": SKILL_MD_FILE,
            "prev_content": current_content,
            "new_content": target_content,
            "rollback_from_ts": record.get("ts"),
            "scanner": {"decision": scan.decision, "reason": scan.reason},
        }
        if scan.decision == "block":
            storage.append_history(skill_name, history_entry)
            raise HTTPException(status_code=400, detail=f"Rollback blocked by security scanner: {scan.reason}")
        config_versions.write_skill(skill_name, {SKILL_MD_FILE: target_content}, who="user:" + get_effective_user_id(), source="undo", extra=history_entry, storage=storage)
        await refresh_skills_system_prompt_cache_async()
        return await get_custom_skill(skill_name, config)
    except HTTPException:
        raise
    except IndexError:
        raise HTTPException(status_code=400, detail="history_index is out of range")
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("Failed to roll back custom skill %s: %s", skill_name, e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to roll back custom skill: {str(e)}")


@router.get("/skills/custom/{skill_name}/versions", response_model=SkillVersionsResponse, summary="A custom skill's version history")
async def custom_skill_versions(skill_name: str, config: AppConfig = Depends(get_config)) -> SkillVersionsResponse:
    storage = get_or_new_skill_storage(app_config=config)
    try:
        name = storage.validate_skill_name(skill_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    versions = config_versions.skill_history(name, storage)
    return SkillVersionsResponse(name=name, current=versions[-1].version if versions else 0, versions=[SkillVersionSummary(**v.summary()) for v in reversed(versions)])


@router.post("/skills/custom/{skill_name}/undo", response_model=SkillVersionsResponse, summary="Restore an earlier version of a custom skill as a new one")
async def undo_custom_skill(skill_name: str, request: SkillUndoRequest, config: AppConfig = Depends(get_config)) -> SkillVersionsResponse:
    storage = get_or_new_skill_storage(app_config=config)
    try:
        name = storage.validate_skill_name(skill_name)
        config_versions.undo("skill", name, request.to_version, who="user:" + get_effective_user_id(), base_version=request.base_version, storage=storage)
    except config_versions.StaleWriteError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except config_versions.VersionNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await refresh_skills_system_prompt_cache_async()
    return await custom_skill_versions(name, config)


@router.get(
    "/skills/{skill_name}",
    response_model=SkillResponse,
    summary="Get Skill Details",
    description="Retrieve detailed information about a specific skill by its name.",
)
async def get_skill(skill_name: str, config: AppConfig = Depends(get_config)) -> SkillResponse:
    try:
        skill_name = skill_name.replace("\r\n", "").replace("\n", "")
        skills = get_or_new_skill_storage(app_config=config).load_skills(enabled_only=False)
        skill = next((s for s in skills if s.name == skill_name), None)

        if skill is None:
            raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' not found")

        return _skill_to_response(skill)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get skill {skill_name}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get skill: {str(e)}")


@router.put(
    "/skills/{skill_name}",
    response_model=SkillResponse,
    summary="Update Skill",
    description="Update a skill's enabled status by modifying the extensions_config.json file.",
)
async def update_skill(skill_name: str, request: SkillUpdateRequest, config: AppConfig = Depends(get_config)) -> SkillResponse:
    try:
        skill_name = skill_name.replace("\r\n", "").replace("\n", "")
        skills = get_or_new_skill_storage(app_config=config).load_skills(enabled_only=False)
        skill = next((s for s in skills if s.name == skill_name), None)

        if skill is None:
            raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' not found")

        config_path = ExtensionsConfig.resolve_config_path()
        if config_path is None:
            config_path = Path.cwd().parent / "extensions_config.json"
            logger.info(f"No existing extensions config found. Creating new config at: {config_path}")

        extensions_config = get_extensions_config()
        extensions_config.skills[skill_name] = SkillStateConfig(enabled=request.enabled)

        config_data = {
            "mcpServers": {name: server.model_dump() for name, server in extensions_config.mcp_servers.items()},
            "skills": {name: {"enabled": skill_config.enabled} for name, skill_config in extensions_config.skills.items()},
        }

        from omniharness.config.extensions_config import atomic_write_json

        atomic_write_json(config_path, config_data)

        logger.info(f"Skills configuration updated and saved to: {config_path}")
        reload_extensions_config()
        await refresh_skills_system_prompt_cache_async()

        skills = get_or_new_skill_storage(app_config=config).load_skills(enabled_only=False)
        updated_skill = next((s for s in skills if s.name == skill_name), None)

        if updated_skill is None:
            raise HTTPException(status_code=500, detail=f"Failed to reload skill '{skill_name}' after update")

        logger.info(f"Skill '{skill_name}' enabled status updated to {request.enabled}")
        return _skill_to_response(updated_skill)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update skill {skill_name}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to update skill: {str(e)}")
