"use client";

import { useEffect, useState } from "react";
import { ApiError, platformApi } from "@mykhaya/api-client";
import { PlatformShell } from "@/components/platform-shell";
import { CcCard, CcSection } from "@/components/control-centre/section";
import { CcPage } from "@/components/control-centre/page-shell";
import { CcPageHeader } from "@/components/control-centre/page-header";
import { CcBadge } from "@/components/control-centre/badge";
import { CcNotice, CcLoadingState } from "@/components/control-centre/status-message";

type Home = { id: string; name: string; member_count: number };
type Package = { id: string; migration_id: string; package_checksum: string; summary: { member_count: number; asset_count: number }; status: string; dry_run_report?: { status: string; matched_existing_users: number; new_users: number } };
type Status = { enabled: boolean; enabled_at: string | null; environment: string; packages: Package[] };
const message = (error: unknown) => error instanceof ApiError ? error.message : "The Home Migration request could not be completed.";

export default function HomeMigrationPage() {
  const [status, setStatus] = useState<Status | null>(null), [homes, setHomes] = useState<Home[]>([]), [homeId, setHomeId] = useState("");
  const [pkg, setPkg] = useState<Package | null>(null), [file, setFile] = useState<File | null>(null), [confirmation, setConfirmation] = useState("");
  const [loading, setLoading] = useState(true), [working, setWorking] = useState(false), [error, setError] = useState("");
  const load = async () => { setLoading(true); setError(""); try { const next = await platformApi.get<Status>("/home-migration/status"); setStatus(next); if (next.environment === "development" && next.enabled) setHomes(await platformApi.get<Home[]>("/home-migration/homes")); } catch (cause) { setError(message(cause)); } finally { setLoading(false); } };
  useEffect(() => { void load(); }, []);
  const run = async (action: () => Promise<void>) => { setWorking(true); setError(""); try { await action(); } catch (cause) { setError(message(cause)); } finally { setWorking(false); } };
  if (loading) return <PlatformShell><CcPage><CcLoadingState label="Loading Home MigrationÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â¦" /></CcPage></PlatformShell>;
  if (!status) return <PlatformShell><CcPage><CcNotice tone="error">{error || "Home Migration status is unavailable."}</CcNotice></CcPage></PlatformShell>;
  const dev = status.environment === "development", prod = status.environment === "production";
  return <PlatformShell><CcPage wide><CcPageHeader eyebrow="Operations" title="Home Migration" description="Move a Home only through a validated migration package. DEV and PROD never connect directly." secondaryActions={<button className="secondary" onClick={() => void load()}>Refresh</button>} />
    {error && <CcNotice tone="error">{error}</CcNotice>}
    <CcCard><div className="cc-card-header"><div><h2>Migration Tool</h2><p>Keep this capability disabled except while performing a migration.</p></div><CcBadge tone={status.enabled ? "warning" : "neutral"}>{status.enabled ? "Enabled" : "Disabled"}</CcBadge></div><p>{status.enabled_at ? `Enabled since ${new Date(status.enabled_at).toLocaleString("en-GB")}. Disable it when finished.` : "Enable Home Migration in PCC Settings before continuing."}</p></CcCard>
    {!status.enabled ? <CcNotice tone="warning">Home Migration is disabled. An owner must enable it in Platform ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ Settings; the server enforces this for every operation.</CcNotice> : <>
      {dev && <CcSection title="Export a Home" description="Generate a package for manual transfer to production."><label>Home<select value={homeId} onChange={(event) => setHomeId(event.target.value)}><option value="">Select a Home</option>{homes.map((home) => <option key={home.id} value={home.id}>{home.name} ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â· {home.member_count} members</option>)}</select></label><div className="cc-action-bar"><button disabled={!homeId || working} onClick={() => void run(async () => { await platformApi.post("/home-migration/preview-export", { home_id: homeId }); })}>Preview export</button><button disabled={!homeId || working} onClick={() => void run(async () => setPkg(await platformApi.post<Package>("/home-migration/export", { home_id: homeId })))}>Generate migration package</button></div>{pkg && <CcNotice tone="success">Package {pkg.migration_id} generated. <a href={`/api/v1/platform/home-migration/packages/${pkg.id}/download`}>Download package</a></CcNotice>}</CcSection>}
      {prod && <CcSection title="Import a Home into PROD" description="Home Migration can create and modify production household data. Review and dry-run before importing."><input type="file" accept="application/json,.json" onChange={(event) => setFile(event.target.files?.[0] ?? null)} /><div className="cc-action-bar"><button disabled={!file || working} onClick={() => void run(async () => { if (!file) return; const form = new FormData(); form.append("package", file); setPkg(await platformApi.upload<Package>("/home-migration/upload", form)); })}>Upload and validate</button><button disabled={!pkg || working} onClick={() => void run(async () => { if (!pkg) return; const result = await platformApi.post<Package>("/home-migration/dry-run", { package_id: pkg.id, reason: "Run Home Migration dry-run" }); setPkg({ ...pkg, ...result }); })}>Run dry-run</button></div>{pkg && <CcCard><p><strong>Migration:</strong> {pkg.migration_id}</p><p><strong>Checksum:</strong> {pkg.package_checksum}</p><p><strong>Members:</strong> {pkg.summary.member_count} ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â· <strong>Assets:</strong> {pkg.summary.asset_count}</p>{pkg.dry_run_report && <CcNotice tone={pkg.dry_run_report.status === "READY_TO_IMPORT" ? "success" : "warning"}>Dry-run: {pkg.dry_run_report.status}. Matched {pkg.dry_run_report.matched_existing_users}; new accounts {pkg.dry_run_report.new_users}.</CcNotice>}<label>Type the migration ID to confirm production creation<input value={confirmation} onChange={(event) => setConfirmation(event.target.value)} /></label><button className="danger" disabled={confirmation !== pkg.migration_id || pkg.dry_run_report?.status !== "READY_TO_IMPORT" || working} onClick={() => void run(async () => { if (!pkg) return; await platformApi.post("/home-migration/import", { package_id: pkg.id, confirmation, reason: "Import Home migration package" }); await load(); })}>Import Home into PROD</button></CcCard>}</CcSection>}
      {!dev && !prod && <CcNotice tone="warning">Home Migration is intentionally unavailable in this environment.</CcNotice>}
    </>}</CcPage></PlatformShell>;
}
