"use client";

import { useParams } from "next/navigation";

import { ProjectView } from "@/components/workspace/ledger/project-view";

export default function ProjectPage() {
  const { project_id } = useParams<{ project_id: string }>();
  return (
    <div className="mx-auto w-full max-w-3xl p-6">
      <ProjectView projectId={project_id} />
    </div>
  );
}
