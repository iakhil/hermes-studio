fn main() {
    ensure_backend_sidecar_placeholder();
    tauri_build::build()
}

fn ensure_backend_sidecar_placeholder() {
    let Ok(target) = std::env::var("TARGET") else {
        return;
    };
    let manifest_dir = std::path::PathBuf::from(
        std::env::var("CARGO_MANIFEST_DIR").unwrap_or_else(|_| ".".to_string()),
    );
    let sidecar = manifest_dir
        .join("bin")
        .join(format!("hermes-studio-backend-{target}"));
    if sidecar.exists() {
        return;
    }

    if let Some(parent) = sidecar.parent() {
        let _ = std::fs::create_dir_all(parent);
    }

    let _ = std::fs::write(
        &sidecar,
        "#!/usr/bin/env sh\nprintf 'Hermes Studio backend sidecar has not been built. Run npm run desktop:build.\\n' >&2\nexit 1\n",
    );

    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        if let Ok(metadata) = std::fs::metadata(&sidecar) {
            let mut permissions = metadata.permissions();
            permissions.set_mode(0o755);
            let _ = std::fs::set_permissions(&sidecar, permissions);
        }
    }
}
