# --- START OF FILE main.py ---

import discord
import feedparser
import os
import json
import time
import datetime
from dotenv import load_dotenv
from discord.ext import tasks, commands
# Optional but recommended imports for better parsing
try:
    from dateutil import parser as dateutil_parser
except ImportError:
    dateutil_parser = None
    print("Warning: 'python-dateutil' not installed. Timestamp parsing might be less reliable. Run: pip install python-dateutil")
try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None
    print("Warning: 'beautifulsoup4' not installed. HTML content cleaning disabled. Run: pip install beautifulsoup4")


load_dotenv()

# --- 設定 ---
# !! 請務必檢查以下設定 !!
config = {
    # 強烈建議從 .env 文件或環境變數讀取 Token
    'token': os.getenv('DISCORD_TOKEN') or 'MTM1ODI3NjQ4MzY3NTU4NjYzMQ.G81GbP.Sl3Tv2f0Ray3sKiav8JNyvDd_moDDR26k9Lrn4',
    'prefix': '!', # 機器人指令前綴 (如果有的話)
    'check_interval': 5 * 60,  # 檢查間隔 (秒), 這裡設為 5 分鐘
    'data_folder': 'data', # 儲存最新 ID 的資料夾

    # --- RSS Feed URLs ---
    # !! 請確認這些 URL 是最新且有效的 !!
    'youtube_rss': 'https://www.youtube.com/feeds/videos.xml?channel_id=UCnUAyD4t2LkvW68YrDh7fDg', # YouTube 頻道 RSS
    'instagram_rss': 'https://rss.app/feeds/4kWOueIAACX2tGNG.xml', # Instagram 帳號 RSS (來自 rss.app)
    'twitter_rss': [
        'https://rss.app/feeds/CV8TjlyQUQGGMPd4.xml',  # Twitter 帳號 1 RSS (@NMIXX_official)
        'https://rss.app/feeds/STiwPfYu6UYxh02f.xml'   # Twitter 帳號 2 RSS (WE_NMIXX)
    ],

    # --- Discord 頻道名稱 ---
    # !! 請確認這些名稱與你伺服器中的頻道名稱一致 !!
    # 建議未來改用頻道 ID 會更穩定
    'youtube_channel_name': 'sns更新（已開發3∕4）',
    'instagram_channel_name': 'sns更新（已開發3∕4）',
    'twitter_channel_name': 'sns更新（已開發3∕4）',
}

# --- 自動產生 Twitter 檔案路徑 ---
# 假設 rss.app 的 URL 包含帳號名或唯一標識
# 注意：如果 URL 格式變化，這裡的檔名提取邏輯可能需要調整
def get_account_name_from_rss(url):
    try:
        # 嘗試從 URL 中提取一個有意義的部分作為檔名基礎
        # 這是一個基於 rss.app 常見格式的猜測
        name_part = url.split('/')[-1].split('.')[0]
        # 移除可能的隨機字符串 (如果有的話)
        # 這裡只是簡單示例，可能需要更複雜的邏輯
        if len(name_part) > 15: # 假設過長的是隨機碼
             name_part = name_part[:10] # 取前10個字符
        return name_part if name_part else "unknown_twitter"
    except Exception:
        return "unknown_twitter"

twitter_latest_paths = [
    os.path.join(config['data_folder'], f"{get_account_name_from_rss(url)}_latest.json")
    for url in config['twitter_rss']
]

# 確保數據文件夾存在
if not os.path.exists(config['data_folder']):
    os.makedirs(config['data_folder'])
    print(f"Created data folder: {config['data_folder']}")

# 儲存最後更新狀態的檔案路徑
youtube_latest_path = os.path.join(config['data_folder'], 'youtube_latest.json')
instagram_latest_path = os.path.join(config['data_folder'], 'instagram_latest.json')


# --- Helper function to safely load last notified ID ---
def load_last_id(filepath, key_name):
    last_notified = {key_name: ''}
    if os.path.exists(filepath):
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read().strip() # 讀取並移除前後空白
                if content: # 確保文件不是空的
                    last_notified = json.loads(content)
                # 確保 key 存在，且值不是 None (處理舊格式或損壞)
                if key_name not in last_notified or last_notified[key_name] is None:
                    last_notified[key_name] = ''
        except json.JSONDecodeError:
            print(f'Warning: Corrupted or empty JSON file: {filepath}. Starting fresh.')
            last_notified = {key_name: ''}
        except Exception as e:
            print(f'Error reading latest file {filepath}: {e}')
            last_notified = {key_name: ''}
    return last_notified

# --- Helper function to safely save last notified ID ---
def save_last_id(filepath, key_name, value):
    # 確保 ID 值是有效的字串
    if not isinstance(value, str) or not value:
         print(f"Warning: Attempted to save invalid ID (value: {value}) to {filepath}. Skipping save.")
         return
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump({key_name: value}, f, ensure_ascii=False, indent=4)
        print(f"Successfully updated {filepath} with ID: {value}")
    except Exception as e:
        print(f"CRITICAL: Failed to write latest ID to {filepath}: {e}")


# --- Helper function to parse timestamp ---
def get_timestamp_from_entry(entry):
    """從 feed entry 獲取 datetime 對象，處理可能的錯誤"""
    dt = None
    # 優先使用 feedparser 解析好的 time struct
    if hasattr(entry, 'published_parsed') and entry.published_parsed:
        try:
            # 轉換為 timezone-aware 的 datetime (UTC)
            dt = datetime.datetime.fromtimestamp(time.mktime(entry.published_parsed), tz=datetime.timezone.utc)
        except (TypeError, ValueError, OverflowError) as e:
             print(f"Could not convert published_parsed {entry.published_parsed} to timestamp: {e}")
             dt = None # 轉換失敗，嘗試下一個方法

    # 如果 published_parsed 失敗或不存在，嘗試解析 published 字串
    if dt is None and hasattr(entry, 'published') and entry.published:
        if dateutil_parser:
            try:
                dt = dateutil_parser.parse(entry.published)
                # 如果解析出來沒有時區信息，假設它是 UTC
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=datetime.timezone.utc)
            except Exception as e:
                print(f"Could not parse timestamp string using dateutil: {entry.published} - Error: {e}")
                dt = None # 解析失敗
        else:
             # 沒有 dateutil，可以嘗試 feedparser 內建的簡單解析 (效果有限)
             try:
                 # feedparser._parse_date Может вернуть None или time.struct_time
                 parsed_date = feedparser.parse(entry.published) # Hacky way, maybe not reliable
                 if parsed_date and parsed_date.entries and hasattr(parsed_date.entries[0], 'published_parsed'):
                     struct_time = parsed_date.entries[0].published_parsed
                     dt = datetime.datetime.fromtimestamp(time.mktime(struct_time), tz=datetime.timezone.utc)
             except Exception:
                  dt = None

    # 如果所有方法都失敗，返回當前 UTC 時間
    if dt is None:
        print(f"Warning: Using current time as timestamp for entry: {entry.get('title', 'N/A')}")
        dt = discord.utils.utcnow()

    return dt

# --- Helper function to clean HTML ---
def clean_html(raw_html):
    if BeautifulSoup and raw_html:
        try:
            soup = BeautifulSoup(raw_html, 'html.parser')
            text = soup.get_text(separator=' ', strip=True)
            return text
        except Exception as e:
            print(f"Error cleaning HTML: {e}")
            return raw_html # 清理失敗返回原始文本
    return raw_html if raw_html else "" # 沒有 BeautifulSoup 或輸入為空

# --- Helper function to truncate text ---
def truncate_text(text, max_length):
    if not text: return ""
    if len(text) <= max_length:
        return text
    # 嘗試在最後一個空格處截斷
    truncated = text[:max_length].rsplit(' ', 1)[0]
    # 如果截斷後太短（比如第一句很長），就直接截斷
    if len(truncated) < max_length * 0.8:
         truncated = text[:max_length]
    return truncated + " ..."


# --- 建立 Discord 客戶端 ---
intents = discord.Intents.default()
intents.message_content = False # 除非你需要讀取用戶指令內容，否則設為 False 更安全
intents.members = False         # 除非你需要成員加入/離開事件或精確的成員列表
intents.guilds = True           # 需要知道機器人在哪些伺服器

client = commands.Bot(command_prefix=config['prefix'], intents=intents)

# --- 檢查 YouTube 更新 ---
@tasks.loop(seconds=config['check_interval'])
async def check_youtube_updates():
    print(f"[{datetime.datetime.now()}] Checking YouTube updates...")
    try:
        feed = feedparser.parse(config['youtube_rss'])
        if not feed.entries:
            print("YouTube feed empty or failed to load.")
            return

        latest_video = feed.entries[0]
        video_id = latest_video.get('yt_videoid') # yt:videoId 通常是最好的 ID
        if not video_id and latest_video.link:
             try: video_id = latest_video.link.split('v=')[1].split('&')[0]
             except IndexError: video_id = latest_video.link # 備用連結

        if not video_id:
            print("Could not extract a usable video ID from YouTube feed entry.")
            return

        last_notified = load_last_id(youtube_latest_path, 'video_id')

        if video_id != last_notified['video_id']:
            print(f'檢測到新的 YouTube 影片: {latest_video.title}')
            link = latest_video.link
            timestamp_dt = get_timestamp_from_entry(latest_video)
            title = latest_video.title if hasattr(latest_video, 'title') else "無標題影片"
            summary = clean_html(latest_video.summary) if hasattr(latest_video, 'summary') else "無描述"

            embed = discord.Embed(
                title=f"[YouTube 更新] {title}",
                url=link,
                color=0xFF0000,
                description=truncate_text(summary, 500), # 截斷描述
                timestamp=timestamp_dt
            )

            author_name = latest_video.author if hasattr(latest_video, 'author') else (feed.feed.title if hasattr(feed.feed, 'title') else 'YouTube Channel')
            author_icon = feed.feed.image.href if hasattr(feed.feed, 'image') and hasattr(feed.feed.image, 'href') else None
            embed.set_author(name=author_name, icon_url=author_icon)

            thumb_url = None
            if hasattr(latest_video, 'media_thumbnail') and latest_video.media_thumbnail:
                thumb_url = latest_video.media_thumbnail[0]['url']
            elif hasattr(latest_video, 'get') and latest_video.get('media_thumbnail'):
                 thumb_url = latest_video.get('media_thumbnail')[0].get('url')
            if thumb_url:
                embed.set_image(url=thumb_url)

            embed.set_footer(text="YouTube 更新通知")

            notification_sent_somewhere = False
            for guild in client.guilds:
                channel = discord.utils.get(guild.text_channels, name=config['youtube_channel_name'])
                if channel:
                    try:
                        await channel.send(embed=embed)
                        print(f"Sent YouTube update to {guild.name}/{channel.name}")
                        notification_sent_somewhere = True
                    except discord.Forbidden:
                        print(f"權限錯誤: 無法在 {guild.name}/{channel.name} 發送 YouTube 更新.")
                    except discord.HTTPException as e:
                        print(f"HTTP 錯誤 ({e.status}): 無法在 {guild.name}/{channel.name} 發送 YouTube 更新: {e.text}")
                    except Exception as e:
                         print(f"未知錯誤在發送 YouTube 更新到 {guild.name}/{channel.name}: {e}")

            if notification_sent_somewhere:
                 save_last_id(youtube_latest_path, 'video_id', video_id)
            else:
                 print("YouTube notification was not sent to any channel. Not updating last ID.")

    except Exception as error:
        print(f'檢查 YouTube 更新時發生嚴重錯誤: {error}')
        import traceback
        traceback.print_exc() # 打印詳細的錯誤追蹤

# --- 檢查 Instagram 更新 ---
@tasks.loop(seconds=config['check_interval'])
async def check_instagram_updates():
    print(f"[{datetime.datetime.now()}] Checking Instagram updates...")
    try:
        headers = {'User-Agent': 'Mozilla/5.0'} # 模擬瀏覽器
        feed = feedparser.parse(config['instagram_rss'], agent=headers.get('User-Agent'))
        if not feed.entries:
            print("Instagram feed empty or failed to load.")
            return

        latest_post = feed.entries[0]
        post_id = latest_post.link # 連結通常是唯一的 ID
        if not post_id:
            print("Could not extract post link (ID) from Instagram feed entry.")
            return

        last_notified = load_last_id(instagram_latest_path, 'post_id')

        if post_id != last_notified['post_id']:
            print(f'檢測到新的 Instagram 貼文: {latest_post.title}')
            link = latest_post.link
            timestamp_dt = get_timestamp_from_entry(latest_post)
            # Instagram 的 title 和 description 可能混亂，優先用 summary
            content = latest_post.summary if hasattr(latest_post, 'summary') else (latest_post.title if hasattr(latest_post, 'title') else "")
            cleaned_content = clean_html(content)

            embed = discord.Embed(
                title="[Instagram 更新]",
                url=link,
                color=0xE1306C,
                description=truncate_text(cleaned_content, 300), # 截斷內文
                timestamp=timestamp_dt
            )

            # 作者通常是 entry author 或 feed title
            author_name = latest_post.author if hasattr(latest_post, 'author') else (feed.feed.title if hasattr(feed.feed, 'title') else 'Instagram')
            # 嘗試從 feed title 提取帳號名（如果有的話）
            if 'Instagram feed for @' in author_name:
                 author_name = author_name.split('@')[1].strip()
            embed.set_author(name=author_name)

            image_url = None
            # 嘗試從 enclosures 找圖片
            if hasattr(latest_post, 'enclosures') and latest_post.enclosures:
                for enc in latest_post.enclosures:
                    if enc.get('type', '').startswith('image/'):
                        image_url = enc.href
                        break
            # 如果 enclosures 沒有，嘗試從 summary/content 的 HTML 中解析 img 標籤
            if not image_url and content and BeautifulSoup:
                 try:
                     soup = BeautifulSoup(content, 'html.parser')
                     img_tag = soup.find('img')
                     if img_tag and img_tag.get('src'):
                         image_url = img_tag['src']
                 except Exception as e:
                     print(f"Error parsing image from Instagram summary HTML: {e}")

            if image_url:
                embed.set_image(url=image_url)

            embed.set_footer(text="Instagram 更新通知")

            notification_sent_somewhere = False
            for guild in client.guilds:
                channel = discord.utils.get(guild.text_channels, name=config['instagram_channel_name'])
                if channel:
                    try:
                        await channel.send(embed=embed)
                        print(f"Sent Instagram update to {guild.name}/{channel.name}")
                        notification_sent_somewhere = True
                    except discord.Forbidden:
                        print(f"權限錯誤: 無法在 {guild.name}/{channel.name} 發送 Instagram 更新.")
                    except discord.HTTPException as e:
                        print(f"HTTP 錯誤 ({e.status}): 無法在 {guild.name}/{channel.name} 發送 Instagram 更新: {e.text}")
                    except Exception as e:
                         print(f"未知錯誤在發送 Instagram 更新到 {guild.name}/{channel.name}: {e}")

            if notification_sent_somewhere:
                save_last_id(instagram_latest_path, 'post_id', post_id)
            else:
                print("Instagram notification was not sent to any channel. Not updating last ID.")

    except Exception as error:
        print(f'檢查 Instagram 更新時發生嚴重錯誤: {error}')
        import traceback
        traceback.print_exc()

# --- 檢查 Twitter 更新 ---
@tasks.loop(seconds=config['check_interval'])
async def check_twitter_updates():
    print(f"[{datetime.datetime.now()}] Checking Twitter updates...")
    for i, rss_url in enumerate(config['twitter_rss']):
        filepath = twitter_latest_paths[i]
        account_name_from_file = os.path.basename(filepath).replace('_latest.json', '') # 用於日誌記錄
        try:
            print(f"Checking Twitter account: {account_name_from_file} via {rss_url}")
            headers = {'User-Agent': 'Mozilla/5.0'}
            feed = feedparser.parse(rss_url, agent=headers.get('User-Agent'))
            if not feed.entries:
                print(f"Twitter feed for {account_name_from_file} empty or failed to load.")
                continue

            latest_tweet = feed.entries[0]
            tweet_id = latest_tweet.link # 推文連結是最好的 ID
            if not tweet_id:
                print(f"Could not extract tweet link (ID) for {account_name_from_file}.")
                continue

            last_notified = load_last_id(filepath, 'tweet_id')

            if tweet_id != last_notified['tweet_id']:
                print(f'檢測到新的 Twitter 推文 from {account_name_from_file}: {latest_tweet.title}')
                link = latest_tweet.link
                timestamp_dt = get_timestamp_from_entry(latest_tweet)
                # 推文內容通常在 title
                content = latest_tweet.title if hasattr(latest_tweet, 'title') else ""
                cleaned_content = clean_html(content) # 清理 HTML 實體等

                embed = discord.Embed(
                    title="[Twitter 更新]",
                    url=link,
                    color=0x1DA1F2,
                    description=truncate_text(cleaned_content, 300), # 截斷內文
                    timestamp=timestamp_dt
                )

                # 作者名通常在 entry.author
                author_name = latest_tweet.author if hasattr(latest_tweet, 'author') else account_name_from_file
                # 嘗試移除可能的前綴如 "(@username)"
                if author_name.startswith("(") and author_name.endswith(")"):
                     author_name = author_name[1:-1]
                embed.set_author(name=author_name)

                image_url = None
                # 優先從 media_content (rss.app 常用)
                if hasattr(latest_tweet, 'media_content') and latest_tweet.media_content:
                     for media in latest_tweet.media_content:
                         if media.get('medium') == 'image' and media.get('url'):
                             image_url = media['url']
                             break
                # 其次嘗試 enclosures
                if not image_url and hasattr(latest_tweet, 'enclosures') and latest_tweet.enclosures:
                     for enc in latest_tweet.enclosures:
                         if enc.get('type', '').startswith('image/'):
                             image_url = enc.href
                             break
                # 最後嘗試從 summary/content HTML 解析 (效果可能不佳)
                if not image_url and hasattr(latest_tweet, 'summary') and BeautifulSoup:
                     try:
                         soup = BeautifulSoup(latest_tweet.summary, 'html.parser')
                         img_tag = soup.find('img')
                         if img_tag and img_tag.get('src'):
                             image_url = img_tag['src']
                     except Exception as e:
                        print(f"Error parsing image from Twitter summary HTML: {e}")

                if image_url:
                    embed.set_image(url=image_url)

                embed.set_footer(text="Twitter 更新通知")

                notification_sent_somewhere = False
                for guild in client.guilds:
                    channel = discord.utils.get(guild.text_channels, name=config['twitter_channel_name'])
                    if channel:
                        try:
                            await channel.send(embed=embed)
                            print(f"Sent Twitter update for {account_name_from_file} to {guild.name}/{channel.name}")
                            notification_sent_somewhere = True
                        except discord.Forbidden:
                            print(f"權限錯誤: 無法在 {guild.name}/{channel.name} 發送 Twitter 更新 for {account_name_from_file}.")
                        except discord.HTTPException as e:
                            print(f"HTTP 錯誤 ({e.status}): 無法在 {guild.name}/{channel.name} 發送 Twitter 更新 for {account_name_from_file}: {e.text}")
                        except Exception as e:
                             print(f"未知錯誤在發送 Twitter 更新到 {guild.name}/{channel.name}: {e}")

                if notification_sent_somewhere:
                    save_last_id(filepath, 'tweet_id', tweet_id)
                else:
                    print(f"Twitter notification for {account_name_from_file} was not sent. Not updating last ID.")

        except Exception as error:
            print(f'檢查 Twitter 帳號 {account_name_from_file} ({rss_url}) 時發生嚴重錯誤: {error}')
            import traceback
            traceback.print_exc()


# --- Bot Events ---
@client.event
async def on_ready():
    print(f'機器人已登入為 {client.user.name} ({client.user.id})')
    print(f'正在監控 {len(client.guilds)} 個伺服器')
    print('正在啟動檢查任務...')
    # 等待 Bot 完全準備好再啟動 tasks
    await client.wait_until_ready()
    if not check_youtube_updates.is_running():
        check_youtube_updates.start()
    if not check_instagram_updates.is_running():
        check_instagram_updates.start()
    if not check_twitter_updates.is_running():
        check_twitter_updates.start()
    print(f"檢查任務已啟動，檢查間隔: {config['check_interval']} 秒.")

@client.event
async def on_guild_join(guild):
    print(f"機器人已加入新的伺服器: {guild.name} (ID: {guild.id})")
    # 你可以在這裡添加歡迎訊息或檢查頻道是否存在

@client.event
async def on_guild_remove(guild):
    print(f"機器人已離開伺服器: {guild.name} (ID: {guild.id})")


# --- 啟動 Bot ---
if __name__ == "__main__":
    bot_token = config.get('token')
    if not bot_token or bot_token == 'YOUR_BOT_TOKEN_HERE':
        print("錯誤：機器人 Token 未在 config 或 .env 文件中設置！請編輯 main.py 或創建 .env 文件。")
    else:
        try:
            print("正在使用提供的 Token 登入 Discord...")
            client.run(bot_token)
        except discord.LoginFailure:
            print("錯誤：無效的 Discord Token，登入失敗。請仔細檢查你的 Token。")
        except discord.PrivilegedIntentsRequired:
             print("錯誤：缺少必要的 Intents。請前往 Discord Developer Portal，為你的機器人啟用 SERVER MEMBERS INTENT 和 MESSAGE CONTENT INTENT (如果需要指令)。")
        except Exception as e:
            print(f"啟動機器人時發生未預期的錯誤: {e}")
            import traceback
            traceback.print_exc()

# --- END OF FILE main.py ---