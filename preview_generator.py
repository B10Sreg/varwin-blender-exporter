import bpy
import os
import io

try:
    from PIL import Image, ImageDraw, ImageFont
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

def generate_preview_images(target=None, out_dir: str = "", title: str = None, is_scene: bool = False):
    """
    Renders or generates 3 preview assets required by Varwin:
    - view.jpg (512x512)
    - thumbnail.jpg (128x128)
    - bundle.png (256x256)
    Returns dict mapping filename -> bytes.
    """
    view_bytes = None
    thumb_bytes = None
    bundle_bytes = None

    if not out_dir:
        out_dir = os.path.expanduser("~")

    # Try Blender offscreen/render first if display/render engine and camera are active
    scene = bpy.context.scene if bpy.context else None
    if scene and scene.camera:
        try:
            render_path = os.path.join(out_dir, "_temp_render.png")

            # Save previous settings
            old_filepath = scene.render.filepath
            old_res_x = scene.render.resolution_x
            old_res_y = scene.render.resolution_y
            old_pct = scene.render.resolution_percentage

            scene.render.resolution_x = 512
            scene.render.resolution_y = 512
            scene.render.resolution_percentage = 100
            scene.render.filepath = render_path

            # Render current frame
            bpy.ops.render.render(write_still=True)

            if os.path.exists(render_path) and os.path.getsize(render_path) > 0:
                with Image.open(render_path) as img:
                    img_rgb = img.convert("RGB")
                    buf_view = io.BytesIO()
                    img_rgb.save(buf_view, format="JPEG", quality=90)
                    view_bytes = buf_view.getvalue()

                    buf_thumb = io.BytesIO()
                    img_rgb.resize((128, 128), Image.Resampling.LANCZOS).save(buf_thumb, format="JPEG", quality=85)
                    thumb_bytes = buf_thumb.getvalue()

                    buf_bundle = io.BytesIO()
                    img.resize((256, 256), Image.Resampling.LANCZOS).save(buf_bundle, format="PNG")
                    bundle_bytes = buf_bundle.getvalue()

                try:
                    os.remove(render_path)
                except Exception:
                    pass

            # Restore scene settings
            scene.render.filepath = old_filepath
            scene.render.resolution_x = old_res_x
            scene.render.resolution_y = old_res_y
            scene.render.resolution_percentage = old_pct
        except Exception:
            # Fallback to PIL synthetic rendering
            pass

    # If Blender render was not used, generate via PIL or native Blender image
    if not view_bytes or not thumb_bytes or not bundle_bytes:
        if HAS_PIL:
            # Dark industrial slate background
            img = Image.new("RGBA", (512, 512), color=(26, 29, 36, 255))
            draw = ImageDraw.Draw(img)

            # Draw tech border & grid accents
            draw.rectangle([(16, 16), (496, 496)], outline=(58, 64, 80), width=2)
            draw.line([(16, 400), (496, 400)], fill=(45, 50, 62), width=1)

            center_x, center_y = 256, 220

            if is_scene:
                # Draw horizon / landscape icon for scene template
                draw.rectangle([(120, 140), (392, 280)], fill=(32, 38, 50), outline=(80, 130, 200), width=2)
                # Mountain/grid lines
                draw.polygon([(140, 260), (220, 170), (280, 240)], fill=(45, 80, 130))
                draw.polygon([(240, 260), (310, 190), (370, 260)], fill=(60, 105, 170))
                draw.ellipse([(320, 155), (350, 185)], fill=(240, 200, 80)) # Sun
                sub_label = "VARWIN SCENE TEMPLATE"
            else:
                # Isometric cube points
                p_top = (center_x, center_y - 90)
                p_right = (center_x + 100, center_y - 30)
                p_bottom = (center_x, center_y + 30)
                p_left = (center_x - 100, center_y - 30)
                p_bot_left = (center_x - 100, center_y + 90)
                p_bot_mid = (center_x, center_y + 150)
                p_bot_right = (center_x + 100, center_y + 90)

                # Top face
                draw.polygon([p_top, p_right, p_bottom, p_left], fill=(60, 110, 180, 255), outline=(100, 160, 240, 255))
                # Left face
                draw.polygon([p_left, p_bottom, p_bot_mid, p_bot_left], fill=(40, 75, 130, 255), outline=(100, 160, 240, 255))
                # Right face
                draw.polygon([p_bottom, p_right, p_bot_right, p_bot_mid], fill=(30, 60, 105, 255), outline=(100, 160, 240, 255))
                sub_label = "VARWIN OBJECT"

            # Text label
            label = title or (target.name if hasattr(target, 'name') else "Varwin Asset")
            draw.text((256, 430), label[:22], fill=(220, 225, 235), anchor="mm")
            draw.text((256, 460), sub_label, fill=(120, 135, 160), anchor="mm")

            # Convert to view.jpg
            img_rgb = img.convert("RGB")
            buf_view = io.BytesIO()
            img_rgb.save(buf_view, format="JPEG", quality=92)
            view_bytes = buf_view.getvalue()

            # thumbnail.jpg (128x128)
            buf_thumb = io.BytesIO()
            img_rgb.resize((128, 128), Image.Resampling.LANCZOS).save(buf_thumb, format="JPEG", quality=85)
            thumb_bytes = buf_thumb.getvalue()

            # bundle.png (256x256)
            buf_bundle = io.BytesIO()
            img.resize((256, 256), Image.Resampling.LANCZOS).save(buf_bundle, format="PNG")
            bundle_bytes = buf_bundle.getvalue()
        else:
            # Minimal valid 1x1 png fallback bytes so package is never corrupted if PIL is not installed
            dummy_png = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfe\xa74e\xee\x00\x00\x00\x00IEND\xaeB`\x82'
            bundle_bytes = dummy_png
            view_bytes = dummy_png
            thumb_bytes = dummy_png

    return {
        "view.jpg": view_bytes,
        "thumbnail.jpg": thumb_bytes,
        "bundle.png": bundle_bytes,
        "spritesheet.jpg": view_bytes
    }
