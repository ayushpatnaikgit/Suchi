import { useState, useEffect, useCallback } from "react";
import { X, FolderOpen, Cloud, FileText, Monitor, Save, Sparkles, RefreshCw, LogOut, CheckCircle, Loader2 } from "lucide-react";
import type { Theme } from "../../hooks/useTheme";

interface Settings {
  library_dir: string;
  sync_backend: string;
  auto_sync: boolean;
  sync_interval_minutes: number;
  gdrive_folder_id: string | null;
  default_export_format: string;
  editor: string;
  gemini_api_key: string;
  gemini_model: string;
}

interface SyncStatus {
  logged_in: boolean;
  email: string | null;
  backend: string;
  last_sync: string | null;
  synced_collections: string[];
}

interface SettingsPanelProps {
  onClose: () => void;
  theme: Theme;
  onToggleTheme: () => void;
}

export function SettingsPanel({ onClose, theme, onToggleTheme }: SettingsPanelProps) {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [syncStatus, setSyncStatus] = useState<SyncStatus | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [syncMessage, setSyncMessage] = useState<string | null>(null);
  const [loggingIn, setLoggingIn] = useState(false);

  const fetchSyncStatus = useCallback(async () => {
    try {
      const r = await fetch("/api/sync/status");
      if (r.ok) setSyncStatus(await r.json());
    } catch { /* ignore */ }
  }, []);

  useEffect(() => {
    fetch("/api/settings")
      .then((r) => r.json())
      .then((data) => { setSettings(data); setLoading(false); })
      .catch((e) => { setError(e.message); setLoading(false); });
    fetchSyncStatus();
  }, [fetchSyncStatus]);

  const handleSave = async () => {
    if (!settings) return;
    setSaving(true);
    setSaved(false);
    try {
      const res = await fetch("/api/settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(settings),
      });
      if (!res.ok) throw new Error("Failed to save");
      const data = await res.json();
      setSettings(data);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const updateField = <K extends keyof Settings>(key: K, value: Settings[K]) => {
    if (settings) setSettings({ ...settings, [key]: value });
  };

  if (loading) {
    return (
      <div className="p-8 flex items-center justify-center h-full bg-white dark:bg-gray-900">
        <span className="text-gray-400 dark:text-gray-500 text-sm">Loading settings...</span>
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto bg-white dark:bg-gray-900">
      {/* Header */}
      <div className="sticky top-0 z-10 bg-white dark:bg-gray-900 border-b border-gray-200 dark:border-gray-700 px-6 py-4 flex items-center justify-between">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">Settings</h2>
        <button onClick={onClose} className="p-1 rounded hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-500 dark:text-gray-400">
          <X size={18} />
        </button>
      </div>

      <div className="px-6 py-5 space-y-8 max-w-xl">
        {error && (
          <div className="p-3 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded text-sm text-red-600 dark:text-red-400">{error}</div>
        )}

        {/* Appearance */}
        <Section icon={<Monitor size={16} />} title="Appearance">
          <Field label="Theme">
            <div className="flex gap-2">
              <ThemeButton label="Light" active={theme === "light"} onClick={() => theme !== "light" && onToggleTheme()} />
              <ThemeButton label="Dark" active={theme === "dark"} onClick={() => theme !== "dark" && onToggleTheme()} />
            </div>
          </Field>
        </Section>

        {/* Library */}
        <Section icon={<FolderOpen size={16} />} title="Library">
          <Field label="Library directory" description="Where your references and PDFs are stored">
            <input
              type="text"
              value={settings?.library_dir || ""}
              onChange={(e) => updateField("library_dir", e.target.value)}
              className="w-full border border-gray-300 dark:border-gray-600 rounded px-3 py-2 text-sm bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 outline-none focus:border-suchi-light font-mono"
            />
          </Field>
          <Field label="Default editor" description="Editor for opening YAML/notes (e.g. vim, code, nano). Falls back to $EDITOR.">
            <input
              type="text"
              value={settings?.editor || ""}
              onChange={(e) => updateField("editor", e.target.value)}
              placeholder="$EDITOR"
              className="w-full border border-gray-300 dark:border-gray-600 rounded px-3 py-2 text-sm bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 outline-none focus:border-suchi-light"
            />
          </Field>
        </Section>

        {/* Export */}
        <Section icon={<FileText size={16} />} title="Export">
          <Field label="Default export format">
            <select
              value={settings?.default_export_format || "bibtex"}
              onChange={(e) => updateField("default_export_format", e.target.value)}
              className="w-full border border-gray-300 dark:border-gray-600 rounded px-3 py-2 text-sm bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 outline-none focus:border-suchi-light"
            >
              <option value="bibtex">BibTeX</option>
              <option value="csl-json">CSL-JSON</option>
              <option value="ris">RIS</option>
            </select>
          </Field>
        </Section>

        {/* AI */}
        <Section icon={<Sparkles size={16} />} title="AI Assistant">
          <Field label="Gemini API key" description="Get one from Google AI Studio (aistudio.google.com). Required for chat features.">
            <input
              type="password"
              value={settings?.gemini_api_key || ""}
              onChange={(e) => updateField("gemini_api_key", e.target.value)}
              placeholder="AIza..."
              className="w-full border border-gray-300 dark:border-gray-600 rounded px-3 py-2 text-sm bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 outline-none focus:border-suchi-light font-mono"
            />
          </Field>
          <Field label="Model" description="Gemini model to use for chat">
            <select
              value={settings?.gemini_model || "gemini-2.0-flash"}
              onChange={(e) => updateField("gemini_model", e.target.value)}
              className="w-full border border-gray-300 dark:border-gray-600 rounded px-3 py-2 text-sm bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 outline-none focus:border-suchi-light"
            >
              <option value="gemini-2.5-flash">Gemini 2.5 Flash (fast)</option>
              <option value="gemini-2.5-pro">Gemini 2.5 Pro (powerful)</option>
              <option value="gemini-3.1-pro">Gemini 3.1 Pro (latest)</option>
            </select>
          </Field>
        </Section>

        {/* Sync */}
        <Section icon={<Cloud size={16} />} title="Sync & Collaboration">
          {syncStatus?.logged_in ? (
            <>
              {/* Signed in state */}
              <div className="rounded-xl border border-green-200 dark:border-green-800/50 bg-green-50 dark:bg-green-900/10 p-4">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-full bg-green-100 dark:bg-green-900/30 flex items-center justify-center">
                    <CheckCircle size={20} className="text-green-600 dark:text-green-400" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium text-gray-900 dark:text-gray-100">Connected to Google Drive</div>
                    <div className="text-xs text-gray-500 dark:text-gray-400 truncate">{syncStatus.email}</div>
                  </div>
                </div>

                {syncStatus.last_sync && (
                  <div className="mt-3 pt-3 border-t border-green-200 dark:border-green-800/50 text-xs text-gray-500 dark:text-gray-400">
                    Last synced: {new Date(syncStatus.last_sync).toLocaleString()}
                  </div>
                )}

                {syncStatus.synced_collections?.length > 0 && (
                  <div className="mt-2 text-xs text-gray-500 dark:text-gray-400">
                    Synced collections: {syncStatus.synced_collections.join(", ")}
                  </div>
                )}
              </div>

              {/* Sync Now button */}
              <div className="flex items-center gap-3 mt-2">
                <button
                  onClick={async () => {
                    setSyncing(true);
                    setSyncMessage(null);
                    try {
                      const r = await fetch("/api/sync/run", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({}),
                      });
                      const data = await r.json();
                      setSyncMessage(`Synced: ${data.pushed} pushed, ${data.pulled} pulled, ${data.conflicts} conflicts`);
                      fetchSyncStatus();
                    } catch (e) {
                      setSyncMessage(`Sync failed: ${e instanceof Error ? e.message : "unknown error"}`);
                    } finally {
                      setSyncing(false);
                    }
                  }}
                  disabled={syncing}
                  className="flex items-center gap-2 px-4 py-2 bg-suchi text-white rounded-lg text-sm hover:bg-suchi-dark disabled:opacity-50"
                >
                  {syncing ? (
                    <Loader2 size={14} className="animate-spin" />
                  ) : (
                    <RefreshCw size={14} />
                  )}
                  {syncing ? "Syncing..." : "Sync Now"}
                </button>
                {syncMessage && (
                  <span className="text-xs text-gray-500 dark:text-gray-400">{syncMessage}</span>
                )}
              </div>

              {/* Auto-sync settings */}
              <Field label="Auto-sync">
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={settings?.auto_sync || false}
                    onChange={(e) => updateField("auto_sync", e.target.checked)}
                    className="rounded border-gray-300 dark:border-gray-600 text-suchi focus:ring-suchi"
                  />
                  <span className="text-sm text-gray-700 dark:text-gray-300">Sync in the background every {settings?.sync_interval_minutes || 15} minutes</span>
                </label>
              </Field>

              {/* Sign Out */}
              <div className="pt-2">
                <button
                  onClick={async () => {
                    if (!confirm("Sign out from Google Drive? Your local library won't be affected.")) return;
                    await fetch("/api/sync/logout", { method: "POST" });
                    setSyncStatus(null);
                    fetchSyncStatus();
                  }}
                  className="flex items-center gap-2 px-4 py-2 text-sm text-red-600 dark:text-red-400 border border-red-200 dark:border-red-800/50 rounded-lg hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors"
                >
                  <LogOut size={14} />
                  Sign out from Google Drive
                </button>
              </div>
            </>
          ) : (
            /* Not signed in */
            <div className="rounded-xl border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800/50 p-5">
              <div className="text-center">
                <Cloud size={32} className="mx-auto text-gray-300 dark:text-gray-600 mb-3" />
                <h4 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-1">Sync your library</h4>
                <p className="text-xs text-gray-400 dark:text-gray-500 mb-4 max-w-xs mx-auto">
                  Sign in with Google to sync your collections across devices and collaborate with others.
                </p>
                <button
                  onClick={async () => {
                    setLoggingIn(true);
                    try {
                      const r = await fetch("/api/sync/login", { method: "POST" });
                      const data = await r.json();
                      if (data.auth_url) {
                        // Open auth URL in new tab
                        window.open(data.auth_url, "_blank");
                        // Poll for login completion
                        const poll = setInterval(async () => {
                          const status = await fetch("/api/sync/status").then(r => r.json());
                          if (status.logged_in) {
                            clearInterval(poll);
                            setSyncStatus(status);
                            setLoggingIn(false);
                          }
                        }, 2000);
                        // Stop polling after 2 minutes
                        setTimeout(() => { clearInterval(poll); setLoggingIn(false); }, 120000);
                      }
                    } catch (e) {
                      setError("Login failed. Try running 'suchi login' from the terminal.");
                      setLoggingIn(false);
                    }
                  }}
                  disabled={loggingIn}
                  className="inline-flex items-center gap-2 px-5 py-2.5 bg-white dark:bg-gray-700 border border-gray-300 dark:border-gray-600 rounded-lg text-sm font-medium text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-600 shadow-sm transition-colors disabled:opacity-50"
                >
                  {loggingIn ? (
                    <Loader2 size={16} className="animate-spin" />
                  ) : (
                    <svg width="16" height="16" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                      <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z" fill="#4285F4"/>
                      <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853"/>
                      <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" fill="#FBBC05"/>
                      <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335"/>
                    </svg>
                  )}
                  {loggingIn ? "Waiting for sign-in..." : "Sign in with Google"}
                </button>
                <p className="text-xs text-gray-400 dark:text-gray-500 mt-3">
                  Or run <code className="bg-gray-200 dark:bg-gray-700 px-1.5 py-0.5 rounded text-xs font-mono">suchi login</code> from terminal
                </p>
              </div>
            </div>
          )}
        </Section>

        {/* Save button */}
        <div className="pt-2 pb-8">
          <button
            onClick={handleSave}
            disabled={saving}
            className="flex items-center gap-2 px-4 py-2 bg-suchi text-white rounded-lg text-sm hover:bg-suchi-dark disabled:opacity-50"
          >
            <Save size={14} />
            {saving ? "Saving..." : saved ? "Saved!" : "Save Settings"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Sub-components ────

function Section({ icon, title, children }: { icon: React.ReactNode; title: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="flex items-center gap-2 mb-4">
        <span className="text-gray-400 dark:text-gray-500">{icon}</span>
        <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300 uppercase tracking-wider">{title}</h3>
      </div>
      <div className="space-y-4 pl-6">{children}</div>
    </div>
  );
}

function Field({ label, description, children }: { label: string; description?: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">{label}</label>
      {description && <p className="text-xs text-gray-400 dark:text-gray-500 mb-2">{description}</p>}
      {children}
    </div>
  );
}

function ThemeButton({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
        active
          ? "bg-suchi text-white"
          : "bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400 hover:bg-gray-200 dark:hover:bg-gray-700"
      }`}
    >
      {label}
    </button>
  );
}
