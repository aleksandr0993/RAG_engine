"use client";

import { useState } from "react";

const base = () => process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

export default function AdminAssignmentsPage() {
  const [projectId, setProjectId] = useState("");
  const [reviewers, setReviewers] = useState("rev_a,rev_b");
  const [out, setOut] = useState("");

  async function autoAssign() {
    const ids = reviewers.split(",").map((s) => s.trim()).filter(Boolean);
    const r = await fetch(`${base()}/api/v1/admin/projects/${projectId}/assignments/auto`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ reviewer_ids: ids }),
    });
    setOut(await r.text());
  }

  async function listAssign() {
    const r = await fetch(`${base()}/api/v1/admin/projects/${projectId}/assignments`);
    setOut(await r.text());
  }

  return (
    <div>
      <h1>Assignments</h1>
      <input placeholder="project_id" value={projectId} onChange={(e) => setProjectId(e.target.value)} />
      <input placeholder="reviewer ids comma-separated" value={reviewers} onChange={(e) => setReviewers(e.target.value)} style={{ width: "100%" }} />
      <div style={{ marginTop: 8 }}>
        <button type="button" onClick={autoAssign}>
          Auto-assign (load balance)
        </button>{" "}
        <button type="button" onClick={listAssign}>
          List
        </button>
      </div>
      <pre>{out}</pre>
    </div>
  );
}
