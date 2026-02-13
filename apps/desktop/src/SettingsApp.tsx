import { useEffect, useState } from "react";
import {
  checkApiStatus,
  checkPermissions,
  createProject,
  getLocalOpenAIStatus,
  initAuth,
  listProjects,
  storeOpenAIKeyLocal,
  updateProject
} from "./api";
import SettingsPanel from "./ui/SettingsPanel";
import type { Project, ProjectSettings } from "./types";

const MODE_OPTIONS = [
  { value: "plan_only", label: "Только план" },
  { value: "research", label: "Исследование" },
  { value: "execute_confirm", label: "Выполнение с подтверждением" },
  { value: "autopilot_safe", label: "Автопилот (безопасный)" }
];

const RUN_MODE_KEY = "astra_run_mode";

export default function SettingsApp() {
  const [, setProjects] = useState<Project[]>([]);
  const [selectedProject, setSelectedProject] = useState<Project | null>(null);
  const [modelName, setModelName] = useState("gpt-4.1");
  const [openaiKey, setOpenaiKey] = useState("");
  const [keyStored, setKeyStored] = useState(false);
  const [apiAvailable, setApiAvailable] = useState<boolean | null>(null);
  const [savingKey, setSavingKey] = useState(false);
  const [settingsMessage, setSettingsMessage] = useState<{ text: string; tone: "success" | "error" | "info" } | null>(null);
  const [permissions, setPermissions] = useState<{ screen_recording?: boolean; accessibility?: boolean } | null>(null);
  const [mode, setMode] = useState<string>(() => localStorage.getItem(RUN_MODE_KEY) || "execute_confirm");

  useEffect(() => {
    const setup = async () => {
      await initAuth();
      const data = await listProjects();
      if (!data.length) {
        const created = await createProject({ name: "Основной", tags: ["default"], settings: {} });
        setProjects([created]);
        setSelectedProject(created);
        setModelName(created.settings?.llm?.model || "gpt-4.1");
        return;
      }
      setProjects(data);
      setSelectedProject(data[0]);
      setModelName(data[0].settings?.llm?.model || "gpt-4.1");
    };
    setup().catch(() => setSettingsMessage({ text: "Не удалось загрузить проект", tone: "error" }));
  }, []);

  useEffect(() => {
    localStorage.setItem(RUN_MODE_KEY, mode);
  }, [mode]);

  useEffect(() => {
    checkPermissions()
      .then(setPermissions)
      .catch(() => setPermissions(null));
  }, []);

  useEffect(() => {
    const check = async () => {
      const ok = await checkApiStatus();
      setApiAvailable(ok);
      try {
        const res = await getLocalOpenAIStatus();
        setKeyStored(res.stored);
      } catch {
        setKeyStored(false);
      }
    };
    void check();
  }, []);

  useEffect(() => {
    if (!settingsMessage) return;
    const timer = window.setTimeout(() => setSettingsMessage(null), 5200);
    return () => window.clearTimeout(timer);
  }, [settingsMessage]);

  const handleSaveSettings = async () => {
    if (!selectedProject) {
      setSettingsMessage({ text: "Проект не найден", tone: "error" });
      return;
    }
    try {
      setSavingKey(true);
      if (openaiKey.trim()) {
        await storeOpenAIKeyLocal(openaiKey.trim());
        setKeyStored(true);
        setOpenaiKey("");
      }
      const current = selectedProject.settings || {};
      const llm = (current.llm || {}) as NonNullable<ProjectSettings["llm"]>;
      const nextSettings = {
        ...current,
        llm: {
          ...llm,
          provider: "openai",
          base_url: llm.base_url || "https://api.openai.com/v1",
          model: modelName.trim() || llm.model || "gpt-4.1"
        }
      };
      const updated = await updateProject(selectedProject.id, { settings: nextSettings });
      setProjects((prev) => prev.map((proj) => (proj.id === updated.id ? updated : proj)));
      setSelectedProject(updated);
      setSettingsMessage({
        text: openaiKey.trim() ? "Ключ и модель сохранены" : "Модель сохранена",
        tone: "success"
      });
    } catch {
      setSettingsMessage({ text: "Не удалось сохранить", tone: "error" });
    } finally {
      setSavingKey(false);
    }
  };

  return (
    <div className="settings-only">
      <SettingsPanel
        modelName={modelName}
        onModelChange={setModelName}
        openaiKey={openaiKey}
        onOpenaiKeyChange={setOpenaiKey}
        keyStored={keyStored}
        apiAvailable={apiAvailable}
        permissions={permissions}
        mode={mode}
        modeOptions={MODE_OPTIONS}
        onModeChange={setMode}
        animatedBg={false}
        onAnimatedBgChange={() => undefined}
        onSave={handleSaveSettings}
        saving={savingKey}
        message={settingsMessage}
        onClose={() => undefined}
        onRefreshPermissions={() =>
          checkPermissions()
            .then(setPermissions)
            .catch(() => setPermissions(null))
        }
        isStandalone
      />
    </div>
  );
}
