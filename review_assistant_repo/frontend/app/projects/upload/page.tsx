"use client";

import { useState } from "react";
import { apiPostForm } from "@/lib/api";

export default function UploadPage() {
  const [token, setToken] = useState("");
  const [status, setStatus] = useState("");

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const fd = new FormData(e.currentTarget);
    try {
      const res = (await apiPostForm("/projects/upload", fd, token || undefined)) as { project_id: string; status: string };
      setStatus(`OK project_id=${res.project_id} status=${res.status}`);
    } catch (err) {
      setStatus(String(err));
    }
  }

  return (
    <div>
      <h1>Upload project</h1>
      <p>Optional Bearer token if backend has REQUIRE_AUTH_FOR_WRITES=true</p>
      <input placeholder="Bearer token" value={token} onChange={(e) => setToken(e.target.value)} style={{ width: "100%" }} />
      <form onSubmit={onSubmit} style={{ marginTop: 8 }}>
        <input type="file" name="file" />
        <div>
          <label>
            source_url (DataLens): <input name="source_url" style={{ width: "100%" }} />
          </label>
        </div>
        <div>
          <label>
            criteria_map_code: <input name="criteria_map_code" placeholder="notebook_practicum_v1" style={{ width: "100%" }} />
          </label>
        </div>
        <button type="submit">Upload</button>
      </form>
      <pre>{status}</pre>
    </div>
  );
}
