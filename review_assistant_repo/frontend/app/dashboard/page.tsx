import { apiGet } from "@/lib/api";

type Project = {
  id: string;
  status: string;
  source_type: string;
  original_filename?: string | null;
  final_verdict?: string | null;
};

async function loadProjects(): Promise<Project[]> {
  try {
    return await apiGet<Project[]>("/projects");
  } catch {
    return [];
  }
}

export default async function DashboardPage() {
  const projects = await loadProjects();
  return (
    <div>
      <h1>Projects</h1>
      <p>
        <small>Data from GET /api/v1/projects</small>
      </p>
      {projects.length === 0 ? (
        <p>No projects loaded (empty list or API error).</p>
      ) : (
        <ul>
          {projects.map((p) => (
            <li key={p.id}>
              <a href={`/projects/${p.id}`}>{p.id}</a> — {p.status} ({p.source_type})
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
