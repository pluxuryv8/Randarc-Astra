from pathlib import Path


def test_run_sh_fail_fast() -> None:
    script = Path("scripts/run.sh").read_text(encoding="utf-8")

    wait_call = script.find("if ! wait_for_api_health 120 0.25; then")
    tauri_start = script.find('nohup npm --prefix apps/desktop run tauri dev >"$LOG_DIR/tauri.log" 2>&1 &')
    fail_exit = script.find("exit 1", wait_call)

    assert wait_call != -1, "run.sh must wait for API health before desktop start"
    assert tauri_start != -1, "run.sh must start tauri in background mode"
    assert wait_call < tauri_start, "API health wait should happen before tauri dev start"
    assert fail_exit != -1 and fail_exit < tauri_start, "API health failure must exit before tauri dev start"
