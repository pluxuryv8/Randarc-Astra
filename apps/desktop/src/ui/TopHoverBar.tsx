type TopHoverBarProps = {
  onHide: () => void;
  onMinimize: () => void;
  onToggleFullscreen: () => void;
  isFullscreen: boolean;
  onToggleCompact: () => void;
  isCompact: boolean;
  onStop: () => void;
  onOpenSettings: () => void;
  onOpenMemory: () => void;
  stopEnabled: boolean;
  streamState?: "idle" | "live" | "reconnecting" | "polling";
};

function streamTone(streamState?: TopHoverBarProps["streamState"]) {
  if (streamState === "live") return "ok";
  if (streamState === "reconnecting") return "warn";
  if (streamState === "polling") return "warn";
  return "muted";
}

export default function TopHoverBar({
  onHide,
  onMinimize,
  onToggleFullscreen,
  isFullscreen,
  onToggleCompact,
  isCompact,
  onStop,
  onOpenSettings,
  onOpenMemory,
  stopEnabled,
  streamState
}: TopHoverBarProps) {
  return (
    <div className="topbar">
      <div className="topbar-left">
        <div className="traffic">
          <button className="traffic-btn close" onClick={onHide} title="Спрятать (Esc)">
            <span className="traffic-dot" />
          </button>
          <button className="traffic-btn minimize" onClick={onMinimize} title="Свернуть">
            <span className="traffic-dot" />
          </button>
          <button
            className={`traffic-btn fullscreen ${isFullscreen ? "active" : ""}`}
            onClick={onToggleFullscreen}
            title={isFullscreen ? "Выйти из полного экрана" : "На весь экран"}
          >
            <span className="traffic-dot" />
          </button>
        </div>
      </div>

      <div className="topbar-right">
        <span className={`stream-dot ${streamTone(streamState)}`} title={streamState ? `События: ${streamState}` : "События"}>
          <span />
        </span>
        <button
          className={`hud-icon ${stopEnabled ? "danger" : "disabled"}`}
          onClick={onStop}
          disabled={!stopEnabled}
          title="Стоп"
        >
          ■
        </button>
        <button className={`hud-icon ${isCompact ? "active" : ""}`} onClick={onToggleCompact} title="Компактный вид">
          ⤡
        </button>
        <button className="hud-icon" onClick={onOpenMemory} title="Память">
          MEM
        </button>
        <button className="hud-icon" onClick={onOpenSettings} title="Настройки">
          ⚙︎
        </button>
      </div>
    </div>
  );
}
