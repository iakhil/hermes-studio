use serde::Serialize;
use tauri::Manager;

#[derive(Serialize)]
struct MacPermissionStatus {
    platform: String,
    accessibility_trusted: Option<bool>,
    screen_recording_granted: Option<bool>,
    screen_recording_hint: Option<String>,
}

#[derive(Clone, Serialize)]
struct VoiceHotkeyPayload {
    shortcut: String,
}

#[tauri::command]
fn mac_permission_status() -> MacPermissionStatus {
    #[cfg(target_os = "macos")]
    {
        MacPermissionStatus {
            platform: "macos".to_string(),
            accessibility_trusted: Some(macos::accessibility_trusted()),
            screen_recording_granted: Some(macos::screen_recording_granted()),
            screen_recording_hint: Some("macOS only shows this app in Screen Recording after a screen-capture permission request.".to_string()),
        }
    }

    #[cfg(not(target_os = "macos"))]
    {
        MacPermissionStatus {
            platform: std::env::consts::OS.to_string(),
            accessibility_trusted: None,
            screen_recording_granted: None,
            screen_recording_hint: None,
        }
    }
}

#[tauri::command]
fn request_accessibility_permission() -> bool {
    #[cfg(target_os = "macos")]
    {
        let _ = open_macos_privacy_pane("accessibility".to_string());
        macos::accessibility_trusted()
    }

    #[cfg(not(target_os = "macos"))]
    {
        false
    }
}

#[tauri::command]
fn open_macos_privacy_pane(pane: String) -> Result<(), String> {
    #[cfg(target_os = "macos")]
    {
        let url = match pane.as_str() {
            "accessibility" => {
                "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"
            }
            "screen-recording" => {
                "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture"
            }
            "microphone" => {
                "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone"
            }
            "automation" => {
                "x-apple.systempreferences:com.apple.preference.security?Privacy_Automation"
            }
            _ => "x-apple.systempreferences:com.apple.preference.security",
        };
        std::process::Command::new("open")
            .arg(url)
            .spawn()
            .map_err(|err| err.to_string())?;
        Ok(())
    }

    #[cfg(not(target_os = "macos"))]
    {
        let _ = pane;
        Err("macOS privacy panes are only available on macOS.".to_string())
    }
}

#[tauri::command]
fn request_screen_recording_permission() -> bool {
    #[cfg(target_os = "macos")]
    {
        macos::request_screen_recording_permission()
    }

    #[cfg(not(target_os = "macos"))]
    {
        false
    }
}

fn main() {
    let app = tauri::Builder::default()
        .setup(|app| {
            #[cfg(target_os = "macos")]
            voice_hotkey::start(app.handle().clone());
            Ok(())
        })
        .on_window_event(|window, event| {
            if window.label() == "main" {
                if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                    api.prevent_close();
                    let _ = window.hide();
                }
            }
        })
        .invoke_handler(tauri::generate_handler![
            mac_permission_status,
            request_accessibility_permission,
            request_screen_recording_permission,
            open_macos_privacy_pane
        ])
        .build(tauri::generate_context!())
        .expect("error while building Hermes Studio");

    app.run(|app_handle, event| {
        #[cfg(target_os = "macos")]
        if let tauri::RunEvent::Reopen { .. } = event {
            if let Some(window) = app_handle.get_webview_window("main") {
                let _ = window.show();
                let _ = window.set_focus();
            }
        }
    });
}

#[cfg(target_os = "macos")]
mod voice_hotkey {
    use super::VoiceHotkeyPayload;
    use serde::Deserialize;
    use std::ffi::c_void;
    use std::fs;
    use std::process::Command;
    use std::sync::atomic::AtomicUsize;
    use std::sync::atomic::{AtomicBool, Ordering};
    use std::sync::mpsc::{self, Sender};
    use std::sync::Mutex;
    use std::sync::OnceLock;
    use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};
    use tauri::{AppHandle, Emitter, Manager};

    const EVENT_FLAGS_CHANGED: u32 = 12;
    const EVENT_TAP_DISABLED_BY_TIMEOUT: u32 = 0xffff_fffe;
    const EVENT_TAP_DISABLED_BY_USER_INPUT: u32 = 0xffff_ffff;
    const EVENT_MASK_FLAGS_CHANGED: u64 = 1_u64 << EVENT_FLAGS_CHANGED;
    const EVENT_TAP_HID: u32 = 0;
    const EVENT_TAP_SESSION: u32 = 1;
    const EVENT_TAP_HEAD_INSERT: u32 = 0;
    const EVENT_TAP_LISTEN_ONLY: u32 = 1;
    const EVENT_SOURCE_HID_SYSTEM_STATE: u32 = 1;
    const VOICE_SHORTCUT_LABEL: &str = "Option+Command";
    const FLAG_MASK_ALTERNATE: u64 = 0x0008_0000;
    const FLAG_MASK_COMMAND: u64 = 0x0010_0000;

    static HOTKEY_TX: OnceLock<Sender<bool>> = OnceLock::new();
    static COMBO_DOWN: AtomicBool = AtomicBool::new(false);
    static EVENT_TAP_PORT: AtomicUsize = AtomicUsize::new(0);
    static NATIVE_RECORDING: OnceLock<Mutex<Option<NativeRecording>>> = OnceLock::new();
    static NATIVE_COMMAND_BUSY: AtomicBool = AtomicBool::new(false);

    struct NativeRecording {
        recorder: usize,
        path: std::path::PathBuf,
        started_at: Instant,
    }

    #[derive(Deserialize)]
    struct VoiceTranscriptionResponse {
        text: String,
    }

    #[derive(Deserialize)]
    struct ChatRunResponse {
        response: String,
        error: Option<String>,
    }

    type CGEventTapProxy = *mut c_void;
    type CGEventType = u32;
    type CGEventRef = *mut c_void;
    type CGEventFlags = u64;
    type CFMachPortRef = *mut c_void;
    type CFRunLoopSourceRef = *mut c_void;
    type CFRunLoopRef = *mut c_void;

    #[link(name = "ApplicationServices", kind = "framework")]
    extern "C" {
        fn CGEventTapCreate(
            tap: u32,
            place: u32,
            options: u32,
            events_of_interest: u64,
            callback: unsafe extern "C" fn(
                CGEventTapProxy,
                CGEventType,
                CGEventRef,
                *mut c_void,
            ) -> CGEventRef,
            user_info: *mut c_void,
        ) -> CFMachPortRef;
        fn CGEventGetFlags(event: CGEventRef) -> CGEventFlags;
        fn CGEventSourceFlagsState(state_id: u32) -> CGEventFlags;
        fn CGEventTapEnable(tap: CFMachPortRef, enable: bool);
    }

    #[link(name = "CoreFoundation", kind = "framework")]
    extern "C" {
        static kCFRunLoopCommonModes: *const c_void;
        fn CFMachPortCreateRunLoopSource(
            allocator: *const c_void,
            port: CFMachPortRef,
            order: isize,
        ) -> CFRunLoopSourceRef;
        fn CFRunLoopGetCurrent() -> CFRunLoopRef;
        fn CFRunLoopAddSource(
            run_loop: CFRunLoopRef,
            source: CFRunLoopSourceRef,
            mode: *const c_void,
        );
        fn CFRunLoopRun();
    }

    pub fn start(app: AppHandle) {
        let (tx, rx) = mpsc::channel::<bool>();
        let _ = HOTKEY_TX.set(tx);
        show_registered_hud(&app);

        let emit_app = app.clone();
        std::thread::spawn(move || {
            for is_down in rx {
                let event = if is_down {
                    play_hotkey_registered_sound();
                    start_native_recording(&emit_app);
                    "voice-hotkey-pressed"
                } else {
                    play_hotkey_released_sound();
                    stop_native_recording_and_run(emit_app.clone());
                    "voice-hotkey-released"
                };
                update_hud_window(&emit_app, is_down);
                let _ = emit_app.emit(
                    event,
                    VoiceHotkeyPayload {
                        shortcut: VOICE_SHORTCUT_LABEL.to_string(),
                    },
                );
            }
        });

        let hud_app = app.clone();
        std::thread::spawn(move || loop {
            show_registered_hud(&hud_app);
            std::thread::sleep(Duration::from_millis(900));
        });

        std::thread::spawn(move || loop {
            let flags = unsafe { CGEventSourceFlagsState(EVENT_SOURCE_HID_SYSTEM_STATE) };
            handle_modifier_flags(flags);
            std::thread::sleep(Duration::from_millis(35));
        });

        std::thread::spawn(move || unsafe {
            let event_tap = create_event_tap();

            if event_tap.is_null() {
                show_registered_hud(&app);
                emit_voice_event(&app, "voice-hotkey-unavailable");
                emit_voice_event_after_delay(app.clone(), "voice-hotkey-unavailable");
                return;
            }
            EVENT_TAP_PORT.store(event_tap as usize, Ordering::SeqCst);
            CGEventTapEnable(event_tap, true);

            let source = CFMachPortCreateRunLoopSource(std::ptr::null(), event_tap, 0);
            if source.is_null() {
                show_registered_hud(&app);
                emit_voice_event(&app, "voice-hotkey-unavailable");
                emit_voice_event_after_delay(app.clone(), "voice-hotkey-unavailable");
                return;
            }

            CFRunLoopAddSource(CFRunLoopGetCurrent(), source, kCFRunLoopCommonModes);
            show_registered_hud(&app);
            emit_voice_event(&app, "voice-hotkey-registered");
            CFRunLoopRun();
        });
    }

    fn native_recording_state() -> &'static Mutex<Option<NativeRecording>> {
        NATIVE_RECORDING.get_or_init(|| Mutex::new(None))
    }

    fn start_native_recording(app: &AppHandle) {
        if NATIVE_COMMAND_BUSY
            .compare_exchange(false, true, Ordering::SeqCst, Ordering::SeqCst)
            .is_err()
        {
            emit_native_status(app, "Voice command already running.");
            return;
        }

        let path = temp_path("hermes-studio-native-voice", "m4a");
        match native_audio::start_recording(&path) {
            Ok(recorder) => {
                if let Ok(mut state) = native_recording_state().lock() {
                    *state = Some(NativeRecording {
                        recorder,
                        path,
                        started_at: Instant::now(),
                    });
                }
                emit_native_status(app, "Listening.");
            }
            Err(err) => {
                NATIVE_COMMAND_BUSY.store(false, Ordering::SeqCst);
                emit_native_status(
                    app,
                    &format!("Could not start native microphone recording: {err}"),
                );
            }
        }
    }

    fn stop_native_recording_and_run(app: AppHandle) {
        let recording = native_recording_state()
            .lock()
            .ok()
            .and_then(|mut state| state.take());

        let Some(recording) = recording else {
            return;
        };

        let elapsed = recording.started_at.elapsed();
        if elapsed < Duration::from_millis(450) {
            std::thread::sleep(Duration::from_millis(450) - elapsed);
        }
        native_audio::stop_recording(recording.recorder);
        emit_native_status(&app, "Transcribing.");

        std::thread::spawn(move || {
            if let Err(err) = run_native_voice_command(&app, &recording.path) {
                emit_native_status(&app, &format!("Voice command failed: {err}"));
                speak_fallback(&format!("Voice command failed. {err}"));
            }
            let _ = fs::remove_file(&recording.path);
            NATIVE_COMMAND_BUSY.store(false, Ordering::SeqCst);
        });
    }

    fn run_native_voice_command(
        app: &AppHandle,
        audio_path: &std::path::Path,
    ) -> Result<(), String> {
        let transcript = transcribe_native_audio(audio_path)?;
        if transcript.trim().is_empty() {
            return Err("No speech was detected.".to_string());
        }

        emit_native_status(app, &format!("Heard: {transcript}"));
        let response = run_chat_command(&transcript)?;
        emit_native_status(app, "Speaking response.");
        speak_response(&response)?;
        Ok(())
    }

    fn transcribe_native_audio(audio_path: &std::path::Path) -> Result<String, String> {
        let output = Command::new("/usr/bin/curl")
            .arg("-sS")
            .arg("--fail-with-body")
            .arg("--max-time")
            .arg("180")
            .arg("-X")
            .arg("POST")
            .arg("http://127.0.0.1:8420/api/v1/voice/transcribe")
            .arg("-H")
            .arg("Content-Type: audio/mp4")
            .arg("--data-binary")
            .arg(format!("@{}", audio_path.display()))
            .output()
            .map_err(|err| format!("Could not call local transcription backend: {err}"))?;

        let stdout = String::from_utf8_lossy(&output.stdout);
        if !output.status.success() {
            let stderr = String::from_utf8_lossy(&output.stderr);
            return Err(format!(
                "Transcription backend error: {}",
                first_non_empty(&stdout, &stderr)
            ));
        }

        let parsed: VoiceTranscriptionResponse = serde_json::from_str(&stdout)
            .map_err(|err| format!("Bad transcription response: {err}"))?;
        Ok(parsed.text.trim().to_string())
    }

    fn run_chat_command(content: &str) -> Result<String, String> {
        let payload = serde_json::json!({ "content": content }).to_string();
        let output = Command::new("/usr/bin/curl")
            .arg("-sS")
            .arg("--fail-with-body")
            .arg("--max-time")
            .arg("600")
            .arg("-X")
            .arg("POST")
            .arg("http://127.0.0.1:8420/api/v1/chat/run")
            .arg("-H")
            .arg("Content-Type: application/json")
            .arg("--data-binary")
            .arg(payload)
            .output()
            .map_err(|err| format!("Could not call local Hermes backend: {err}"))?;

        let stdout = String::from_utf8_lossy(&output.stdout);
        if !output.status.success() {
            let stderr = String::from_utf8_lossy(&output.stderr);
            return Err(format!(
                "Hermes backend error: {}",
                first_non_empty(&stdout, &stderr)
            ));
        }

        let parsed: ChatRunResponse =
            serde_json::from_str(&stdout).map_err(|err| format!("Bad Hermes response: {err}"))?;
        if let Some(error) = parsed.error.filter(|error| !error.trim().is_empty()) {
            return Err(error);
        }
        let response = parsed.response.trim().to_string();
        if response.is_empty() {
            Ok("Done.".to_string())
        } else {
            Ok(response)
        }
    }

    fn speak_response(text: &str) -> Result<(), String> {
        let output_path = temp_path("hermes-studio-native-talkback", "aiff");
        let payload = serde_json::json!({ "text": text }).to_string();
        let output = Command::new("/usr/bin/curl")
            .arg("-sS")
            .arg("--fail-with-body")
            .arg("--max-time")
            .arg("180")
            .arg("-X")
            .arg("POST")
            .arg("http://127.0.0.1:8420/api/v1/voice/speak")
            .arg("-H")
            .arg("Content-Type: application/json")
            .arg("--data-binary")
            .arg(payload)
            .arg("-o")
            .arg(&output_path)
            .output()
            .map_err(|err| format!("Could not synthesize voice: {err}"))?;

        if !output.status.success() {
            let stdout = String::from_utf8_lossy(&output.stdout);
            let stderr = String::from_utf8_lossy(&output.stderr);
            speak_fallback(text);
            return Err(format!(
                "Voice synthesis failed: {}",
                first_non_empty(&stdout, &stderr)
            ));
        }

        let status = Command::new("/usr/bin/afplay")
            .arg(&output_path)
            .status()
            .map_err(|err| format!("Could not play synthesized voice: {err}"));
        let _ = fs::remove_file(&output_path);
        status.and_then(|status| {
            if status.success() {
                Ok(())
            } else {
                Err("Could not play synthesized voice.".to_string())
            }
        })
    }

    fn speak_fallback(text: &str) {
        let _ = Command::new("/usr/bin/say").arg(text).status();
    }

    fn emit_native_status(app: &AppHandle, message: &str) {
        let _ = app.emit("voice-native-status", message.to_string());
    }

    fn temp_path(prefix: &str, extension: &str) -> std::path::PathBuf {
        let millis = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|duration| duration.as_millis())
            .unwrap_or_default();
        std::env::temp_dir().join(format!(
            "{prefix}-{}-{millis}.{extension}",
            std::process::id()
        ))
    }

    fn first_non_empty<'a>(first: &'a str, second: &'a str) -> String {
        let selected = if first.trim().is_empty() {
            second
        } else {
            first
        };
        selected.trim().chars().take(800).collect()
    }

    fn play_hotkey_registered_sound() {
        play_system_sound("/System/Library/Sounds/Glass.aiff", "0.25");
    }

    fn play_hotkey_released_sound() {
        play_system_sound("/System/Library/Sounds/Pop.aiff", "0.22");
    }

    fn play_system_sound(path: &'static str, volume: &'static str) {
        std::thread::spawn(move || {
            let _ = Command::new("/usr/bin/afplay")
                .arg("-v")
                .arg(volume)
                .arg(path)
                .status();
        });
    }

    fn emit_voice_event(app: &AppHandle, event: &str) {
        let _ = app.emit(
            event,
            VoiceHotkeyPayload {
                shortcut: VOICE_SHORTCUT_LABEL.to_string(),
            },
        );
    }

    fn emit_voice_event_after_delay(app: AppHandle, event: &'static str) {
        std::thread::spawn(move || {
            std::thread::sleep(Duration::from_millis(1200));
            emit_voice_event(&app, event);
        });
    }

    unsafe fn create_event_tap() -> CFMachPortRef {
        for tap_location in [EVENT_TAP_HID, EVENT_TAP_SESSION] {
            let event_tap = CGEventTapCreate(
                tap_location,
                EVENT_TAP_HEAD_INSERT,
                EVENT_TAP_LISTEN_ONLY,
                EVENT_MASK_FLAGS_CHANGED,
                flags_changed_callback,
                std::ptr::null_mut(),
            );
            if !event_tap.is_null() {
                return event_tap;
            }
        }
        std::ptr::null_mut()
    }

    fn show_registered_hud(app: &AppHandle) {
        if let Some(window) = app.get_webview_window("voice-hud") {
            show_hud_window(&window);
        }
    }

    fn update_hud_window(app: &AppHandle, _is_down: bool) {
        if let Some(window) = app.get_webview_window("voice-hud") {
            show_hud_window(&window);
        }
    }

    fn show_hud_window(window: &tauri::WebviewWindow) {
        let _ = window.set_always_on_top(true);
        let _ = window.set_visible_on_all_workspaces(true);
        let _ = window.set_focusable(false);
        position_hud_window(window);
        macos_hud_window::raise(window);
        let _ = window.show();
        macos_hud_window::raise(window);
    }

    fn position_hud_window(window: &tauri::WebviewWindow) {
        let monitor = window
            .cursor_position()
            .ok()
            .and_then(|position| {
                window
                    .monitor_from_point(position.x, position.y)
                    .ok()
                    .flatten()
            })
            .or_else(|| window.current_monitor().ok().flatten())
            .or_else(|| window.primary_monitor().ok().flatten());

        let Some(monitor) = monitor else {
            return;
        };

        let work_area = monitor.work_area();
        let window_size = window.outer_size().unwrap_or_else(|_| (88, 88).into());
        let margin = (18.0 * monitor.scale_factor()).round() as i32;
        let work_left = work_area.position.x;
        let work_top = work_area.position.y;
        let work_right = work_left + work_area.size.width as i32;
        let work_bottom = work_top + work_area.size.height as i32;
        let x = (work_right - window_size.width as i32 - margin).max(work_left);
        let y = (work_bottom - window_size.height as i32 - margin).max(work_top);
        let _ = window.set_position(tauri::PhysicalPosition::new(x, y));
    }

    unsafe extern "C" fn flags_changed_callback(
        _proxy: CGEventTapProxy,
        event_type: CGEventType,
        event: CGEventRef,
        _user_info: *mut c_void,
    ) -> CGEventRef {
        if event_type == EVENT_TAP_DISABLED_BY_TIMEOUT
            || event_type == EVENT_TAP_DISABLED_BY_USER_INPUT
        {
            let event_tap = EVENT_TAP_PORT.load(Ordering::SeqCst) as CFMachPortRef;
            if !event_tap.is_null() {
                CGEventTapEnable(event_tap, true);
            }
            return event;
        }

        if event_type != EVENT_FLAGS_CHANGED {
            return event;
        }

        handle_modifier_flags(CGEventGetFlags(event));
        event
    }

    fn handle_modifier_flags(flags: CGEventFlags) {
        let both_down = flags & FLAG_MASK_ALTERNATE != 0 && flags & FLAG_MASK_COMMAND != 0;
        let was_down = COMBO_DOWN.swap(both_down, Ordering::SeqCst);

        if both_down != was_down {
            if let Some(tx) = HOTKEY_TX.get() {
                let _ = tx.send(both_down);
            }
        }
    }

    mod native_audio {
        use std::ffi::{c_char, c_void, CString};
        use std::path::Path;

        type Id = *mut c_void;
        type Sel = *mut c_void;

        const AUDIO_FORMAT_MPEG4_AAC: u32 = 0x6161_6320;
        const AUDIO_QUALITY_HIGH: isize = 96;

        #[link(name = "AVFoundation", kind = "framework")]
        extern "C" {
            static AVFormatIDKey: Id;
            static AVSampleRateKey: Id;
            static AVNumberOfChannelsKey: Id;
            static AVEncoderAudioQualityKey: Id;
        }

        #[link(name = "objc")]
        extern "C" {
            fn objc_getClass(name: *const c_char) -> Id;
            fn sel_registerName(name: *const c_char) -> Sel;
            fn objc_msgSend();
        }

        pub fn start_recording(path: &Path) -> Result<usize, String> {
            let path = path
                .to_str()
                .ok_or_else(|| "Recording path is not valid UTF-8.".to_string())?;

            unsafe {
                let pool = autorelease_pool();
                let result = start_recording_inner(path).map(|recorder| recorder as usize);
                release(pool);
                result
            }
        }

        pub fn stop_recording(recorder: usize) {
            unsafe {
                let recorder = recorder as Id;
                if recorder.is_null() {
                    return;
                }
                send_no_args(recorder, "stop");
                release(recorder);
            }
        }

        unsafe fn start_recording_inner(path: &str) -> Result<Id, String> {
            let ns_path = ns_string(path)?;
            let url = send_id_id(class("NSURL")?, "fileURLWithPath:", ns_path);
            if url.is_null() {
                return Err("Could not create recording file URL.".to_string());
            }

            let settings = send_class_no_args(class("NSMutableDictionary")?, "dictionary");
            if settings.is_null() {
                return Err("Could not create audio recorder settings.".to_string());
            }
            dictionary_set(settings, number_u32(AUDIO_FORMAT_MPEG4_AAC)?, AVFormatIDKey);
            dictionary_set(settings, number_f64(44_100.0)?, AVSampleRateKey);
            dictionary_set(settings, number_isize(1)?, AVNumberOfChannelsKey);
            dictionary_set(
                settings,
                number_isize(AUDIO_QUALITY_HIGH)?,
                AVEncoderAudioQualityKey,
            );

            let recorder_class = class("AVAudioRecorder")?;
            let recorder_alloc = send_class_no_args(recorder_class, "alloc");
            let recorder = send_init_url_settings_error(
                recorder_alloc,
                "initWithURL:settings:error:",
                url,
                settings,
            );
            if recorder.is_null() {
                return Err("AVAudioRecorder could not be initialized.".to_string());
            }

            let _ = send_bool_no_args(recorder, "prepareToRecord");
            if !send_bool_no_args(recorder, "record") {
                release(recorder);
                return Err(
                    "AVAudioRecorder could not start. Check Hermes Studio microphone permission."
                        .to_string(),
                );
            }
            Ok(recorder)
        }

        unsafe fn autorelease_pool() -> Id {
            let Ok(pool_class) = class("NSAutoreleasePool") else {
                return std::ptr::null_mut();
            };
            let pool = send_class_no_args(pool_class, "alloc");
            send_no_args_return_id(pool, "init")
        }

        unsafe fn ns_string(value: &str) -> Result<Id, String> {
            let value =
                CString::new(value).map_err(|_| "String contains a null byte.".to_string())?;
            let string_class = class("NSString")?;
            let sel = selector_ref("stringWithUTF8String:");
            let msg_send: extern "C" fn(Id, Sel, *const c_char) -> Id =
                std::mem::transmute(objc_msgSend as *const ());
            Ok(msg_send(string_class, sel, value.as_ptr()))
        }

        unsafe fn number_u32(value: u32) -> Result<Id, String> {
            let sel = selector_ref("numberWithUnsignedInt:");
            let msg_send: extern "C" fn(Id, Sel, u32) -> Id =
                std::mem::transmute(objc_msgSend as *const ());
            Ok(msg_send(class("NSNumber")?, sel, value))
        }

        unsafe fn number_isize(value: isize) -> Result<Id, String> {
            let sel = selector_ref("numberWithInteger:");
            let msg_send: extern "C" fn(Id, Sel, isize) -> Id =
                std::mem::transmute(objc_msgSend as *const ());
            Ok(msg_send(class("NSNumber")?, sel, value))
        }

        unsafe fn number_f64(value: f64) -> Result<Id, String> {
            let sel = selector_ref("numberWithDouble:");
            let msg_send: extern "C" fn(Id, Sel, f64) -> Id =
                std::mem::transmute(objc_msgSend as *const ());
            Ok(msg_send(class("NSNumber")?, sel, value))
        }

        unsafe fn dictionary_set(dictionary: Id, object: Id, key: Id) {
            let sel = selector_ref("setObject:forKey:");
            let msg_send: extern "C" fn(Id, Sel, Id, Id) =
                std::mem::transmute(objc_msgSend as *const ());
            msg_send(dictionary, sel, object, key);
        }

        unsafe fn class(name: &str) -> Result<Id, String> {
            let name =
                CString::new(name).map_err(|_| "Class name contains a null byte.".to_string())?;
            let class = objc_getClass(name.as_ptr());
            if class.is_null() {
                Err("Objective-C class was not found.".to_string())
            } else {
                Ok(class)
            }
        }

        unsafe fn send_class_no_args(receiver: Id, selector: &str) -> Id {
            send_no_args_return_id(receiver, selector)
        }

        unsafe fn send_no_args_return_id(receiver: Id, selector: &str) -> Id {
            let sel = selector_ref(selector);
            let msg_send: extern "C" fn(Id, Sel) -> Id =
                std::mem::transmute(objc_msgSend as *const ());
            msg_send(receiver, sel)
        }

        unsafe fn send_id_id(receiver: Id, selector: &str, value: Id) -> Id {
            let sel = selector_ref(selector);
            let msg_send: extern "C" fn(Id, Sel, Id) -> Id =
                std::mem::transmute(objc_msgSend as *const ());
            msg_send(receiver, sel, value)
        }

        unsafe fn send_init_url_settings_error(
            receiver: Id,
            selector: &str,
            url: Id,
            settings: Id,
        ) -> Id {
            let sel = selector_ref(selector);
            let msg_send: extern "C" fn(Id, Sel, Id, Id, *mut Id) -> Id =
                std::mem::transmute(objc_msgSend as *const ());
            msg_send(receiver, sel, url, settings, std::ptr::null_mut())
        }

        unsafe fn send_bool_no_args(receiver: Id, selector: &str) -> bool {
            let sel = selector_ref(selector);
            let msg_send: extern "C" fn(Id, Sel) -> i8 =
                std::mem::transmute(objc_msgSend as *const ());
            msg_send(receiver, sel) != 0
        }

        unsafe fn send_no_args(receiver: Id, selector: &str) {
            let sel = selector_ref(selector);
            let msg_send: extern "C" fn(Id, Sel) = std::mem::transmute(objc_msgSend as *const ());
            msg_send(receiver, sel);
        }

        unsafe fn release(receiver: Id) {
            if !receiver.is_null() {
                send_no_args(receiver, "release");
            }
        }

        unsafe fn selector_ref(selector: &str) -> Sel {
            let selector =
                CString::new(selector).expect("selector names cannot contain null bytes");
            sel_registerName(selector.as_ptr())
        }
    }

    mod macos_hud_window {
        use std::ffi::{c_char, c_void, CString};

        type Id = *mut c_void;
        type Sel = *mut c_void;

        const NS_WINDOW_COLLECTION_BEHAVIOR_CAN_JOIN_ALL_SPACES: usize = 1 << 0;
        const NS_WINDOW_COLLECTION_BEHAVIOR_TRANSIENT: usize = 1 << 3;
        const NS_WINDOW_COLLECTION_BEHAVIOR_STATIONARY: usize = 1 << 4;
        const NS_WINDOW_COLLECTION_BEHAVIOR_IGNORES_CYCLE: usize = 1 << 6;
        const NS_WINDOW_COLLECTION_BEHAVIOR_FULL_SCREEN_AUXILIARY: usize = 1 << 8;
        const NS_WINDOW_COLLECTION_BEHAVIOR_CAN_JOIN_ALL_APPLICATIONS: usize = 1 << 18;
        const NS_WINDOW_STYLE_MASK_NONACTIVATING_PANEL: usize = 1 << 7;
        const NS_WINDOW_STYLE_MASK_HUD_WINDOW: usize = 1 << 13;
        const CG_WINDOW_LEVEL_KEY_ASSISTIVE_TECH_HIGH: i32 = 20;

        #[link(name = "ApplicationServices", kind = "framework")]
        extern "C" {
            fn CGWindowLevelForKey(key: i32) -> i32;
        }

        #[link(name = "objc")]
        extern "C" {
            fn sel_registerName(name: *const c_char) -> Sel;
            fn objc_msgSend();
        }

        pub fn raise(window: &tauri::WebviewWindow) {
            let scheduler = window.clone();
            let hud_window = window.clone();
            let _ = scheduler.run_on_main_thread(move || {
                let Ok(ns_window) = hud_window.ns_window() else {
                    return;
                };

                unsafe {
                    configure_overlay_window(ns_window);
                }
            });
        }

        unsafe fn configure_overlay_window(ns_window: Id) {
            if ns_window.is_null() {
                return;
            }

            send_bool(ns_window, "setCanHide:", false);
            send_bool(ns_window, "setHidesOnDeactivate:", false);
            send_bool(ns_window, "setIgnoresMouseEvents:", true);
            let style_mask = send_get_usize(ns_window, "styleMask")
                | NS_WINDOW_STYLE_MASK_NONACTIVATING_PANEL
                | NS_WINDOW_STYLE_MASK_HUD_WINDOW;
            send_usize(ns_window, "setStyleMask:", style_mask);
            send_isize(
                ns_window,
                "setLevel:",
                CGWindowLevelForKey(CG_WINDOW_LEVEL_KEY_ASSISTIVE_TECH_HIGH) as isize,
            );
            send_usize(
                ns_window,
                "setCollectionBehavior:",
                NS_WINDOW_COLLECTION_BEHAVIOR_CAN_JOIN_ALL_SPACES
                    | NS_WINDOW_COLLECTION_BEHAVIOR_TRANSIENT
                    | NS_WINDOW_COLLECTION_BEHAVIOR_STATIONARY
                    | NS_WINDOW_COLLECTION_BEHAVIOR_IGNORES_CYCLE
                    | NS_WINDOW_COLLECTION_BEHAVIOR_FULL_SCREEN_AUXILIARY
                    | NS_WINDOW_COLLECTION_BEHAVIOR_CAN_JOIN_ALL_APPLICATIONS,
            );
            send_no_args(ns_window, "orderFrontRegardless");
        }

        unsafe fn send_no_args(receiver: Id, selector: &str) {
            let sel = selector_ref(selector);
            let msg_send: extern "C" fn(Id, Sel) = std::mem::transmute(objc_msgSend as *const ());
            msg_send(receiver, sel);
        }

        unsafe fn send_bool(receiver: Id, selector: &str, value: bool) {
            let sel = selector_ref(selector);
            let msg_send: extern "C" fn(Id, Sel, i8) =
                std::mem::transmute(objc_msgSend as *const ());
            msg_send(receiver, sel, i8::from(value));
        }

        unsafe fn send_isize(receiver: Id, selector: &str, value: isize) {
            let sel = selector_ref(selector);
            let msg_send: extern "C" fn(Id, Sel, isize) =
                std::mem::transmute(objc_msgSend as *const ());
            msg_send(receiver, sel, value);
        }

        unsafe fn send_usize(receiver: Id, selector: &str, value: usize) {
            let sel = selector_ref(selector);
            let msg_send: extern "C" fn(Id, Sel, usize) =
                std::mem::transmute(objc_msgSend as *const ());
            msg_send(receiver, sel, value);
        }

        unsafe fn send_get_usize(receiver: Id, selector: &str) -> usize {
            let sel = selector_ref(selector);
            let msg_send: extern "C" fn(Id, Sel) -> usize =
                std::mem::transmute(objc_msgSend as *const ());
            msg_send(receiver, sel)
        }

        unsafe fn selector_ref(selector: &str) -> Sel {
            let selector =
                CString::new(selector).expect("selector names cannot contain null bytes");
            sel_registerName(selector.as_ptr())
        }
    }
}

#[cfg(target_os = "macos")]
mod macos {
    #[link(name = "ApplicationServices", kind = "framework")]
    extern "C" {
        fn AXIsProcessTrusted() -> bool;
    }

    #[link(name = "CoreGraphics", kind = "framework")]
    extern "C" {
        fn CGPreflightScreenCaptureAccess() -> bool;
        fn CGRequestScreenCaptureAccess() -> bool;
    }

    pub fn accessibility_trusted() -> bool {
        unsafe { AXIsProcessTrusted() }
    }

    pub fn screen_recording_granted() -> bool {
        unsafe { CGPreflightScreenCaptureAccess() }
    }

    pub fn request_screen_recording_permission() -> bool {
        unsafe { CGRequestScreenCaptureAccess() }
    }
}
