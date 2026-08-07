import os
import re
import sys
import asyncio
import threading
import datetime
import subprocess
import webbrowser
import base64
import json
os.environ.setdefault("SDL_AUDIODRIVER", "pipewire")
import edge_tts
import openwakeword
import pygame
import speech_recognition as sr
import pyaudio
import numpy as np
import keyboard
from openai import OpenAI
from openwakeword.model import Model
import pystray
from PIL import Image, ImageDraw
import pyautogui

# PyQt6 GUI Imports
from PyQt6.QtWidgets import QApplication, QWidget, QLabel, QVBoxLayout
from PyQt6.QtCore import Qt, pyqtSignal, QObject
from PyQt6.QtGui import QFont, QShortcut

# Windows Volume Control Imports
try:
    from comtypes import CLSCTX_ALL
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
    HAS_PYCAW = True
except ImportError:
    HAS_PYCAW = False

# --- 🖥️ PyQt6 GUI & SIGNAL BRIDGE ---

class HUDBridge(QObject):
    """Bridge to safely communicate between background async loop and PyQt main GUI thread."""
    status_signal = pyqtSignal(str, str) # (Status Text, Color Hex)

hud_bridge = HUDBridge()

class JarvisHUD(QWidget):
    """Floating transparent overlay HUD for JARVIS."""
    def __init__(self):
        super().__init__()
        self.init_ui()
        hud_bridge.status_signal.connect(self.update_status)

    def init_ui(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        backtick_shortcut = QShortcut(Qt.Key.Key_QuoteLeft, self)
        backtick_shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
        backtick_shortcut.activated.connect(trigger_hotkey)

        esc_shortcut = QShortcut(Qt.Key.Key_Escape, self)
        esc_shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
        esc_shortcut.activated.connect(stop_hotkey)

        screen = QApplication.primaryScreen().geometry()
        hud_width = 280
        hud_height = 80
        pos_x = int((screen.width() - hud_width) / 2)
        self.setGeometry(pos_x, 30, hud_width, hud_height)

        layout = QVBoxLayout()
        layout.setContentsMargins(15, 10, 15, 10)

        self.title_label = QLabel("J.A.R.V.I.S.")
        self.title_label.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self.title_label.setStyleSheet("color: #888888; letter-spacing: 2px;")

        self.status_label = QLabel("STANDBY")
        self.status_label.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        self.status_label.setStyleSheet("color: #00d2ff;")

        layout.addWidget(self.title_label)
        layout.addWidget(self.status_label)
        self.setLayout(layout)

        self.setStyleSheet("""
            QWidget {
                background-color: rgba(15, 15, 20, 0.85);
                border: 1px solid rgba(0, 210, 255, 0.4);
                border-radius: 12px;
            }
        """)

    def mousePressEvent(self, event):
        trigger_hotkey()

    def update_status(self, status: str, color_hex: str):
        self.status_label.setText(status.upper())
        self.status_label.setStyleSheet(f"color: {color_hex}; font-weight: bold;")
        self.setStyleSheet(f"""
            QWidget {{
                background-color: rgba(15, 15, 20, 0.85);
                border: 1px solid {color_hex};
                border-radius: 12px;
            }}
        """)

def set_hud_status(status_text: str, color_hex: str):
    hud_bridge.status_signal.emit(status_text, color_hex)

# --- 🎤 ENGINE INITIALIZATION ---

pygame.mixer.init()
recognizer = sr.Recognizer()

print("⌛ Loading wake word engine...")
wakeword_model = Model(wakeword_model_paths=[
    os.path.join(os.path.dirname(openwakeword.__file__), "resources", "models", "hey_jarvis_v0.1.onnx")
])

# NOTE: legacy standalone script - use src/jarvis_core.py instead.
# The API key is read from config: src/config.py (user config dir, never committed).
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import config as app_config
_CONFIG = app_config.AppConfig()
_client_config = _CONFIG.data
client_groq = OpenAI(
    base_url="https://api.groq.com/openai/v1",
    api_key=_client_config.get("api_key") or "missing"
)

running = True
trigger_manual_listen = False
stop_speech_requested = False

# Conversation Memory Buffer
conversation_history = [
    {
        "role": "system",
        "content": (
            "You are JARVIS, a highly capable AI assistant running on the user's Linux PC. "
            "You have tools to control the computer: open apps, close apps, open websites, "
            "control volume, lock the screen, take screenshots, analyze the screen, and close windows. "
            "IMPORTANT: Only use the analyze_screen tool if the user explicitly asks about what's on "
            "their screen. For questions about time, use get_current_time. For simple chat, just answer "
            "directly. Keep conversational context from previous turns. Reply concisely, like a voice assistant."
        )
    }
]

def trigger_hotkey():
    global trigger_manual_listen, stop_speech_requested
    trigger_manual_listen = True
    stop_speech_requested = True

def stop_hotkey():
    global stop_speech_requested
    stop_speech_requested = True

def create_tray_icon():
    width, height = 64, 64
    image = Image.new('RGB', (width, height), color=(30, 30, 30))
    dc = ImageDraw.Draw(image)
    dc.ellipse((8, 8, width - 8, height - 8), fill=(0, 180, 255))
    return image

# --- 🔊 SAFE AUDIO PLAYBACK & INTERRUPT ---

async def speak(text: str):
    global stop_speech_requested
    stop_speech_requested = False
    
    set_hud_status("SPEAKING", "#00ff88") # Green HUD
    print(f"🤖 Jarvis: {text}")
    audio_file = "jarvis_speech.mp3"
    
    try:
        communicate = edge_tts.Communicate(text, "en-US-ChristopherNeural")
        await communicate.save(audio_file)

        pygame.mixer.music.load(audio_file)
        pygame.mixer.music.play()

        # Non-blocking check for stop interrupt (Hotkeys: 'Esc' or '`')
        while pygame.mixer.music.get_busy():
            if stop_speech_requested:
                print("\n🛑 Speech interrupted by user!")
                pygame.mixer.music.stop()
                set_hud_status("STOPPED", "#ff0000")
                stop_speech_requested = False
                break
            await asyncio.sleep(0.05)

        pygame.mixer.music.unload()
    except Exception as e:
        print(f"\n⚠️ Audio Playback Error: {e}\n")

# --- 👁️ GROQ VISION ENGINE ---

def capture_and_analyze_screen(prompt: str) -> str:
    set_hud_status("ANALYZING SCREEN", "#a855f7") # Purple HUD
    screenshot_path = "jarvis_vision_temp.png"
    try:
        print("📸 Capturing screen...")
        screenshot = pyautogui.screenshot()
        screenshot.save(screenshot_path)

        print("👁️ Analyzing visual context...")
        with open(screenshot_path, "rb") as img_file:
            base64_image = base64.b64encode(img_file.read()).decode('utf-8')

        response = client_groq.chat.completions.create(
            model="qwen/qwen3.6-27b",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text", 
                            "text": (
                                "You are JARVIS inspecting the user's screen. "
                                f"Answer this query based on what you see: {prompt}"
                            )
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{base64_image}"
                            }
                        }
                    ]
                }
            ],
            max_tokens=300
        )

        if os.path.exists(screenshot_path):
            os.remove(screenshot_path)

        content = response.choices[0].message.content.strip()
        cleaned_content = re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL).strip()
        return cleaned_content if cleaned_content else content

    except Exception as e:
        print(f"⚠️ Screen Vision Error: {e}")
        if os.path.exists(screenshot_path):
            try:
                os.remove(screenshot_path)
            except Exception:
                pass
        return "Vision error, boss."

# --- 🛠️ LINUX AUTOMATION ENGINE ---

def set_master_volume(level_percent: int):
    try:
        if "mute" in " ".join(sys.argv) and level_percent == 0:
            os.system("wpctl set-mute @DEFAULT_AUDIO_SINK@ 1")
        else:
            os.system(f"wpctl set-volume @DEFAULT_AUDIO_SINK@ {max(0, min(100, level_percent))}%")
            os.system("wpctl set-mute @DEFAULT_AUDIO_SINK@ 0")
        return True
    except Exception:
        return False

def close_app_by_name(app_name: str) -> bool:
    process_map = {
        "chrome": "chrome", "discord": "discord", "steam": "steam",
        "notepad": "gedit", "calculator": "gnome-calculator", "calc": "gnome-calculator",
        "roblox": "roblox", "edge": "microsoft-edge", "browser": "firefox",
        "firefox": "firefox", "terminal": "kitty", "terminal2": "gnome-terminal",
        "kde": "konsole", "files": "nautilus", "nautilus": "nautilus",
        "vscode": "code", "code": "code", "spotify": "spotify", "vlc": "vlc",
        "gimp": "gimp", "blender": "blender", "obs": "obs", "libreoffice": "libreoffice",
        "thunderbird": "thunderbird", "slack": "slack", "telegram": "telegram",
        "whatsapp": "whatsapp", "zoom": "zoom", "teams": "teams", "discord2": "discord",
        "music": "spotify", "games": "steam"
    }
    target_proc = process_map.get(app_name.lower(), app_name.lower())
    return os.system(f"pkill -f '{target_proc}'") == 0

def open_app_by_name(app_name: str) -> bool:
    app_map = {
        "discord": "discord", "steam": "steam", "roblox": "roblox",
        "spotify": "spotify", "vlc": "vlc", "gimp": "gimp", "blender": "blender",
        "obs": "obs", "libreoffice": "libreoffice", "thunderbird": "thunderbird",
        "slack": "slack", "telegram": "telegram", "zoom": "zoom", "teams": "teams",
        "code": "code", "vscode": "code", "files": "nautilus", "nautilus": "nautilus",
        "terminal": "kitty", "kde": "konsole"
    }
    app = app_map.get(app_name.lower(), app_name.lower())
    return os.system(f"nohup {app} >/dev/null 2>&1 &") == 0

def handle_system_commands(user_input: str) -> str:
    cmd = user_input.lower().strip()

    # Reset Memory Command
    if any(kw in cmd for kw in ["forget everything", "clear memory", "reset memory", "forget conversation"]):
        global conversation_history
        conversation_history = [conversation_history[0]]
        return "Memory cleared, boss."

    # Deactivate Command
    if any(word in cmd for word in ["deactivate", "exit jarvis", "quit jarvis", "stop jarvis", "turn off", "shutdown"]):
        global running
        running = False
        return "Deactivating, boss."

    # Screen Vision Trigger
    vision_keywords = ["screen", "look at", "what do you see", "check this", "display", "monitor", "what is on my"]
    if any(kw in cmd for kw in vision_keywords):
        return capture_and_analyze_screen(user_input)

    elif "close tab" in cmd:
        try:
            keyboard.send("ctrl+w")
        except Exception:
            os.system("wmctrl -c :ACTIVE: >/dev/null 2>&1")
        return "Closing tab."
    elif "close window" in cmd:
        os.system("wmctrl -c :ACTIVE: >/dev/null 2>&1")
        return "Closing window."
    elif cmd.startswith("close "):
        app_target = cmd.replace("close ", "").strip()
        close_app_by_name(app_target)
        return f"Closed {app_target}."
    elif "open chrome" in cmd or "open browser" in cmd or "open internet" in cmd:
        webbrowser.open("https://www.google.com")
        return "Opening browser."
    elif "open youtube" in cmd:
        webbrowser.open("https://www.youtube.com")
        return "Opening YouTube."
    elif "open google" in cmd:
        webbrowser.open("https://www.google.com")
        return "Opening Google."
    elif "open github" in cmd:
        webbrowser.open("https://www.github.com")
        return "Opening GitHub."
    elif "open discord" in cmd or "open steam" in cmd or "open roblox" in cmd:
        app_to_open = "discord" if "discord" in cmd else ("steam" if "steam" in cmd else "roblox")
        open_app_by_name(app_to_open)
        return f"Opening {app_to_open}."
    elif "open spotify" in cmd or "open music" in cmd:
        open_app_by_name("spotify")
        return "Opening Spotify."
    elif "open terminal" in cmd or "open console" in cmd:
        open_app_by_name("terminal")
        return "Opening terminal."
    elif "open files" in cmd or "open file manager" in cmd:
        open_app_by_name("files")
        return "Opening file manager."
    elif cmd.startswith("open "):
        app_target = cmd.replace("open ", "").strip()
        open_app_by_name(app_target)
        return f"Opening {app_target}."
    elif "lock pc" in cmd or "lock screen" in cmd:
        os.system("loginctl lock-session >/dev/null 2>&1")
        return "Locking PC."
    elif "mute volume" in cmd:
        os.system("wpctl set-mute @DEFAULT_AUDIO_SINK@ 1")
        return "Muted."
    elif "unmute" in cmd:
        os.system("wpctl set-mute @DEFAULT_AUDIO_SINK@ 0")
        return "Unmuted."
    elif "volume up" in cmd:
        os.system("wpctl set-volume @DEFAULT_AUDIO_SINK@ 5%+")
        return "Volume up."
    elif "volume down" in cmd:
        os.system("wpctl set-volume @DEFAULT_AUDIO_SINK@ 5%-")
        return "Volume down."
    elif "set volume to" in cmd or "volume to" in cmd:
        numbers = re.findall(r'\d+', cmd)
        if numbers:
            vol_val = int(numbers[0])
            set_master_volume(vol_val)
            return f"Volume set to {vol_val}%."
    elif "screenshot" in cmd or "take a picture" in cmd:
        shot_path = os.path.expanduser("~/Pictures/screenshot_jarvis.png")
        os.makedirs(os.path.dirname(shot_path), exist_ok=True)
        os.system(f"import {shot_path} 2>/dev/null || gnome-screenshot -f {shot_path} 2>/dev/null")
        return f"Screenshot saved to {shot_path}."

    return ""

# --- 🎙️ VOICE LOOPS & AI MEMORY ---

def listen_for_wakeword() -> bool:
    global trigger_manual_listen, running
    set_hud_status("STANDBY", "#00d2ff") # Cyan HUD
    print("\n💤 Sleeping... (Say 'Hey Jarvis' or press '`' key)")
    
    FORMAT = pyaudio.paInt16
    CHANNELS = 1
    RATE = 16000
    CHUNK = 1280

    audio = pyaudio.PyAudio()
    stream = None

    try:
        stream = audio.open(format=FORMAT, channels=CHANNELS, rate=RATE, input=True, frames_per_buffer=CHUNK)
        wakeword_model.reset()

        while running:
            if trigger_manual_listen:
                trigger_manual_listen = False
                print("\n⚡ Hotkey Trigger Activated!")
                return True

            try:
                data = stream.read(CHUNK, exception_on_overflow=False)
                audio_data = np.frombuffer(data, dtype=np.int16)

                prediction = wakeword_model.predict(audio_data)
                for model_name, score in prediction.items():
                    if score > 0.5:
                        print(f"\n⚡ Wake Word Detected! ({model_name}: {score:.2f})")
                        return True
            except OSError as e:
                # Handle mic disconnect/reconnect glitches without crashing
                print(f"⚠️ Audio Stream Glitch: {e}. Retrying mic access...")
                break

        return False
    finally:
        # Robust stream shutdown
        if stream is not None:
            try:
                if stream.is_active():
                    stream.stop_stream()
                stream.close()
            except Exception:
                pass
        try:
            audio.terminate()
        except Exception:
            pass

def listen_for_command() -> str:
    set_hud_status("LISTENING...", "#ff0055") # Pink HUD
    with sr.Microphone() as source:
        print("🎤 Listening...")
        recognizer.adjust_for_ambient_noise(source, duration=0.3)
        try:
            audio = recognizer.listen(source, timeout=5, phrase_time_limit=10)
            set_hud_status("PROCESSING...", "#ffaa00") # Amber HUD
            print("🧠 Processing...")
            text = recognizer.recognize_google(audio)
            print(f"🗣️ You: {text}")
            return text
        except (sr.WaitTimeoutError, sr.UnknownValueError):
            return ""
        except sr.RequestError as e:
            print(f"❌ Speech Error: {e}")
            return ""

# --- 🧰 AI FUNCTION CALLING (tools) ---

ACTION_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "open_application",
            "description": "Open an application on the user's Linux system (e.g. discord, steam, spotify, terminal, files, code).",
            "parameters": {
                "type": "object",
                "properties": {"app": {"type": "string", "description": "Name of the application to open"}},
                "required": ["app"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "close_application",
            "description": "Close a running application on the user's Linux system.",
            "parameters": {
                "type": "object",
                "properties": {"app": {"type": "string", "description": "Name of the application to close"}},
                "required": ["app"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "open_website",
            "description": "Open a website in the default browser (e.g. youtube, google, github).",
            "parameters": {
                "type": "object",
                "properties": {"site": {"type": "string", "description": "Website name or URL to open"}},
                "required": ["site"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "set_volume",
            "description": "Set the master volume to a percentage, or mute/unmute, or change volume by steps.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["set", "mute", "unmute", "up", "down"], "description": "What to do with the volume"},
                    "level": {"type": "integer", "description": "Target volume percentage (0-100), only for 'set'"}
                },
                "required": ["action"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "lock_screen",
            "description": "Lock the user's PC screen.",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "take_screenshot",
            "description": "Take a screenshot and save it to the Pictures folder.",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_screen",
            "description": "Capture and visually analyze the user's screen to answer a question about what is on it.",
            "parameters": {
                "type": "object",
                "properties": {"question": {"type": "string", "description": "The question about the screen contents"}},
                "required": ["question"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_current_time",
            "description": "Get the current date and time of the user's system.",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "close_window",
            "description": "Close the currently active window.",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "clear_memory",
            "description": "Clear the conversation memory / forget the conversation history.",
            "parameters": {"type": "object", "properties": {}}
        }
    }
]

def execute_action(tool_name: str, tool_args: dict) -> str:
    try:
        if tool_name == "open_application":
            open_app_by_name(tool_args.get("app", ""))
            return f"Opened {tool_args.get('app', 'app')}."
        elif tool_name == "close_application":
            close_app_by_name(tool_args.get("app", ""))
            return f"Closed {tool_args.get('app', 'app')}."
        elif tool_name == "open_website":
            site = tool_args.get("site", "").strip()
            if not site.startswith("http"):
                site = f"https://{site.replace(' ', '')}"
            webbrowser.open(site)
            return f"Opened {tool_args.get('site')} in the browser."
        elif tool_name == "set_volume":
            action = tool_args.get("action")
            if action == "set":
                set_master_volume(int(tool_args.get("level", 50)))
                return f"Volume set to {tool_args.get('level')} percent."
            elif action == "mute":
                os.system("wpctl set-mute @DEFAULT_AUDIO_SINK@ 1")
                return "Volume muted."
            elif action == "unmute":
                os.system("wpctl set-mute @DEFAULT_AUDIO_SINK@ 0")
                return "Volume unmuted."
            elif action == "up":
                os.system("wpctl set-volume @DEFAULT_AUDIO_SINK@ 5%+")
                return "Volume increased."
            elif action == "down":
                os.system("wpctl set-volume @DEFAULT_AUDIO_SINK@ 5%-")
                return "Volume decreased."
        elif tool_name == "lock_screen":
            os.system("loginctl lock-session >/dev/null 2>&1")
            return "Screen locked."
        elif tool_name == "take_screenshot":
            shot_path = os.path.expanduser("~/Pictures/screenshot_jarvis.png")
            os.makedirs(os.path.dirname(shot_path), exist_ok=True)
            pyautogui.screenshot().save(shot_path)
            return f"Screenshot saved to {shot_path}."
        elif tool_name == "analyze_screen":
            return capture_and_analyze_screen(tool_args.get("question", "What is on my screen?"))
        elif tool_name == "close_window":
            os.system("wmctrl -c :ACTIVE: >/dev/null 2>&1")
            return "Closed the active window."
        elif tool_name == "get_current_time":
            now = datetime.datetime.now()
            return f"The current time is {now.strftime('%I:%M %p')} on {now.strftime('%A, %B %d, %Y')}."
        elif tool_name == "clear_memory":
            global conversation_history
            conversation_history = [conversation_history[0]]
            return "Conversation memory cleared."
        return "Action executed."
    except Exception as e:
        print(f"⚠️ Action Error ({tool_name}): {e}")
        return f"Failed to execute {tool_name}."

async def fetch_ai_response(user_prompt: str) -> str:
    global conversation_history
    set_hud_status("THINKING...", "#ffaa00")

    conversation_history.append({"role": "user", "content": user_prompt})

    if len(conversation_history) > 9:
        conversation_history = [conversation_history[0]] + conversation_history[-8:]

    try:
        response = client_groq.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=conversation_history,
            tools=ACTION_TOOLS,
            temperature=0.6,
            max_tokens=400
        )
        message = response.choices[0].message

        if message.tool_calls:
            conversation_history.append(message)
            for tool_call in message.tool_calls:
                tool_name = tool_call.function.name
                try:
                    tool_args = json.loads(tool_call.function.arguments or "{}")
                except json.JSONDecodeError:
                    tool_args = {}
                print(f"🧰 Executing: {tool_name}({tool_args})")
                result = execute_action(tool_name, tool_args)
                conversation_history.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result
                })

            follow_up = client_groq.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=conversation_history,
                temperature=0.6,
                max_tokens=300
            )
            cleaned_reply = re.sub(r'<think>.*?</think>', '', follow_up.choices[0].message.content.strip(), flags=re.DOTALL).strip()
        else:
            cleaned_reply = re.sub(r'<think>.*?</think>', '', message.content.strip(), flags=re.DOTALL).strip()

        conversation_history.append({"role": "assistant", "content": cleaned_reply})
        return cleaned_reply
    except Exception as e:
        err_str = str(e)
        if "tool_use_failed" in err_str or "failed_generation" in err_str:
            print("🔄 Tool call parsing failed, recovering from emitted call...")
            try:
                match = re.search(r"<function=([\w]+)(\{.*?\})?(?:</function>|>)", err_str)
                if match:
                    tool_name = match.group(1)
                    try:
                        tool_args = json.loads(match.group(2) or "{}")
                    except json.JSONDecodeError:
                        tool_args = {}
                    print(f"🧰 Executing (recovered): {tool_name}({tool_args})")
                    result = execute_action(tool_name, tool_args)
                    conversation_history.append({"role": "user", "content": f"[Action {tool_name} executed: {result}]"})
                else:
                    conversation_history.append({"role": "user", "content": user_prompt})

                follow_up = client_groq.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    messages=conversation_history,
                    temperature=0.6,
                    max_tokens=300
                )
                retry_content = follow_up.choices[0].message.content.strip()
                cleaned_retry = re.sub(r'<think>.*?</think>', '', retry_content, flags=re.DOTALL).strip()
                conversation_history.append({"role": "assistant", "content": cleaned_retry})
                return cleaned_retry
            except Exception:
                pass
        print(f"❌ Groq API Error: {e}")
        return "Connection error."

async def main_call_loop():
    global running
    await speak("HUD online, boss.")
    
    while running:
        try:
            if listen_for_wakeword():
                await speak("Yes?")
                
                in_conversation = True
                while in_conversation and running:
                    user_input = listen_for_command()
                    
                    if not user_input:
                        in_conversation = False
                        break
                        
                    if user_input.lower() in ["deactivate", "exit", "quit", "stop jarvis", "goodbye", "nevermind"]:
                        await speak("Deactivating.")
                        running = False
                        in_conversation = False
                        break
                        
                    system_reply = handle_system_commands(user_input)
                    if system_reply:
                        await speak(system_reply)
                        if not running:
                            break
                        in_conversation = False
                    else:
                        reply = await fetch_ai_response(user_input)
                        await speak(reply)
                        in_conversation = False

        except KeyboardInterrupt:
            running = False
            break
        except Exception as e:
            print(f"⚠️ Loop error: {e}. Recovering...")
            await asyncio.sleep(1)
            
    set_hud_status("OFFLINE", "#555555")

def start_backend_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_until_complete(main_call_loop())

def on_activate(icon, item):
    global trigger_manual_listen
    trigger_manual_listen = True

def on_quit(icon, item):
    global running
    running = False
    icon.stop()

def setup_tray():
    menu = pystray.Menu(
        pystray.MenuItem("Trigger Jarvis", on_activate, default=True),
        pystray.MenuItem("Exit Jarvis", on_quit)
    )
    icon = pystray.Icon("JARVIS", create_tray_icon(), "JARVIS Voice Assistant", menu)
    icon.run()

# --- 🚀 ENTRY POINT ---

if __name__ == "__main__":
    try:
        keyboard.add_hotkey('`', trigger_hotkey)
        keyboard.add_hotkey('esc', stop_hotkey)
    except Exception:
        pass

    tray_thread = threading.Thread(target=setup_tray, daemon=True)
    tray_thread.start()

    backend_loop = asyncio.new_event_loop()
    backend_thread = threading.Thread(target=start_backend_loop, args=(backend_loop,), daemon=True)
    backend_thread.start()

    app = QApplication(sys.argv)
    hud = JarvisHUD()
    hud.show()

    exit_code = app.exec()
    running = False
    pygame.mixer.quit()
    if os.path.exists("jarvis_speech.mp3"):
        try:
            os.remove("jarvis_speech.mp3")
        except PermissionError:
            pass
    sys.exit(exit_code)