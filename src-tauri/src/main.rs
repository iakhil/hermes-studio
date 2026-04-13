use serde::Serialize;

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
            "accessibility" => "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
            "screen-recording" => "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture",
            "microphone" => "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone",
            "automation" => "x-apple.systempreferences:com.apple.preference.security?Privacy_Automation",
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
    tauri::Builder::default()
        .setup(|app| {
            #[cfg(target_os = "macos")]
            voice_hotkey::start(app.handle().clone());
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            mac_permission_status,
            request_accessibility_permission,
            request_screen_recording_permission,
            open_macos_privacy_pane
        ])
        .run(tauri::generate_context!())
        .expect("error while running Hermes Studio");
}

#[cfg(target_os = "macos")]
mod voice_hotkey {
    use super::VoiceHotkeyPayload;
    use std::ffi::c_void;
    use std::sync::atomic::{AtomicBool, Ordering};
    use std::sync::mpsc::{self, Sender};
    use std::sync::OnceLock;
    use tauri::{AppHandle, Emitter, Manager};

    const EVENT_FLAGS_CHANGED: u32 = 12;
    const EVENT_MASK_FLAGS_CHANGED: u64 = 1_u64 << EVENT_FLAGS_CHANGED;
    const EVENT_TAP_SESSION: u32 = 1;
    const EVENT_TAP_HEAD_INSERT: u32 = 0;
    const EVENT_TAP_LISTEN_ONLY: u32 = 1;
    const VOICE_SHORTCUT_LABEL: &str = "Option+Command";
    const FLAG_MASK_ALTERNATE: u64 = 0x0008_0000;
    const FLAG_MASK_COMMAND: u64 = 0x0010_0000;

    static HOTKEY_TX: OnceLock<Sender<bool>> = OnceLock::new();
    static COMBO_DOWN: AtomicBool = AtomicBool::new(false);

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

        let emit_app = app.clone();
        std::thread::spawn(move || {
            for is_down in rx {
                let event = if is_down {
                    "voice-hotkey-pressed"
                } else {
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

        std::thread::spawn(move || unsafe {
            let event_tap = CGEventTapCreate(
                EVENT_TAP_SESSION,
                EVENT_TAP_HEAD_INSERT,
                EVENT_TAP_LISTEN_ONLY,
                EVENT_MASK_FLAGS_CHANGED,
                flags_changed_callback,
                std::ptr::null_mut(),
            );

            if event_tap.is_null() {
                let _ = app.emit(
                    "voice-hotkey-unavailable",
                    VoiceHotkeyPayload {
                        shortcut: VOICE_SHORTCUT_LABEL.to_string(),
                    },
                );
                return;
            }

            let source = CFMachPortCreateRunLoopSource(std::ptr::null(), event_tap, 0);
            if source.is_null() {
                let _ = app.emit(
                    "voice-hotkey-unavailable",
                    VoiceHotkeyPayload {
                        shortcut: VOICE_SHORTCUT_LABEL.to_string(),
                    },
                );
                return;
            }

            CFRunLoopAddSource(CFRunLoopGetCurrent(), source, kCFRunLoopCommonModes);
            show_registered_hud(&app);
            let _ = app.emit(
                "voice-hotkey-registered",
                VoiceHotkeyPayload {
                    shortcut: VOICE_SHORTCUT_LABEL.to_string(),
                },
            );
            CFRunLoopRun();
        });
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
        let _ = window.show();
        macos_hud_window::raise(window);
    }

    unsafe extern "C" fn flags_changed_callback(
        _proxy: CGEventTapProxy,
        event_type: CGEventType,
        event: CGEventRef,
        _user_info: *mut c_void,
    ) -> CGEventRef {
        if event_type != EVENT_FLAGS_CHANGED {
            return event;
        }

        let flags = CGEventGetFlags(event);
        let both_down =
            flags & FLAG_MASK_ALTERNATE != 0 && flags & FLAG_MASK_COMMAND != 0;
        let was_down = COMBO_DOWN.swap(both_down, Ordering::SeqCst);

        if both_down != was_down {
            if let Some(tx) = HOTKEY_TX.get() {
                let _ = tx.send(both_down);
            }
        }

        event
    }

    mod macos_hud_window {
        use std::ffi::{c_char, c_void, CString};

        type Id = *mut c_void;
        type Sel = *mut c_void;

        const NS_SCREEN_SAVER_WINDOW_LEVEL: isize = 1000;
        const NS_WINDOW_COLLECTION_BEHAVIOR_CAN_JOIN_ALL_SPACES: usize = 1 << 0;
        const NS_WINDOW_COLLECTION_BEHAVIOR_TRANSIENT: usize = 1 << 3;
        const NS_WINDOW_COLLECTION_BEHAVIOR_STATIONARY: usize = 1 << 4;
        const NS_WINDOW_COLLECTION_BEHAVIOR_IGNORES_CYCLE: usize = 1 << 6;
        const NS_WINDOW_COLLECTION_BEHAVIOR_FULL_SCREEN_AUXILIARY: usize = 1 << 8;

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
            send_bool(ns_window, "setIgnoresMouseEvents:", true);
            send_isize(ns_window, "setLevel:", NS_SCREEN_SAVER_WINDOW_LEVEL);
            send_usize(
                ns_window,
                "setCollectionBehavior:",
                NS_WINDOW_COLLECTION_BEHAVIOR_CAN_JOIN_ALL_SPACES
                    | NS_WINDOW_COLLECTION_BEHAVIOR_TRANSIENT
                    | NS_WINDOW_COLLECTION_BEHAVIOR_STATIONARY
                    | NS_WINDOW_COLLECTION_BEHAVIOR_IGNORES_CYCLE
                    | NS_WINDOW_COLLECTION_BEHAVIOR_FULL_SCREEN_AUXILIARY,
            );
            send_no_args(ns_window, "orderFrontRegardless");
        }

        unsafe fn send_no_args(receiver: Id, selector: &str) {
            let sel = selector_ref(selector);
            let msg_send: extern "C" fn(Id, Sel) =
                std::mem::transmute(objc_msgSend as *const ());
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

        unsafe fn selector_ref(selector: &str) -> Sel {
            let selector = CString::new(selector).expect("selector names cannot contain null bytes");
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
