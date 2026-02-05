use base64::{engine::general_purpose::STANDARD as BASE64, Engine as _};
use image::codecs::jpeg::JpegEncoder;
use image::imageops::FilterType;
use image::DynamicImage;
use xcap::Monitor;

#[derive(Debug, Clone)]
pub struct ScreenCapture {
    pub image_base64: String,
    pub width: u32,
    pub height: u32,
    pub screen_width: u32,
    pub screen_height: u32,
}

pub fn capture_screen(max_width: u32, quality: u8) -> Result<ScreenCapture, String> {
    let monitor = Monitor::all()
        .map_err(|e| e.to_string())?
        .into_iter()
        .next()
        .ok_or_else(|| "Монитор не найден".to_string())?;

    let screen_width = monitor.width().map_err(|e| e.to_string())?;
    let screen_height = monitor.height().map_err(|e| e.to_string())?;

    let image = monitor.capture_image().map_err(|e| e.to_string())?;
    let mut dynamic = DynamicImage::ImageRgba8(image);

    let target_width = if screen_width > max_width { max_width } else { screen_width };
    let target_height = ((screen_height as f32) * (target_width as f32 / screen_width as f32)) as u32;

    dynamic = dynamic.resize_exact(target_width, target_height, FilterType::Nearest);
    let rgb = dynamic.to_rgb8();

    let mut buffer = Vec::with_capacity(200_000);
    let mut encoder = JpegEncoder::new_with_quality(&mut buffer, quality);
    encoder.encode_image(&rgb).map_err(|e| e.to_string())?;

    Ok(ScreenCapture {
        image_base64: BASE64.encode(&buffer),
        width: target_width,
        height: target_height,
        screen_width,
        screen_height,
    })
}
