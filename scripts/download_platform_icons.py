#!/usr/bin/env python3
"""
Platform Icon Downloader for DoD Intel Platform
Downloads images from Wikimedia Commons and resizes to 512x512 PNG
Automatically searches for real images when specified files don't exist
"""

import os
import re
import sys
import time
from pathlib import Path
from io import BytesIO
from typing import Optional, List, Tuple
from dataclasses import dataclass
import requests
from PIL import Image

# Configuration
OUTPUT_DIR = Path(__file__).parent.parent / "frontend" / "public" / "assets" / "platforms"
IMAGE_SIZE = (512, 512)
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
TIMEOUT = 30
DELAY = 1.0  # Delay between requests to be nice to the API

# User agent for Wikimedia API (required)
HEADERS = {
    "User-Agent": "DoD-Intel-Platform/1.0 (Platform icon downloader for educational defense intel platform; contact: educational-use)"
}

@dataclass
class PlatformIcon:
    """Represents a platform icon to download."""
    name: str
    search_terms: List[str]  # Search terms to find images
    category: str

# All platforms with search terms for finding real images
PLATFORMS: List[PlatformIcon] = [
    # Air Platforms - Army Aviation
    PlatformIcon("AH-64-Apache", ["AH-64 Apache helicopter"], "Air"),
    PlatformIcon("CH-47F-Chinook", ["CH-47 Chinook helicopter"], "Air"),
    PlatformIcon("MQ-1C-Gray-Eagle", ["MQ-1C Gray Eagle", "Gray Eagle UAV"], "Air"),
    PlatformIcon("RQ-7-Shadow", ["RQ-7 Shadow UAV", "RQ-7 Shadow"], "Air"),
    PlatformIcon("UH-60M-Black-Hawk", ["UH-60 Black Hawk helicopter"], "Air"),

    # Air Platforms - Navy/Marine Aviation
    PlatformIcon("AH-1Z-Viper", ["AH-1Z Viper helicopter", "USMC AH-1Z"], "Air"),
    PlatformIcon("CH-53K-King-Stallion", ["CH-53K King Stallion", "CH-53E Super Stallion"], "Air"),
    PlatformIcon("MH-60R-Seahawk", ["MH-60R Seahawk", "SH-60 Seahawk"], "Air"),
    PlatformIcon("MH-60S-Seahawk", ["MH-60S Seahawk", "MH-60S Knighthawk"], "Air"),
    PlatformIcon("UH-1Y-Venom", ["UH-1Y Venom helicopter"], "Air"),

    # Air Platforms - ISR
    PlatformIcon("E-2D-Hawkeye", ["E-2 Hawkeye aircraft", "E-2D Advanced Hawkeye"], "Air"),
    PlatformIcon("E-3-AWACS", ["E-3 Sentry AWACS", "Boeing E-3"], "Air"),
    PlatformIcon("E-8-JSTARS", ["E-8 Joint STARS", "E-8C JSTARS"], "Air"),
    PlatformIcon("P-8A-Poseidon", ["P-8 Poseidon aircraft", "Boeing P-8"], "Air"),
    PlatformIcon("RC-135-Rivet-Joint", ["RC-135 Rivet Joint", "RC-135 aircraft"], "Air"),

    # Air Platforms - Special Mission
    PlatformIcon("AC-130J-Ghostrider", ["AC-130 Ghostrider", "AC-130 gunship"], "Air"),
    PlatformIcon("EC-37B-Compass-Call", ["EC-130H Compass Call", "Compass Call aircraft"], "Air"),
    PlatformIcon("MC-130J-Commando-II", ["MC-130J Commando", "MC-130 aircraft"], "Air"),

    # Air Platforms - Tanker
    PlatformIcon("KC-135-Stratotanker", ["KC-135 Stratotanker", "Boeing KC-135"], "Air"),
    PlatformIcon("KC-46-Pegasus", ["KC-46 Pegasus tanker", "KC-46A"], "Air"),

    # Air Platforms - Tiltrotor
    PlatformIcon("CMV-22B-Osprey", ["V-22 Osprey", "CMV-22 Osprey"], "Air"),
    PlatformIcon("CV-22B-Osprey", ["CV-22 Osprey", "V-22 Osprey USAF"], "Air"),
    PlatformIcon("MV-22B-Osprey", ["MV-22 Osprey", "V-22 Osprey Marines"], "Air"),

    # Air Platforms - Transport
    PlatformIcon("C-130J-Hercules", ["C-130J Super Hercules", "Lockheed C-130J"], "Air"),
    PlatformIcon("C-17-Globemaster", ["C-17 Globemaster", "Boeing C-17"], "Air"),
    PlatformIcon("C-5-Galaxy", ["C-5 Galaxy aircraft", "Lockheed C-5"], "Air"),

    # Air Platforms - UAS
    PlatformIcon("MQ-4C-Triton", ["MQ-4C Triton", "Triton UAV"], "Air"),
    PlatformIcon("MQ-9-Reaper", ["MQ-9 Reaper drone", "General Atomics MQ-9"], "Air"),
    PlatformIcon("RQ-4-Global-Hawk", ["RQ-4 Global Hawk", "Global Hawk UAV"], "Air"),

    # Land Platforms - Combat Vehicles
    PlatformIcon("ACV", ["Amphibious Combat Vehicle", "BAE ACV"], "Land"),
    PlatformIcon("AMPV", ["Armored Multi-Purpose Vehicle", "AMPV vehicle"], "Land"),
    PlatformIcon("JLTV", ["Joint Light Tactical Vehicle", "Oshkosh JLTV"], "Land"),
    PlatformIcon("M1A2-Abrams", ["M1 Abrams tank", "M1A2 Abrams"], "Land"),
    PlatformIcon("M2-Bradley", ["M2 Bradley fighting vehicle", "Bradley IFV"], "Land"),
    PlatformIcon("M-ATV", ["M-ATV vehicle", "Oshkosh M-ATV"], "Land"),
    PlatformIcon("MaxxPro-MRAP", ["MaxxPro MRAP", "Navistar MaxxPro"], "Land"),
    PlatformIcon("Stryker", ["Stryker vehicle", "M1126 Stryker"], "Land"),

    # Land Platforms - Air Defense
    PlatformIcon("Avenger", ["Avenger air defense", "AN/TWQ-1 Avenger"], "Land"),
    PlatformIcon("M-SHORAD", ["M-SHORAD Stryker", "Maneuver SHORAD"], "Land"),
    PlatformIcon("NASAMS", ["NASAMS missile", "NASAMS launcher"], "Land"),
    PlatformIcon("Patriot", ["Patriot missile system", "MIM-104 Patriot"], "Land"),

    # Land Platforms - Artillery
    PlatformIcon("HIMARS", ["HIMARS rocket system", "M142 HIMARS"], "Land"),
    PlatformIcon("M109-Paladin", ["M109 Paladin howitzer", "M109A6 Paladin"], "Land"),
    PlatformIcon("M120-Mortar", ["M120 mortar", "120mm mortar"], "Land"),
    PlatformIcon("M777", ["M777 howitzer", "M777 artillery"], "Land"),
    PlatformIcon("MLRS", ["M270 MLRS", "Multiple Launch Rocket System"], "Land"),

    # Land Platforms - Strategic Fires
    PlatformIcon("LRHW-Dark-Eagle", ["Dark Eagle hypersonic", "LRHW missile"], "Land"),
    PlatformIcon("MRC-Typhon", ["Typhon missile system", "Mid-Range Capability"], "Land"),

    # Land Platforms - Engineering
    PlatformIcon("Buffalo-MPCV", ["Buffalo mine protected vehicle", "Buffalo MPCV"], "Land"),
    PlatformIcon("D7-Armored-Bulldozer", ["D7 armored bulldozer", "Caterpillar D7 armored"], "Land"),
    PlatformIcon("Husky-VMMD", ["Husky VMMD", "Husky mine detector"], "Land"),
    PlatformIcon("Joint-Assault-Bridge", ["Joint Assault Bridge", "M60 AVLB"], "Land"),

    # Land Platforms - Logistics
    PlatformIcon("FMTV", ["FMTV truck", "Family of Medium Tactical Vehicles"], "Land"),
    PlatformIcon("HEMTT", ["HEMTT truck", "Heavy Expanded Mobility Tactical Truck"], "Land"),
    PlatformIcon("HET", ["M1070 HET", "Heavy Equipment Transporter"], "Land"),
    PlatformIcon("PLS", ["Palletized Load System", "PLS truck Army"], "Land"),

    # Sea Platforms - Surface Combatants
    PlatformIcon("DDG-51-Arleigh-Burke", ["USS Arleigh Burke", "Arleigh Burke destroyer"], "Sea"),
    PlatformIcon("FFG-62-Constellation", ["Constellation class frigate", "FFG-62"], "Sea"),
    PlatformIcon("LCS-Freedom", ["USS Freedom LCS", "Freedom class LCS"], "Sea"),
    PlatformIcon("LCS-Independence", ["USS Independence LCS", "Independence class LCS"], "Sea"),

    # Sea Platforms - Small Surface
    PlatformIcon("Avenger-MCM", ["USS Avenger MCM", "Avenger class minesweeper"], "Sea"),
    PlatformIcon("Cyclone-PC", ["Cyclone class patrol", "USS Cyclone"], "Sea"),
    PlatformIcon("Mark-VI-Patrol-Boat", ["Mark VI patrol boat", "Mark VI Navy"], "Sea"),

    # Sea Platforms - Amphibious
    PlatformIcon("LCAC", ["LCAC hovercraft", "Landing Craft Air Cushion"], "Sea"),
    PlatformIcon("LHA-America", ["USS America LHA", "America class"], "Sea"),
    PlatformIcon("LHD-Wasp", ["USS Wasp LHD", "Wasp class"], "Sea"),
    PlatformIcon("LPD-17-San-Antonio", ["USS San Antonio LPD", "San Antonio class"], "Sea"),
    PlatformIcon("SSC", ["Ship to Shore Connector", "SSC Navy hovercraft"], "Sea"),

    # Sea Platforms - Auxiliary
    PlatformIcon("ESB-Puller", ["USNS Lewis B Puller", "Expeditionary Sea Base"], "Sea"),
    PlatformIcon("T-AKE-Lewis-Clark", ["USNS Lewis and Clark", "Lewis and Clark class"], "Sea"),
    PlatformIcon("T-AO-John-Lewis", ["USNS John Lewis", "John Lewis class oiler"], "Sea"),
    PlatformIcon("T-EPF-Spearhead", ["USNS Spearhead", "Spearhead class EPF"], "Sea"),

    # Sea Platforms - Subsurface
    PlatformIcon("Los-Angeles-SSN", ["USS Los Angeles submarine", "Los Angeles class SSN"], "Sea"),
    PlatformIcon("Virginia-SSN", ["USS Virginia submarine", "Virginia class submarine"], "Sea"),

    # Sea Platforms - Unmanned
    PlatformIcon("Ghost-Fleet-LUSV", ["LUSV unmanned", "Large Unmanned Surface Vehicle"], "Sea"),
    PlatformIcon("Orca-XLUUV", ["Orca XLUUV", "Boeing Orca submarine"], "Sea"),
    PlatformIcon("Sea-Hunter-MDUSV", ["Sea Hunter", "ACTUV Sea Hunter"], "Sea"),

    # EW Systems
    PlatformIcon("AN-ALQ-172-EPAWSS", ["F-15E Strike Eagle", "F-15E USAF"], "EW"),
    PlatformIcon("AN-ALQ-214-IDECM", ["F/A-18 Hornet", "F-18 Super Hornet"], "EW"),
    PlatformIcon("AN-ALQ-249-NGJ", ["EA-18G Growler", "Electronic Attack"], "EW"),
    PlatformIcon("AN-ALQ-99-TJS", ["EA-18G Growler jamming", "EA-18G electronic warfare"], "EW"),
    PlatformIcon("AN-MLQ-40-Prophet", ["Prophet SIGINT", "AN/MLQ-40"], "EW"),
    PlatformIcon("AN-SLQ-32-SEWIP", ["AN/SLQ-32", "SEWIP Navy"], "EW"),

    # Counter-UAS
    PlatformIcon("LMADIS", ["LMADIS system", "Light Marine Air Defense"], "Counter-UAS"),
    PlatformIcon("MADIS", ["MADIS system", "Marine Air Defense"], "Counter-UAS"),

    # SOCOM Platforms
    PlatformIcon("GMV-1-1-Flyer-72", ["GMV special forces vehicle", "Ground Mobility Vehicle"], "SOCOM"),
    PlatformIcon("MH-47G-Chinook", ["MH-47G Chinook", "160th SOAR Chinook"], "SOCOM"),
    PlatformIcon("MH-60M-Black-Hawk", ["MH-60M Black Hawk", "160th SOAR Black Hawk"], "SOCOM"),

    # Coast Guard
    PlatformIcon("Heritage-Class-OPC", ["Heritage class cutter", "Offshore Patrol Cutter"], "Coast-Guard"),
    PlatformIcon("Legend-Class-NSC", ["Legend class cutter", "USCGC Bertholf"], "Coast-Guard"),
    PlatformIcon("MH-60T-Jayhawk", ["MH-60T Jayhawk", "Coast Guard helicopter"], "Coast-Guard"),
    PlatformIcon("Sentinel-Class-FRC", ["Sentinel class cutter", "Fast Response Cutter"], "Coast-Guard"),

    # Fixed Platforms
    PlatformIcon("Aircraft-Parking-Ramps", ["aircraft parking ramp military", "flight line USAF"], "Fixed"),
    PlatformIcon("Air-Operations-Center", ["Air Operations Center military", "AOC command center"], "Fixed"),
    PlatformIcon("Ammunition-Supply-Point", ["ammunition supply point military", "ASP Army"], "Fixed"),
    PlatformIcon("AMPV-Mission-Command", ["AMPV Mission Command", "Armored Multi-Purpose Vehicle"], "Fixed"),
    PlatformIcon("AN-PLQ-7-CREW", ["CREW counter IED", "Counter RCIED Electronic Warfare"], "Fixed"),
    PlatformIcon("AN-TPQ-53", ["AN/TPQ-53 radar", "counterfire radar Army"], "Fixed"),
    PlatformIcon("AN-TPS-80-GATOR", ["AN/TPS-80 G/ATOR", "Ground Air Task Oriented Radar"], "Fixed"),
    PlatformIcon("AN-TSC-154-SMART-T", ["SMART-T satellite terminal", "AN/TSC-154"], "Fixed"),
    PlatformIcon("AN-TSQ-253-VMAX", ["VMAX satellite", "wideband satellite terminal"], "Fixed"),
    PlatformIcon("E-8-JSTARS", ["E-8 Joint STARS", "JSTARS aircraft"], "Air"),
    PlatformIcon("FAB-T", ["FAB-T terminal", "Family of Advanced Beyond Line-of-Sight Terminals"], "Space"),
    PlatformIcon("FARP", ["Forward Arming Refueling Point", "FARP helicopter"], "Fixed"),
    PlatformIcon("FORGE-Ground-System", ["space ground system", "satellite control"], "Space"),
    PlatformIcon("Fuel-Farm", ["military fuel farm", "fuel storage military"], "Fixed"),
    PlatformIcon("GPS-Operational-Control", ["GPS control segment", "GPS operations"], "Space"),
    PlatformIcon("Hardened-Aircraft-Shelters", ["hardened aircraft shelter", "HAS military"], "Fixed"),
    PlatformIcon("Husky-VMMD", ["Husky mine detector", "Husky VMMD"], "Land"),
    PlatformIcon("Joint-Network-Node", ["Joint Network Node", "JNN military communications"], "Fixed"),
    PlatformIcon("Joint-Operations-Center", ["Joint Operations Center", "military command center"], "Fixed"),
    PlatformIcon("M1132-Stryker-ESV", ["Stryker Engineer", "M1132 Stryker"], "Land"),
    PlatformIcon("Role-2-Medical", ["Role 2 medical", "field hospital military"], "Fixed"),
    PlatformIcon("S351-Nemesis-DCS", ["dry combat submersible", "SEAL delivery vehicle"], "SOCOM"),
    PlatformIcon("Satellite-Control-Network", ["AFSCN satellite", "Air Force Satellite Control Network"], "Space"),
    PlatformIcon("Satellite-Transportable-Terminal", ["satellite terminal military", "SATCOM terminal"], "Space"),
    PlatformIcon("Stryker-Command-Vehicle", ["Stryker command", "M1130 Stryker CV"], "Land"),
    PlatformIcon("TOCs", ["Tactical Operations Center", "TOC military"], "Fixed"),

    # ==========================================
    # RED FORCE PLATFORMS
    # ==========================================

    # China - UAS
    PlatformIcon("Wing-Loong-II", ["Wing Loong II UAV", "CAIG Wing Loong II"], "Red-UAS"),
    PlatformIcon("WZ-7-Soaring-Dragon", ["WZ-7 Soaring Dragon", "Guizhou Soaring Dragon"], "Red-UAS"),
    PlatformIcon("WZ-8", ["WZ-8 reconnaissance drone", "WZ-8 UAV China"], "Red-UAS"),
    PlatformIcon("GJ-11-Sharp-Sword", ["GJ-11 Sharp Sword UCAV", "Sharp Sword drone China"], "Red-UAS"),
    PlatformIcon("CH-7", ["CH-7 drone China", "CASC CH-7 UAV"], "Red-UAS"),
    PlatformIcon("Jiutian-Drone-Mothership", ["drone swarm mothership", "Chinese drone swarm"], "Red-UAS"),

    # China - Missiles
    PlatformIcon("DF-21D", ["DF-21D missile", "Dong Feng 21D anti-ship ballistic missile"], "Red-Missiles"),
    PlatformIcon("DF-26", ["DF-26 missile", "Dong Feng 26 missile"], "Red-Missiles"),
    PlatformIcon("DF-100", ["DF-100 cruise missile", "CJ-100 missile"], "Red-Missiles"),
    PlatformIcon("YJ-12", ["YJ-12 anti-ship missile", "Ying Ji 12 missile"], "Red-Missiles"),
    PlatformIcon("YJ-18", ["YJ-18 anti-ship missile", "Ying Ji 18"], "Red-Missiles"),
    PlatformIcon("YJ-21", ["YJ-21 hypersonic missile China", "Eagle Strike 21"], "Red-Missiles"),
    PlatformIcon("YJ-83", ["YJ-83 anti-ship missile", "C-803 missile"], "Red-Missiles"),
    PlatformIcon("CJ-10-DH-10", ["CJ-10 cruise missile", "DH-10 cruise missile China"], "Red-Missiles"),
    PlatformIcon("CJ-20", ["CJ-20 cruise missile", "Chang Jian 20"], "Red-Missiles"),
    PlatformIcon("CM-401", ["CM-401 missile", "CM-401 anti-ship ballistic missile"], "Red-Missiles"),
    PlatformIcon("LS-6", ["LS-6 guided bomb China", "LS-6 precision munition"], "Red-Missiles"),
    PlatformIcon("CM-506KG", ["CM-506KG loitering munition", "Chinese loitering munition"], "Red-Missiles"),

    # China - Air Defense
    PlatformIcon("HQ-9", ["HQ-9 air defense system", "HQ-9 SAM"], "Red-Air-Defense"),
    PlatformIcon("HQ-16", ["HQ-16 missile system", "HQ-16 SAM China"], "Red-Air-Defense"),
    PlatformIcon("HQ-17", ["HQ-17 air defense", "HQ-17 SAM system"], "Red-Air-Defense"),
    PlatformIcon("FK-4000", ["FK-4000 CIWS", "FK-4000 China"], "Red-Air-Defense"),
    PlatformIcon("S-400", ["S-400 missile system China", "S-400 Triumf"], "Red-Air-Defense"),

    # China - C4ISR
    PlatformIcon("KJ-500", ["KJ-500 AEW aircraft", "KJ-500 AWACS China"], "Red-C4ISR"),
    PlatformIcon("Y-8-Y-9-ISR-Family", ["Y-8 ISR aircraft China", "Shaanxi Y-9 electronic warfare"], "Red-C4ISR"),
    PlatformIcon("Yaogan-Constellation", ["Yaogan satellite China", "Yaogan reconnaissance satellite"], "Red-C4ISR"),
    PlatformIcon("SIAR-Network", ["ship-borne radar network China", "Chinese integrated air radar"], "Red-C4ISR"),
    PlatformIcon("JY-27", ["JY-27 radar China", "JY-27 VHF radar"], "Red-C4ISR"),

    # China - Naval
    PlatformIcon("Type-052D-Luyang-III", ["Type 052D destroyer", "Luyang III destroyer"], "Red-Naval"),
    PlatformIcon("Type-055-Renhai", ["Type 055 destroyer", "Renhai class cruiser"], "Red-Naval"),
    PlatformIcon("Type-039A-Yuan", ["Type 039A submarine", "Yuan class submarine"], "Red-Naval"),
    PlatformIcon("Type-094-Jin", ["Type 094 submarine", "Jin class submarine"], "Red-Naval"),

    # Russia - UAS
    PlatformIcon("Orion-Inokhodets", ["Orion drone Russia", "Inokhodets UAV"], "Red-UAS"),
    PlatformIcon("S-70-Okhotnik", ["S-70 Okhotnik drone", "Sukhoi S-70 Okhotnik"], "Red-UAS"),
    PlatformIcon("Lancet-Loitering-Munition", ["Lancet drone Russia", "ZALA Lancet loitering munition"], "Red-UAS"),
    PlatformIcon("Orlan-10", ["Orlan-10 drone Russia", "Orlan-10 UAV"], "Red-UAS"),
    PlatformIcon("KUB-BLA", ["KUB-BLA drone Russia", "ZALA KUB kamikaze drone"], "Red-UAS"),

    # Russia - Missiles
    PlatformIcon("P-800-Oniks", ["P-800 Oniks missile", "Yakhont anti-ship missile"], "Red-Missiles"),
    PlatformIcon("3M22-Zircon", ["Zircon hypersonic missile", "3M22 Tsirkon"], "Red-Missiles"),
    PlatformIcon("Kh-47M2-Kinzhal", ["Kinzhal hypersonic missile", "Kh-47M2 Kinzhal"], "Red-Missiles"),
    PlatformIcon("3M14-Kalibr", ["Kalibr cruise missile", "3M14 Kalibr"], "Red-Missiles"),
    PlatformIcon("Kh-101", ["Kh-101 cruise missile Russia", "Kh-101 missile"], "Red-Missiles"),

    # Russia - Air Defense
    PlatformIcon("S-400-Russia", ["S-400 Triumf Russia", "S-400 air defense system"], "Red-Air-Defense"),
    PlatformIcon("Buk-M2-M3", ["Buk missile system", "Buk-M3 SAM"], "Red-Air-Defense"),
    PlatformIcon("Pantsir-S1-S2", ["Pantsir-S1 air defense", "Pantsir missile system"], "Red-Air-Defense"),

    # Russia - C4ISR
    PlatformIcon("A-50-Mainstay", ["A-50 Mainstay AWACS", "Beriev A-50"], "Red-C4ISR"),
    PlatformIcon("Liana-ELINT", ["Liana satellite Russia", "Lotos-S ELINT satellite"], "Red-C4ISR"),
    PlatformIcon("Nebo-M", ["Nebo-M radar Russia", "Nebo-M radar system"], "Red-C4ISR"),

    # Russia - Naval
    PlatformIcon("Improved-Kilo-636", ["Kilo class submarine", "Project 636 Varshavyanka"], "Red-Naval"),
    PlatformIcon("Yasen-Class", ["Yasen class submarine", "Severodvinsk submarine"], "Red-Naval"),
    PlatformIcon("Slava-Class", ["Slava class cruiser", "Moskva cruiser"], "Red-Naval"),

    # Iran - UAS
    PlatformIcon("Shahed-136", ["Shahed 136 drone", "Shahed-136 Iran drone"], "Red-UAS"),
    PlatformIcon("Mohajer-6", ["Mohajer-6 drone Iran", "Mohajer-6 UAV"], "Red-UAS"),
    PlatformIcon("Shahed-149-Gaza", ["Shahed 149 Gaza drone", "Shahed-149 UAV Iran"], "Red-UAS"),

    # Iran - Missiles
    PlatformIcon("Noor", ["Noor missile Iran", "Noor anti-ship missile"], "Red-Missiles"),
    PlatformIcon("Khalij-Fars", ["Khalij Fars missile Iran", "Persian Gulf anti-ship ballistic missile"], "Red-Missiles"),
    PlatformIcon("Soumar", ["Soumar cruise missile Iran", "Soumar missile"], "Red-Missiles"),
    PlatformIcon("Hoveyzeh", ["Hoveyzeh cruise missile Iran", "Hoveyzeh missile"], "Red-Missiles"),
    PlatformIcon("Fateh-313-Zolfaghar", ["Fateh-313 missile Iran", "Zolfaghar missile"], "Red-Missiles"),
    PlatformIcon("Kheibar-Shekan", ["Kheibar Shekan missile Iran", "Kheibar Shekan ballistic missile"], "Red-Missiles"),
    PlatformIcon("Emad", ["Emad missile Iran", "Emad ballistic missile Iran"], "Red-Missiles"),

    # Iran - Air Defense
    PlatformIcon("Bavar-373", ["Bavar-373 air defense Iran", "Bavar 373 missile system"], "Red-Air-Defense"),
    PlatformIcon("3rd-Khordad", ["3rd Khordad air defense Iran", "Third Khordad missile system"], "Red-Air-Defense"),

    # Iran - Naval
    PlatformIcon("Ghadir-Class", ["Ghadir submarine Iran", "Ghadir class midget submarine"], "Red-Naval"),
    PlatformIcon("Fast-Attack-Craft", ["Iran fast attack craft", "IRGC fast boat"], "Red-Naval"),

    # Houthis
    PlatformIcon("Samad-3", ["Samad 3 drone Houthi", "Samad UAV Yemen"], "Red-UAS"),
    PlatformIcon("Qasef-2K", ["Qasef-2K drone Houthi", "Qasef drone Yemen"], "Red-UAS"),
    PlatformIcon("Waaed", ["Wa'aed drone Houthi", "Houthi Shahed drone"], "Red-UAS"),
    PlatformIcon("Asef", ["Asef missile Houthi", "Houthi anti-ship ballistic missile"], "Red-Missiles"),
    PlatformIcon("Al-Mandab-2", ["Al-Mandab 2 missile Houthi", "Al Mandab anti-ship missile Yemen"], "Red-Missiles"),

    # North Korea
    PlatformIcon("Saebyeol-4", ["North Korea drone", "DPRK reconnaissance UAV"], "Red-UAS"),
    PlatformIcon("Saebyeol-9", ["North Korea attack drone", "DPRK combat UAV"], "Red-UAS"),
    PlatformIcon("DPRK-GPS-Jammers", ["GPS jammer military", "electronic warfare GPS jamming"], "Red-EW"),

    # Narco-Cartels
    PlatformIcon("Narco-Drone-COTS", ["DJI Mavic 2 Zoom drone", "DJI Mavic 2"], "Red-UAS"),
    PlatformIcon("Narco-Drone-Heavy", ["hexacopter drone", "heavy lift hexacopter drone"], "Red-UAS"),

    # Non-State Actors (Hamas / Hezbollah)
    PlatformIcon("Mirsad-1", ["Ababil UAV", "Ababil drone Iran Hezbollah"], "Red-UAS"),
    PlatformIcon("Zouari", ["Hamas drone", "Hamas kamikaze drone"], "Red-UAS"),
    PlatformIcon("Shehab", ["Hamas Shehab drone", "Hamas UAV Ababil"], "Red-UAS"),
]


def search_commons_image(session: requests.Session, search_terms: List[str]) -> Optional[str]:
    """Search Wikimedia Commons for an image and return the file title."""
    for query in search_terms:
        params = {
            "action": "query",
            "format": "json",
            "list": "search",
            "srnamespace": "6",  # File namespace
            "srsearch": f"{query} filetype:bitmap",
            "srlimit": "10"
        }
        try:
            response = session.get(COMMONS_API, params=params, headers=HEADERS, timeout=TIMEOUT)
            if response.status_code == 200:
                data = response.json()
                results = data.get("query", {}).get("search", [])
                # Filter for good image types (jpg, png)
                for result in results:
                    title = result.get("title", "")
                    if title.lower().endswith(('.jpg', '.jpeg', '.png')):
                        return title
        except Exception as e:
            print(f"  Search error for '{query}': {e}")
    return None


def get_image_url(session: requests.Session, file_title: str) -> Optional[str]:
    """Get direct image URL from Wikimedia Commons API."""
    params = {
        "action": "query",
        "format": "json",
        "titles": file_title,
        "prop": "imageinfo",
        "iiprop": "url",
        "iiurlwidth": 800  # Request thumbnail for faster download
    }

    try:
        response = session.get(COMMONS_API, params=params, headers=HEADERS, timeout=TIMEOUT)
        if response.status_code != 200:
            return None
        data = response.json()
        pages = data.get("query", {}).get("pages", {})
        for page in pages.values():
            if "imageinfo" in page:
                info = page["imageinfo"][0]
                return info.get("thumburl") or info.get("url")
    except Exception as e:
        print(f"  Error getting URL for {file_title}: {e}")
    return None


def process_image(image_data: bytes, output_path: Path, size: Tuple[int, int] = IMAGE_SIZE) -> bool:
    """Process image: convert to RGB, resize, and save as PNG."""
    try:
        img = Image.open(BytesIO(image_data))

        # Convert to RGB (handle RGBA, P, LA modes)
        if img.mode in ('RGBA', 'P', 'LA'):
            background = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'P':
                img = img.convert('RGBA')
            if img.mode in ('RGBA', 'LA'):
                background.paste(img, mask=img.split()[-1])
            else:
                background.paste(img)
            img = background
        elif img.mode != 'RGB':
            img = img.convert('RGB')

        # Resize maintaining aspect ratio
        img.thumbnail((max(size), max(size)), Image.LANCZOS)

        # Create square canvas with white background
        square = Image.new('RGB', size, (255, 255, 255))
        offset = ((size[0] - img.width) // 2, (size[1] - img.height) // 2)
        square.paste(img, offset)

        # Save as PNG
        square.save(output_path, 'PNG', optimize=True)
        return True
    except Exception as e:
        print(f"  Error processing image: {e}")
        return False


def download_platform_icon(platform: PlatformIcon, output_dir: Path, session: requests.Session) -> Tuple[str, bool, str]:
    """Download and process a single platform icon."""
    filename = f"{platform.name.lower()}.png"
    output_path = output_dir / filename

    # Skip if already exists
    if output_path.exists():
        return platform.name, True, "Already exists"

    # Search for an image on Wikimedia Commons
    file_title = search_commons_image(session, platform.search_terms)
    if not file_title:
        return platform.name, False, "No image found in search"

    # Get image URL from Commons API
    image_url = get_image_url(session, file_title)
    if not image_url:
        return platform.name, False, "Could not get image URL"

    # Download image
    try:
        response = session.get(image_url, headers=HEADERS, timeout=TIMEOUT)
        if response.status_code != 200:
            return platform.name, False, f"HTTP {response.status_code}"
        image_data = response.content
    except requests.Timeout:
        return platform.name, False, "Download timeout"
    except Exception as e:
        return platform.name, False, f"Download error: {e}"

    # Process and save image
    if process_image(image_data, output_path):
        return platform.name, True, f"Downloaded ({file_title})"
    else:
        return platform.name, False, "Processing failed"


def main():
    """Main download function."""
    print("Platform Icon Downloader")
    print("========================")
    print(f"Output directory: {OUTPUT_DIR}")
    print(f"Total platforms: {len(PLATFORMS)}")
    print()

    # Create output directory
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Track results
    success_count = 0
    failed: List[Tuple[str, str]] = []
    skipped_count = 0

    # Create a session for connection pooling
    session = requests.Session()

    print("Downloading icons (searching Wikimedia Commons)...")
    print()

    for i, platform in enumerate(PLATFORMS, 1):
        name, success, message = download_platform_icon(platform, OUTPUT_DIR, session)

        if success:
            if message == "Already exists":
                skipped_count += 1
                status = "SKIP"
            else:
                success_count += 1
                status = "OK"
        else:
            failed.append((name, message))
            status = "FAIL"

        try:
            print(f"  [{i}/{len(PLATFORMS)}] [{status}] {name}: {message}")
        except UnicodeEncodeError:
            print(f"  [{i}/{len(PLATFORMS)}] [{status}] {name}: (filename has special chars)")

        # Add delay between requests (skip for already existing files)
        if message != "Already exists":
            time.sleep(DELAY)

    # Summary
    print()
    print("=" * 50)
    print("Summary:")
    print(f"  Downloaded: {success_count}")
    print(f"  Skipped (already exist): {skipped_count}")
    print(f"  Failed: {len(failed)}")

    if failed:
        print()
        print("Failed downloads:")
        for name, reason in failed:
            print(f"  - {name}: {reason}")

    print()
    print(f"Icons saved to: {OUTPUT_DIR}")

    return len(failed) == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
