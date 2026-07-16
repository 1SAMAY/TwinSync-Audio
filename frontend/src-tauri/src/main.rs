#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    if let Err(error) = twinsync_audio_lib::run() {
        show_startup_error(&error);
    }
}

#[cfg(windows)]
fn show_startup_error(error: &str) {
    use std::{iter, ptr};

    #[link(name = "user32")]
    unsafe extern "system" {
        fn MessageBoxW(
            window: *mut core::ffi::c_void,
            text: *const u16,
            caption: *const u16,
            kind: u32,
        ) -> i32;
    }

    let message = format!(
        "TwinSync Audio could not start.\n\nThe bundled Microsoft Edge WebView2 runtime or another required Windows component is missing or damaged. TwinSync never downloads dependencies silently. Reinstall TwinSync Audio or re-extract the complete portable ZIP.\n\nDetails: {error}"
    );
    let text: Vec<u16> = message.encode_utf16().chain(iter::once(0)).collect();
    let caption: Vec<u16> = "TwinSync Audio startup error"
        .encode_utf16()
        .chain(iter::once(0))
        .collect();
    unsafe { MessageBoxW(ptr::null_mut(), text.as_ptr(), caption.as_ptr(), 0x10) };
}

#[cfg(not(windows))]
fn show_startup_error(error: &str) {
    eprintln!("TwinSync Audio could not start: {error}");
}
