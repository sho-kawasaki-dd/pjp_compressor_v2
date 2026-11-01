from __future__ import annotations

import json
import sys
import tkinter as tk
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.contracts import CapabilityReport
import frontend.i18n as i18n
import frontend.ui_tkinter as ui_module
import frontend.ui_tkinter_state as ui_state


def main() -> None:
    payload = json.loads(sys.argv[1])
    report_data = payload['report']
    report_data['ffmpeg_encoders'] = frozenset(report_data['ffmpeg_encoders'])
    report = CapabilityReport(**report_data)
    i18n.load('ja')
    ui_module.detect_capabilities = lambda: report
    ui_module.init_mixer = lambda: (True, None)
    ui_module.get_default_dirs = lambda: (payload['input_dir'], payload['output_dir'])
    ui_state.VIDEO_ENABLED_DEFAULT = payload['enabled']

    try:
        app = ui_module.App()
    except tk.TclError as exc:
        print('PJP_UI_RESULT=' + json.dumps({'skip': f'Tk runtime unavailable: {exc}'}))
        return
    except RuntimeError as exc:
        if str(exc) != 'Unable to load tkdnd library.':
            raise
        print('PJP_UI_RESULT=' + json.dumps({'skip': str(exc)}))
        return

    try:
        app.withdraw()
        tabs = (app.settings_tab, app.output_settings_tab, app.app_settings_tab, app.log_tab)
        tab_selection_ok = True
        for tab in tabs:
            app.notebook.select(tab)
            tab_selection_ok &= app.notebook.select() == str(tab)

        state = {
            'tab_order_ok': app.notebook.tabs() == tuple(map(str, tabs)),
            'tab_selection_ok': tab_selection_ok,
            'stop_state': str(app.stop_button.cget('state')),
            'enable_disabled': app.video_enable_check.instate(('disabled',)),
            'quality_state': str(app.video_quality_scale.cget('state')),
            'h265_widget_present': hasattr(app, 'video_h265_rb'),
            'codec_label': app.video_codec_label.cget('text'),
            'combos_readonly': [combo.instate(('readonly',)) for combo in app._video_combo_widgets],
            'combos_disabled': [combo.instate(('disabled',)) for combo in app._video_combo_widgets],
            'engine_status': app.video_engine_status_var.get(),
        }
        if report.video_available:
            app.video_enabled.set(False)
            app._update_video_controls()
            state['combos_disabled_after_toggle'] = all(combo.instate(('disabled',)) for combo in app._video_combo_widgets)
            app.video_enabled.set(True)
            app._update_video_controls()
            state['combos_readonly_after_toggle'] = all(combo.instate(('readonly',)) for combo in app._video_combo_widgets)
        print('PJP_UI_RESULT=' + json.dumps(state))
    finally:
        app.destroy()


if __name__ == '__main__':
    main()
