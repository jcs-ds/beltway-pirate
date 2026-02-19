#!/usr/bin/env python3
"""
Download organization icons from Wikimedia Commons.
Based on organization_icon_sourcing_guide.md

Usage:
    python scripts/download_org_icons.py [--all] [--service SERVICE]
"""

import os
import re
import sys
import time
import argparse
import requests
from pathlib import Path
from urllib.parse import quote

# Base paths
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
ICONS_DIR = PROJECT_ROOT / "frontend" / "public" / "assets" / "org-icons"

# Wikimedia API endpoint
WIKI_API = "https://commons.wikimedia.org/w/api.php"

# Core service/organization seals - these are the high-priority fallback images
CORE_ICONS = {
    # DoD-level
    "dod/dod": "File:United_States_Department_of_Defense_Seal.svg",
    "dod/darpa": "File:DARPA_Logo.svg",
    "dod/disa": "File:Defense_Information_Systems_Agency_seal.svg",
    "dod/dia": "File:US_Defense_Intelligence_Agency_(DIA)_seal.svg",
    "dod/nsa": "File:Seal_of_the_U.S._National_Security_Agency.svg",
    "dod/diu": "File:Defense_Innovation_Unit_Logo.svg",

    # Army
    "army/army": "File:United_States_Army_Seal.svg",
    "army/amc": "File:United_States_Army_Materiel_Command_SSI.svg",
    "army/tradoc": "File:United_States_Army_Training_and_Doctrine_Command_SSI.svg",
    "army/forscom": "File:United_States_Army_Forces_Command_SSI.svg",
    "army/arcyber": "File:United_States_Army_Cyber_Command_SSI.svg",
    "army/inscom": "File:INSCOM_SSI.svg",
    "army/afc": "File:Army_Futures_Command_SSI.svg",
    "army/devcom": "File:Combat_Capabilities_Development_Command_logo.svg",
    "army/peo-aviation": "File:PEO_Aviation.svg",

    # Navy
    "navy/navy": "File:Emblem_of_the_United_States_Navy.svg",
    "navy/navsea": "File:Seal_of_the_United_States_Naval_Sea_Systems_Command.svg",
    "navy/navair": "File:Seal_of_the_United_States_Naval_Air_Systems_Command.svg",
    "navy/navwar": "File:NAVWAR_logo.svg",
    "navy/onr": "File:Office_of_Naval_Research_Official_Logo.svg",
    "navy/nrl": "File:US_Naval_Research_Laboratory_Logo.svg",
    "navy/fleet-cyber": "File:Seal_of_the_United_States_Fleet_Cyber_Command.svg",

    # Air Force
    "air-force/air-force": "File:Seal_of_the_United_States_Department_of_the_Air_Force.svg",
    "air-force/acc": "File:Air_Combat_Command.svg",
    "air-force/amc": "File:Air_Mobility_Command.svg",
    "air-force/afmc": "File:Air_Force_Materiel_Command.svg",
    "air-force/afsoc": "File:Air_Force_Special_Operations_Command.svg",
    "air-force/pacaf": "File:Pacific_Air_Forces.svg",
    "air-force/usafe": "File:United_States_Air_Forces_in_Europe_-_Air_Forces_Africa.svg",
    "air-force/aflcmc": "File:Air_Force_Life_Cycle_Management_Center.svg",
    "air-force/afrl": "File:Air_Force_Research_Laboratory.svg",
    "air-force/afwerx": "File:AFWERX_logo.svg",
    "air-force/16th-af": "File:Sixteenth_Air_Force.svg",
    "air-force/350th-sww": "File:350th_Spectrum_Warfare_Wing.svg",

    # Space Force
    "space-force/space-force": "File:Seal_of_the_United_States_Space_Force.svg",
    "space-force/ssc": "File:Space_Systems_Command.svg",
    "space-force/sda": "File:Space_Development_Agency_logo.svg",
    "space-force/spoc": "File:Space_Operations_Command.svg",
    "space-force/starcom": "File:Space_Training_and_Readiness_Command.svg",

    # Marine Corps
    "usmc/usmc": "File:Emblem_of_the_United_States_Marine_Corps.svg",
    "usmc/marforcyber": "File:United_States_Marine_Corps_Forces_Cyberspace_Command_insignia_(transparent_background).svg",
    "usmc/marcorsyscom": "File:Marine_Corps_Systems_Command_Logo.svg",

    # SOCOM
    "socom/socom": "File:Seal_of_the_United_States_Special_Operations_Command.svg",
    "socom/jsoc": "File:Joint_Special_Operations_Command_emblem.svg",
    "socom/marsoc": "File:Seal_of_the_United_States_Marine_Corps_Forces_Special_Operations_Command.svg",
    "socom/usasoc": "File:United_States_Army_Special_Operations_Command_SSI_(1989-2015).svg",
    "socom/nsw": "File:Naval_Special_Warfare_Command_insignia_(transparent_background).svg",

    # COCOMs
    "dod/cybercom": "File:Seal_of_the_United_States_Cyber_Command.svg",
    "dod/stratcom": "File:Seal_of_the_United_States_Strategic_Command.svg",
    "dod/northcom": "File:Seal_of_the_United_States_Northern_Command.svg",
    "dod/southcom": "File:Seal_of_the_United_States_Southern_Command.svg",
    "dod/centcom": "File:Seal_of_the_United_States_Central_Command.svg",
    "dod/eucom": "File:Seal_of_the_United_States_European_Command.svg",
    "dod/africom": "File:Seal_of_the_United_States_Africa_Command.svg",
    "dod/indopacom": "File:Seal_of_the_United_States_Indo-Pacific_Command.svg",
    "dod/transcom": "File:Seal_of_the_United_States_Transportation_Command.svg",
    "dod/spacecom": "File:Seal_of_the_United_States_Space_Command.svg",

    # Congress
    "congress/congress": "File:Seal_of_the_United_States_Congress.svg",
    "congress/house": "File:Seal_of_the_United_States_House_of_Representatives.svg",
    "congress/senate": "File:Seal_of_the_United_States_Senate.svg",
}


def get_image_url(file_name: str) -> str | None:
    """Get the direct image URL from Wikimedia Commons."""
    params = {
        "action": "query",
        "titles": file_name,
        "prop": "imageinfo",
        "iiprop": "url",
        "format": "json",
    }

    # Wikimedia requires a User-Agent header
    headers = {
        "User-Agent": "DoD-Intel-Platform/1.0 (educational project; https://github.com/) Python/requests"
    }

    try:
        resp = requests.get(WIKI_API, params=params, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        pages = data.get("query", {}).get("pages", {})
        for page_id, page_data in pages.items():
            if page_id == "-1":
                print(f"  [WARN] File not found: {file_name}")
                return None
            imageinfo = page_data.get("imageinfo", [])
            if imageinfo:
                return imageinfo[0].get("url")
    except Exception as e:
        print(f"  [ERROR] API error for {file_name}: {e}")
        return None

    return None


def download_image(url: str, output_path: Path) -> bool:
    """Download an image and save it."""
    headers = {
        "User-Agent": "DoD-Intel-Platform/1.0 (educational project; https://github.com/) Python/requests"
    }
    try:
        resp = requests.get(url, headers=headers, timeout=60)
        resp.raise_for_status()

        # Ensure parent directory exists
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Save the file
        with open(output_path, "wb") as f:
            f.write(resp.content)

        return True
    except Exception as e:
        print(f"  [ERROR] Download failed: {e}")
        return False


def remove_white_background(png_path: Path, tolerance: int = 30) -> bool:
    """Remove white/light background from a PNG, making it transparent.

    Args:
        png_path: Path to the PNG file
        tolerance: How close to white a pixel must be to be made transparent (0-255)
    """
    try:
        from PIL import Image
        import numpy as np

        img = Image.open(png_path).convert("RGBA")
        data = np.array(img)

        # Find pixels that are close to white (R, G, B all > 255 - tolerance)
        # and make them transparent
        r, g, b, a = data[:, :, 0], data[:, :, 1], data[:, :, 2], data[:, :, 3]

        # Pixels where all RGB channels are above threshold (near white)
        threshold = 255 - tolerance
        white_mask = (r > threshold) & (g > threshold) & (b > threshold)

        # Also catch pure white
        pure_white = (r == 255) & (g == 255) & (b == 255)

        # Combine masks
        bg_mask = white_mask | pure_white

        # Set alpha to 0 for background pixels
        data[:, :, 3] = np.where(bg_mask, 0, a)

        # Save the result
        result = Image.fromarray(data)
        result.save(png_path, "PNG")
        return True

    except ImportError:
        print("  [WARN] Pillow/numpy not available for background removal")
        return False
    except Exception as e:
        print(f"  [WARN] Background removal failed: {e}")
        return False


def convert_svg_to_png(svg_path: Path, png_path: Path, size: int = 256) -> bool:
    """Convert SVG to PNG using cairosvg or Pillow."""
    converted = False

    try:
        # Try cairosvg first (better SVG support)
        import cairosvg
        cairosvg.svg2png(url=str(svg_path), write_to=str(png_path),
                        output_width=size, output_height=size)
        converted = True
    except (ImportError, OSError):
        # OSError occurs when Cairo library is not installed on the system
        pass

    if not converted:
        try:
            # Fall back to svglib + reportlab
            from svglib.svglib import svg2rlg
            from reportlab.graphics import renderPM

            drawing = svg2rlg(str(svg_path))
            if drawing:
                # Scale to target size
                scale = size / max(drawing.width, drawing.height)
                drawing.scale(scale, scale)
                drawing.width *= scale
                drawing.height *= scale

                png_data = renderPM.drawToString(drawing, fmt="PNG")
                with open(png_path, "wb") as f:
                    f.write(png_data)
                converted = True
        except ImportError:
            pass

    if converted:
        # Try to remove white background from the converted PNG
        remove_white_background(png_path)
        return True

    # No conversion available - just keep the SVG
    return False


def process_icon(icon_path: str, wiki_file: str, force: bool = False) -> bool:
    """Download and process a single icon."""
    # Determine output paths
    png_path = ICONS_DIR / f"{icon_path}.png"
    svg_path = ICONS_DIR / f"{icon_path}.svg"

    # Skip if already exists (unless force)
    if png_path.exists() and not force:
        print(f"  [SKIP] {icon_path} already exists")
        return True

    print(f"  Processing {icon_path}...")

    # Get the image URL
    url = get_image_url(wiki_file)
    if not url:
        return False

    # Determine if it's SVG or raster
    is_svg = url.lower().endswith(".svg")

    if is_svg:
        # Download SVG first
        if not download_image(url, svg_path):
            return False

        # Try to convert to PNG
        if convert_svg_to_png(svg_path, png_path):
            # Remove SVG if conversion succeeded
            svg_path.unlink(missing_ok=True)
            print(f"  [OK] Downloaded and converted {icon_path}")
        else:
            # Keep SVG - the frontend can handle SVG files
            print(f"  [OK] Downloaded {icon_path} (SVG only - no PNG conversion available)")
    else:
        # Download raster image directly
        if not download_image(url, png_path):
            return False
        print(f"  [OK] Downloaded {icon_path}")

    return True


def fix_all_backgrounds(tolerance: int = 30) -> int:
    """Remove white backgrounds from all existing PNG icons."""
    png_files = list(ICONS_DIR.rglob("*.png"))
    print(f"Processing {len(png_files)} PNG files...")

    fixed = 0
    for png_path in png_files:
        rel_path = png_path.relative_to(ICONS_DIR)
        if remove_white_background(png_path, tolerance):
            print(f"  [OK] Fixed {rel_path}")
            fixed += 1
        else:
            print(f"  [SKIP] {rel_path}")

    return fixed


def main():
    parser = argparse.ArgumentParser(description="Download organization icons from Wikimedia Commons")
    parser.add_argument("--all", action="store_true", help="Download all core icons")
    parser.add_argument("--service", type=str, help="Download icons for specific service (dod, army, navy, etc.)")
    parser.add_argument("--force", action="store_true", help="Re-download existing icons")
    parser.add_argument("--fix-backgrounds", action="store_true", help="Remove white backgrounds from existing PNGs")
    parser.add_argument("--tolerance", type=int, default=30, help="Background removal tolerance (0-255, default 30)")
    args = parser.parse_args()

    # Handle fix-backgrounds mode
    if args.fix_backgrounds:
        print("Removing white backgrounds from existing icons...")
        fixed = fix_all_backgrounds(args.tolerance)
        print(f"\nDone! Fixed {fixed} icons.")
        return 0

    # Determine which icons to download
    if args.service:
        icons = {k: v for k, v in CORE_ICONS.items() if k.startswith(args.service + "/")}
        if not icons:
            print(f"No icons found for service: {args.service}")
            print(f"Available: dod, army, navy, air-force, space-force, usmc, socom, congress")
            return 1
    elif args.all:
        icons = CORE_ICONS
    else:
        # Default: just download the main service seals
        icons = {k: v for k, v in CORE_ICONS.items() if k.count("/") == 1 and k.endswith(k.split("/")[0])}

    print(f"Downloading {len(icons)} icons...")
    print(f"Output directory: {ICONS_DIR}")
    print()

    success = 0
    failed = 0

    for icon_path, wiki_file in icons.items():
        if process_icon(icon_path, wiki_file, args.force):
            success += 1
        else:
            failed += 1

        # Rate limiting - be nice to Wikimedia
        time.sleep(0.5)

    print()
    print(f"Done! Success: {success}, Failed: {failed}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
