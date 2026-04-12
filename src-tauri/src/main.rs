use serde::Serialize;

#[derive(Serialize)]
struct MacPermissionStatus {
    platform: String,
    accessibility_trusted: Option<bool>,
    screen_recording_granted: Option<bool>,
    screen_recording_hint: Option<String>,
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
