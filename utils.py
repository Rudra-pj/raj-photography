from PIL import Image, ImageFile, ImageOps
import qrcode
import os
import socket
from moviepy import VideoFileClip, ImageClip, CompositeVideoClip

# Support HEIC images (common from iPhones)
try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except ImportError:
    pass

# Handle truncated/corrupted images gracefully
ImageFile.LOAD_TRUNCATED_IMAGES = True

def generate_thumbnail(source_path, output_path, size=(400, 400)):
    """Generates a small JPEG thumbnail for an image or video."""
    try:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        file_ext = os.path.splitext(source_path)[1].lower()
        
        if file_ext in [".mp4", ".mov", ".avi"]:
            # For videos, take the first frame
            clip = VideoFileClip(source_path)
            # Use 1 second mark if possible to avoid black frames at 0
            t = min(1.0, clip.duration / 2)
            clip.save_frame(output_path, t=t)
            clip.close()
            # Then resize the saved frame
            img = Image.open(output_path)
        else:
            img = Image.open(source_path)
            img = ImageOps.exif_transpose(img)
            
        img.thumbnail(size, Image.Resampling.LANCZOS)
        if img.mode != "RGB":
            img = img.convert("RGB")
        img.save(output_path, "JPEG", quality=85)
        return output_path
    except Exception as e:
        print(f"Thumbnail error for {source_path}: {e}")
        return None

# def get_local_ip():
#     """Gets the local IP address of the machine to allow network access."""
#     try:
#         # Create a dummy socket to find the local IP
#         s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
#         s.connect(("8.8.8.8", 80))
#         local_ip = s.getsockname()[0]
#         s.close()
#         return local_ip
#     except:
#         return "localhost"
import os

def get_local_ip():
    #if os.getenv("STREAMLIT_SERVER_HEADLESS"):
        # Running on Streamlit Cloud
    return "https://raj-photographyy.streamlit.app"
    #else:
        # Running locally
        #return "http://localhost:8501"

def generate_qr_code(url, save_path):
    """Generates a QR code for the given URL and saves it to the specified path."""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(url)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")
    
    # Ensure directory exists
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    
    img.save(save_path)
    return save_path

def apply_watermark_to_image(base_image_path, watermark_path, output_path):
    """Overlays a watermark on an image at the bottom-right corner."""
    try:
        base_img = Image.open(base_image_path)
        # Handle phone image rotation (EXIF orientation)
        base_img = ImageOps.exif_transpose(base_img)
        base_img = base_img.convert("RGBA")
        
        watermark = Image.open(watermark_path).convert("RGBA")
    except Exception as e:
        raise ValueError(f"Could not open image. The file may be in an unsupported format or corrupted. Error: {str(e)}")

    base_w, base_h = base_img.size
    
    # Resize watermark to be 15% of the image width (smaller, more professional)
    wm_w, wm_h = watermark.size
    new_wm_w = int(base_w * 0.15)
    new_wm_h = int(wm_h * (new_wm_w / wm_w))
    watermark = watermark.resize((new_wm_w, new_wm_h), Image.Resampling.LANCZOS)

    # Apply 80% transparency to the watermark for a premium feel
    # This involves manipulating the alpha channel
    if watermark.mode == 'RGBA':
        alpha = watermark.getchannel('A')
        new_alpha = alpha.point(lambda i: int(i * 0.8)) # 80% of original opacity
        watermark.putalpha(new_alpha)

    # Position: Bottom-right with 3% padding (more breathing room)
    padding = int(base_w * 0.03)
    position = (base_w - new_wm_w - padding, base_h - new_wm_h - padding)

    # Create transparency layer
    transparent = Image.new('RGBA', (base_w, base_h), (0, 0, 0, 0))
    transparent.paste(base_img, (0, 0))
    transparent.paste(watermark, position, mask=watermark)
    
    # Convert back to RGB if saving as JPEG
    result = transparent.convert("RGB")
    
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    result.save(output_path, quality=95)
    return output_path

def apply_watermark_to_video(base_video_path, watermark_path, output_path):
    """Overlays a watermark on a video at the bottom-right corner."""
    # Placeholder implementation using MoviePy
    video = VideoFileClip(base_video_path)
    
    # Load and resize watermark
    padding_val = int(video.w * 0.03) # 3% padding matching images
    from moviepy.video.fx import Margin, Resize
    
    wm_clip = (ImageClip(watermark_path)
               .with_duration(video.duration)
               .with_effects([
                   Resize(width=video.w * 0.15),
                   Margin(right=padding_val, bottom=padding_val, opacity=0)
               ])
               .with_opacity(0.8)
               .with_position(("right", "bottom")))

    final = CompositeVideoClip([video, wm_clip])
    
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    # Note: This can be slow and might need optimization for production
    final.write_videofile(output_path, codec="libx264", audio_codec="aac")
    return output_path



