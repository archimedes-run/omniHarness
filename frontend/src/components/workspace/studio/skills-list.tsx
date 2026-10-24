"use client";

import { useQueries } from "@tanstack/react-query";
import {
  BookOpenIcon,
  BotIcon,
  FileIcon,
  PlusIcon,
  SearchIcon,
  SparklesIcon,
} from "lucide-react";
import { useMemo, useRef, useState } from "react";

import { useAgents, type Agent } from "@/core/agents";
import { useSkills } from "@/core/skills/hooks";
import type { Skill } from "@/core/skills/type";
import { loadSkillFiles, loadSkillStudio } from "@/core/studio";

import { agentTitle } from "./agents-list";
import { useStudioCopy } from "./copy";
import { Glyph, skillLook } from "./parts";
import { ListHead, useStudio } from "./studio";

/** "project-status-format" -> "Project status format". */
export function skillTitle(name: string) {
  const words = name.replace(/[-_]+/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** The agents that may load a skill (an agent with no list loads every
 * enabled skill). */
export function usersOf(
  skill: Pick<Skill, "name" | "enabled">,
  agents: Agent[],
): Agent[] {
  return agents.filter((a) =>
    a.skills === null ? skill.enabled : a.skills.includes(skill.name),
  );
}

/** The Skills list (design: 14 skills list). */
export function SkillsList() {
  const c = useStudioCopy();
  const studio = useStudio();
  const { skills, isLoading, error } = useSkills();
  const { agents } = useAgents();
  const [q, setQ] = useState("");
  const search = useRef<HTMLInputElement>(null);
  const custom = useMemo(
    () => skills.filter((s) => s.category === "custom"),
    [skills],
  );
  const looks = useQueries({
    queries: custom.map((s) => ({
      queryKey: ["skills", "studio", s.name],
      queryFn: () => loadSkillStudio(s.name),
      staleTime: 60_000,
    })),
  });
  const files = useQueries({
    queries: custom.map((s) => ({
      queryKey: ["skills", "files", s.name],
      queryFn: () => loadSkillFiles(s.name),
      staleTime: 60_000,
    })),
  });
  const needle = q.trim().toLowerCase();
  const shown = skills.filter(
    (s) =>
      !needle || `${s.name} ${s.description}`.toLowerCase().includes(needle),
  );

  const onKeyDown = (e: React.KeyboardEvent) => {
    const typing = /INPUT|TEXTAREA|SELECT/.test(
      (e.target as HTMLElement).tagName,
    );
    if (typing || e.metaKey || e.ctrlKey || e.altKey) return;
    if (e.key === "/") {
      e.preventDefault();
      search.current?.focus();
    } else if (e.key === "n" || e.key === "N") {
      e.preventDefault();
      studio.go({ view: "skill", id: null });
    }
  };

  let content;
  if (isLoading) content = <p className="help">{c.skills.loading}</p>;
  else if (error)
    content = (
      <p className="err" role="alert">
        {c.skills.loadFailed(error.message)}
      </p>
    );
  else if (needle && !shown.length)
    content = <div className="empty-search">{c.skills.noMatch(q)}</div>;
  else
    content = (
      <div className="cards" data-testid="skill-cards">
        {shown.map((s) => {
          const i = custom.findIndex((x) => x.name === s.name);
          const record = i >= 0 ? looks[i]?.data : undefined;
          const look = skillLook(s.name, record?.icon, record?.color);
          const nFiles = i >= 0 ? (files[i]?.data?.files.length ?? 0) : 0;
          const users = usersOf(s, agents).map(agentTitle);
          const title = skillTitle(s.name);
          return (
            <button
              key={s.name}
              type="button"
              className="acard"
              onClick={() => studio.go({ view: "skill", id: s.name })}
              aria-label={c.skills.editAria(title)}
              data-testid={`skill-card-${s.name}`}
            >
              <div className="top">
                <Glyph icon={look.icon} color={look.color} />
                <div className="grow">
                  <div
                    className="row"
                    style={{ justifyContent: "space-between", gap: 8 }}
                  >
                    <span className="nm">{title}</span>
                    {s.category !== "custom" ? (
                      <span className="pill muted">{c.skills.builtIn}</span>
                    ) : null}
                  </div>
                  <div className="pp" style={{ marginTop: 4 }}>
                    {s.description}
                  </div>
                </div>
              </div>
              <div className="meta">
                <BotIcon size={14} aria-hidden />
                <span className="grow">
                  {users.length
                    ? c.skills.usedBy(c.and(users))
                    : c.skills.notUsed}
                </span>
                {nFiles ? (
                  <span title={c.skills.files(nFiles)}>
                    <FileIcon size={13} aria-hidden /> {nFiles}
                  </span>
                ) : null}
              </div>
            </button>
          );
        })}
        <button
          type="button"
          className="acard new"
          onClick={() => studio.go({ view: "skill", id: null })}
          data-testid="skill-teach-new"
        >
          <SparklesIcon size={22} aria-hidden />
          <b style={{ fontWeight: 600 }}>{c.skills.teachTitle}</b>
          <span className="help">{c.skills.teachBody}</span>
        </button>
      </div>
    );

  return (
    <div className="contents" onKeyDown={onKeyDown}>
      <ListHead
        which="skills"
        title={c.skills.title}
        subtitle={c.skills.subtitle}
        icon={<BookOpenIcon size={18} />}
      />
      <div className="m-body" data-testid="skills-list">
        <div className="toolbar">
          <label className="with-ico">
            <SearchIcon size={15} aria-hidden />
            <span className="sr-only">{c.skills.search}</span>
            <input
              ref={search}
              className="input"
              type="search"
              placeholder={c.skills.search}
              value={q}
              onChange={(e) => setQ(e.target.value)}
              data-testid="skills-search"
            />
          </label>
          <span className="grow" />
          <button
            type="button"
            className="btn solid"
            onClick={() => studio.go({ view: "skill", id: null })}
            data-testid="skills-new"
          >
            <PlusIcon size={16} aria-hidden />
            {c.skills.newSkill}
          </button>
        </div>
        {content}
      </div>
      <footer className="m-foot">
        <span className="hint">{c.skills.footer}</span>
      </footer>
    </div>
  );
}
