"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  LEAD_AGENT_ID,
  avatarIdFor,
  avatarMeta,
  createAgent,
  randomAvatar,
  updateAgent,
  useAgents,
  type Agent,
} from "@/core/agents";
import { browserZone } from "@/core/automations/schedule";
import {
  agentStatus,
  allowlistOf,
  createSchedule,
  deleteSchedule,
  draft,
  draftedSelection,
  legacySelection,
  loadAgentRuns,
  loadChannels,
  saveAutonomy,
  selectionOf,
  skillSlug,
  undoTo,
  updateSchedule,
  useAgentRuns,
  useAutonomy,
  useToolCatalog,
  type AgentDraft,
} from "@/core/studio";

import { AgentConfigStep, type ConfigPanel } from "./agent-config";
import {
  agentFields,
  anyDirty,
  formOf,
  rowsOf,
  scheduleChanges,
  stepDirty,
  type AgentForm,
  type SchedRow,
} from "./agent-form";
import {
  AgentReviewStep,
  AgentScheduleStep,
  AgentSetupStep,
} from "./agent-steps";
import { agentTitle } from "./agents-list";
import { useStudioCopy } from "./copy";
import { Av, StatusPill } from "./parts";
import { useStudio } from "./studio";
import {
  FootLeft,
  NextButton,
  SaveButton,
  WizardShell,
  useWizardShortcuts,
} from "./wizard-shell";

function blankForm(avatar: string): AgentForm {
  return {
    avatar,
    name: "",
    sentence: "",
    instructions: "",
    selection: null,
    toolsTouched: true,
    skills: [],
    grants: [],
    schedules: [],
    notify: { telegram: true, home: true },
  };
}

function errorText(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

/**
 * The Agent stepper (design 03-13): Agent Setup, Configuration, Schedule,
 * Notifications & review. A new agent walks the steps; an existing one opens
 * with every step reachable, marks what is unsaved, and saves from any step
 * (⌘S). Nothing is written until Save; Save writes the agent (one version),
 * then its grants (the Autonomy action), then its schedules (006-F routes).
 */
export function AgentWizard({
  id,
  initialStep,
  initialPanel,
  initialSentence,
}: {
  id: string | null;
  initialStep?: number;
  initialPanel?: string;
  initialSentence?: string;
}) {
  const c = useStudioCopy();
  const studio = useStudio();
  const queryClient = useQueryClient();
  const isNew = id === null;
  const isLead = id === LEAD_AGENT_ID;
  const { agents, isLoading: agentsLoading } = useAgents();
  const agent: Agent | null =
    isNew || isLead ? null : (agents.find((a) => a.name === id) ?? null);
  const { runs, isLoading: runsLoading } = useAgentRuns(isNew ? null : id);
  const { autonomy, error: autonomyError } = useAutonomy(
    isNew ? LEAD_AGENT_ID : id,
  );
  const { catalog, error: catalogError } = useToolCatalog(!isLead);
  const { data: channels } = useQuery({
    queryKey: ["channels"],
    queryFn: loadChannels,
    staleTime: 60_000,
    retry: false,
  });

  const [orig, setOrig] = useState<AgentForm | null>(() =>
    isNew ? blankForm(randomAvatar()) : null,
  );
  const [form, setForm] = useState<AgentForm | null>(() =>
    orig ? { ...orig, sentence: initialSentence ?? "" } : null,
  );
  const [step, setStep] = useState(Math.min(4, Math.max(1, initialStep ?? 1)));
  const [reached, setReached] = useState(
    isNew ? Math.max(1, initialStep ?? 1) : 4,
  );
  const [panel, setPanel] = useState<ConfigPanel>(
    initialPanel === "skills" || initialPanel === "autonomy"
      ? initialPanel
      : "integrations",
  );
  const [drafted, setDrafted] = useState<{
    before: AgentForm;
    suggestedGrants: string[];
    dropped: string[];
  } | null>(null);
  const [drafting, setDrafting] = useState(false);
  const [draftError, setDraftError] = useState<string | null>(null);
  const [nameError, setNameError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [leaving, setLeaving] = useState<null | (() => void)>(null);
  /** Inner overlays Esc closes first: the avatar picker, the schedule editor. */
  const inner = useRef<{ picker: boolean; editor: boolean; close: () => void }>(
    { picker: false, editor: false, close: () => undefined },
  );

  // Build the working copy once what it is read from has arrived.
  useEffect(() => {
    if (orig || isNew) return;
    if (isLead) {
      if (!autonomy || runsLoading) return;
      const base: AgentForm = {
        ...blankForm("merlo"),
        name: c.agents.lead,
        sentence: c.agents.leadPurpose,
        toolsTouched: false,
        skills: null,
        grants: autonomy.classes.filter((k) => k.granted).map((k) => k.id),
        schedules: rowsOf(runs?.schedules ?? []),
      };
      setOrig(base);
      setForm(base);
      return;
    }
    if (!agent || !autonomy || runsLoading) return;
    const base = formOf(
      {
        ...agent,
        display_name: agentTitle(agent),
      },
      avatarIdFor(agent.name, agent.avatar),
      autonomy.classes.filter((k) => k.granted).map((k) => k.id),
      rowsOf(runs?.schedules ?? []),
    );
    setOrig(base);
    setForm(base);
  }, [
    orig,
    isNew,
    isLead,
    agent,
    autonomy,
    runs,
    runsLoading,
    c.agents.lead,
    c.agents.leadPurpose,
  ]);

  // The tool ticks, once the catalog is here.
  useEffect(() => {
    if (!catalog || !orig || orig.selection) return;
    const selection = isNew
      ? {}
      : agent?.tools
        ? selectionOf(agent.tools, catalog)
        : legacySelection(agent?.tool_groups ?? null, catalog);
    setOrig((o) => (o ? { ...o, selection } : o));
    setForm((f) => (f ? { ...f, selection: f.selection ?? selection } : f));
  }, [catalog, orig, isNew, agent]);

  const dirty = !!form && !!orig && !isNew && anyDirty(form, orig);
  const started =
    !!form &&
    isNew &&
    !!(form.name.trim() || form.sentence.trim() || form.instructions.trim());

  const patch = useCallback((next: Partial<AgentForm>) => {
    setForm((f) => (f ? { ...f, ...next } : f));
    setSaveError(null);
  }, []);

  const goList = useCallback(() => studio.go({ view: "agents" }), [studio]);

  // -- leaving ------------------------------------------------------------
  /** Set once the person chose (Discard, or a save that went through): the
   * navigation that follows is not asked about again. */
  const bypass = useRef(false);
  const requestLeave = useCallback(
    (then: () => void) => {
      if (!bypass.current && (dirty || started)) setLeaving(() => then);
      else then();
    },
    [dirty, started],
  );
  useEffect(() => {
    studio.registerEditor({
      escape: () => {
        if (inner.current.picker || inner.current.editor) {
          inner.current.close();
          return true;
        }
        return false;
      },
      requestLeave,
      dirty: () => dirty || started,
    });
    return () => studio.registerEditor(null);
  }, [studio, requestLeave, dirty, started]);

  // -- draft from one sentence ----------------------------------------------
  const runDraft = useCallback(async () => {
    if (!form) return;
    const sentence = form.sentence.trim();
    if (!sentence) {
      setDraftError(c.agent.draftNeedsSentence);
      return;
    }
    setDraftError(null);
    setDrafting(true);
    try {
      const result = await draft("agent", {
        sentence,
        agent_name: isNew || isLead ? null : id,
      });
      const d: AgentDraft = result.agent!;
      const before = drafted?.before ?? form;
      const selection =
        catalog && d.integrations?.length
          ? draftedSelection(d.integrations, catalog)
          : form.selection;
      const schedules: SchedRow[] = d.schedule
        ? [
            ...form.schedules.filter((s) => s.ruleId),
            {
              key: `draft-${Date.now()}`,
              ruleId: null,
              cron: d.schedule.cron,
              timezone: d.schedule.timezone ?? browserZone(),
              prompt: sentence,
              name: "",
              telegram: form.notify.telegram,
              home: form.notify.home,
              enabled: true,
              nextRun: null,
              heldUntil: null,
            },
          ]
        : form.schedules;
      setForm({
        ...form,
        name: form.name.trim() ? form.name : d.display_name,
        instructions: d.instructions,
        selection,
        toolsTouched:
          form.toolsTouched || !!(catalog && d.integrations?.length),
        skills: d.skills.length ? d.skills : form.skills,
        schedules: isLead ? form.schedules : schedules,
      });
      setDrafted({
        before,
        suggestedGrants: d.autonomy ?? [],
        dropped: result.dropped,
      });
      if (isNew) setReached(4);
    } catch (e) {
      setDraftError(c.agent.draftFailed(errorText(e)));
    } finally {
      setDrafting(false);
    }
  }, [form, drafted, catalog, isNew, isLead, id, c.agent]);

  const undoDraft = () => {
    if (!drafted || !form) return;
    setForm({ ...drafted.before, avatar: form.avatar });
    setDrafted(null);
    if (isNew) setReached(Math.max(1, step));
  };

  // -- save -------------------------------------------------------------------
  const save = useCallback(async (): Promise<boolean> => {
    if (!form || !orig || saving) return false;
    if (isLead && !anyDirty(form, orig)) return true;
    if (!isLead && !form.name.trim()) {
      setNameError(c.agent.nameSaveNeeded);
      setStep(1);
      return false;
    }
    if (!isNew && !anyDirty(form, orig)) return true;
    setSaving(true);
    setSaveError(null);
    const tools =
      catalog && form.selection && form.toolsTouched
        ? allowlistOf(form.selection, catalog, agent?.tools ?? null)
        : null;
    let name = id ?? "";
    let savedAgent = false;
    try {
      let version = isNew ? 0 : (agent?.version ?? autonomy?.version ?? 0);
      const before = agent?.version ?? 0;
      if (isNew) {
        const slug = skillSlug(form.name) || "agent";
        const created = await createAgent({
          name: slug,
          ...(agentFields(form, null, tools) as object),
          source: drafted ? "draft" : "manual",
        });
        name = created.name;
        version = created.version ?? 1;
      } else if (!isLead) {
        const fields = agentFields(form, orig, tools);
        if (Object.keys(fields).length) {
          const saved = await updateAgent(name, {
            ...fields,
            base_version: agent?.version ?? 0,
            source: drafted ? "draft" : "manual",
          });
          version = saved.version ?? version;
        }
      }
      savedAgent = true;
      const grantsChanged =
        [...form.grants].sort().join() !== [...orig.grants].sort().join();
      if (grantsChanged) {
        const base = isLead ? (autonomy?.version ?? 0) : version;
        const view = await saveAutonomy(name, form.grants, base);
        version = view.version;
      }
      const changes = scheduleChanges(form.schedules, orig.schedules);
      if (changes.length) {
        let rules = isNew
          ? (await loadAgentRuns(name)).rules_version
          : runs?.rules_version;
        if (!rules) throw new Error(c.agent.notWritable);
        for (const change of changes) {
          if (change.kind === "create")
            rules = (
              await createSchedule(name, { ...change.body, version: rules })
            ).version;
          else if (change.kind === "update")
            rules = (
              await updateSchedule(name, change.ruleId, {
                ...change.body,
                version: rules,
              })
            ).version;
          else
            rules = (await deleteSchedule(name, change.ruleId, rules)).version;
        }
      }
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["agents"] }),
        queryClient.invalidateQueries({ queryKey: ["studio"] }),
        queryClient.invalidateQueries({ queryKey: ["triggerRules"] }),
        queryClient.invalidateQueries({ queryKey: ["home", "upcoming"] }),
      ]);
      const label = form.name.trim() || c.agents.lead;
      if (isNew) {
        studio.toast(c.agent.created(label));
        return true;
      }
      // What is saved now is the new baseline; schedules come back from the
      // engine with their rule ids (a new one has none until it is written).
      let saved = form;
      if (changes.length) {
        const rows = rowsOf((await loadAgentRuns(name)).schedules);
        saved = { ...form, schedules: rows };
        setForm((f) => (f ? { ...f, schedules: rows } : f));
      }
      setOrig(saved);
      setDrafted(null);
      const undo =
        !isLead && before > 0 && version > before
          ? () =>
              void (async () => {
                try {
                  await undoTo("agent", name, before, version);
                  await queryClient.invalidateQueries({ queryKey: ["agents"] });
                  setOrig(null);
                  setForm(null);
                  studio.toast(c.agent.undone);
                } catch (e) {
                  studio.toast(c.agent.saveFailed(errorText(e)));
                }
              })()
          : undefined;
      studio.toast(c.agent.saved(label), undo);
      return true;
    } catch (e) {
      const stale =
        (e as { status?: number }).status === 409 ||
        errorText(e).includes("changed since you opened it");
      const why = stale ? c.agent.stale : errorText(e);
      setSaveError(
        savedAgent ? c.agent.partlySaved(why) : c.agent.saveFailed(why),
      );
      await queryClient.invalidateQueries({ queryKey: ["studio", "runs"] });
      if (savedAgent && isNew) {
        // The agent exists now: continue as an edit of it.
        bypass.current = true;
        studio.go({ view: "agent", id: name, step });
      }
      return false;
    } finally {
      setSaving(false);
    }
  }, [
    form,
    orig,
    saving,
    isLead,
    isNew,
    catalog,
    agent,
    id,
    autonomy,
    drafted,
    runs,
    queryClient,
    studio,
    step,
    c,
  ]);

  const saveAndThen = useCallback(
    async (then?: () => void) => {
      const ok = await save();
      if (ok && isNew) {
        bypass.current = true;
        goList();
      } else if (ok && then) then();
    },
    [save, isNew, goList],
  );

  // -- steps --------------------------------------------------------------
  const goStep = (n: number) => {
    if (isNew && n > reached && n > step + 1) return;
    if (n > step && step === 1 && !isLead && !form?.name.trim()) {
      setNameError(c.agent.nameNeeded);
      return;
    }
    setNameError(null);
    if (isNew) setReached((r) => Math.max(r, n));
    setStep(n);
  };
  const next = () => (step < 4 ? goStep(step + 1) : undefined);

  useWizardShortcuts(
    () => void saveAndThen(),
    () => {
      if (step < 4) next();
    },
  );

  // -- render ---------------------------------------------------------------
  if (!form || !orig) {
    const gone = !isNew && !isLead && !agentsLoading && !agent;
    return (
      <div className="contents" data-testid="agent-wizard-loading">
        <div className="m-body">
          <p className={gone ? "err" : "help"} role={gone ? "alert" : "status"}>
            {gone
              ? c.agent.gone(id ?? "")
              : autonomyError
                ? c.agent.autonomyFailed(autonomyError.message)
                : c.agents.loading}
          </p>
        </div>
      </div>
    );
  }

  const steps = c.agent.steps.map((label, i) => ({
    label,
    dirty: !isNew && stepDirty(form, orig, i + 1),
    drafted: isNew && !!drafted,
  }));
  const status = isNew ? null : agentStatus(form.instructions, runs);
  const saveLabel = isNew ? c.agent.createAgent : c.agent.saveChanges;
  const title = form.name.trim() || c.agent.untitled;
  const footer = (
    <>
      <FootLeft
        step={step}
        onPrev={() => goStep(step - 1)}
        onCancel={() => requestLeave(goList)}
        dirty={dirty}
      />
      <span className="grow" />
      {saveError ? (
        <span
          className="err"
          role="alert"
          data-testid="wizard-save-error"
          style={{ maxWidth: 360 }}
        >
          {saveError}
        </span>
      ) : null}
      {step < 4 && !isNew ? (
        <SaveButton
          label={saveLabel}
          onClick={() => void saveAndThen()}
          dirty={dirty}
          saving={saving}
        />
      ) : null}
      {step < 4 ? (
        <NextButton label={c.agent.steps[step]!} onClick={next} />
      ) : (
        <SaveButton
          label={saveLabel}
          onClick={() => void saveAndThen()}
          dirty
          primary
          saving={saving}
        />
      )}
    </>
  );

  let body;
  if (step === 1)
    body = (
      <AgentSetupStep
        form={form}
        patch={patch}
        isNew={isNew}
        isLead={isLead}
        drafted={!!drafted}
        draftInfo={drafted}
        drafting={drafting}
        draftError={draftError}
        nameError={nameError}
        onDraft={() => void runDraft()}
        onUndoDraft={undoDraft}
        saveLabel={saveLabel}
        inner={inner}
      />
    );
  else if (step === 2)
    body = (
      <AgentConfigStep
        form={form}
        orig={orig}
        patch={patch}
        isNew={isNew}
        isLead={isLead}
        legacy={!isNew && !isLead && !agent?.tools}
        panel={panel}
        onPanel={setPanel}
        catalog={catalog}
        catalogError={catalogError}
        autonomy={autonomy}
        autonomyError={autonomyError}
        suggestedGrants={drafted?.suggestedGrants ?? []}
      />
    );
  else if (step === 3)
    body = (
      <AgentScheduleStep
        form={form}
        patch={patch}
        isLead={isLead}
        drafted={isNew && !!drafted}
        runs={runs}
        inner={inner}
      />
    );
  else
    body = (
      <AgentReviewStep
        form={form}
        orig={orig}
        patch={patch}
        isNew={isNew}
        isLead={isLead}
        legacy={!isNew && !isLead && !agent?.tools && !form.toolsTouched}
        catalog={catalog}
        autonomy={autonomy}
        telegram={channels?.channels?.telegram}
        onJump={(n, p) => {
          if (p) setPanel(p);
          goStep(n);
        }}
      />
    );

  return (
    <div className="contents" data-testid="agent-wizard-root">
      <WizardShell
        kind={c.agent.kind}
        backLabel={c.agents.title}
        onBack={() => requestLeave(goList)}
        isNew={isNew}
        step={step}
        reached={reached}
        steps={steps}
        onStep={goStep}
        identity={
          <Av id={form.avatar} size={40} alt={avatarMeta(form.avatar).name} />
        }
        title={title}
        badges={
          isNew ? (
            <span className="pill muted">{c.notSavedYet}</span>
          ) : status ? (
            <StatusPill status={status} />
          ) : null
        }
        subtitle={form.sentence.trim() || c.agent.startHint}
        dirty={dirty}
        leaving={
          leaving
            ? {
                steps: isNew
                  ? [c.agent.steps[0]!]
                  : [1, 2, 3, 4]
                      .filter((n) => stepDirty(form, orig, n))
                      .map((n) => c.agent.steps[n - 1]!),
                saving,
                onKeep: () => setLeaving(null),
                onDiscard: () => {
                  const then = leaving;
                  setLeaving(null);
                  bypass.current = true;
                  then();
                },
                onSave: () => {
                  const then = leaving;
                  void save().then((ok) => {
                    if (ok) {
                      setLeaving(null);
                      bypass.current = true;
                      then();
                    }
                  });
                },
              }
            : null
        }
        footer={footer}
        testId="agent-wizard"
      >
        {body}
      </WizardShell>
    </div>
  );
}

export type InnerRef = React.MutableRefObject<{
  picker: boolean;
  editor: boolean;
  close: () => void;
}>;
