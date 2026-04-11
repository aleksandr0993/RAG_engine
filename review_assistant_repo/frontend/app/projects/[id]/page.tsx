import { apiGet } from "@/lib/api";

type Project = {
  id: string;
  status: string;
  source_type: string;
  final_verdict?: string | null;
  review_markdown?: string | null;
};

export default async function ProjectDetailPage({ params }: { params: { id: string } }) {
  let project: Project | null = null;
  try {
    project = await apiGet<Project>(`/projects/${params.id}`);
  } catch {
    project = null;
  }
  if (!project) return <p>Project not found or API error.</p>;
  return (
    <div>
      <h1>Project {project.id}</h1>
      <p>
        Status: <strong>{project.status}</strong> · Type: {project.source_type} · Verdict: {project.final_verdict ?? "—"}
      </p>
      <h2>Review markdown</h2>
      <pre style={{ whiteSpace: "pre-wrap" }}>{project.review_markdown ?? "(empty)"}</pre>
    </div>
  );
}
