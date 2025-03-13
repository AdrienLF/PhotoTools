from PIL import Image, ImageDraw, ImageFont, ImageFilter
import os

# Create output directory if it doesn't exist
output_dir = "tokyo_ward_titles"
if not os.path.exists(output_dir):
    os.makedirs(output_dir)

# Configuration
width, height = 1080, 1920  # 9:16 aspect ratio for vertical videos
background_color = (0, 0, 0, 0)  # Transparent background
kanji_color = (255, 255, 255, 255)  # White text
romaji_color = (255, 255, 255, 255)  # White text
shadow_color = (0, 0, 0, 128)  # Semi-transparent black for shadow
shadow_offset = (4, 4)  # Shadow offset (right and down)
shadow_blur = 3  # Blur radius for the shadow

# Tokyo's 23 wards with their Kanji and Romaji names
tokyo_wards = [
    {"kanji": "千代田区", "romaji": "Chiyoda"},
    {"kanji": "中央区", "romaji": "Chuo"},
    {"kanji": "港区", "romaji": "Minato"},
    {"kanji": "新宿区", "romaji": "Shinjuku"},
    {"kanji": "文京区", "romaji": "Bunkyo"},
    {"kanji": "台東区", "romaji": "Taito"},
    {"kanji": "墨田区", "romaji": "Sumida"},
    {"kanji": "江東区", "romaji": "Koto"},
    {"kanji": "品川区", "romaji": "Shinagawa"},
    {"kanji": "目黒区", "romaji": "Meguro"},
    {"kanji": "大田区", "romaji": "Ota"},
    {"kanji": "世田谷区", "romaji": "Setagaya"},
    {"kanji": "渋谷区", "romaji": "Shibuya"},
    {"kanji": "中野区", "romaji": "Nakano"},
    {"kanji": "杉並区", "romaji": "Suginami"},
    {"kanji": "豊島区", "romaji": "Toshima"},
    {"kanji": "北区", "romaji": "Kita"},
    {"kanji": "荒川区", "romaji": "Arakawa"},
    {"kanji": "板橋区", "romaji": "Itabashi"},
    {"kanji": "練馬区", "romaji": "Nerima"},
    {"kanji": "足立区", "romaji": "Adachi"},
    {"kanji": "葛飾区", "romaji": "Katsushika"},
    {"kanji": "江戸川区", "romaji": "Edogawa"}
]


# Function to draw text with a drop shadow
def draw_text_with_shadow(draw, position, text, font, text_color, shadow_color, shadow_offset, shadow_blur, image):
    # Create a temporary image for the shadow
    shadow_img = Image.new("RGBA", image.size, (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow_img)

    # Draw the text on the shadow image
    shadow_draw.text(
        (position[0] + shadow_offset[0], position[1] + shadow_offset[1]),
        text,
        font=font,
        fill=shadow_color
    )

    # Apply blur to the shadow
    shadow_img = shadow_img.filter(ImageFilter.GaussianBlur(radius=shadow_blur))

    # Composite the shadow onto the main image
    image = Image.alpha_composite(image, shadow_img)

    # Draw the actual text on the main image
    draw = ImageDraw.Draw(image)
    draw.text(position, text, fill=text_color, font=font)

    return image


# Function to generate title images
def generate_ward_title(ward_info):
    # Create a new transparent image
    image = Image.new("RGBA", (width, height), background_color)
    draw = ImageDraw.Draw(image)

    # Load fonts - you'll need to provide the actual font file paths
    try:
        kanji_font = ImageFont.truetype("AB_appare-Regular.ttf", 150)  # Adjust size as needed
        romaji_font = ImageFont.truetype("NotoSerifJP-VariableFont_wght.ttf", 80)
        romaji_font.set_variation_by_name('Bold')
        tilde_font = ImageFont.truetype("AB_appare-Regular.ttf", 80)  # For the tilde
    except IOError:
        print("Font files not found. Please update the font paths in the script.")
        return

    # Calculate positions for vertical text
    kanji_text = "\n".join(ward_info["kanji"])

    # Get text dimensions for centering
    kanji_bbox = draw.textbbox((0, 0), kanji_text, font=kanji_font, align='center')
    kanji_width = kanji_bbox[2] - kanji_bbox[0]
    kanji_height = kanji_bbox[3] - kanji_bbox[1]

    romaji_bbox = draw.textbbox((0, 0), ward_info["romaji"], font=romaji_font)
    romaji_width = romaji_bbox[2] - romaji_bbox[0]

    tilde_bbox = draw.textbbox((0, 0), "~", font=tilde_font)
    tilde_width = tilde_bbox[2] - tilde_bbox[0]

    # Center the kanji text horizontally and position it in the upper portion
    kanji_x = (width - kanji_width) // 2
    kanji_y = height // 3 - kanji_height // 2

    # Draw the kanji text with shadow
    image = draw_text_with_shadow(
        draw,
        (kanji_x, kanji_y),
        kanji_text,
        kanji_font,
        kanji_color,
        shadow_color,
        shadow_offset,
        shadow_blur,
        image
    )

    # Update draw object after modifying image
    draw = ImageDraw.Draw(image)

    # Calculate positions for tilde and romaji
    tilde_x = (width - tilde_width) // 2
    tilde_y = kanji_y + kanji_height + 40  # Adjust spacing as needed

    # Draw the romaji text centered below where the tilde would be
    romaji_x = (width - romaji_width) // 2
    romaji_y = tilde_y + tilde_bbox[3] - tilde_bbox[1] + 40  # Adjust spacing as needed

    # Draw the romaji text with shadow
    image = draw_text_with_shadow(
        draw,
        (romaji_x, romaji_y),
        ward_info["romaji"],
        romaji_font,
        romaji_color,
        shadow_color,
        shadow_offset,
        shadow_blur,
        image
    )

    # Save the image
    filename = f"{output_dir}/{ward_info['romaji'].lower()}_ward.png"
    image.save(filename)
    print(f"Generated: {filename}")


# Generate titles for all 23 wards
def generate_all_ward_titles():
    print(f"Generating title images for all 23 Tokyo wards...")
    for ward in tokyo_wards:
        generate_ward_title(ward)
    print(f"All titles generated in the '{output_dir}' directory.")


if __name__ == "__main__":
    generate_all_ward_titles()