import { readFile } from "fs/promises";
import path from "path";

export default async function CatalogPage() {
  let text = "";
  try {
    const repoRoot = path.join(process.cwd(), "..");
    const p = path.join(repoRoot, "data", "reviewer_comment_catalog.json");
    text = await readFile(p, "utf-8");
  } catch {
    text = "{}";
  }
  let pretty = text;
  try {
    pretty = JSON.stringify(JSON.parse(text), null, 2);
  } catch {
    /* raw */
  }
  return (
    <div>
      <h1>Reviewer comment catalog</h1>
      <p>
        <small>Reads ../data/reviewer_comment_catalog.json relative to frontend/ (build a catalog with the Python script).</small>
      </p>
      <pre style={{ maxHeight: "70vh", overflow: "auto", fontSize: 12 }}>{pretty.slice(0, 120_000)}</pre>
    </div>
  );
}
