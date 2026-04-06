import { useState, useEffect } from "react";
import { X, FolderOpen, Cloud, FileText, Monitor, Save, Sparkles } from "lucide-react";
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

  useEffect(() => {
    fetch("/api/settings")
      .then((r) => r.json())
      .then((data) => { setSettings(data); setLoading(false); })
      .catch((e) => { setError(e.message); setLoading(false); });
  }, []);

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
        <Section icon={<Cloud size={16} />} title="Sync">
          <Field label="Storage backend">
            <select
              value={settings?.sync_backend || "none"}
              onChange={(e) => updateField("sync_backend", e.target.value)}
              className="w-full border border-gray-300 dark:border-gray-600 rounded px-3 py-2 text-sm bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 outline-none focus:border-suchi-light"
            >
              <option value="none">None (local only)</option>
              <option value="gdrive">Google Drive</option>
            </select>
          </Field>
          {settings?.sync_backend === "gdrive" && (
            <>
              <Field label="Auto-sync">
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={settings?.auto_sync || false}
                    onChange={(e) => updateField("auto_sync", e.target.checked)}
                    className="rounded border-gray-300 dark:border-gray-600"
                  />
                  <span className="text-sm text-gray-700 dark:text-gray-300">Automatically sync in the background</span>
                </label>
              </Field>
              <Field label="Sync interval (minutes)">
                <input
                  type="number"
                  min={1}
                  max={120}
                  value={settings?.sync_interval_minutes || 15}
                  onChange={(e) => updateField("sync_interval_minutes", parseInt(e.target.value) || 15)}
                  className="w-24 border border-gray-300 dark:border-gray-600 rounded px-3 py-2 text-sm bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 outline-none focus:border-suchi-light"
                />
              </Field>
              <Field label="Google Drive folder ID" description="Leave empty to use the app's default folder">
                <input
                  type="text"
                  value={settings?.gdrive_folder_id || ""}
                  onChange={(e) => updateField("gdrive_folder_id", e.target.value || null)}
                  placeholder="auto"
                  className="w-full border border-gray-300 dark:border-gray-600 rounded px-3 py-2 text-sm bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 outline-none focus:border-suchi-light font-mono"
                />
              </Field>
            </>
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
