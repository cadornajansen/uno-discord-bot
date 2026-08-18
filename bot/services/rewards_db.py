from collections import Counter
import csv
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import io
import logging
from pathlib import Path
import random
import sqlite3
from typing import Optional

logger = logging.getLogger(__name__)

PHT = timezone(timedelta(hours=8))


class RewardsError(Exception):
    """Base exception for rewards and economy operations."""
    pass


class DailyAlreadyClaimedError(RewardsError):
    """Raised when user has already claimed their daily reward today."""
    def __init__(self, message: str, next_claim_time: Optional[datetime] = None):
        super().__init__(message)
        self.next_claim_time = next_claim_time


class InsufficientPointsError(RewardsError):
    """Raised when user lacks the points required for an action."""
    pass


class ShieldActiveError(RewardsError):
    """Raised when an action is blocked by an active Immunity Shield."""
    def __init__(self, message: str, shield_until: Optional[datetime] = None):
        super().__init__(message)
        self.shield_until = shield_until


class MaxBetsReachedError(RewardsError):
    """Raised when user reaches their daily gambling limit (3 bets/day)."""
    pass


class MaxTriviaReachedError(RewardsError):
    """Raised when user has already completed 3 trivia quizzes today."""
    pass


from enum import Enum
import random


@dataclass(frozen=True)
class TriviaQuestion:
    question: str
    options: list[str]
    correct_index: int
    explanation: str
    category: str


TRIVIA_QUESTIONS: list[TriviaQuestion] = [
    # -------------------------------------------------------------------------
    # 🖥️ Intro to Computing & Fundamentals of Programming
    # -------------------------------------------------------------------------
    TriviaQuestion(
        question="How many bits make up a single byte in standard computer architecture?",
        options=["4 bits", "8 bits", "16 bits", "32 bits"],
        correct_index=1,
        explanation="A byte consists of exactly 8 bits, capable of representing 256 (2^8) distinct values.",
        category="🖥️ Intro to Computing",
    ),
    TriviaQuestion(
        question="Which of the following is considered an INPUT hardware device?",
        options=["Monitor", "Keyboard", "Speaker", "Printer"],
        correct_index=1,
        explanation="A keyboard sends data into the computer system, making it an input device.",
        category="🖥️ Intro to Computing",
    ),
    TriviaQuestion(
        question="What does the acronym 'GUI' stand for in software and operating systems?",
        options=["General User Input", "Graphical User Interface", "Global Unified Internet", "Graphic Utility Instruction"],
        correct_index=1,
        explanation="GUI stands for Graphical User Interface, enabling visual interaction with icons and windows.",
        category="🖥️ Intro to Computing",
    ),
    TriviaQuestion(
        question="In computer memory units, exactly how many bytes are in 1 Kilobyte (KB) in binary notation?",
        options=["1000 bytes", "1024 bytes", "512 bytes", "2048 bytes"],
        correct_index=1,
        explanation="In binary computing (2^10), 1 Kilobyte equals 1,024 bytes.",
        category="🖥️ Intro to Computing",
    ),
    TriviaQuestion(
        question="In programming fundamentals, what is a 'variable'?",
        options=["A permanent hardware chip", "A named memory location that stores a value", "A syntax error in code", "A type of computer screen"],
        correct_index=1,
        explanation="A variable is a symbolic name given to a memory location that holds changeable data during program execution.",
        category="💻 Fund. of Programming",
    ),
    TriviaQuestion(
        question="What type of programming error occurs when code violates the grammatical rules of the programming language?",
        options=["Syntax Error", "Logic Error", "Runtime Error", "Segmentation Fault"],
        correct_index=0,
        explanation="A Syntax Error happens when the code breaks grammatical language rules (e.g. missing semicolon or bracket).",
        category="💻 Fund. of Programming",
    ),
    TriviaQuestion(
        question="In most modern programming languages (such as C, Java, and Python), array indexing starts at what number?",
        options=["1", "0", "-1", "Any number specified"],
        correct_index=1,
        explanation="Zero-based indexing is standard in most languages, meaning the first element is at index 0.",
        category="💻 Fund. of Programming",
    ),
    TriviaQuestion(
        question="What tool translates entire high-level source code into machine code before program execution?",
        options=["Interpreter", "Compiler", "Debugger", "Text Editor"],
        correct_index=1,
        explanation="A Compiler translates the entire program into machine code upfront, whereas an Interpreter translates line-by-line.",
        category="💻 Fund. of Programming",
    ),
    TriviaQuestion(
        question="RAM (Random Access Memory) retains all of its stored data even after the computer is powered off.",
        options=["True", "False"],
        correct_index=1,
        explanation="False! RAM is volatile memory and loses all its stored data immediately when power is lost.",
        category="🖥️ Intro to Computing",
    ),
    TriviaQuestion(
        question="Open-source software allows anyone to inspect, modify, and enhance its source code freely.",
        options=["True", "False"],
        correct_index=0,
        explanation="True! Open-source licenses grant users rights to study, change, and distribute the software.",
        category="🖥️ Intro to Computing",
    ),
    TriviaQuestion(
        question="An infinite loop is a loop that continues running indefinitely because its terminating condition is never met.",
        options=["True", "False"],
        correct_index=0,
        explanation="True! If the loop's exit condition never evaluates to false, the loop runs forever until terminated.",
        category="💻 Fund. of Programming",
    ),
    TriviaQuestion(
        question="Comments written in code are executed by the CPU to help speed up program calculations.",
        options=["True", "False"],
        correct_index=1,
        explanation="False! Comments are completely ignored by compilers and interpreters; they exist solely for human readers.",
        category="💻 Fund. of Programming",
    ),
    TriviaQuestion(
        question="Pseudocode is an informal, human-readable outline of a computer algorithm without strict syntax.",
        options=["True", "False"],
        correct_index=0,
        explanation="True! Pseudocode uses natural language and structured conventions to design algorithms before coding.",
        category="💻 Fund. of Programming",
    ),

    # -------------------------------------------------------------------------
    # ⚡ General Science — Physics
    # -------------------------------------------------------------------------
    TriviaQuestion(
        question="According to Newton's First Law of Motion, an object at rest will stay at rest unless acted upon by what?",
        options=["Gravity only", "An unbalanced external force", "Frictional heat", "Magnetic pull"],
        correct_index=1,
        explanation="Newton's 1st Law (Law of Inertia) states an object remains at rest or in uniform motion unless acted upon by a net external force.",
        category="⚡ Physics",
    ),
    TriviaQuestion(
        question="What is the approximate speed of light in a vacuum?",
        options=["3,000 km/s", "30,000 km/s", "300,000 km/s", "3,000,000 km/s"],
        correct_index=2,
        explanation="Light travels at approximately 300,000 km/s (or 3 × 10^8 m/s) in a vacuum.",
        category="⚡ Physics",
    ),
    TriviaQuestion(
        question="What is the standard International System (SI) unit for measuring electrical resistance?",
        options=["Volt", "Watt", "Ohm (Ω)", "Ampere"],
        correct_index=2,
        explanation="The Ohm (symbol Ω) is the SI unit of electrical resistance, defined by Ohm's Law (V = I * R).",
        category="⚡ Physics",
    ),
    TriviaQuestion(
        question="What is the approximate acceleration due to Earth's gravity near the surface?",
        options=["5.8 m/s²", "9.8 m/s²", "14.2 m/s²", "19.6 m/s²"],
        correct_index=1,
        explanation="Standard Earth surface gravity causes freefalling objects to accelerate at approximately 9.8 m/s².",
        category="⚡ Physics",
    ),
    TriviaQuestion(
        question="Sound waves can easily travel across a complete vacuum like outer space.",
        options=["True", "False"],
        correct_index=1,
        explanation="False! Sound is a mechanical wave that requires a physical medium (gas, liquid, solid) to propagate.",
        category="⚡ Physics",
    ),
    TriviaQuestion(
        question="Sound travels significantly faster through water and solid metals than through air.",
        options=["True", "False"],
        correct_index=0,
        explanation="True! Sound travels faster in denser media (about 1,480 m/s in water vs 343 m/s in air) because molecules are closer together.",
        category="⚡ Physics",
    ),
    TriviaQuestion(
        question="The Law of Conservation of Energy states that energy cannot be created or destroyed, only transformed from one form to another.",
        options=["True", "False"],
        correct_index=0,
        explanation="True! The total energy of an isolated system always remains constant over time.",
        category="⚡ Physics",
    ),

    # -------------------------------------------------------------------------
    # 🧬 General Science — Biology & Life Science
    # -------------------------------------------------------------------------
    TriviaQuestion(
        question="Which cellular organelle is famously known as the 'powerhouse of the cell' for generating ATP energy?",
        options=["Nucleus", "Ribosome", "Mitochondrion", "Golgi Apparatus"],
        correct_index=2,
        explanation="Mitochondria produce most of the chemical energy (ATP) needed by the cell through cellular respiration.",
        category="🧬 Biology",
    ),
    TriviaQuestion(
        question="What green pigment inside plant chloroplasts absorbs sunlight to drive photosynthesis?",
        options=["Carotenoid", "Chlorophyll", "Hemoglobin", "Melanin"],
        correct_index=1,
        explanation="Chlorophyll absorbs blue and red light wavelengths and reflects green light, powering photosynthesis.",
        category="🧬 Biology",
    ),
    TriviaQuestion(
        question="What does the scientific acronym 'DNA' stand for?",
        options=["Deoxyribonucleic Acid", "Dynamic Nucleic Antigen", "Dual Nitrogen Acetate", "Deoxyribose Nitrogen Acid"],
        correct_index=0,
        explanation="DNA stands for Deoxyribonucleic Acid, the molecule carrying genetic instructions for all living organisms.",
        category="🧬 Biology",
    ),
    TriviaQuestion(
        question="Which component of human blood is primarily responsible for transporting oxygen throughout the body?",
        options=["White Blood Cells", "Platelets", "Red Blood Cells (Hemoglobin)", "Blood Plasma"],
        correct_index=2,
        explanation="Red blood cells contain iron-rich hemoglobin protein that binds and delivers oxygen to tissues.",
        category="🧬 Biology",
    ),
    TriviaQuestion(
        question="Plants release oxygen into the atmosphere as a natural byproduct of photosynthesis.",
        options=["True", "False"],
        correct_index=0,
        explanation="True! During light reactions, water molecules are split, releasing oxygen (O2) into the air.",
        category="🧬 Biology",
    ),
    TriviaQuestion(
        question="Viruses are classified as complete living cells that contain their own nucleus and organelles.",
        options=["True", "False"],
        correct_index=1,
        explanation="False! Viruses are non-cellular genetic material (DNA/RNA) enclosed in a protein coat and rely on host cells to replicate.",
        category="🧬 Biology",
    ),
    TriviaQuestion(
        question="A normal human body cell (somatic cell) contains 46 chromosomes arranged in 23 pairs.",
        options=["True", "False"],
        correct_index=0,
        explanation="True! Humans have 22 pairs of autosomes and 1 pair of sex chromosomes, totaling 46 chromosomes.",
        category="🧬 Biology",
    ),

    # -------------------------------------------------------------------------
    # 🇵🇭 Philippine History, Culture & Lore
    # -------------------------------------------------------------------------
    TriviaQuestion(
        question="Who is recognized as the National Hero of the Philippines for his literary works that inspired the revolution?",
        options=["Andres Bonifacio", "Dr. Jose Rizal", "Emilio Aguinaldo", "Apolinario Mabini"],
        correct_index=1,
        explanation="Dr. Jose Rizal inspired the Philippine national awakening through his novels Noli Me Tangere and El Filibusterismo.",
        category="🇵🇭 Philippine History",
    ),
    TriviaQuestion(
        question="On what date did General Emilio Aguinaldo proclaim Philippine Independence in Kawit, Cavite?",
        options=["June 12, 1898", "July 4, 1946", "August 21, 1983", "November 30, 1896"],
        correct_index=0,
        explanation="Philippine Independence was proclaimed on June 12, 1898, where the Philippine flag was first unfurled.",
        category="🇵🇭 Philippine History",
    ),
    TriviaQuestion(
        question="Who is known as the 'Father of the Philippine Revolution' and Supremo of the Katipunan (KKK)?",
        options=["Antonio Luna", "Andres Bonifacio", "Marcelo H. del Pilar", "Emilio Jacinto"],
        correct_index=1,
        explanation="Andres Bonifacio founded the Katipunan in 1892 and led the armed uprising against Spanish colonial rule.",
        category="🇵🇭 Philippine History",
    ),
    TriviaQuestion(
        question="Who was honored as the 'Mother of the Katipunan' (Tandang Sora) for feeding and nursing wounded revolutionaries?",
        options=["Gabriela Silang", "Melchora Aquino", "Teresa Magbanua", "Trinidad Tecson"],
        correct_index=1,
        explanation="Melchora Aquino (Tandang Sora) operated a sanctuary in Balintawak, feeding and caring for Katipuneros at age 84.",
        category="🇵🇭 Philippine History",
    ),
    TriviaQuestion(
        question="What is the name of the ancient pre-colonial indigenous alphasyllabary writing script of the Philippines?",
        options=["Baybayin", "Alibata", "Sanskrit", "Hanunoo"],
        correct_index=0,
        explanation="Baybayin is the authentic pre-colonial writing system widely used across Luzon and Visayas before Spanish arrival.",
        category="🇵🇭 Philippine Culture",
    ),
    TriviaQuestion(
        question="Approximately how many islands comprise the Philippine archipelago during high tide?",
        options=["1,776", "4,500", "7,641", "10,200"],
        correct_index=2,
        explanation="According to the National Mapping and Resource Information Authority (NAMRIA), the Philippines has 7,641 islands.",
        category="🇵🇭 Philippine Geography",
    ),
    TriviaQuestion(
        question="What is the longest continuous mountain range in the Philippines, serving as a natural shield against typhoons?",
        options=["Cordillera Central", "Sierra Madre", "Caraballo Mountains", "Zambales Mountains"],
        correct_index=1,
        explanation="The Sierra Madre spans over 540 kilometers along eastern Luzon, acting as a crucial barrier against Pacific storms.",
        category="🇵🇭 Philippine Geography",
    ),
    TriviaQuestion(
        question="In what historic walled district of Manila is Pamantasan ng Lungsod ng Maynila (PLM) located?",
        options=["Binondo", "Quiapo", "Intramuros", "Ermita"],
        correct_index=2,
        explanation="PLM is located inside the historic walled city of Intramuros, founded by the Spanish in the 16th century.",
        category="🏛️ PLM Lore",
    ),
    TriviaQuestion(
        question="The Battle of Mactan, where chieftain Lapu-Lapu defeated Portuguese explorer Ferdinand Magellan, occurred in the year 1521.",
        options=["True", "False"],
        correct_index=0,
        explanation="True! On April 27, 1521, Lapu-Lapu and his warriors defeated Magellan's expedition on the shores of Mactan.",
        category="🇵🇭 Philippine History",
    ),
    TriviaQuestion(
        question="The melody of the Philippine National Anthem ('Lupang Hinirang') was composed by Julian Felipe in 1898.",
        options=["True", "False"],
        correct_index=0,
        explanation="True! Julian Felipe composed the 'Marcha Nacional Filipina' upon the request of Emilio Aguinaldo.",
        category="🇵🇭 Philippine History",
    ),
    TriviaQuestion(
        question="Mount Mayon in Albay, Bicol is internationally renowned for having an almost perfectly symmetrical conical shape.",
        options=["True", "False"],
        correct_index=0,
        explanation="True! Mount Mayon is celebrated as the world's most symmetrical stratovolcano cone.",
        category="🇵🇭 Philippine Geography",
    ),
    TriviaQuestion(
        question="Pamantasan ng Lungsod ng Maynila (PLM) is a tuition-free local government university chartered by the City of Manila in 1965.",
        options=["True", "False"],
        correct_index=0,
        explanation="True! PLM was established under Republic Act 4196 in 1965 and provides free quality education funded by Manila taxpayers.",
        category="🏛️ PLM Lore",
    ),
    TriviaQuestion(
        question="The word 'Intramuros' translates literally from Latin/Spanish as 'within the walls'.",
        options=["True", "False"],
        correct_index=0,
        explanation="True! 'Intra' (within) and 'muros' (walls) refers to the fortified Spanish colonial stone walls of Old Manila.",
        category="🏛️ PLM Lore",
    ),
]


@dataclass(frozen=True)
class TriviaResult:
    is_correct: bool
    points_awarded: int
    new_balance: int
    trivia_remaining: int


class ItemNotFoundError(RewardsError):
    """Raised when user attempts to consume an item they do not own."""
    pass


class BetOutcome(str, Enum):
    JACKPOT = "JACKPOT"
    DOUBLE = "DOUBLE"
    SKILL_DROP = "SKILL_DROP"
    REFUND = "REFUND"
    BUST = "BUST"


ITEM_DEFINITIONS = {
    "pickpocket": {
        "name": "🦹 Pickpocket Card",
        "description": "Allows you to attempt to steal 40%–60% points from a classmate with `/steal`.",
        "usable": False,
    },
    "shield_1w": {
        "name": "🛡️ 1-Week Immunity Shield",
        "description": "Protects your wallet completely from all `/steal` attempts for 7 days.",
        "usable": True,
    },
    "double_daily": {
        "name": "⚡ 2x Daily Booster Card",
        "description": "Doubles the points awarded on your next `/daily` claim.",
        "usable": True,
    },
    "streak_bandage": {
        "name": "🩹 Streak Bandage",
        "description": "Repairs a broken `/daily` streak back to its previous number.",
        "usable": True,
    },
    "uno_reverse": {
        "name": "🔄 Uno Reverse Card",
        "description": "Passive trap! Reverses any `/steal` attempt to steal 40%–60% from the attacker instead.",
        "usable": False,
    },
    "airdrop": {
        "name": "🌧️ Point Airdrop",
        "description": "Launches a 100-pt public care package in chat for the first 4 fast classmates to catch (+25 pts each)!",
        "usable": True,
    },
    "gacha_box": {
        "name": "📦 Mystery Gacha Box",
        "description": "Lucky lootbox with rewards up to 1,000 points and exclusive badges.",
        "usable": True,
    },
    "shield_breaker": {
        "name": "🔨 EMP Shield Breaker",
        "description": "Target a protected classmate to instantly shatter their active Immunity Shield!",
        "usable": True,
    },
    "tax_audit": {
        "name": "🕵️ Class Treasurer Audit",
        "description": "Target a Top-3 Leaderboard player to audit 5% of their points into your wallet (max 200 pts)!",
        "usable": True,
    },
    "coffee_bribe": {
        "name": "☕ Dean's Coffee Bribe",
        "description": "Instant lucky grant of +100 to +180 Uno Points from the CS Faculty coffee fund!",
        "usable": True,
    },
}


SHOP_CATALOG = {
    "pickpocket": {
        "name": "🦹 Pickpocket Card",
        "cost": 100,
        "category": "consumable",
        "subcategory": "offense",
        "description": "Consumable skill card that lets you attempt to steal 40%–60% points with `/steal`.",
    },
    "shield_1w": {
        "name": "🛡️ 1-Week Immunity Shield",
        "cost": 150,
        "category": "consumable",
        "subcategory": "defense",
        "description": "Consumable item that protects your points from `/steal` attempts for 7 days.",
    },
    "double_daily": {
        "name": "⚡ 2x Daily Booster Card",
        "cost": 120,
        "category": "consumable",
        "subcategory": "defense",
        "description": "Doubles the points earned on your next `/daily` attendance claim.",
    },
    "uno_reverse": {
        "name": "🔄 Uno Reverse Card",
        "cost": 180,
        "category": "consumable",
        "subcategory": "offense",
        "description": "Passive trap! Counter-steals 40%–60% from anyone who attempts to `/steal` from you.",
    },
    "airdrop": {
        "name": "🌧️ Point Airdrop",
        "cost": 120,
        "category": "consumable",
        "subcategory": "events",
        "description": "Launches a 100-pt public care package for the first 4 classmates to catch (+25 pts each).",
    },
    "gacha_box": {
        "name": "📦 Mystery Gacha Box",
        "cost": 150,
        "category": "consumable",
        "subcategory": "events",
        "description": "Lucky lootbox with rewards up to 1,000 points and exclusive badges.",
    },
    "shield_breaker": {
        "name": "🔨 EMP Shield Breaker",
        "cost": 140,
        "category": "consumable",
        "subcategory": "offense",
        "description": "Target a protected classmate to instantly shatter their active Immunity Shield.",
    },
    "tax_audit": {
        "name": "🕵️ Class Treasurer Audit",
        "cost": 200,
        "category": "consumable",
        "subcategory": "offense",
        "description": "Target a Top-3 Leaderboard player to audit 5% of their points into your wallet.",
    },
    "coffee_bribe": {
        "name": "☕ Dean's Coffee Bribe",
        "cost": 100,
        "category": "consumable",
        "subcategory": "defense",
        "description": "Instant lucky grant of +100 to +180 Uno Points.",
    },
    "coffee": {
        "name": "☕ Intramuros Coffee Treat",
        "cost": 1200,
        "category": "physical",
        "subcategory": "prizes",
        "description": "₱50–₱80 Iced Coffee / drink treat around PLM / Intramuros (7-Eleven / Lawson).",
    },
    "gcash_100": {
        "name": "💳 GCash Gift Card ₱100",
        "cost": 2200,
        "category": "physical",
        "subcategory": "prizes",
        "description": "₱100 Direct GCash transfer to your Philippine mobile number.",
    },
    "printing_1m": {
        "name": "🖨️ Free Printing Service (1 Month)",
        "cost": 2800,
        "category": "physical",
        "subcategory": "prizes",
        "description": "Free academic reviewer / project paper printing service for 30 days.",
    },
    "nitro_1m": {
        "name": "🚀 1 Month Discord Nitro",
        "cost": 5500,
        "category": "physical",
        "subcategory": "prizes",
        "description": "1 Month Discord Nitro subscription sent directly via Discord gift link.",
    },
}

PET_CATALOG: dict[str, dict] = {
    "tuxedo_cat": {
        "id": "tuxedo_cat",
        "name": "🐱 Tuxedo Cat",
        "species": "cat",
        "cost": 50,
        "image_file": "tuxedo-cat.jpg",
        "title": "The Serene Feline",
        "perk_title": "2x Daily Attendance Points",
        "perk_desc": "Doubles points earned from daily attendance (/daily) permanently.",
        "friendly_with": "Golden Retriever, Scholar Owl",
        "rival_with": "Trickster Fox, Pickpockets",
        "favorite_snack": "Fresh Tuna Treats",
        "duel_perk": "Feline Agility: +10% Dodge in RPG Arena",
        "quotes": [
            "Purring peacefully next to your reviewer notebooks~",
            "Meow! Don't forget to take a study break!",
            "Napping on your keyboard while you write code...",
            "Slowly blinks with calm, soothing feline wisdom.",
        ],
    },
    "calico_cat": {
        "id": "calico_cat",
        "name": "🐱 Fluffy Calico Cat",
        "species": "cat",
        "cost": 100,
        "image_file": "talico-brown-cat.jpg",
        "title": "The Cozy Companion",
        "perk_title": "2x Daily Attendance Points",
        "perk_desc": "Doubles points earned from daily attendance (/daily) permanently.",
        "friendly_with": "Lop-Eared Bunny, Pink Axolotl",
        "rival_with": "Arctic Ice Fox, Serpents",
        "favorite_snack": "Warm Milk Biscuits",
        "duel_perk": "Feline Agility: +10% Dodge in RPG Arena",
        "quotes": [
            "Curled up in a warm fluffy ball beside your laptop.",
            "Soft purrs echo across your study desk~",
            "Paws gently at your notes, wishing you good luck!",
        ],
    },
    "golden_dog": {
        "id": "golden_dog",
        "name": "🐶 Golden Retriever",
        "species": "dog",
        "cost": 50,
        "image_file": "golden-retriever-dog.jpg",
        "title": "The Faithful Guard Pup",
        "perk_title": "Guard Dog Defense (+40% Thief Bust)",
        "perk_desc": "75% chance to catch thieves red-handed and bite them for a fine.",
        "friendly_with": "Tuxedo Cat, Lop-Eared Bunny, Master Oogway",
        "rival_with": "Trickster Fox, Classmate Thieves",
        "favorite_snack": "Roasted Marrow Bones",
        "duel_perk": "Intimidating Bark: 20% chance to reduce opponent roll by 15",
        "quotes": [
            "Barking happily and guarding your points wallet!",
            "Tail wagging at maximum speed! Ready for duty!",
            "Sniffing around for sneaky pickpockets in the server...",
            "Gives your hand a reassuring warm boop!",
        ],
    },
    "shiba_dog": {
        "id": "shiba_dog",
        "name": "🐶 Shiba Inu",
        "species": "dog",
        "cost": 100,
        "image_file": "shiba-inu-dog.jpg",
        "title": "The Alert Scout",
        "perk_title": "Guard Dog Defense (+40% Thief Bust)",
        "perk_desc": "75% chance to catch thieves red-handed and bite them for a fine.",
        "friendly_with": "Calico Cat, Frost Owl",
        "rival_with": "Arctic Ice Fox, Classmate Thieves",
        "favorite_snack": "Crispy Wagyu Bites",
        "duel_perk": "Intimidating Bark: 20% chance to reduce opponent roll by 15",
        "quotes": [
            "Standing at attention with sharp perked ears!",
            "Much loyalty, very protection, wow!",
            "Vigilantly watching over your hard-earned points.",
        ],
    },
    "brown_bunny": {
        "id": "brown_bunny",
        "name": "🐰 Lop-Eared Bunny",
        "species": "bunny",
        "cost": 150,
        "image_file": "brown-bunny.jpg",
        "title": "The Lucky Rabbit",
        "perk_title": "Lucky Gambler (+15% Bet Win Rates)",
        "perk_desc": "Increases /bet Jackpot and Double chances, reducing Bust rate to 20%.",
        "friendly_with": "Golden Retriever, Pink Axolotl",
        "rival_with": "Scholar Owl, Trickster Fox",
        "favorite_snack": "Organic Clover Crunch",
        "duel_perk": "Lucky Reroll: Auto-rerolls rolls under 30 in Dice Duel",
        "quotes": [
            "Twitching its nose, bringing cosmic gambling luck!",
            "Hopping around with a lucky four-leaf clover in its mouth~",
            "Lady luck is smiling on your next roll!",
            "Ears perked up, sensing a massive jackpot approaching!",
        ],
    },
    "white_bunny": {
        "id": "white_bunny",
        "name": "🐰 Moon Rabbit",
        "species": "bunny",
        "cost": 200,
        "image_file": "white-bunny.jpg",
        "title": "The Celestial Lucky Charm",
        "perk_title": "Lucky Gambler (+15% Bet Win Rates)",
        "perk_desc": "Increases /bet Jackpot and Double chances, reducing Bust rate to 20%.",
        "friendly_with": "Master Oogway, Fiery Goldfish",
        "rival_with": "Frost Owl, Arctic Ice Fox",
        "favorite_snack": "Celestial Moon Mochi",
        "duel_perk": "Lucky Reroll: Auto-rerolls rolls under 30 in Dice Duel",
        "quotes": [
            "Shining with lunar luck from celestial skies.",
            "Blessing your bets with pure lunar fortune~",
            "Softly thumping its feet in excitement!",
        ],
    },
    "scholar_owl": {
        "id": "scholar_owl",
        "name": "🦉 Scholar Owl",
        "species": "owl",
        "cost": 150,
        "image_file": "owl.jpg",
        "title": "The Academic Owl",
        "perk_title": "Quiz Master (+25 pts/quiz & 4th Attempt)",
        "perk_desc": "Earns +75 pts per correct trivia quiz and unlocks a 4th daily attempt.",
        "friendly_with": "Tuxedo Cat, Master Oogway",
        "rival_with": "Lop-Eared Bunny, High-Roll Gamblers",
        "favorite_snack": "Energy Acorn Berries",
        "duel_perk": "Calculated Strike: +10 clutch roll bonus in close clashes",
        "quotes": [
            "Perched on your shoulder solving discrete math problems.",
            "Hoot! Knowledge is the ultimate superpower!",
            "Reviewing your algorithm notes with keen analytical eyes.",
            "Adjusting tiny spectacles and nodding approvingly.",
        ],
    },
    "ice_owl": {
        "id": "ice_owl",
        "name": "🦉 Frost Owl",
        "species": "owl",
        "cost": 200,
        "image_file": "ice-owl.jpg",
        "title": "The Glacial Scholar",
        "perk_title": "Quiz Master (+25 pts/quiz & 4th Attempt)",
        "perk_desc": "Earns +75 pts per correct trivia quiz and unlocks a 4th daily attempt.",
        "friendly_with": "Shiba Inu, Arctic Ice Fox",
        "rival_with": "Fiery Goldfish, Moon Rabbit",
        "favorite_snack": "Glacial Frost Berries",
        "duel_perk": "Calculated Strike: +10 clutch roll bonus in close clashes",
        "quotes": [
            "Radiating cool, calculated intellect and focus.",
            "Wisdom sharper than winter frost.",
            "Hoot! Stay cool and master your exams.",
        ],
    },
    "oogway_turtle": {
        "id": "oogway_turtle",
        "name": "🐢 Master Oogway Turtle",
        "species": "turtle",
        "cost": 200,
        "image_file": "master-oogway-turtle.jpg",
        "title": "The Zen Grandmaster",
        "perk_title": "Permanent Streak Freeze & +2d Shield",
        "perk_desc": "Daily attendance streak never resets, and shields last +2 extra days.",
        "friendly_with": "Tuxedo Cat, Golden Retriever, Scholar Owl",
        "rival_with": "Impatient Rerollers, Haste",
        "favorite_snack": "Sacred Peach Blossoms",
        "duel_perk": "Zen Fortitude: +20 Parry Block reduction in RPG Arena",
        "quotes": [
            "Yesterday is history, tomorrow is a mystery, today is a gift~",
            "Slow and steady wins the semester.",
            "Meditating peacefully. Your streak is completely safe.",
            "Never rushes, never worries. Total academic tranquility.",
        ],
    },
    "orange_fox": {
        "id": "orange_fox",
        "name": "🦊 Trickster Fox",
        "species": "fox",
        "cost": 200,
        "image_file": "orange-fox.jpg",
        "title": "The Cunning Rogue",
        "perk_title": "Master Pickpocket (+15% Steal & +10 Airdrop)",
        "perk_desc": "Increases /steal success rate to 80% and gains +35 pts from airdrops.",
        "friendly_with": "Rainbow Axolotl, Fiery Goldfish",
        "rival_with": "Golden Retriever, Class Treasurer",
        "favorite_snack": "Canteen Chicken Skewers",
        "duel_perk": "Consolation Siphon: 25% chance on loss to recover 20% wager",
        "quotes": [
            "Grinning slyly with an eye on the rich kids' wallets...",
            "Quick on its feet, ready for the next stealth heist!",
            "Slinking through the shadows with scavenged loot.",
            "Winks playfully and tosses a shiny gold coin.",
        ],
    },
    "ice_fox": {
        "id": "ice_fox",
        "name": "🦊 Arctic Ice Fox",
        "species": "fox",
        "cost": 250,
        "image_file": "ice-fox.jpg",
        "title": "The Glacial Phantom",
        "perk_title": "Master Pickpocket (+15% Steal & +10 Airdrop)",
        "perk_desc": "Increases /steal success rate to 80% and gains +35 pts from airdrops.",
        "friendly_with": "Frost Owl, Pink Axolotl",
        "rival_with": "Shiba Inu, Class Treasurer",
        "favorite_snack": "Smoked Salmon Flakes",
        "duel_perk": "Consolation Siphon: 25% chance on loss to recover 20% wager",
        "quotes": [
            "Gliding like a silent shadow across icy winds.",
            "Leaving no tracks, taking only points.",
            "A chillingly swift rogue companion.",
        ],
    },
    "pink_axolotl": {
        "id": "pink_axolotl",
        "name": "🦎 Pastel Pink Axolotl",
        "species": "axolotl",
        "cost": 150,
        "image_file": "pink-axolotl.jpg",
        "title": "The Charming Mascot",
        "perk_title": "Economy Titan (5% Shop Cashback)",
        "perk_desc": "Refunds 5% Uno Points cashback on all shop redemptions.",
        "friendly_with": "Calico Cat, Lop-Eared Bunny, Fiery Goldfish",
        "rival_with": "Point Drains, Market Crashes",
        "favorite_snack": "Hydro Gel Shrimp",
        "duel_perk": "Bubble Shield: Absorbs first 15 DMG in RPG Arena",
        "quotes": [
            "Floating cheerfully with fluffy pink gills!",
            "Bringing vibrant financial blessings to your wallet~",
            "Smiles delightfully, splashing bubbles of good fortune!",
        ],
    },
    "rainbow_axolotl": {
        "id": "rainbow_axolotl",
        "name": "🦎 Rainbow Axolotl",
        "species": "axolotl",
        "cost": 250,
        "image_file": "rainbow-axolotl.jpg",
        "title": "The Mythical Prismatic Mascot",
        "perk_title": "Economy Titan (5% Shop Cashback)",
        "perk_desc": "Refunds 5% Uno Points cashback on all shop redemptions & rainbow aura.",
        "friendly_with": "Trickster Fox, Fiery Goldfish, Moon Rabbit",
        "rival_with": "Monotone Voids, Point Audits",
        "favorite_snack": "Prismatic Star Drops",
        "duel_perk": "Bubble Shield: Absorbs first 15 DMG in RPG Arena",
        "quotes": [
            "Shimmering with majestic iridescent colors!",
            "Radiating a mythical aura of supreme prestige and wealth.",
            "A rare legendary creature of pure computational prosperity!",
        ],
    },
    "fiery_goldfish": {
        "id": "fiery_goldfish",
        "name": "🐠 Fiery Lucky Goldfish",
        "species": "goldfish",
        "cost": 150,
        "image_file": "fiery-goldfish.jpg",
        "title": "The Fortune Fish",
        "perk_title": "Economy Titan (5% Shop Cashback)",
        "perk_desc": "Refunds 5% Uno Points cashback on all shop redemptions.",
        "friendly_with": "Pink Axolotl, Lop-Eared Bunny, Trickster Fox",
        "rival_with": "Frost Owl, Ice Creatures",
        "favorite_snack": "Fortune Pellets",
        "duel_perk": "Lucky Splash: 10% chance to double dice roll clutch",
        "quotes": [
            "Swimming in golden currents of endless good fortune!",
            "Glowing brightly with blazing prosperity!",
            "Splashing lucky droplets across your inventory.",
        ],
    },
}

PET_ROTATION_ORDER: list[str] = [
    "tuxedo_cat",
    "golden_dog",
    "brown_bunny",
    "scholar_owl",
    "oogway_turtle",
    "orange_fox",
    "pink_axolotl",
    "calico_cat",
    "shiba_dog",
    "white_bunny",
    "ice_owl",
    "ice_fox",
    "rainbow_axolotl",
    "fiery_goldfish",
]

# Integrate pets into the shop catalog
for _pet_id, _p in PET_CATALOG.items():
    SHOP_CATALOG[_pet_id] = {
        "name": _p["name"],
        "cost": _p["cost"],
        "category": "pet",
        "subcategory": "pets",
        "description": f"[{_p['title']}] {_p['perk_desc']}",
    }


@dataclass(frozen=True)
class PetRecord:
    id: int
    user_id: int
    pet_id: str
    species: str
    nickname: str
    happiness: int
    last_interacted: Optional[str]
    level: int
    xp: int
    is_active: bool
    adopted_at: str
    display_name: str
    perk_title: str
    perk_desc: str
    image_file: str
    quote: str


@dataclass(frozen=True)
class PetInteractResult:
    pet_id: str
    species: str
    nickname: str
    action: str
    happiness: int
    level: int
    xp: int
    leveled_up: bool
    quote: str
    message: str


@dataclass(frozen=True)
class BetResult:
    outcome: BetOutcome
    wager: int
    points_delta: int
    total_payout: int
    new_balance: int
    reward_item_id: Optional[str] = None
    reward_item_name: Optional[str] = None
    daily_bets_count: int = 1
    max_daily_bets: int = 10
    bets_remaining: int = 9


@dataclass(frozen=True)
class SlotsResult:
    reels: list[str]
    multiplier: float
    wager: int
    points_won: int
    points_delta: int
    new_balance: int
    is_jackpot: bool
    description: str


@dataclass(frozen=True)
class CoinflipResult:
    choice: str
    result: str
    won: bool
    wager: int
    points_delta: int
    new_balance: int


@dataclass(frozen=True)
class BlackjackCard:
    suit: str
    rank: str
    value: int

    def __str__(self) -> str:
        return f"{self.rank}{self.suit}"


@dataclass
class BlackjackGame:
    user_id: int
    wager: int
    player_hand: list[BlackjackCard]
    dealer_hand: list[BlackjackCard]
    status: str  # "IN_PROGRESS", "PLAYER_WIN", "DEALER_WIN", "BLACKJACK", "PUSH", "BUST"
    points_delta: int = 0
    new_balance: int = 0
    message: str = ""


@dataclass
class HighLowGame:
    user_id: int
    wager: int
    current_card: BlackjackCard
    streak: int
    current_multiplier: float
    status: str  # "IN_PROGRESS", "WON_ROUND", "BUST", "CASHED_OUT"
    points_delta: int = 0
    new_balance: int = 0
    message: str = ""


@dataclass(frozen=True)
class WorkResult:
    job_title: str
    company_or_prof: str
    description: str
    points_earned: int
    bonus_item_name: Optional[str]
    new_balance: int


@dataclass(frozen=True)
class ScavengeResult:
    location: str
    description: str
    points_earned: int
    new_balance: int


@dataclass(frozen=True)
class BountyRecord:
    id: int
    target_id: int
    creator_id: int
    amount: int
    is_claimed: bool
    claimed_by: Optional[int]
    created_at: str


@dataclass(frozen=True)
class DuelResult:
    challenger_id: int
    target_id: int
    wager: int
    challenger_roll: int
    target_roll: int
    winner_id: Optional[int]
    pot_won: int
    is_tie: bool
    bounty_won: int = 0
    pet_perk_activated: Optional[str] = None
    siphoned_amount: int = 0
    mode: str = "dice"


@dataclass
class RPSDuelGame:
    challenger_id: int
    target_id: int
    wager: int
    challenger_choice: Optional[str] = None
    target_choice: Optional[str] = None
    winner_id: Optional[int] = None
    loser_id: Optional[int] = None
    is_tie: bool = False
    is_over: bool = False
    pot_won: int = 0
    bounty_won: int = 0
    siphoned_amount: int = 0
    perk_msg: Optional[str] = None


@dataclass
class RouletteDuelGame:
    challenger_id: int
    target_id: int
    wager: int
    current_turn_id: int
    chamber: list[bool]
    current_index: int = 0
    is_over: bool = False
    exploded: bool = False
    loser_id: Optional[int] = None
    winner_id: Optional[int] = None
    pot_won: int = 0
    bounty_won: int = 0
    siphoned_amount: int = 0
    perk_msg: Optional[str] = None


@dataclass
class RPGCombatGame:
    challenger_id: int
    target_id: int
    wager: int
    c_hp: int = 100
    t_hp: int = 100
    turn_number: int = 1
    c_action: Optional[str] = None
    t_action: Optional[str] = None
    last_round_log: list[str] = field(default_factory=list)
    is_over: bool = False
    winner_id: Optional[int] = None
    loser_id: Optional[int] = None
    pot_won: int = 0
    bounty_won: int = 0
    siphoned_amount: int = 0
    perk_msg: Optional[str] = None


@dataclass(frozen=True)
class StealResult:
    success: bool
    blocked_by_shield: bool
    points_stolen: int
    fine_paid: int
    thief_new_balance: int
    target_new_balance: int
    reversed_by_uno: bool = False


@dataclass(frozen=True)
class UseItemResult:
    item_id: str
    item_name: str
    description: str
    shield_until: Optional[datetime] = None
    points_awarded: int = 0
    points_deducted: int = 0
    target_id: Optional[int] = None
    bonus_item_name: Optional[str] = None
    gacha_tier: Optional[str] = None
    new_balance: int = 0


@dataclass(frozen=True)
class UserRecord:
    user_id: int
    points: int
    lifetime_points: int
    daily_streak: int
    last_daily_claim: Optional[str]
    daily_bets_count: int
    last_bet_date: Optional[str]
    daily_trivia_count: int
    last_trivia_date: Optional[str]
    shield_until: Optional[str]
    created_at: str
    bank_points: int = 0
    last_work_time: Optional[str] = None
    last_scavenge_time: Optional[str] = None
    has_claimed_starter: bool = False
    duel_wins: int = 0
    duel_losses: int = 0
    duel_streak: int = 0
    bounties_claimed: int = 0
    bet_win_streak: int = 0
    bet_rigged_loss_remaining: int = 0
    bet_loss_streak: int = 0
    last_tax_collection: Optional[str] = None


@dataclass(frozen=True)
class DailyClaimResult:
    points_awarded: int
    base_points: int
    streak_bonus: int
    streak: int
    new_balance: int
    milestone_3k_unlocked: bool


@dataclass(frozen=True)
class UserLeaderboardEntry:
    rank: int
    user_id: int
    points: int
    daily_streak: int
    lifetime_points: int


@dataclass(frozen=True)
class UserProfile:
    user_id: int
    points: int
    lifetime_points: int
    daily_streak: int
    rank: int
    has_shield: bool
    shield_until: Optional[datetime]
    inventory: dict[str, int]
    badges: list[str]
    active_pet: Optional[PetRecord] = None
    bank_points: int = 0
    has_claimed_starter: bool = False
    duel_wins: int = 0
    duel_losses: int = 0
    duel_streak: int = 0
    bounties_claimed: int = 0


STARTER_PET_CHOICES: list[str] = ["tuxedo_cat", "golden_dog", "brown_bunny"]


SLOTS_SYMBOLS: list[dict] = [
    {"emoji": "🍒", "name": "Cherry", "weight": 32, "mult_3": 3.0, "mult_2": 0.5},
    {"emoji": "🍋", "name": "Lemon", "weight": 26, "mult_3": 4.0, "mult_2": 0.5},
    {"emoji": "🍇", "name": "Grape", "weight": 20, "mult_3": 6.0, "mult_2": 0.8},
    {"emoji": "💎", "name": "Diamond", "weight": 12, "mult_3": 10.0, "mult_2": 1.0},
    {"emoji": "👑", "name": "Crown", "weight": 7, "mult_3": 20.0, "mult_2": 1.5},
    {"emoji": "🃏", "name": "Uno Wild", "weight": 3, "mult_3": 35.0, "mult_2": 2.0},
]

WORK_JOBS: list[dict] = [
    {
        "title": "AVR Projector Whisperer",
        "company": "College of Engineering & Technology",
        "desc": "Fixed the faulty VGA-to-HDMI adapter right before the Dean's presentation.",
        "min_pts": 18,
        "max_pts": 32,
    },
    {
        "title": "C++ Debugging Hero",
        "company": "BSCS 2nd Year Lab",
        "desc": "Fixed a sophomore's memory leak and dangling pointer nightmare in 10 minutes.",
        "min_pts": 22,
        "max_pts": 40,
    },
    {
        "title": "Campus Pastry Distributor",
        "company": "Intramuros Treat Stand",
        "desc": "Sold homemade cookies and brownies to starving computer science students.",
        "min_pts": 15,
        "max_pts": 28,
    },
    {
        "title": "Freelance Web Scraper",
        "company": "PLM Student Startup",
        "desc": "Scraped research dataset papers for a senior thesis project.",
        "min_pts": 25,
        "max_pts": 45,
    },
    {
        "title": "Discrete Math Peer Tutor",
        "company": "Uno Study Circle",
        "desc": "Explained proof by induction to confused classmates before the midterms.",
        "min_pts": 20,
        "max_pts": 35,
    },
    {
        "title": "Linux Server Maintenance",
        "company": "PLM CS Lab",
        "desc": "Rebooted the lab workstation servers and cleared junk swap memory.",
        "min_pts": 22,
        "max_pts": 38,
    },
]

SCAVENGE_LOCATIONS: list[dict] = [
    {
        "location": "Plaza Roma / Intramuros Walls",
        "desc": "Searched around the cobblestone walkways and found forgotten coins from tourists.",
        "min_pts": 5,
        "max_pts": 12,
    },
    {
        "location": "Lawson Convenience Store Corner",
        "desc": "Picked up dropped change near the coffee machine and a lucky voucher.",
        "min_pts": 6,
        "max_pts": 15,
    },
    {
        "location": "CET Computer Lab Benches",
        "desc": "Looked under the keyboard trays and discovered loose Uno coins left behind.",
        "min_pts": 8,
        "max_pts": 18,
    },
    {
        "location": "PLM Grandstand & Oval",
        "desc": "Found extra pocket change dropped by jogging classmates after PE class.",
        "min_pts": 5,
        "max_pts": 14,
    },
    {
        "location": "Campus Canteen Recycle Bin",
        "desc": "Turned in recyclable bottles and cans for instant campus deposit points.",
        "min_pts": 7,
        "max_pts": 16,
    },
]

CARD_SUITS: list[str] = ["♠️", "♥️", "♦️", "♣️"]
CARD_RANKS: list[tuple[str, int]] = [
    ("2", 2),
    ("3", 3),
    ("4", 4),
    ("5", 5),
    ("6", 6),
    ("7", 7),
    ("8", 8),
    ("9", 9),
    ("10", 10),
    ("J", 10),
    ("Q", 10),
    ("K", 10),
    ("A", 11),
]


def create_random_card() -> BlackjackCard:
    suit = random.choice(CARD_SUITS)
    rank, val = random.choice(CARD_RANKS)
    return BlackjackCard(suit=suit, rank=rank, value=val)


def calculate_blackjack_score(hand: list[BlackjackCard]) -> int:
    score = sum(c.value for c in hand)
    aces = sum(1 for c in hand if c.rank == "A")
    while score > 21 and aces > 0:
        score -= 10
        aces -= 1
    return score


class RewardsDBService:
    """Thread-safe SQLite database service managing student economy, streaks, and inventory."""

    def __init__(self, db_path: Path | str = "data/rewards.db"):
        self.db_path = Path(db_path)
        self._is_memory = str(self.db_path) == ":memory:"
        self._mem_conn: Optional[sqlite3.Connection] = None
        self._active_blackjack: dict[int, BlackjackGame] = {}
        self._active_highlow: dict[int, HighLowGame] = {}
        self._pending_duels: dict[int, dict] = {}
        self._active_rps: dict[str, RPSDuelGame] = {}
        self._active_roulette: dict[str, RouletteDuelGame] = {}
        self._active_rpg: dict[str, RPGCombatGame] = {}

        if self._is_memory:
            self._mem_conn = sqlite3.connect(":memory:", check_same_thread=False)
            self._mem_conn.row_factory = sqlite3.Row
        else:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        if self._is_memory and self._mem_conn is not None:
            return self._mem_conn
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        return conn

    def _init_db(self) -> None:
        conn = self._get_connection()
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    points INTEGER DEFAULT 0,
                    lifetime_points INTEGER DEFAULT 0,
                    daily_streak INTEGER DEFAULT 0,
                    last_daily_claim TEXT,
                    daily_bets_count INTEGER DEFAULT 0,
                    last_bet_date TEXT,
                    daily_trivia_count INTEGER DEFAULT 0,
                    last_trivia_date TEXT,
                    shield_until TEXT,
                    bank_points INTEGER DEFAULT 0,
                    last_work_time TEXT,
                    last_scavenge_time TEXT,
                    has_claimed_starter INTEGER DEFAULT 0,
                    duel_wins INTEGER DEFAULT 0,
                    duel_losses INTEGER DEFAULT 0,
                    duel_streak INTEGER DEFAULT 0,
                    bounties_claimed INTEGER DEFAULT 0,
                    bet_win_streak INTEGER DEFAULT 0,
                    bet_rigged_loss_remaining INTEGER DEFAULT 0,
                    bet_loss_streak INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS inventory (
                    user_id INTEGER,
                    item_id TEXT,
                    quantity INTEGER DEFAULT 1,
                    PRIMARY KEY (user_id, item_id)
                );

                CREATE TABLE IF NOT EXISTS transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    amount INTEGER,
                    action_type TEXT,
                    description TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS redemptions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    item_name TEXT,
                    points_spent INTEGER,
                    status TEXT DEFAULT 'PENDING',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS user_trivia_history (
                    user_id INTEGER,
                    question_id INTEGER,
                    PRIMARY KEY (user_id, question_id)
                );

                CREATE TABLE IF NOT EXISTS user_pets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    pet_id TEXT NOT NULL,
                    species TEXT NOT NULL,
                    nickname TEXT NOT NULL,
                    happiness INTEGER DEFAULT 100,
                    last_interacted TEXT,
                    level INTEGER DEFAULT 1,
                    xp INTEGER DEFAULT 0,
                    is_active INTEGER DEFAULT 0,
                    adopted_at TEXT NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                );
                CREATE INDEX IF NOT EXISTS idx_user_pets_user ON user_pets(user_id);

                CREATE TABLE IF NOT EXISTS bounties (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    target_id INTEGER NOT NULL,
                    creator_id INTEGER NOT NULL,
                    amount INTEGER NOT NULL,
                    is_claimed INTEGER DEFAULT 0,
                    claimed_by INTEGER,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_bounties_target ON bounties(target_id);
                """
        )
        # Migration: ensure extra columns exist
        cursor = conn.execute("PRAGMA table_info(users)")
        cols = [r["name"] for r in cursor.fetchall()]
        if "daily_trivia_count" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN daily_trivia_count INTEGER DEFAULT 0")
        if "last_trivia_date" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN last_trivia_date TEXT")
        if "bank_points" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN bank_points INTEGER DEFAULT 0")
        if "last_work_time" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN last_work_time TEXT")
        if "last_scavenge_time" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN last_scavenge_time TEXT")
        if "has_claimed_starter" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN has_claimed_starter INTEGER DEFAULT 0")
        if "duel_wins" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN duel_wins INTEGER DEFAULT 0")
        if "duel_losses" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN duel_losses INTEGER DEFAULT 0")
        if "duel_streak" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN duel_streak INTEGER DEFAULT 0")
        if "bounties_claimed" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN bounties_claimed INTEGER DEFAULT 0")
        if "bet_win_streak" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN bet_win_streak INTEGER DEFAULT 0")
        if "bet_rigged_loss_remaining" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN bet_rigged_loss_remaining INTEGER DEFAULT 0")
        if "bet_loss_streak" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN bet_loss_streak INTEGER DEFAULT 0")
        if "last_tax_collection" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN last_tax_collection TEXT")
        conn.commit()

    def get_or_create_user(self, user_id: int) -> UserRecord:
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
            if not row:
                conn.execute(
                    "INSERT INTO users (user_id, points, lifetime_points, daily_streak) VALUES (?, 0, 0, 0)",
                    (user_id,),
                )
                conn.commit()
                row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()

            keys = row.keys()
            return UserRecord(
                user_id=row["user_id"],
                points=row["points"],
                lifetime_points=row["lifetime_points"],
                daily_streak=row["daily_streak"],
                last_daily_claim=row["last_daily_claim"],
                daily_bets_count=row["daily_bets_count"],
                last_bet_date=row["last_bet_date"],
                daily_trivia_count=row["daily_trivia_count"] if "daily_trivia_count" in keys else 0,
                last_trivia_date=row["last_trivia_date"] if "last_trivia_date" in keys else None,
                shield_until=row["shield_until"],
                created_at=row["created_at"],
                bank_points=row["bank_points"] if "bank_points" in keys else 0,
                last_work_time=row["last_work_time"] if "last_work_time" in keys else None,
                last_scavenge_time=row["last_scavenge_time"] if "last_scavenge_time" in keys else None,
                has_claimed_starter=bool(row["has_claimed_starter"]) if "has_claimed_starter" in keys else False,
                duel_wins=row["duel_wins"] if "duel_wins" in keys else 0,
                duel_losses=row["duel_losses"] if "duel_losses" in keys else 0,
                duel_streak=row["duel_streak"] if "duel_streak" in keys else 0,
                bounties_claimed=row["bounties_claimed"] if "bounties_claimed" in keys else 0,
                bet_win_streak=row["bet_win_streak"] if "bet_win_streak" in keys else 0,
                bet_rigged_loss_remaining=row["bet_rigged_loss_remaining"] if "bet_rigged_loss_remaining" in keys else 0,
                bet_loss_streak=row["bet_loss_streak"] if "bet_loss_streak" in keys else 0,
                last_tax_collection=row["last_tax_collection"] if "last_tax_collection" in keys else None,
            )

    def get_balance(self, user_id: int) -> int:
        user = self.get_or_create_user(user_id)
        return user.points

    def _pet_row_to_record(self, r: sqlite3.Row) -> PetRecord:
        pet_id = r["pet_id"]
        cat_info = PET_CATALOG.get(pet_id, {})
        quotes = cat_info.get("quotes", ["Looking at you with adoration~"])
        random_quote = random.choice(quotes)
        return PetRecord(
            id=r["id"],
            user_id=r["user_id"],
            pet_id=pet_id,
            species=r["species"],
            nickname=r["nickname"],
            happiness=r["happiness"],
            last_interacted=r["last_interacted"],
            level=r["level"],
            xp=r["xp"],
            is_active=bool(r["is_active"]),
            adopted_at=r["adopted_at"],
            display_name=cat_info.get("name", r["nickname"]),
            perk_title=cat_info.get("perk_title", "Loyal Companion"),
            perk_desc=cat_info.get("perk_desc", ""),
            image_file=cat_info.get("image_file", "tuxedo-cat.jpg"),
            quote=random_quote,
        )

    def claim_starter_pet(self, user_id: int, pet_id: str, nickname: Optional[str] = None) -> PetRecord:
        """Claim a free starter companion (0 pts) from the starter trio (Tuxedo Cat, Golden Retriever, Lop-Eared Bunny)."""
        clean_id = pet_id.strip().lower()
        if clean_id not in STARTER_PET_CHOICES:
            raise RewardsError(f"'{pet_id}' is not an eligible free starter! Choose: 🐱 Tuxedo Cat, 🐶 Golden Retriever, or 🐰 Lop-Eared Bunny.")

        user = self.get_or_create_user(user_id)
        if user.has_claimed_starter:
            raise RewardsError("You have already claimed your free starter companion! Adopt more companions from `/shop` or `/pet adopt`.")

        info = PET_CATALOG[clean_id]
        species = info["species"]
        chosen_name = nickname.strip() if nickname and nickname.strip() else info["name"]

        with self._get_connection() as conn:
            existing = conn.execute(
                "SELECT id FROM user_pets WHERE user_id = ? AND pet_id = ?",
                (user_id, clean_id),
            ).fetchone()
            if existing:
                raise RewardsError(f"You already own **{info['name']}**!")

            active_pet = conn.execute(
                "SELECT id FROM user_pets WHERE user_id = ? AND is_active = 1",
                (user_id,),
            ).fetchone()
            is_active = 1 if not active_pet else 0

            now_str = datetime.now(timezone.utc).isoformat()
            cursor = conn.execute(
                """
                INSERT INTO user_pets (user_id, pet_id, species, nickname, happiness, level, xp, is_active, adopted_at)
                VALUES (?, ?, ?, ?, 100, 1, 0, ?, ?)
                """,
                (user_id, clean_id, species, chosen_name, is_active, now_str),
            )
            pet_db_id = cursor.lastrowid
            conn.execute("UPDATE users SET has_claimed_starter = 1 WHERE user_id = ?", (user_id,))
            conn.commit()

            row = conn.execute("SELECT * FROM user_pets WHERE id = ?", (pet_db_id,)).fetchone()
            return self._pet_row_to_record(row)

    def adopt_pet(self, user_id: int, pet_id: str, nickname: Optional[str] = None) -> PetRecord:
        """Adopt a pet companion from the pet catalog."""
        if pet_id not in PET_CATALOG:
            raise RewardsError(f"Pet '{pet_id}' is not found in the Pet Shelter catalog.")

        info = PET_CATALOG[pet_id]
        cost = info["cost"]
        species = info["species"]
        chosen_name = nickname.strip() if nickname and nickname.strip() else info["name"]

        with self._get_connection() as conn:
            existing = conn.execute(
                "SELECT id FROM user_pets WHERE user_id = ? AND pet_id = ?",
                (user_id, pet_id),
            ).fetchone()
            if existing:
                raise RewardsError(f"You have already adopted **{info['name']}**!")

            active_pet = conn.execute(
                "SELECT id FROM user_pets WHERE user_id = ? AND is_active = 1",
                (user_id,),
            ).fetchone()
            is_active = 1 if not active_pet else 0

        self.deduct_points(user_id, cost, "PET_ADOPTION", f"Adopted {info['name']}")

        now_str = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO user_pets (user_id, pet_id, species, nickname, happiness, level, xp, is_active, adopted_at)
                VALUES (?, ?, ?, ?, 100, 1, 0, ?, ?)
                """,
                (user_id, pet_id, species, chosen_name, is_active, now_str),
            )
            pet_db_id = cursor.lastrowid
            conn.commit()

            row = conn.execute("SELECT * FROM user_pets WHERE id = ?", (pet_db_id,)).fetchone()
            return self._pet_row_to_record(row)

    def get_user_pets(self, user_id: int) -> list[PetRecord]:
        """Fetch all pets owned by a user."""
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM user_pets WHERE user_id = ? ORDER BY is_active DESC, id ASC",
                (user_id,),
            ).fetchall()
            return [self._pet_row_to_record(r) for r in rows]

    def get_active_pet(self, user_id: int) -> Optional[PetRecord]:
        """Fetch user's currently equipped active pet companion."""
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM user_pets WHERE user_id = ? AND is_active = 1 LIMIT 1",
                (user_id,),
            ).fetchone()
            if not row:
                return None
            return self._pet_row_to_record(row)

    def switch_active_pet(self, user_id: int, pet_id: str) -> PetRecord:
        """Switch active companion to a specified owned pet."""
        with self._get_connection() as conn:
            target = conn.execute(
                "SELECT id FROM user_pets WHERE user_id = ? AND pet_id = ?",
                (user_id, pet_id),
            ).fetchone()
            if not target:
                raise RewardsError(f"You do not own the pet '{pet_id}'! Adopt one from `/shop`.")

            conn.execute("UPDATE user_pets SET is_active = 0 WHERE user_id = ?", (user_id,))
            conn.execute("UPDATE user_pets SET is_active = 1 WHERE id = ?", (target["id"],))
            conn.commit()

            row = conn.execute("SELECT * FROM user_pets WHERE id = ?", (target["id"],)).fetchone()
            return self._pet_row_to_record(row)

    def interact_pet(self, user_id: int, action: str = "pet") -> PetInteractResult:
        """Interact with active pet (feed or pet) to increase happiness and gain XP."""
        active = self.get_active_pet(user_id)
        if not active:
            raise RewardsError("You don't have an active pet companion equipped! Adopt one from `/shop`.")

        now = datetime.now(PHT)
        today_str = now.strftime("%Y-%m-%d")

        new_xp = active.xp + 15
        new_level = active.level
        leveled_up = False
        xp_needed = new_level * 50

        if new_xp >= xp_needed:
            new_level += 1
            new_xp -= xp_needed
            leveled_up = True

        new_happiness = min(100, active.happiness + 20)

        with self._get_connection() as conn:
            conn.execute(
                """
                UPDATE user_pets
                SET happiness = ?, level = ?, xp = ?, last_interacted = ?
                WHERE id = ?
                """,
                (new_happiness, new_level, new_xp, today_str, active.id),
            )
            conn.commit()

        action_verbs = {
            "feed": ("fed a delicious gourmet treat to", "nom nom nom! *happily eats the treat*"),
            "pet": ("gently petted and cuddled", "purrs and leans happily into your hand!"),
        }
        verb, reaction = action_verbs.get(action, ("interacted with", "looks at you with love!"))

        msg = f"You {verb} **{active.nickname}**!\n💖 Happiness: **{new_happiness}%** | ⭐ Level: **{new_level}** (XP: {new_xp}/{new_level * 50})"
        if leveled_up:
            msg += f"\n🎉 **LEVEL UP!** {active.nickname} reached **Level {new_level}**!"

        return PetInteractResult(
            pet_id=active.pet_id,
            species=active.species,
            nickname=active.nickname,
            action=action,
            happiness=new_happiness,
            level=new_level,
            xp=new_xp,
            leveled_up=leveled_up,
            quote=active.quote,
            message=msg,
        )

    def rename_pet(self, user_id: int, pet_id: str, new_nickname: str) -> PetRecord:
        """Rename an owned pet."""
        clean_name = new_nickname.strip()
        if not clean_name:
            raise RewardsError("Nickname cannot be empty.")
        if len(clean_name) > 32:
            raise RewardsError("Nickname must be 32 characters or fewer.")

        with self._get_connection() as conn:
            target = conn.execute(
                "SELECT id FROM user_pets WHERE user_id = ? AND pet_id = ?",
                (user_id, pet_id),
            ).fetchone()
            if not target:
                raise RewardsError(f"You do not own the pet '{pet_id}'.")

            conn.execute(
                "UPDATE user_pets SET nickname = ? WHERE id = ?",
                (clean_name, target["id"]),
            )
            conn.commit()

            row = conn.execute("SELECT * FROM user_pets WHERE id = ?", (target["id"],)).fetchone()
            return self._pet_row_to_record(row)

    def sell_pet(self, user_id: int, pet_id: str) -> dict:
        """Sell / release an owned companion back to the shelter for a points refund (60% base + level bonuses)."""
        clean_id = pet_id.strip().lower()
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM user_pets WHERE user_id = ? AND pet_id = ?",
                (user_id, clean_id),
            ).fetchone()
            if not row:
                raise RewardsError(f"You do not own the pet '{clean_id}'! You cannot sell a companion you don't have.")

            pet_rec = self._pet_row_to_record(row)
            base_cost = PET_CATALOG.get(clean_id, {}).get("cost", 500)

            # Base refund: 60% of original cost
            base_refund = int(base_cost * 0.60)
            # Level bonus: +25 pts per level above 1
            level_bonus = (pet_rec.level - 1) * 25
            total_refund = base_refund + level_bonus

            was_active = bool(row["is_active"])

            # Delete pet from inventory
            conn.execute("DELETE FROM user_pets WHERE id = ?", (row["id"],))

            # If the sold pet was active, switch to next available companion
            new_active_pet = None
            if was_active:
                remaining = conn.execute(
                    "SELECT id FROM user_pets WHERE user_id = ? ORDER BY level DESC, id ASC LIMIT 1",
                    (user_id,),
                ).fetchone()
                if remaining:
                    conn.execute("UPDATE user_pets SET is_active = 1 WHERE id = ?", (remaining["id"],))
                    new_active_row = conn.execute("SELECT * FROM user_pets WHERE id = ?", (remaining["id"],)).fetchone()
                    new_active_pet = self._pet_row_to_record(new_active_row)

            conn.commit()

        # Add refund points to user balance
        new_balance = self.add_points(
            user_id,
            total_refund,
            "PET_SALE",
            f"Released {pet_rec.nickname} ({pet_rec.display_name}) back to the Pet Shelter",
        )

        return {
            "user_id": user_id,
            "pet_id": clean_id,
            "pet_name": pet_rec.display_name,
            "nickname": pet_rec.nickname,
            "level": pet_rec.level,
            "refund_amount": total_refund,
            "base_refund": base_refund,
            "level_bonus": level_bonus,
            "new_balance": new_balance,
            "new_active_pet": new_active_pet,
        }

    def get_featured_pet(self, now: Optional[datetime] = None) -> dict:
        """Calculate the currently spotlighted pet drop based on a 3-day deterministic rotation cycle."""
        current_time = now or datetime.now(PHT)
        if current_time.tzinfo is None:
            current_time = current_time.replace(tzinfo=PHT)
        else:
            current_time = current_time.astimezone(PHT)

        # Anchor date: 2026-08-18 00:00:00 PHT
        anchor = datetime(2026, 8, 18, 0, 0, 0, tzinfo=PHT)
        diff_seconds = max(0, int((current_time - anchor).total_seconds()))
        cycle_duration = 3 * 86400  # 3 days in seconds

        cycle_number = diff_seconds // cycle_duration
        seconds_into_cycle = diff_seconds % cycle_duration
        seconds_remaining = cycle_duration - seconds_into_cycle

        pet_index = int(cycle_number % len(PET_ROTATION_ORDER))
        featured_pet_id = PET_ROTATION_ORDER[pet_index]
        pet_info = PET_CATALOG[featured_pet_id]

        cycle_day = (seconds_into_cycle // 86400) + 1
        days_remaining = seconds_remaining // 86400
        hours_remaining = (seconds_remaining % 86400) // 3600

        next_drop_dt = current_time + timedelta(seconds=seconds_remaining)

        return {
            "pet_id": featured_pet_id,
            "pet_info": pet_info,
            "cycle_number": cycle_number,
            "cycle_day": int(cycle_day),
            "days_remaining": int(days_remaining),
            "hours_remaining": int(hours_remaining),
            "seconds_remaining": int(seconds_remaining),
            "next_drop_timestamp": int(next_drop_dt.timestamp()),
        }

    def claim_daily(self, user_id: int, now: Optional[datetime] = None) -> DailyClaimResult:
        """Process daily point claim with streak multipliers, pet buffs, and 3k milestone detection."""
        current_time = now or datetime.now(PHT)
        if current_time.tzinfo is None:
            current_time = current_time.replace(tzinfo=PHT)
        else:
            current_time = current_time.astimezone(PHT)

        today_str = current_time.strftime("%Y-%m-%d")
        yesterday_str = (current_time - timedelta(days=1)).strftime("%Y-%m-%d")

        user = self.get_or_create_user(user_id)

        if user.last_daily_claim == today_str:
            tomorrow_midnight = (current_time + timedelta(days=1)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            raise DailyAlreadyClaimedError(
                "You have already claimed your daily reward today! Next claim available tomorrow at midnight (PHT).",
                next_claim_time=tomorrow_midnight,
            )

        active_pet = self.get_active_pet(user_id)

        # Streak calculation (Turtle freezes streak on missed days!)
        if user.last_daily_claim == yesterday_str:
            new_streak = user.daily_streak + 1
        elif active_pet and active_pet.species == "turtle" and user.daily_streak > 0:
            new_streak = user.daily_streak + 1
        else:
            new_streak = 1

        base_points = 20
        streak_bonus = min((new_streak - 1) * 2, 20)
        total_points = base_points + streak_bonus

        # Cat 2x Daily Perk!
        if active_pet and active_pet.species == "cat":
            base_points *= 2
            streak_bonus *= 2
            total_points *= 2

        new_balance = user.points + total_points
        new_lifetime = user.lifetime_points + total_points
        milestone_unlocked = (user.lifetime_points < 3000 <= new_lifetime)

        with self._get_connection() as conn:
            conn.execute(
                """
                UPDATE users
                SET points = points + ?,
                    lifetime_points = lifetime_points + ?,
                    daily_streak = ?,
                    last_daily_claim = ?
                WHERE user_id = ?
                """,
                (total_points, total_points, new_streak, today_str, user_id),
            )
            desc = f"Daily Claim (Streak: {new_streak}d, Bonus: +{streak_bonus}pts)"
            if active_pet and active_pet.species == "cat":
                desc += " [🐱 2x Cat Perk!]"
            conn.execute(
                """
                INSERT INTO transactions (user_id, amount, action_type, description)
                VALUES (?, ?, 'DAILY', ?)
                """,
                (user_id, total_points, desc),
            )
            conn.commit()

        return DailyClaimResult(
            points_awarded=total_points,
            base_points=base_points,
            streak_bonus=streak_bonus,
            streak=new_streak,
            new_balance=new_balance,
            milestone_3k_unlocked=milestone_unlocked,
        )

    def add_points(self, user_id: int, amount: int, action_type: str, description: str = "") -> int:
        """Add points to user balance and lifetime total."""
        self.get_or_create_user(user_id)
        with self._get_connection() as conn:
            conn.execute(
                """
                UPDATE users
                SET points = points + ?,
                    lifetime_points = lifetime_points + ?
                WHERE user_id = ?
                """,
                (amount, amount if amount > 0 else 0, user_id),
            )
            conn.execute(
                """
                INSERT INTO transactions (user_id, amount, action_type, description)
                VALUES (?, ?, ?, ?)
                """,
                (user_id, amount, action_type, description),
            )
            conn.commit()
            row = conn.execute("SELECT points FROM users WHERE user_id = ?", (user_id,)).fetchone()
            return row["points"]

    def deduct_points(self, user_id: int, amount: int, action_type: str, description: str = "") -> int:
        """Deduct points from user balance."""
        user = self.get_or_create_user(user_id)
        if user.points < amount:
            raise InsufficientPointsError(
                f"Insufficient points. You have {user.points} pts, but need {amount} pts."
            )

        with self._get_connection() as conn:
            conn.execute(
                "UPDATE users SET points = points - ? WHERE user_id = ?",
                (amount, user_id),
            )
            conn.execute(
                """
                INSERT INTO transactions (user_id, amount, action_type, description)
                VALUES (?, ?, ?, ?)
                """,
                (user_id, -amount, action_type, description),
            )
            conn.commit()
            row = conn.execute("SELECT points FROM users WHERE user_id = ?", (user_id,)).fetchone()
            return row["points"]

    def has_active_shield(self, user_id: int, now: Optional[datetime] = None) -> bool:
        """Check if user has an active Immunity Shield."""
        current_time = now or datetime.now(PHT)
        if current_time.tzinfo is None:
            current_time = current_time.replace(tzinfo=PHT)
        else:
            current_time = current_time.astimezone(PHT)

        user = self.get_or_create_user(user_id)
        if not user.shield_until:
            return False

        try:
            shield_dt = datetime.fromisoformat(user.shield_until)
            if shield_dt.tzinfo is None:
                shield_dt = shield_dt.replace(tzinfo=PHT)
            return shield_dt > current_time
        except ValueError:
            return False

    def activate_shield(self, user_id: int, duration_days: int = 7, now: Optional[datetime] = None) -> datetime:
        """Activate Immunity Shield for specified duration (default 7 days + 2 days if Turtle pet)."""
        current_time = now or datetime.now(PHT)
        if current_time.tzinfo is None:
            current_time = current_time.replace(tzinfo=PHT)
        else:
            current_time = current_time.astimezone(PHT)

        active_pet = self.get_active_pet(user_id)
        if active_pet and active_pet.species == "turtle":
            duration_days += 2

        shield_until = current_time + timedelta(days=duration_days)
        iso_str = shield_until.isoformat()

        with self._get_connection() as conn:
            conn.execute(
                "UPDATE users SET shield_until = ? WHERE user_id = ?",
                (iso_str, user_id),
            )
            conn.commit()
        return shield_until

    def add_item(self, user_id: int, item_id: str, quantity: int = 1) -> None:
        self.get_or_create_user(user_id)
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO inventory (user_id, item_id, quantity)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id, item_id) DO UPDATE SET quantity = quantity + ?
                """,
                (user_id, item_id, quantity, quantity),
            )
            conn.commit()

    def remove_item(self, user_id: int, item_id: str, quantity: int = 1) -> bool:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT quantity FROM inventory WHERE user_id = ? AND item_id = ?",
                (user_id, item_id),
            ).fetchone()
            if not row or row["quantity"] < quantity:
                raise ItemNotFoundError(f"You do not have enough of item '{item_id}'.")

            new_qty = row["quantity"] - quantity
            if new_qty > 0:
                conn.execute(
                    "UPDATE inventory SET quantity = ? WHERE user_id = ? AND item_id = ?",
                    (new_qty, user_id, item_id),
                )
            else:
                conn.execute(
                    "DELETE FROM inventory WHERE user_id = ? AND item_id = ?",
                    (user_id, item_id),
                )
            conn.commit()
            return True

    def get_inventory(self, user_id: int) -> dict[str, int]:
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT item_id, quantity FROM inventory WHERE user_id = ?",
                (user_id,),
            ).fetchall()
            return {row["item_id"]: row["quantity"] for row in rows}

    def get_leaderboard(self, limit: int = 10, offset: int = 0) -> tuple[list[UserLeaderboardEntry], int]:
        """Fetch sorted leaderboard entries with pagination."""
        with self._get_connection() as conn:
            total_count = conn.execute("SELECT COUNT(*) as count FROM users").fetchone()["count"]
            rows = conn.execute(
                """
                SELECT user_id, points, daily_streak, lifetime_points
                FROM users
                ORDER BY points DESC, lifetime_points DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()

            entries = [
                UserLeaderboardEntry(
                    rank=offset + i + 1,
                    user_id=r["user_id"],
                    points=r["points"],
                    daily_streak=r["daily_streak"],
                    lifetime_points=r["lifetime_points"],
                )
                for i, r in enumerate(rows)
            ]
            return entries, total_count

    def get_profile(self, user_id: int, now: Optional[datetime] = None) -> UserProfile:
        """Fetch comprehensive user profile including rank, badges, and inventory."""
        current_time = now or datetime.now(timezone.utc)
        user = self.get_or_create_user(user_id)

        # Compute rank
        with self._get_connection() as conn:
            rank_row = conn.execute(
                "SELECT COUNT(*) + 1 as rank FROM users WHERE points > ?",
                (user.points,),
            ).fetchone()
            user_rank = rank_row["rank"]

        # Parse shield
        has_shield = False
        shield_dt = None
        if user.shield_until:
            try:
                s_dt = datetime.fromisoformat(user.shield_until)
                if s_dt.tzinfo is None:
                    s_dt = s_dt.replace(tzinfo=timezone.utc)
                if s_dt > current_time:
                    has_shield = True
                    shield_dt = s_dt
            except ValueError:
                pass

        # Badges
        badges = []
        if user.lifetime_points >= 3000:
            badges.append("🍫 Exam Survivor")
        if user.daily_streak >= 7:
            badges.append("🔥 7-Day Streak")
        if user_rank == 1:
            badges.append("👑 Top 1 Scholar")
        elif user_rank <= 3:
            badges.append("🌟 Top 3 Elite")
        if user.duel_wins >= 25:
            badges.append("👑 Campus Gladiator")
        elif user.duel_wins >= 5:
            badges.append("🗡️ Duelist")
        if user.bounties_claimed >= 1:
            badges.append("🎯 Bounty Hunter")
        if user.duel_streak >= 5:
            badges.append("🔥 Undefeated Duelist")

        inv = self.get_inventory(user_id)
        active_pet = self.get_active_pet(user_id)

        return UserProfile(
            user_id=user.user_id,
            points=user.points,
            lifetime_points=user.lifetime_points,
            daily_streak=user.daily_streak,
            rank=user_rank,
            has_shield=has_shield,
            shield_until=shield_dt,
            inventory=inv,
            badges=badges,
            active_pet=active_pet,
            bank_points=user.bank_points,
            has_claimed_starter=user.has_claimed_starter,
            duel_wins=user.duel_wins,
            duel_losses=user.duel_losses,
            duel_streak=user.duel_streak,
            bounties_claimed=user.bounties_claimed,
        )

    def record_redemption(self, user_id: int, item_id: str) -> dict:
        """Deduct points and log a prize redemption, consumable purchase, or pet adoption."""
        if item_id in PET_CATALOG:
            pet_rec = self.adopt_pet(user_id, item_id)
            return {
                "id": pet_rec.id,
                "user_id": user_id,
                "item_id": item_id,
                "item_name": pet_rec.display_name,
                "points_spent": PET_CATALOG[item_id]["cost"],
                "category": "pet",
                "status": "DELIVERED",
                "pet": pet_rec,
            }

        if item_id not in SHOP_CATALOG:
            raise RewardsError(f"Item '{item_id}' is not available in the shop.")

        item = SHOP_CATALOG[item_id]
        points_cost = item["cost"]
        item_name = item["name"]

        # Deduct points
        self.deduct_points(user_id, points_cost, "SHOP_PURCHASE", f"Purchased {item_name}")

        # Check for 5% Cashback perk from Axolotl / Dragon / Goldfish
        active_pet = self.get_active_pet(user_id)
        if active_pet and active_pet.species in ("axolotl", "dragon", "goldfish"):
            cashback = max(1, int(points_cost * 0.05))
            self.add_points(user_id, cashback, "PET_CASHBACK", f"5% Cashback from {active_pet.nickname}")

        # If consumable item, automatically grant to inventory
        if item.get("category") == "consumable":
            self.add_item(user_id, item_id, 1)
            status = "DELIVERED"
        else:
            status = "PENDING"

        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO redemptions (user_id, item_name, points_spent, status)
                VALUES (?, ?, ?, ?)
                """,
                (user_id, item_name, points_cost, status),
            )
            conn.commit()
            redemption_id = cursor.lastrowid

        return {
            "id": redemption_id,
            "user_id": user_id,
            "item_id": item_id,
            "item_name": item_name,
            "points_spent": points_cost,
            "category": item.get("category"),
            "status": status,
        }

    def update_redemption_status(self, redemption_id: int, status: str) -> dict:
        """Approve or reject a redemption. If rejected, automatically refunds points."""
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM redemptions WHERE id = ?", (redemption_id,)
            ).fetchone()
            if not row:
                raise RewardsError(f"Redemption ID #{redemption_id} not found.")

            user_id = row["user_id"]
            points_spent = row["points_spent"]
            item_name = row["item_name"]
            prev_status = row["status"]

            if prev_status != "PENDING" and status in ("APPROVED", "REJECTED"):
                raise RewardsError(f"Redemption #{redemption_id} is already {prev_status}.")

            conn.execute(
                "UPDATE redemptions SET status = ? WHERE id = ?",
                (status, redemption_id),
            )
            conn.commit()

        # If rejected, refund points to user
        if status == "REJECTED":
            self.add_points(user_id, points_spent, "REDEEM_REFUND", f"Refund for rejected {item_name}")

        return {
            "id": redemption_id,
            "user_id": user_id,
            "item_name": item_name,
            "points_spent": points_spent,
            "status": status,
        }

    def get_user_transactions(self, user_id: int, limit: int = 5) -> list[dict]:
        """Fetch latest transactions for a user."""
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT amount, action_type, description, created_at
                FROM transactions
                WHERE user_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
            return [dict(r) for r in rows]

    def play_bet(
        self,
        user_id: int,
        wager: int = 50,
        now: Optional[datetime] = None,
        fixed_outcome: Optional[BetOutcome] = None,
        fixed_skill: Optional[str] = None,
    ) -> BetResult:
        """Place a roulette bet (min 10 pts, max 100 pts, limit 10 bets/day). Outcomes: Jackpot (4x profit), Double (1x profit), Skill Drop, Refund, Bust."""
        if wager < 10:
            raise RewardsError("Minimum bet amount is 10 Uno Points!")
        if wager > 100:
            raise RewardsError("Maximum bet amount is 100 Uno Points!")

        user = self.get_or_create_user(user_id)
        if user.points < wager:
            raise InsufficientPointsError(
                f"You need at least {wager:,} pts to place this bet! You have {user.points:,} pts."
            )

        current_time = now or datetime.now(PHT)
        if current_time.tzinfo is None:
            current_time = current_time.replace(tzinfo=PHT)
        else:
            current_time = current_time.astimezone(PHT)
        today_str = current_time.strftime("%Y-%m-%d")

        # Daily bet limit: 10 bets per day (PHT)
        MAX_DAILY_BETS = 10
        if user.last_bet_date == today_str:
            current_daily_bets = user.daily_bets_count
        else:
            current_daily_bets = 0

        if current_daily_bets >= MAX_DAILY_BETS:
            raise MaxBetsReachedError(
                f"You have reached your daily limit of {MAX_DAILY_BETS} bets! Return tomorrow after 00:00 (PHT) to test your luck again."
            )

        new_daily_bets = current_daily_bets + 1
        bets_remaining = MAX_DAILY_BETS - new_daily_bets

        # Track streak states
        win_streak = user.bet_win_streak
        rigged_losses = user.bet_rigged_loss_remaining
        loss_streak = user.bet_loss_streak

        active_pet = self.get_active_pet(user_id)
        is_bunny = active_pet and active_pet.species == "bunny"

        # Determine outcome
        if fixed_outcome is not None:
            outcome = fixed_outcome
            if outcome in (BetOutcome.JACKPOT, BetOutcome.DOUBLE, BetOutcome.SKILL_DROP):
                win_streak += 1
                loss_streak = 0
                if win_streak >= 5:
                    rigged_losses = 7
                    win_streak = 0
            elif outcome == BetOutcome.BUST:
                win_streak = 0
                if rigged_losses > 0:
                    rigged_losses -= 1
                else:
                    loss_streak += 1
        elif rigged_losses > 0:
            # Rigged House Edge: After 5 continuous wins, player suffers 7 forced losses
            outcome = BetOutcome.BUST
            rigged_losses -= 1
            win_streak = 0
            loss_streak += 1
        elif loss_streak >= 5:
            # Pity System: After 5 continuous losses, guarantee a pity win
            roll = random.random()
            if roll < 0.70:
                outcome = BetOutcome.DOUBLE
            elif roll < 0.90:
                outcome = BetOutcome.SKILL_DROP
            else:
                outcome = BetOutcome.JACKPOT
            loss_streak = 0
            win_streak += 1
            if win_streak >= 5:
                rigged_losses = 7
                win_streak = 0
        else:
            # Standard Probability Roll (Tuned with healthy House Edge: ~55% Bust)
            roll = random.random()
            if is_bunny:
                # Bunny companion (+10% luck boost)
                if roll < 0.08:
                    outcome = BetOutcome.JACKPOT
                elif roll < 0.24:
                    outcome = BetOutcome.DOUBLE
                elif roll < 0.42:
                    outcome = BetOutcome.SKILL_DROP
                elif roll < 0.55:
                    outcome = BetOutcome.REFUND
                else:
                    outcome = BetOutcome.BUST
            else:
                # Standard odds: 5% Jackpot, 12% Double, 15% Skill Drop, 13% Refund, 55% Bust
                if roll < 0.05:
                    outcome = BetOutcome.JACKPOT
                elif roll < 0.17:
                    outcome = BetOutcome.DOUBLE
                elif roll < 0.32:
                    outcome = BetOutcome.SKILL_DROP
                elif roll < 0.45:
                    outcome = BetOutcome.REFUND
                else:
                    outcome = BetOutcome.BUST

            # Update win/loss streaks
            if outcome in (BetOutcome.JACKPOT, BetOutcome.DOUBLE, BetOutcome.SKILL_DROP):
                win_streak += 1
                loss_streak = 0
                if win_streak >= 5:
                    # 5 Continuous Wins reached! House activates 7-loss rigged penalty
                    rigged_losses = 7
                    win_streak = 0
            elif outcome == BetOutcome.BUST:
                win_streak = 0
                loss_streak += 1

        # Calculate payouts
        points_delta = 0
        total_payout = 0
        reward_item_id = None
        reward_item_name = None

        if outcome == BetOutcome.JACKPOT:
            points_delta = wager * 3  # Net gain: +3x wager (4x total return)
            total_payout = wager * 4
            new_balance = user.points + points_delta
            new_lifetime = user.lifetime_points + points_delta
        elif outcome == BetOutcome.DOUBLE:
            points_delta = wager  # Net gain: +1x wager (2x total return)
            total_payout = wager * 2
            new_balance = user.points + points_delta
            new_lifetime = user.lifetime_points + points_delta
        elif outcome == BetOutcome.SKILL_DROP:
            points_delta = 0  # Reimbursed wager + free card
            total_payout = wager
            new_balance = user.points
            new_lifetime = user.lifetime_points
            possible_skills = [
                "pickpocket",
                "shield_1w",
                "double_daily",
                "uno_reverse",
                "airdrop",
                "gacha_box",
                "shield_breaker",
                "tax_audit",
                "coffee_bribe",
            ]
            reward_item_id = fixed_skill if fixed_skill in possible_skills else random.choice(possible_skills)
            reward_item_name = ITEM_DEFINITIONS[reward_item_id]["name"]
            self.add_item(user_id, reward_item_id, 1)
        elif outcome == BetOutcome.REFUND:
            points_delta = 0
            total_payout = wager
            new_balance = user.points
            new_lifetime = user.lifetime_points
        else:  # BUST
            points_delta = -wager
            total_payout = 0
            new_balance = user.points - wager
            new_lifetime = user.lifetime_points

        with self._get_connection() as conn:
            conn.execute(
                """
                UPDATE users
                SET points = ?,
                    lifetime_points = ?,
                    daily_bets_count = ?,
                    last_bet_date = ?,
                    bet_win_streak = ?,
                    bet_rigged_loss_remaining = ?,
                    bet_loss_streak = ?
                WHERE user_id = ?
                """,
                (new_balance, new_lifetime, new_daily_bets, today_str, win_streak, rigged_losses, loss_streak, user_id),
            )
            action_desc = f"Bet Outcome: {outcome.value} ({'+' if points_delta > 0 else ''}{points_delta} pts, wager: {wager} pts)"
            if is_bunny:
                action_desc += " [🐰 Bunny Perk!]"
            if reward_item_name:
                action_desc += f" + Won {reward_item_name}"
            conn.execute(
                """
                INSERT INTO transactions (user_id, amount, action_type, description)
                VALUES (?, ?, 'BET', ?)
                """,
                (user_id, points_delta, action_desc),
            )
            conn.commit()

        return BetResult(
            outcome=outcome,
            wager=wager,
            points_delta=points_delta,
            total_payout=total_payout,
            new_balance=new_balance,
            reward_item_id=reward_item_id,
            reward_item_name=reward_item_name,
            daily_bets_count=new_daily_bets,
            max_daily_bets=MAX_DAILY_BETS,
            bets_remaining=bets_remaining,
        )

    def play_slots(
        self,
        user_id: int,
        wager: int = 50,
        fixed_reels: Optional[list[str]] = None,
    ) -> SlotsResult:
        """Spin 3 slot machine reels (max 100 pts). Match 2 for consolation prize, match 3 for huge multipliers up to 35x!"""
        if wager < 10:
            raise RewardsError("Minimum slots wager is 10 Uno Points!")
        if wager > 100:
            raise RewardsError("Maximum slots wager is 100 Uno Points!")

        user = self.get_or_create_user(user_id)
        if user.points < wager:
            raise InsufficientPointsError(
                f"You need at least {wager:,} pts to spin the slots! You have {user.points:,} pts."
            )

        active_pet = self.get_active_pet(user_id)
        is_bunny = active_pet and active_pet.species == "bunny"

        if fixed_reels is not None and len(fixed_reels) == 3:
            reels = fixed_reels
        else:
            symbols = []
            weights = []
            for s in SLOTS_SYMBOLS:
                symbols.append(s["emoji"])
                w = s["weight"]
                if is_bunny and s["emoji"] in ("💎", "👑", "🃏"):
                    w += 4  # Bunny luck perk
                weights.append(w)
            reels = random.choices(symbols, weights=weights, k=3)

        # Calculate matching
        sym_counts = Counter(reels)
        most_common_sym, count = sym_counts.most_common(1)[0]
        sym_def = next((s for s in SLOTS_SYMBOLS if s["emoji"] == most_common_sym), SLOTS_SYMBOLS[0])

        is_jackpot = False
        if count == 3:
            multiplier = sym_def["mult_3"]
            is_jackpot = (most_common_sym == "🃏")
            desc = f"🎉 TRIPLE MATCH! 3x {sym_def['name']} ({multiplier:.1f}x Multiplier)!"
        elif count == 2:
            multiplier = sym_def["mult_2"]
            desc = f"✨ DOUBLE MATCH! 2x {sym_def['name']} ({multiplier:.1f}x Consolation Payout)!"
        else:
            multiplier = 0.0
            desc = "❌ No match. Better luck on the next spin!"

        points_won = int(wager * multiplier)
        points_delta = points_won - wager
        new_balance = user.points + points_delta
        new_lifetime = user.lifetime_points + max(0, points_delta)

        with self._get_connection() as conn:
            conn.execute(
                "UPDATE users SET points = ?, lifetime_points = ? WHERE user_id = ?",
                (new_balance, new_lifetime, user_id),
            )
            act_desc = f"Slots: [{' '.join(reels)}] -> {desc} ({'+' if points_delta > 0 else ''}{points_delta} pts)"
            conn.execute(
                "INSERT INTO transactions (user_id, amount, action_type, description) VALUES (?, ?, 'SLOTS', ?)",
                (user_id, points_delta, act_desc),
            )
            conn.commit()

        return SlotsResult(
            reels=reels,
            multiplier=multiplier,
            wager=wager,
            points_won=points_won,
            points_delta=points_delta,
            new_balance=new_balance,
            is_jackpot=is_jackpot,
            description=desc,
        )

    def play_coinflip(
        self,
        user_id: int,
        choice: str,
        wager: int = 50,
        fixed_flip: Optional[str] = None,
    ) -> CoinflipResult:
        """Fast 1.75x payout coin toss (limit 100 pts max)."""
        if wager < 10:
            raise RewardsError("Minimum coinflip wager is 10 Uno Points!")
        if wager > 100:
            raise RewardsError("Maximum coinflip wager is 100 Uno Points!")

        user = self.get_or_create_user(user_id)
        if user.points < wager:
            raise InsufficientPointsError(
                f"You need at least {wager:,} pts to flip! You have {user.points:,} pts."
            )

        clean_choice = choice.lower().strip()
        if clean_choice in ("h", "head", "heads"):
            picked = "heads"
        elif clean_choice in ("t", "tail", "tails"):
            picked = "tails"
        else:
            raise RewardsError("Invalid choice! Choose either `heads` (H) or `tails` (T).")

        active_pet = self.get_active_pet(user_id)
        is_bunny = active_pet and active_pet.species == "bunny"

        if fixed_flip is not None:
            result = fixed_flip.lower().strip()
        else:
            # 46% win rate (54% loss rate) to provide balanced house edge, 50% with Bunny
            win_chance = 0.50 if is_bunny else 0.46
            if random.random() < win_chance:
                result = picked
            else:
                result = "tails" if picked == "heads" else "heads"

        won = (picked == result)
        # 1.75x total return (+0.75x net profit on win)
        points_delta = int(wager * 0.75) if won else -wager
        new_balance = user.points + points_delta
        new_lifetime = user.lifetime_points + (points_delta if won else 0)

        with self._get_connection() as conn:
            conn.execute(
                "UPDATE users SET points = ?, lifetime_points = ? WHERE user_id = ?",
                (new_balance, new_lifetime, user_id),
            )
            act_desc = f"Coinflip: Picked {picked}, Flipped {result} -> {'WON (1.75x)' if won else 'LOST'} ({'+' if points_delta > 0 else ''}{points_delta} pts)"
            conn.execute(
                "INSERT INTO transactions (user_id, amount, action_type, description) VALUES (?, ?, 'COINFLIP', ?)",
                (user_id, points_delta, act_desc),
            )
            conn.commit()

        return CoinflipResult(
            choice=picked,
            result=result,
            won=won,
            wager=wager,
            points_delta=points_delta,
            new_balance=new_balance,
        )

    def get_active_blackjack(self, user_id: int) -> Optional[BlackjackGame]:
        return self._active_blackjack.get(user_id)

    def start_blackjack(
        self,
        user_id: int,
        wager: int = 50,
        fixed_player_cards: Optional[list[BlackjackCard]] = None,
        fixed_dealer_cards: Optional[list[BlackjackCard]] = None,
    ) -> BlackjackGame:
        """Start a new blackjack game, dealing 2 cards each (max 100 pts)."""
        if wager < 10:
            raise RewardsError("Minimum blackjack wager is 10 Uno Points!")
        if wager > 100:
            raise RewardsError("Maximum blackjack wager is 100 Uno Points!")

        user = self.get_or_create_user(user_id)
        if user.points < wager:
            raise InsufficientPointsError(
                f"You need at least {wager:,} pts to play blackjack! You have {user.points:,} pts."
            )

        # Deduct wager upfront
        self.deduct_points(user_id, wager, "BLACKJACK_BET", f"Started Blackjack hand with {wager} pts wager")

        p_hand = fixed_player_cards or [create_random_card(), create_random_card()]
        d_hand = fixed_dealer_cards or [create_random_card(), create_random_card()]

        p_score = calculate_blackjack_score(p_hand)
        d_score = calculate_blackjack_score(d_hand)

        game = BlackjackGame(
            user_id=user_id,
            wager=wager,
            player_hand=p_hand,
            dealer_hand=d_hand,
            status="IN_PROGRESS",
            points_delta=0,
            new_balance=self.get_balance(user_id),
            message="Your turn! Hit to draw or Stand to hold.",
        )

        # Natural 21 Check
        if p_score == 21:
            if d_score == 21:
                game.status = "PUSH"
                game.points_delta = 0
                self.add_points(user_id, wager, "BLACKJACK_PUSH", "Both hit 21: Push/Tie refund")
                game.new_balance = self.get_balance(user_id)
                game.message = "🤝 Both you and the dealer hit 21! Push — wager refunded."
            else:
                game.status = "BLACKJACK"
                payout = int(wager * 2.5)  # 3:2 payout + wager returned
                game.points_delta = payout - wager
                self.add_points(user_id, payout, "BLACKJACK_WIN", "Natural Blackjack 21 Win (3:2 payout)")
                game.new_balance = self.get_balance(user_id)
                game.message = f"👑 NATURAL BLACKJACK 21! You won +{game.points_delta:,} pts!"
            self._active_blackjack.pop(user_id, None)
        else:
            self._active_blackjack[user_id] = game

        return game

    def hit_blackjack(self, user_id: int, fixed_card: Optional[BlackjackCard] = None) -> BlackjackGame:
        """Hit: draw 1 card for player."""
        game = self._active_blackjack.get(user_id)
        if not game or game.status != "IN_PROGRESS":
            raise RewardsError("You don't have an active blackjack game in progress!")

        new_card = fixed_card or create_random_card()
        game.player_hand.append(new_card)
        p_score = calculate_blackjack_score(game.player_hand)

        if p_score > 21:
            game.status = "BUST"
            game.points_delta = -game.wager
            game.new_balance = self.get_balance(user_id)
            game.message = f"💥 BUSTED ({p_score})! You lost your {game.wager:,} pts wager."
            self._active_blackjack.pop(user_id, None)
        elif p_score == 21:
            return self.stand_blackjack(user_id)
        else:
            game.message = f"Hit with {new_card}. Hand score: **{p_score}**. Hit or Stand?"

        return game

    def stand_blackjack(self, user_id: int, fixed_dealer_draws: Optional[list[BlackjackCard]] = None) -> BlackjackGame:
        """Stand: dealer draws until reaching 17, then hand resolves."""
        game = self._active_blackjack.get(user_id)
        if not game or game.status != "IN_PROGRESS":
            raise RewardsError("You don't have an active blackjack game in progress!")

        p_score = calculate_blackjack_score(game.player_hand)

        if fixed_dealer_draws:
            for c in fixed_dealer_draws:
                game.dealer_hand.append(c)
        else:
            while calculate_blackjack_score(game.dealer_hand) < 17:
                game.dealer_hand.append(create_random_card())

        d_score = calculate_blackjack_score(game.dealer_hand)

        if d_score > 21:
            game.status = "PLAYER_WIN"
            payout = game.wager * 2
            game.points_delta = game.wager
            self.add_points(user_id, payout, "BLACKJACK_WIN", "Dealer busted! Player won.")
            game.new_balance = self.get_balance(user_id)
            game.message = f"🎉 Dealer busted ({d_score})! You won **+{game.wager:,} pts**!"
        elif p_score > d_score:
            game.status = "PLAYER_WIN"
            payout = game.wager * 2
            game.points_delta = game.wager
            self.add_points(user_id, payout, "BLACKJACK_WIN", f"Player {p_score} beat Dealer {d_score}")
            game.new_balance = self.get_balance(user_id)
            game.message = f"🎉 You win ({p_score} vs {d_score})! Won **+{game.wager:,} pts**!"
        elif p_score == d_score:
            game.status = "PUSH"
            game.points_delta = 0
            self.add_points(user_id, game.wager, "BLACKJACK_PUSH", "Tie with dealer: Push refund")
            game.new_balance = self.get_balance(user_id)
            game.message = f"🤝 Push tie ({p_score} vs {d_score})! Your {game.wager:,} pts wager was refunded."
        else:
            game.status = "DEALER_WIN"
            game.points_delta = -game.wager
            game.new_balance = self.get_balance(user_id)
            game.message = f"❌ Dealer wins ({d_score} vs {p_score}). You lost {game.wager:,} pts."

        self._active_blackjack.pop(user_id, None)
        return game

    def double_down_blackjack(
        self,
        user_id: int,
        fixed_card: Optional[BlackjackCard] = None,
        fixed_dealer_draws: Optional[list[BlackjackCard]] = None,
    ) -> BlackjackGame:
        """Double down: double wager, receive exactly 1 card, then dealer resolves."""
        game = self._active_blackjack.get(user_id)
        if not game or game.status != "IN_PROGRESS":
            raise RewardsError("You don't have an active blackjack game in progress!")

        if len(game.player_hand) > 2:
            raise RewardsError("You can only Double Down on your starting 2 cards!")

        user = self.get_or_create_user(user_id)
        if user.points < game.wager:
            raise InsufficientPointsError(
                f"You need another {game.wager:,} pts to Double Down! (Wallet: {user.points:,} pts)"
            )

        self.deduct_points(user_id, game.wager, "BLACKJACK_DOUBLE", "Doubled down blackjack wager")
        game.wager *= 2

        new_card = fixed_card or create_random_card()
        game.player_hand.append(new_card)
        p_score = calculate_blackjack_score(game.player_hand)

        if p_score > 21:
            game.status = "BUST"
            game.points_delta = -game.wager
            game.new_balance = self.get_balance(user_id)
            game.message = f"💥 BUSTED ({p_score}) on Double Down! You lost {game.wager:,} pts."
            self._active_blackjack.pop(user_id, None)
            return game

        return self.stand_blackjack(user_id, fixed_dealer_draws=fixed_dealer_draws)

    def get_active_highlow(self, user_id: int) -> Optional[HighLowGame]:
        return self._active_highlow.get(user_id)

    def start_highlow(
        self,
        user_id: int,
        wager: int = 50,
        fixed_card: Optional[BlackjackCard] = None,
    ) -> HighLowGame:
        """Start a high-low streak game with a starting card (limit 100 pts max)."""
        if wager < 10:
            raise RewardsError("Minimum High-Low wager is 10 Uno Points!")
        if wager > 100:
            raise RewardsError("Maximum High-Low wager is 100 Uno Points!")

        user = self.get_or_create_user(user_id)
        if user.points < wager:
            raise InsufficientPointsError(
                f"You need at least {wager:,} pts to play High-Low! You have {user.points:,} pts."
            )

        self.deduct_points(user_id, wager, "HIGHLOW_BET", f"Started High-Low with {wager} pts")
        start_c = fixed_card or create_random_card()

        game = HighLowGame(
            user_id=user_id,
            wager=wager,
            current_card=start_c,
            streak=0,
            current_multiplier=1.0,
            status="IN_PROGRESS",
            points_delta=0,
            new_balance=self.get_balance(user_id),
            message=f"Starting card: **{start_c}** (Value {start_c.value}). Will the next card be Higher or Lower?",
        )
        self._active_highlow[user_id] = game
        return game

    def guess_highlow(
        self,
        user_id: int,
        guess: str,
        fixed_next_card: Optional[BlackjackCard] = None,
    ) -> HighLowGame:
        """Guess whether next card is higher or lower."""
        game = self._active_highlow.get(user_id)
        if not game or game.status not in ("IN_PROGRESS", "WON_ROUND"):
            raise RewardsError("You don't have an active High-Low game in progress!")

        clean_guess = guess.lower().strip()
        if clean_guess not in ("higher", "lower", "high", "low", "h", "l"):
            raise RewardsError("Invalid guess! Choose `higher` (🔼) or `lower` (🔽).")

        is_higher = clean_guess in ("higher", "high", "h")
        next_c = fixed_next_card or create_random_card()

        old_val = game.current_card.value
        new_val = next_c.value
        game.current_card = next_c

        if new_val == old_val:
            game.message = f"🃏 Drawn **{next_c}** (Value {new_val}). Equal value! Streak safe at {game.streak}. Guess again!"
            return game

        correct = (new_val > old_val) if is_higher else (new_val < old_val)
        if not correct:
            game.status = "BUST"
            game.points_delta = -game.wager
            game.new_balance = self.get_balance(user_id)
            game.message = f"❌ Drawn **{next_c}** (Value {new_val}). Wrong guess! Busted and lost {game.wager:,} pts."
            self._active_highlow.pop(user_id, None)
            return game

        game.streak += 1
        mult_ladder = [1.3, 1.8, 2.8, 5.0, 9.0, 16.0]
        idx = min(game.streak - 1, len(mult_ladder) - 1)
        game.current_multiplier = mult_ladder[idx]
        pot_payout = int(game.wager * game.current_multiplier)

        if game.streak >= 6:
            game.status = "CASHED_OUT"
            game.points_delta = pot_payout - game.wager
            self.add_points(user_id, pot_payout, "HIGHLOW_MAX_WIN", f"Hit max 6-card streak on High-Low! ({game.current_multiplier}x)")
            game.new_balance = self.get_balance(user_id)
            game.message = f"👑 MAXIMUM 6-STREAK HIT! Auto cashed out for **+{game.points_delta:,} pts** ({pot_payout:,} pts total)!"
            self._active_highlow.pop(user_id, None)
        else:
            game.status = "WON_ROUND"
            game.message = (
                f"✅ Drawn **{next_c}** (Value {new_val})! Streak: **{game.streak}** 🔥\n"
                f"Current Multiplier: **{game.current_multiplier:.1f}x** (Current Cashout: **{pot_payout:,} pts**)\n"
                "Guess again or Cash Out now!"
            )

        return game

    def cashout_highlow(self, user_id: int) -> HighLowGame:
        """Cash out current High-Low multiplier winnings."""
        game = self._active_highlow.get(user_id)
        if not game or game.status not in ("IN_PROGRESS", "WON_ROUND"):
            raise RewardsError("You don't have an active High-Low game to cash out!")

        if game.streak == 0:
            raise RewardsError("You need at least 1 correct guess before you can cash out!")

        payout = int(game.wager * game.current_multiplier)
        game.status = "CASHED_OUT"
        game.points_delta = payout - game.wager
        self.add_points(user_id, payout, "HIGHLOW_CASHOUT", f"Cashed out {game.streak}-streak at {game.current_multiplier}x")
        game.new_balance = self.get_balance(user_id)
        game.message = f"💰 Cashed out **{payout:,} Uno Points** (Net Profit: **+{game.points_delta:,} pts**)!"
        self._active_highlow.pop(user_id, None)
        return game

    def execute_work(
        self,
        user_id: int,
        now: Optional[datetime] = None,
        fixed_job_index: Optional[int] = None,
    ) -> WorkResult:
        """Work an odd job on campus (1-hour cooldown). Earns 40–120 pts + random chance of skill item."""
        current_time = now or datetime.now(timezone.utc)
        user = self.get_or_create_user(user_id)

        COOLDOWN_SECONDS = 3600  # 1 hour
        if user.last_work_time:
            try:
                last_w = datetime.fromisoformat(user.last_work_time)
                if last_w.tzinfo is None:
                    last_w = last_w.replace(tzinfo=timezone.utc)
                diff = (current_time - last_w).total_seconds()
                if diff < COOLDOWN_SECONDS:
                    rem = int(COOLDOWN_SECONDS - diff)
                    mins, secs = divmod(rem, 60)
                    raise RewardsError(f"⏳ You're exhausted from your last shift! Rest for **{mins}m {secs}s**.")
            except ValueError:
                pass

        job = WORK_JOBS[fixed_job_index if fixed_job_index is not None and 0 <= fixed_job_index < len(WORK_JOBS) else random.randint(0, len(WORK_JOBS) - 1)]
        earned = random.randint(job["min_pts"], job["max_pts"])

        bonus_item_name = None
        if random.random() < 0.25:
            skill_keys = ["pickpocket", "shield_1w", "double_daily", "uno_reverse", "gacha_box", "coffee_bribe"]
            chosen_skill = random.choice(skill_keys)
            self.add_item(user_id, chosen_skill, 1)
            bonus_item_name = ITEM_DEFINITIONS[chosen_skill]["name"]

        new_balance = user.points + earned
        new_lifetime = user.lifetime_points + earned

        with self._get_connection() as conn:
            conn.execute(
                "UPDATE users SET points = ?, lifetime_points = ?, last_work_time = ? WHERE user_id = ?",
                (new_balance, new_lifetime, current_time.isoformat(), user_id),
            )
            act_desc = f"Work: {job['title']} (+{earned} pts)"
            if bonus_item_name:
                act_desc += f" + Bonus Item {bonus_item_name}"
            conn.execute(
                "INSERT INTO transactions (user_id, amount, action_type, description) VALUES (?, ?, 'WORK', ?)",
                (user_id, earned, act_desc),
            )
            conn.commit()

        return WorkResult(
            job_title=job["title"],
            company_or_prof=job["company"],
            description=job["desc"],
            points_earned=earned,
            bonus_item_name=bonus_item_name,
            new_balance=new_balance,
        )

    def execute_scavenge(
        self,
        user_id: int,
        now: Optional[datetime] = None,
        fixed_location_index: Optional[int] = None,
    ) -> ScavengeResult:
        """Scavenge around campus for pocket change (30-min cooldown). Earns 10–40 pts."""
        current_time = now or datetime.now(timezone.utc)
        user = self.get_or_create_user(user_id)

        COOLDOWN_SECONDS = 1800  # 30 mins
        if user.last_scavenge_time:
            try:
                last_s = datetime.fromisoformat(user.last_scavenge_time)
                if last_s.tzinfo is None:
                    last_s = last_s.replace(tzinfo=timezone.utc)
                diff = (current_time - last_s).total_seconds()
                if diff < COOLDOWN_SECONDS:
                    rem = int(COOLDOWN_SECONDS - diff)
                    mins, secs = divmod(rem, 60)
                    raise RewardsError(f"⏳ Nothing left to scavenge nearby! Wait **{mins}m {secs}s**.")
            except ValueError:
                pass

        loc = SCAVENGE_LOCATIONS[fixed_location_index if fixed_location_index is not None and 0 <= fixed_location_index < len(SCAVENGE_LOCATIONS) else random.randint(0, len(SCAVENGE_LOCATIONS) - 1)]
        earned = random.randint(loc["min_pts"], loc["max_pts"])

        new_balance = user.points + earned
        new_lifetime = user.lifetime_points + earned

        with self._get_connection() as conn:
            conn.execute(
                "UPDATE users SET points = ?, lifetime_points = ?, last_scavenge_time = ? WHERE user_id = ?",
                (new_balance, new_lifetime, current_time.isoformat(), user_id),
            )
            act_desc = f"Scavenge: {loc['location']} (+{earned} pts)"
            conn.execute(
                "INSERT INTO transactions (user_id, amount, action_type, description) VALUES (?, ?, 'SCAVENGE', ?)",
                (user_id, earned, act_desc),
            )
            conn.commit()

        return ScavengeResult(
            location=loc["location"],
            description=loc["desc"],
            points_earned=earned,
            new_balance=new_balance,
        )

    # ==================== BOUNTY SYSTEM ====================

    def place_bounty(self, creator_id: int, target_id: int, amount: int) -> dict:
        """Place a wanted bounty on a student."""
        if creator_id == target_id:
            raise RewardsError("You cannot place a bounty on yourself!")
        if amount < 50:
            raise RewardsError("Minimum bounty placement is 50 Uno Points!")

        creator = self.get_or_create_user(creator_id)
        if creator.points < amount:
            raise InsufficientPointsError(f"You need at least {amount:,} pts to place this bounty (you have {creator.points:,} pts)!")

        self.deduct_points(creator_id, amount, "BOUNTY_PLACED", f"Placed {amount:,} pts bounty on user {target_id}")

        with self._get_connection() as conn:
            cursor = conn.execute(
                "INSERT INTO bounties (target_id, creator_id, amount, is_claimed) VALUES (?, ?, ?, 0)",
                (target_id, creator_id, amount),
            )
            b_id = cursor.lastrowid
            total_pool = conn.execute(
                "SELECT COALESCE(SUM(amount), 0) as total FROM bounties WHERE target_id = ? AND is_claimed = 0",
                (target_id,),
            ).fetchone()["total"]
            conn.commit()

        return {
            "bounty_id": b_id,
            "creator_id": creator_id,
            "target_id": target_id,
            "amount": amount,
            "total_pool": total_pool,
        }

    def get_active_bounties(self, target_id: Optional[int] = None) -> list[BountyRecord]:
        """Fetch uncompleted bounties, optionally filtered by target."""
        with self._get_connection() as conn:
            if target_id is not None:
                rows = conn.execute(
                    "SELECT * FROM bounties WHERE target_id = ? AND is_claimed = 0 ORDER BY id DESC",
                    (target_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM bounties WHERE is_claimed = 0 ORDER BY id DESC"
                ).fetchall()

            return [
                BountyRecord(
                    id=r["id"],
                    target_id=r["target_id"],
                    creator_id=r["creator_id"],
                    amount=r["amount"],
                    is_claimed=bool(r["is_claimed"]),
                    claimed_by=r["claimed_by"],
                    created_at=r["created_at"],
                )
                for r in rows
            ]

    def get_bounty_board(self) -> list[dict]:
        """Fetch aggregated wanted board with total bounty pools per target."""
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT target_id, SUM(amount) as total_bounty, COUNT(*) as bounty_count
                FROM bounties
                WHERE is_claimed = 0
                GROUP BY target_id
                ORDER BY total_bounty DESC
                LIMIT 10
                """
            ).fetchall()
            return [
                {
                    "target_id": r["target_id"],
                    "total_bounty": r["total_bounty"],
                    "bounty_count": r["bounty_count"],
                }
                for r in rows
            ]

    def claim_bounties_on_target(self, winner_id: int, target_id: int) -> int:
        """Claim all open bounties on target user and award them to the winner."""
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(amount), 0) as total FROM bounties WHERE target_id = ? AND is_claimed = 0",
                (target_id,),
            ).fetchone()
            total_bounty = row["total"] if row else 0

            if total_bounty > 0:
                conn.execute(
                    "UPDATE bounties SET is_claimed = 1, claimed_by = ? WHERE target_id = ? AND is_claimed = 0",
                    (winner_id, target_id),
                )
                conn.execute(
                    "UPDATE users SET bounties_claimed = bounties_claimed + 1 WHERE user_id = ?",
                    (winner_id,),
                )
                conn.commit()

        if total_bounty > 0:
            self.add_points(winner_id, total_bounty, "BOUNTY_CLAIM", f"Claimed wanted bounty on user {target_id}")

        return total_bounty

    def record_duel_outcome(self, winner_id: Optional[int], loser_id: Optional[int]) -> None:
        """Update PvP win/loss counters and win streaks."""
        with self._get_connection() as conn:
            if winner_id is not None:
                conn.execute(
                    "UPDATE users SET duel_wins = duel_wins + 1, duel_streak = duel_streak + 1 WHERE user_id = ?",
                    (winner_id,),
                )
            if loser_id is not None:
                conn.execute(
                    "UPDATE users SET duel_losses = duel_losses + 1, duel_streak = 0 WHERE user_id = ?",
                    (loser_id,),
                )
            conn.commit()

    def _apply_pet_duel_modifiers(self, player_id: int, opponent_id: int, initial_roll: int) -> tuple[int, Optional[str]]:
        """Apply active pet perks to a player's duel roll."""
        pet = self.get_active_pet(player_id)
        opp_pet = self.get_active_pet(opponent_id)
        final_roll = initial_roll
        perk_msg = None

        # 1. Bunny: Lucky Reroll if under 30
        if pet and pet.species == "bunny" and final_roll < 30:
            final_roll = random.randint(35, 100)
            perk_msg = f"🐰 **{pet.nickname}**'s *Lucky Reroll* boosted roll to **{final_roll}**!"

        # 2. Opponent Dog: Intimidating Bark (20% chance to reduce final roll by 15)
        if opp_pet and opp_pet.species == "dog" and random.random() < 0.20:
            final_roll = max(1, final_roll - 15)
            bark_txt = f"🐶 Opponent's **{opp_pet.nickname}** barked fiercely (-15 to roll)!"
            perk_msg = f"{perk_msg} | {bark_txt}" if perk_msg else bark_txt

        return final_roll, perk_msg

    def _check_fox_siphon(self, loser_id: int, wager: int) -> tuple[int, Optional[str]]:
        """Fox perk: 25% chance on loss to sneakily siphon back 20% of lost wager."""
        pet = self.get_active_pet(loser_id)
        if pet and pet.species == "fox" and random.random() < 0.25:
            siphon = max(1, int(wager * 0.20))
            self.add_points(loser_id, siphon, "PET_PERK", f"{pet.nickname} Fox Siphon refund")
            return siphon, f"🦊 **{pet.nickname}** sneakily siphoned back **{siphon:,} pts** ({pet.perk_title})!"
        return 0, None

    # ==================== DUEL GAME MODES ====================

    def resolve_duel(
        self,
        challenger_id: int,
        target_id: int,
        wager: int,
        fixed_c_roll: Optional[int] = None,
        fixed_t_roll: Optional[int] = None,
    ) -> DuelResult:
        """Resolve a 1v1 PvP dice roll duel between two students."""
        if challenger_id == target_id:
            raise RewardsError("You cannot duel yourself!")

        if wager < 10:
            raise RewardsError("Minimum duel wager is 10 Uno Points!")
        if wager > 200:
            raise RewardsError("Maximum duel wager is 200 Uno Points!")

        c_user = self.get_or_create_user(challenger_id)
        t_user = self.get_or_create_user(target_id)

        if c_user.points < wager:
            raise InsufficientPointsError(f"Challenger needs at least {wager:,} pts (has {c_user.points:,} pts)!")
        if t_user.points < wager:
            raise InsufficientPointsError(f"Target needs at least {wager:,} pts (has {t_user.points:,} pts)!")

        # Deduct wager from both
        self.deduct_points(challenger_id, wager, "DUEL_WAGER", f"1v1 Duel wager against user {target_id}")
        self.deduct_points(target_id, wager, "DUEL_WAGER", f"1v1 Duel wager against user {challenger_id}")

        c_roll = fixed_c_roll or random.randint(1, 100)
        t_roll = fixed_t_roll or random.randint(1, 100)

        # Pet perks for dice duel
        c_perk_msg = None
        t_perk_msg = None
        if fixed_c_roll is None and fixed_t_roll is None:
            c_roll, c_perk_msg = self._apply_pet_duel_modifiers(challenger_id, target_id, c_roll)
            t_roll, t_perk_msg = self._apply_pet_duel_modifiers(target_id, challenger_id, t_roll)

            # Owl clutch bonus: if rolls are within 5 points, Owl owner gains +10!
            c_pet = self.get_active_pet(challenger_id)
            t_pet = self.get_active_pet(target_id)
            if c_pet and c_pet.species == "owl" and abs(c_roll - t_roll) <= 5:
                c_roll += 10
                c_perk_msg = (c_perk_msg or "") + f" 🦉 **{c_pet.nickname}** calculated clutch (+10 roll)!"
            elif t_pet and t_pet.species == "owl" and abs(c_roll - t_roll) <= 5:
                t_roll += 10
                t_perk_msg = (t_perk_msg or "") + f" 🦉 **{t_pet.nickname}** calculated clutch (+10 roll)!"

        while c_roll == t_roll and fixed_c_roll is None and fixed_t_roll is None:
            c_roll = random.randint(1, 100)
            t_roll = random.randint(1, 100)

        total_pot = int(wager * 1.95)  # 5% server burn to eliminate collusion / alt point farming
        is_tie = (c_roll == t_roll)
        bounty_won = 0
        siphoned_amount = 0

        if is_tie:
            self.add_points(challenger_id, wager, "DUEL_REFUND", "Duel tie refund")
            self.add_points(target_id, wager, "DUEL_REFUND", "Duel tie refund")
            winner_id = None
            pot_won = wager
        elif c_roll > t_roll:
            winner_id = challenger_id
            self.add_points(challenger_id, total_pot, "DUEL_WIN", f"Won 1v1 Duel against user {target_id}")
            pot_won = total_pot
            bounty_won = self.claim_bounties_on_target(challenger_id, target_id)
            self.record_duel_outcome(challenger_id, target_id)
            siphoned_amount, fox_msg = self._check_fox_siphon(target_id, wager)
            if fox_msg:
                t_perk_msg = (t_perk_msg or "") + f" {fox_msg}"
        else:
            winner_id = target_id
            self.add_points(target_id, total_pot, "DUEL_WIN", f"Won 1v1 Duel against user {challenger_id}")
            pot_won = total_pot
            bounty_won = self.claim_bounties_on_target(target_id, challenger_id)
            self.record_duel_outcome(target_id, challenger_id)
            siphoned_amount, fox_msg = self._check_fox_siphon(challenger_id, wager)
            if fox_msg:
                c_perk_msg = (c_perk_msg or "") + f" {fox_msg}"

        perk_combined = " | ".join(filter(None, [c_perk_msg, t_perk_msg])) or None

        return DuelResult(
            challenger_id=challenger_id,
            target_id=target_id,
            wager=wager,
            challenger_roll=c_roll,
            target_roll=t_roll,
            winner_id=winner_id,
            pot_won=pot_won,
            is_tie=is_tie,
            bounty_won=bounty_won,
            pet_perk_activated=perk_combined,
            siphoned_amount=siphoned_amount,
            mode="dice",
        )

    def resolve_rps_duel(
        self,
        challenger_id: int,
        target_id: int,
        c_choice: str,
        t_choice: str,
        wager: int,
    ) -> RPSDuelGame:
        """Resolve RPS duel (rock beats scissors, scissors beats paper, paper beats rock)."""
        valid = {"rock": "🪨 Rock", "paper": "📄 Paper", "scissors": "✂️ Scissors"}
        c_c = c_choice.lower().strip()
        t_c = t_choice.lower().strip()
        if c_c not in valid or t_c not in valid:
            raise RewardsError("Invalid RPS choice! Must be rock, paper, or scissors.")

        c_user = self.get_or_create_user(challenger_id)
        t_user = self.get_or_create_user(target_id)
        if c_user.points < wager:
            raise InsufficientPointsError("Challenger does not have enough points!")
        if t_user.points < wager:
            raise InsufficientPointsError("Target does not have enough points!")

        self.deduct_points(challenger_id, wager, "DUEL_WAGER", f"RPS Duel against {target_id}")
        self.deduct_points(target_id, wager, "DUEL_WAGER", f"RPS Duel against {challenger_id}")

        total_pot = wager * 2
        bounty_won = 0
        siphoned_amount = 0
        perk_msg = None

        if c_c == t_c:
            self.add_points(challenger_id, wager, "DUEL_REFUND", "RPS tie refund")
            self.add_points(target_id, wager, "DUEL_REFUND", "RPS tie refund")
            winner_id = None
            loser_id = None
            is_tie = True
            pot_won = wager
        elif (c_c == "rock" and t_c == "scissors") or (c_c == "paper" and t_c == "rock") or (c_c == "scissors" and t_c == "paper"):
            winner_id = challenger_id
            loser_id = target_id
            is_tie = False
            self.add_points(challenger_id, total_pot, "DUEL_WIN", f"Won RPS Duel against {target_id}")
            pot_won = total_pot
            bounty_won = self.claim_bounties_on_target(challenger_id, target_id)
            self.record_duel_outcome(challenger_id, target_id)
            siphoned_amount, perk_msg = self._check_fox_siphon(target_id, wager)
        else:
            winner_id = target_id
            loser_id = challenger_id
            is_tie = False
            self.add_points(target_id, total_pot, "DUEL_WIN", f"Won RPS Duel against {challenger_id}")
            pot_won = total_pot
            bounty_won = self.claim_bounties_on_target(target_id, challenger_id)
            self.record_duel_outcome(target_id, challenger_id)
            siphoned_amount, perk_msg = self._check_fox_siphon(challenger_id, wager)

        return RPSDuelGame(
            challenger_id=challenger_id,
            target_id=target_id,
            wager=wager,
            challenger_choice=valid[c_c],
            target_choice=valid[t_c],
            winner_id=winner_id,
            loser_id=loser_id,
            is_tie=is_tie,
            is_over=True,
            pot_won=pot_won,
            bounty_won=bounty_won,
            siphoned_amount=siphoned_amount,
            perk_msg=perk_msg,
        )

    def start_roulette_game(self, challenger_id: int, target_id: int, wager: int) -> RouletteDuelGame:
        """Start a 6-card Uno Russian Roulette duel."""
        c_user = self.get_or_create_user(challenger_id)
        t_user = self.get_or_create_user(target_id)
        if c_user.points < wager:
            raise InsufficientPointsError("Challenger does not have enough points!")
        if t_user.points < wager:
            raise InsufficientPointsError("Target does not have enough points!")

        self.deduct_points(challenger_id, wager, "DUEL_WAGER", f"Roulette Duel against {target_id}")
        self.deduct_points(target_id, wager, "DUEL_WAGER", f"Roulette Duel against {challenger_id}")

        chamber = [False] * 6
        bomb_pos = random.randint(0, 5)
        chamber[bomb_pos] = True

        game_key = f"{min(challenger_id, target_id)}_{max(challenger_id, target_id)}"
        game = RouletteDuelGame(
            challenger_id=challenger_id,
            target_id=target_id,
            wager=wager,
            current_turn_id=challenger_id,
            chamber=chamber,
            current_index=0,
            is_over=False,
            exploded=False,
        )
        self._active_roulette[game_key] = game
        return game

    def pull_roulette_trigger(self, player_id: int, opponent_id: int) -> RouletteDuelGame:
        """Pull the trigger in an active Russian Roulette duel."""
        game_key = f"{min(player_id, opponent_id)}_{max(player_id, opponent_id)}"
        if game_key not in self._active_roulette:
            raise RewardsError("No active roulette game found between these players!")

        game = self._active_roulette[game_key]
        if game.is_over:
            raise RewardsError("This roulette game has already ended!")
        if game.current_turn_id != player_id:
            raise RewardsError("It is not your turn to draw!")

        is_bomb = game.chamber[game.current_index]
        game.current_index += 1

        if is_bomb:
            game.is_over = True
            game.exploded = True
            game.loser_id = player_id
            game.winner_id = opponent_id
            total_pot = game.wager * 2
            game.pot_won = total_pot

            self.add_points(opponent_id, total_pot, "DUEL_WIN", f"Won Roulette Duel against {player_id}")
            game.bounty_won = self.claim_bounties_on_target(opponent_id, player_id)
            self.record_duel_outcome(opponent_id, player_id)
            game.siphoned_amount, game.perk_msg = self._check_fox_siphon(player_id, game.wager)
            self._active_roulette.pop(game_key, None)
        else:
            # Switch turn
            game.current_turn_id = opponent_id

        return game

    def start_rpg_game(self, challenger_id: int, target_id: int, wager: int) -> RPGCombatGame:
        """Start a 100 HP Turn-Based RPG Duel."""
        c_user = self.get_or_create_user(challenger_id)
        t_user = self.get_or_create_user(target_id)
        if c_user.points < wager:
            raise InsufficientPointsError("Challenger does not have enough points!")
        if t_user.points < wager:
            raise InsufficientPointsError("Target does not have enough points!")

        self.deduct_points(challenger_id, wager, "DUEL_WAGER", f"RPG Duel against {target_id}")
        self.deduct_points(target_id, wager, "DUEL_WAGER", f"RPG Duel against {challenger_id}")

        game_key = f"{min(challenger_id, target_id)}_{max(challenger_id, target_id)}"
        game = RPGCombatGame(
            challenger_id=challenger_id,
            target_id=target_id,
            wager=wager,
            c_hp=100,
            t_hp=100,
            turn_number=1,
        )
        self._active_rpg[game_key] = game
        return game

    def submit_rpg_action(self, player_id: int, opponent_id: int, action: str) -> RPGCombatGame:
        """Submit a combat action ('strike', 'block', 'ultimate') for an RPG duel round."""
        game_key = f"{min(player_id, opponent_id)}_{max(player_id, opponent_id)}"
        if game_key not in self._active_rpg:
            raise RewardsError("No active RPG duel found!")

        game = self._active_rpg[game_key]
        if game.is_over:
            raise RewardsError("This RPG duel is already finished!")

        if action not in ("strike", "block", "ultimate"):
            raise RewardsError("Invalid combat action!")

        if player_id == game.challenger_id:
            game.c_action = action
        elif player_id == game.target_id:
            game.t_action = action

        # If both players submitted, resolve the round!
        if game.c_action is not None and game.t_action is not None:
            logs = []
            c_act = game.c_action
            t_act = game.t_action

            # Resolve Challenger attack
            c_dmg = 0
            if c_act == "strike":
                c_dmg = random.randint(20, 35)
            elif c_act == "ultimate":
                hit_rate = 0.65 if (self.get_active_pet(game.challenger_id) and self.get_active_pet(game.challenger_id).species == "bunny") else 0.50
                if random.random() < hit_rate:
                    c_dmg = random.randint(50, 65)
                    logs.append("⚡ **Challenger Landed Critical Ultimate!**")
                else:
                    logs.append("💨 **Challenger Ultimate Missed!**")

            # Resolve Target attack
            t_dmg = 0
            if t_act == "strike":
                t_dmg = random.randint(20, 35)
            elif t_act == "ultimate":
                hit_rate = 0.65 if (self.get_active_pet(game.target_id) and self.get_active_pet(game.target_id).species == "bunny") else 0.50
                if random.random() < hit_rate:
                    t_dmg = random.randint(50, 65)
                    logs.append("⚡ **Target Landed Critical Ultimate!**")
                else:
                    logs.append("💨 **Target Ultimate Missed!**")

            # Apply Blocks & Parries
            if t_act == "block":
                c_dmg = int(c_dmg * 0.30)
                t_dmg += 10
                logs.append("🛡️ **Target Parried!** (Reduced incoming damage & reflected 10 DMG)")
            if c_act == "block":
                t_dmg = int(t_dmg * 0.30)
                c_dmg += 10
                logs.append("🛡️ **Challenger Parried!** (Reduced incoming damage & reflected 10 DMG)")

            game.t_hp = max(0, game.t_hp - c_dmg)
            game.c_hp = max(0, game.c_hp - t_dmg)
            logs.append(f"⚔️ **Round {game.turn_number}**: Challenger dealt **{c_dmg} DMG** | Target dealt **{t_dmg} DMG**")

            game.last_round_log = logs
            game.turn_number += 1
            game.c_action = None
            game.t_action = None

            # Check win conditions
            if game.c_hp <= 0 or game.t_hp <= 0:
                game.is_over = True
                total_pot = game.wager * 2
                game.pot_won = total_pot

                if game.c_hp > game.t_hp:
                    game.winner_id = game.challenger_id
                    game.loser_id = game.target_id
                    self.add_points(game.challenger_id, total_pot, "DUEL_WIN", f"Won RPG Duel against {game.target_id}")
                    game.bounty_won = self.claim_bounties_on_target(game.challenger_id, game.target_id)
                    self.record_duel_outcome(game.challenger_id, game.target_id)
                    game.siphoned_amount, game.perk_msg = self._check_fox_siphon(game.target_id, game.wager)
                elif game.t_hp > game.c_hp:
                    game.winner_id = game.target_id
                    game.loser_id = game.challenger_id
                    self.add_points(game.target_id, total_pot, "DUEL_WIN", f"Won RPG Duel against {game.challenger_id}")
                    game.bounty_won = self.claim_bounties_on_target(game.target_id, game.challenger_id)
                    self.record_duel_outcome(game.target_id, game.challenger_id)
                    game.siphoned_amount, game.perk_msg = self._check_fox_siphon(game.challenger_id, game.wager)
                else:
                    # Mutual KO tie refund
                    self.add_points(game.challenger_id, game.wager, "DUEL_REFUND", "RPG Tie refund")
                    self.add_points(game.target_id, game.wager, "DUEL_REFUND", "RPG Tie refund")
                    game.winner_id = None
                    game.loser_id = None
                    game.pot_won = game.wager

                self._active_rpg.pop(game_key, None)

        return game

    def bank_deposit(self, user_id: int, amount: int) -> dict:
        """Deposit wallet points into protected campus bank vault (10% banking fee)."""
        if amount <= 0:
            raise RewardsError("Deposit amount must be greater than 0!")

        user = self.get_or_create_user(user_id)
        if user.points < amount:
            raise InsufficientPointsError(
                f"You only have {user.points:,} pts in your wallet to deposit!"
            )

        fee = max(1, int(amount * 0.10))
        credited = amount - fee
        new_wallet = user.points - amount
        new_bank = user.bank_points + credited

        with self._get_connection() as conn:
            conn.execute(
                "UPDATE users SET points = ?, bank_points = ? WHERE user_id = ?",
                (new_wallet, new_bank, user_id),
            )
            conn.execute(
                "INSERT INTO transactions (user_id, amount, action_type, description) VALUES (?, ?, 'BANK_DEPOSIT', ?)",
                (user_id, -fee, f"Deposited {amount:,} pts into Piggy Bank (10% Fee: {fee:,} pts, Credited: {credited:,} pts)"),
            )
            conn.commit()

        return {
            "amount_deposited": amount,
            "fee": fee,
            "amount_credited": credited,
            "new_wallet": new_wallet,
            "new_bank": new_bank,
        }

    def bank_withdraw(self, user_id: int, amount: int) -> dict:
        """Withdraw points from bank vault into wallet (10% withdrawal fee)."""
        if amount <= 0:
            raise RewardsError("Withdrawal amount must be greater than 0!")

        user = self.get_or_create_user(user_id)
        if user.bank_points < amount:
            raise InsufficientPointsError(
                f"You only have {user.bank_points:,} pts in your bank account to withdraw!"
            )

        fee = max(1, int(amount * 0.10))
        credited = amount - fee
        new_bank = user.bank_points - amount
        new_wallet = user.points + credited

        with self._get_connection() as conn:
            conn.execute(
                "UPDATE users SET points = ?, bank_points = ? WHERE user_id = ?",
                (new_wallet, new_bank, user_id),
            )
            conn.execute(
                "INSERT INTO transactions (user_id, amount, action_type, description) VALUES (?, ?, 'BANK_WITHDRAW', ?)",
                (user_id, -fee, f"Withdrew {amount:,} pts from Piggy Bank (10% Fee: {fee:,} pts, Received: {credited:,} pts)"),
            )
            conn.commit()

        return {
            "amount_withdrawn": amount,
            "fee": fee,
            "amount_credited": credited,
            "new_wallet": new_wallet,
            "new_bank": new_bank,
        }

    def collect_daily_tax(self, user_id: int, now: Optional[datetime] = None) -> Optional[dict]:
        """Collect 24-hr wealth tax: 8% on assets, or 10% for wealthy accounts (1k+ pts)."""
        current_time = now or datetime.now(PHT)
        if current_time.tzinfo is None:
            current_time = current_time.replace(tzinfo=PHT)
        else:
            current_time = current_time.astimezone(PHT)
        today_str = current_time.strftime("%Y-%m-%d")

        user = self.get_or_create_user(user_id)
        if user.last_tax_collection == today_str:
            return None

        total_assets = user.points + user.bank_points
        if total_assets < 10:
            with self._get_connection() as conn:
                conn.execute(
                    "UPDATE users SET last_tax_collection = ? WHERE user_id = ?",
                    (today_str, user_id),
                )
                conn.commit()
            return None

        tax_rate = 0.10 if total_assets >= 1000 else 0.08
        tax_amount = max(1, int(total_assets * tax_rate))

        # Deduct from wallet first, then bank
        new_wallet = max(0, user.points - tax_amount)
        wallet_deducted = user.points - new_wallet
        remaining_tax = tax_amount - wallet_deducted
        new_bank = max(0, user.bank_points - remaining_tax)

        with self._get_connection() as conn:
            conn.execute(
                """
                UPDATE users
                SET points = ?,
                    bank_points = ?,
                    last_tax_collection = ?
                WHERE user_id = ?
                """,
                (new_wallet, new_bank, today_str, user_id),
            )
            conn.execute(
                """
                INSERT INTO transactions (user_id, amount, action_type, description)
                VALUES (?, ?, 'TAX', ?)
                """,
                (user_id, -tax_amount, f"Daily Wealth Tax ({int(tax_rate * 100)}% on {total_assets:,} pts net worth)"),
            )
            conn.commit()

        return {
            "user_id": user_id,
            "tax_rate": tax_rate,
            "total_assets": total_assets,
            "tax_amount": tax_amount,
            "new_wallet": new_wallet,
            "new_bank": new_bank,
        }

    def collect_all_pending_taxes(self, now: Optional[datetime] = None) -> list[dict]:
        """Collect taxes from all users eligible for 24-hr tax collection."""
        current_time = now or datetime.now(PHT)
        if current_time.tzinfo is None:
            current_time = current_time.replace(tzinfo=PHT)
        else:
            current_time = current_time.astimezone(PHT)
        today_str = current_time.strftime("%Y-%m-%d")

        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT user_id FROM users
                WHERE (last_tax_collection IS NULL OR last_tax_collection != ?)
                  AND (points + bank_points) >= 10
                """,
                (today_str,),
            ).fetchall()

        results = []
        for r in rows:
            res = self.collect_daily_tax(r["user_id"], now=current_time)
            if res:
                results.append(res)
        return results

    def execute_steal(
        self,
        thief_id: int,
        target_id: int,
        now: Optional[datetime] = None,
        fixed_success: Optional[bool] = None,
        fixed_amount: Optional[int] = None,
    ) -> StealResult:
        """Attempt to steal 40-60% of target points using a Pickpocket Card (checked against target shield, dog guard, and Uno Reverse)."""
        if thief_id == target_id:
            raise RewardsError("You cannot pickpocket yourself!")

        target = self.get_or_create_user(target_id)
        if target.points < 20:
            raise RewardsError(f"That classmate only has {target.points} pts. They're too broke to steal from (< 20 pts)!")

        # Consume pickpocket card
        self.remove_item(thief_id, "pickpocket", 1)

        # Check target Uno Reverse Card (passive counter-trap!)
        target_inv = self.get_inventory(target_id)
        if target_inv.get("uno_reverse", 0) > 0:
            self.remove_item(target_id, "uno_reverse", 1)
            thief = self.get_or_create_user(thief_id)
            rev_pct = random.uniform(0.15, 0.30)
            calc_counter = min(120, int(thief.points * rev_pct))
            counter_stolen = min(thief.points, max(10, calc_counter))
            if counter_stolen > 0:
                thief_new = self.deduct_points(thief_id, counter_stolen, "UNO_REVERSE_LOST", f"Counter-stolen by user {target_id}")
                target_new = self.add_points(target_id, counter_stolen, "UNO_REVERSE_WON", f"Uno Reverse counter-steal from user {thief_id}")
            else:
                thief_new = thief.points
                target_new = target.points
            return StealResult(
                success=False,
                blocked_by_shield=False,
                points_stolen=counter_stolen,
                fine_paid=0,
                thief_new_balance=thief_new,
                target_new_balance=target_new,
                reversed_by_uno=True,
            )

        # Check target immunity shield
        if self.has_active_shield(target_id, now=now):
            thief = self.get_or_create_user(thief_id)
            return StealResult(
                success=False,
                blocked_by_shield=True,
                points_stolen=0,
                fine_paid=0,
                thief_new_balance=thief.points,
                target_new_balance=target.points,
                reversed_by_uno=False,
            )

        # Check pet perks: Fox increases steal success, Dog dramatically increases bust chance
        thief_pet = self.get_active_pet(thief_id)
        target_pet = self.get_active_pet(target_id)

        success_rate = 0.60
        if thief_pet and thief_pet.species == "fox":
            success_rate += 0.15

        if target_pet and target_pet.species == "dog":
            success_rate = min(success_rate, 0.25)  # Dog guard catches thieves 75% of the time!

        is_success = fixed_success if fixed_success is not None else (random.random() < success_rate)

        if is_success:
            pct = random.uniform(0.15, 0.30)
            calc_stolen = min(120, int(target.points * pct))
            stolen = fixed_amount if fixed_amount is not None else max(10, calc_stolen)
            stolen = min(stolen, target.points)

            target_new = self.deduct_points(target_id, stolen, "STEAL_VICTIM", f"Stolen by user {thief_id}")
            thief_new = self.add_points(thief_id, stolen, "STEAL_SUCCESS", f"Stolen from user {target_id}")

            return StealResult(
                success=True,
                blocked_by_shield=False,
                points_stolen=stolen,
                fine_paid=0,
                thief_new_balance=thief_new,
                target_new_balance=target_new,
                reversed_by_uno=False,
            )
        else:
            # Thief caught red-handed!
            thief = self.get_or_create_user(thief_id)
            base_fine = 30
            if target_pet and target_pet.species == "dog":
                base_fine = 50  # Extra dog bite fine!
            fine = min(base_fine, thief.points)
            if fine > 0:
                thief_new = self.deduct_points(thief_id, fine, "STEAL_FINE", f"Caught stealing from user {target_id}")
                target_new = self.add_points(target_id, fine, "STEAL_COMPENSATION", f"Compensation from caught thief {thief_id}")
            else:
                thief_new = thief.points
                target_new = target.points

            return StealResult(
                success=False,
                blocked_by_shield=False,
                points_stolen=0,
                fine_paid=fine,
                thief_new_balance=thief_new,
                target_new_balance=target_new,
                reversed_by_uno=False,
            )

    def use_item(
        self,
        user_id: int,
        item_id: str,
        target_id: Optional[int] = None,
        now: Optional[datetime] = None,
    ) -> UseItemResult:
        """Consume and activate an item from user's inventory."""
        if item_id not in ITEM_DEFINITIONS or not ITEM_DEFINITIONS[item_id]["usable"]:
            raise RewardsError(f"Item '{item_id}' cannot be activated directly.")

        user = self.get_or_create_user(user_id)
        shield_until = None
        points_awarded = 0
        points_deducted = 0
        bonus_item_name = None
        gacha_tier = None
        new_balance = user.points

        if item_id == "shield_1w":
            self.remove_item(user_id, item_id, 1)
            shield_until = self.activate_shield(user_id, duration_days=7, now=now)
            desc = f"Activated 7-Day Immunity Shield! Protected until <t:{int(shield_until.timestamp())}:f>."

        elif item_id == "double_daily":
            self.remove_item(user_id, item_id, 1)
            desc = "Activated 2x Daily Booster! Your next `/daily` claim will reward double points."

        elif item_id == "streak_bandage":
            self.remove_item(user_id, item_id, 1)
            desc = "Applied Streak Bandage! Your daily streak is safe."

        elif item_id == "shield_breaker":
            if not target_id:
                raise RewardsError("You must specify a target classmate with `/use shield_breaker @classmate`!")
            if target_id == user_id:
                raise RewardsError("You cannot break your own shield!")
            if not self.has_active_shield(target_id, now=now):
                raise RewardsError("That classmate does not have an active Immunity Shield to break!")

            self.remove_item(user_id, item_id, 1)
            with self._get_connection() as conn:
                conn.execute("UPDATE users SET shield_until = NULL WHERE user_id = ?", (target_id,))
                conn.commit()
            desc = f"🔨 EMP Shatter! You struck <@{target_id}> with an EMP shockwave and completely destroyed their Immunity Shield!"

        elif item_id == "tax_audit":
            if not target_id:
                raise RewardsError("You must specify a Top-3 classmate to audit with `/use tax_audit @classmate`!")
            if target_id == user_id:
                raise RewardsError("You cannot audit yourself!")
            target_profile = self.get_profile(target_id, now=now)
            if target_profile.rank > 3:
                raise RewardsError(
                    f"That classmate is ranked #{target_profile.rank}. The Class Treasurer Audit can only target students in the Top 3!"
                )
            self.remove_item(user_id, item_id, 1)
            tax_amount = min(max(int(target_profile.points * 0.05), 10), 200)
            self.deduct_points(target_id, tax_amount, "TAX_AUDITED", f"Audited by Class Treasurer {user_id}")
            new_balance = self.add_points(user_id, tax_amount, "TAX_COLLECTED", f"Collected 5% Class Tax from {target_id}")
            points_awarded = tax_amount
            desc = f"🕵️ Class Treasurer Audit executed! You audited a 5% Class Fund Tax (**+{tax_amount:,} Uno Points**) from <@{target_id}>!"

        elif item_id == "coffee_bribe":
            self.remove_item(user_id, item_id, 1)
            bribe_pts = random.randint(50, 120)
            new_balance = self.add_points(user_id, bribe_pts, "COFFEE_BRIBE", "Dean's Coffee Bribe Grant")
            points_awarded = bribe_pts
            desc = f"☕ You treated the CS Faculty to iced coffee and received an academic grant of **+{bribe_pts} Uno Points**!"

        elif item_id == "gacha_box":
            self.remove_item(user_id, item_id, 1)
            roll = random.random()
            if roll < 0.50:
                gacha_tier = "🥉 Common"
                pts = random.randint(30, 60)
                b_item = "pickpocket"
            elif roll < 0.80:
                gacha_tier = "🥈 Rare"
                pts = random.randint(70, 120)
                b_item = "shield_1w"
            elif roll < 0.95:
                gacha_tier = "🥇 Epic"
                pts = random.randint(140, 200)
                b_item = "uno_reverse"
            else:
                gacha_tier = "💎 LEGENDARY"
                pts = 350
                b_item = "uno_reverse"

            self.add_item(user_id, b_item, 1)
            bonus_item_name = ITEM_DEFINITIONS[b_item]["name"]
            new_balance = self.add_points(user_id, pts, "GACHA_BOX", f"Gacha Lootbox {gacha_tier}")
            points_awarded = pts
            desc = (
                f"📦 Opened Mystery Gacha Box!\n"
                f"🌟 Tier: **{gacha_tier}**\n"
                f"💰 Reward: **+{pts:,} Uno Points**\n"
                f"🎁 Bonus Item: **{bonus_item_name}**"
            )

        elif item_id == "airdrop":
            self.remove_item(user_id, item_id, 1)
            desc = "Launched a 100-pt Point Airdrop in the channel!"

        else:
            self.remove_item(user_id, item_id, 1)
            desc = f"Activated {ITEM_DEFINITIONS[item_id]['name']}!"

        return UseItemResult(
            item_id=item_id,
            item_name=ITEM_DEFINITIONS[item_id]["name"],
            description=desc,
            shield_until=shield_until,
            points_awarded=points_awarded,
            points_deducted=points_deducted,
            target_id=target_id,
            bonus_item_name=bonus_item_name,
            gacha_tier=gacha_tier,
            new_balance=new_balance,
        )

    def export_csv(self) -> str:
        """Export users and points to a clean CSV string."""
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT user_id, points, lifetime_points, daily_streak, last_daily_claim, shield_until, created_at
                FROM users
                ORDER BY points DESC
                """
            ).fetchall()

            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(["user_id", "points", "lifetime_points", "daily_streak", "last_daily_claim", "shield_until", "created_at"])
            for r in rows:
                writer.writerow([r["user_id"], r["points"], r["lifetime_points"], r["daily_streak"], r["last_daily_claim"], r["shield_until"], r["created_at"]])
            return output.getvalue()

    def get_random_trivia_question(
        self,
        user_id: Optional[int] = None,
        exclude_index: Optional[int] = None,
    ) -> tuple[int, TriviaQuestion]:
        """Return a random trivia question, tracking per-user history in SQLite to avoid repeats."""
        total_questions = len(TRIVIA_QUESTIONS)
        if total_questions == 0:
            raise RewardsError("No trivia questions available.")

        if user_id is None:
            available_indices = list(range(total_questions))
            if exclude_index is not None and len(available_indices) > 1 and exclude_index in available_indices:
                available_indices.remove(exclude_index)
            chosen_idx = random.choice(available_indices)
            return chosen_idx, TRIVIA_QUESTIONS[chosen_idx]

        with self._get_connection() as conn:
            seen_rows = conn.execute(
                "SELECT question_id FROM user_trivia_history WHERE user_id = ?",
                (user_id,),
            ).fetchall()
            seen_ids = {r["question_id"] for r in seen_rows}

            # If user has seen all questions in the bank, clear history to start fresh cycle
            if len(seen_ids) >= total_questions:
                conn.execute("DELETE FROM user_trivia_history WHERE user_id = ?", (user_id,))
                conn.commit()
                seen_ids = set()

            available_indices = [i for i in range(total_questions) if i not in seen_ids]
            if exclude_index is not None and len(available_indices) > 1 and exclude_index in available_indices:
                available_indices.remove(exclude_index)

            if not available_indices:
                available_indices = list(range(total_questions))

            chosen_idx = random.choice(available_indices)

            # Record seen question into history
            conn.execute(
                "INSERT OR IGNORE INTO user_trivia_history (user_id, question_id) VALUES (?, ?)",
                (user_id, chosen_idx),
            )
            conn.commit()

        return chosen_idx, TRIVIA_QUESTIONS[chosen_idx]

    def record_trivia_attempt(
        self,
        user_id: int,
        is_correct: bool,
        now: Optional[datetime] = None,
    ) -> TriviaResult:
        """Process a trivia answer. If correct, awards +50 pts (or +75 pts and 4 attempts if Scholar Owl pet equipped)."""
        active_pet = self.get_active_pet(user_id)
        is_owl = bool(active_pet and active_pet.species == "owl")
        TRIVIA_REWARD = 40 if is_owl else 25
        MAX_TRIVIA = 4 if is_owl else 3

        current_time = now or datetime.now(PHT)
        if current_time.tzinfo is None:
            current_time = current_time.replace(tzinfo=PHT)
        else:
            current_time = current_time.astimezone(PHT)
        today_str = current_time.strftime("%Y-%m-%d")

        user = self.get_or_create_user(user_id)

        if user.last_trivia_date == today_str and user.daily_trivia_count >= MAX_TRIVIA:
            raise MaxTriviaReachedError(
                f"You have already completed all {MAX_TRIVIA} of your trivia quizzes for today! Come back tomorrow after midnight PHT."
            )

        new_trivia_count = (user.daily_trivia_count + 1) if user.last_trivia_date == today_str else 1
        trivia_remaining = MAX_TRIVIA - new_trivia_count

        points_awarded = TRIVIA_REWARD if is_correct else 0
        new_balance = user.points + points_awarded
        new_lifetime = user.lifetime_points + points_awarded

        with self._get_connection() as conn:
            conn.execute(
                """
                UPDATE users
                SET points = ?,
                    lifetime_points = ?,
                    daily_trivia_count = ?,
                    last_trivia_date = ?
                WHERE user_id = ?
                """,
                (new_balance, new_lifetime, new_trivia_count, today_str, user_id),
            )
            action_desc = f"Trivia Quiz {'Correct (+' + str(points_awarded) + ' pts)' if is_correct else 'Incorrect (0 pts)'}"
            if is_owl and is_correct:
                action_desc += " [🦉 Owl Perk!]"
            conn.execute(
                """
                INSERT INTO transactions (user_id, amount, action_type, description)
                VALUES (?, ?, 'TRIVIA', ?)
                """,
                (user_id, points_awarded, action_desc),
            )
            conn.commit()

        return TriviaResult(
            is_correct=is_correct,
            points_awarded=points_awarded,
            new_balance=new_balance,
            trivia_remaining=trivia_remaining,
        )
